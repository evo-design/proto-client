"""Main client entrypoint."""

import hashlib
import os
import platform
from pathlib import Path, PurePosixPath
from typing import Any

import httpx

from proto_client._defaults import RUNS_BASE_URL, TOOLS_BASE_URL
from proto_client._http import RetryConfig, RetryTransport
from proto_client._version import VERSION
from proto_client.assets import AssetsNamespace, set_default_assets_namespace
from proto_client.errors import from_response
from proto_client.models import AssetRef, MeResponse
from proto_client.runs import RunsNamespace
from proto_client.tools import ToolsNamespace


class ProtoClient:
    """Unified client for Proto Bio APIs.

    Usage::

        client = ProtoClient(api_key="...")
        result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})
    """

    def __init__(
        self,
        api_key: str | None = None,
        timeout: float = 600.0,
        max_retries: int = 2,
        retry_config: RetryConfig | None = None,
        app_user_id: str | None = None,
    ) -> None:
        """Initialize the client.

        Args:
            api_key: API key for authentication. Falls back to ``PROTO_API_KEY`` env var.
            timeout: Default request timeout in seconds.
            max_retries: Number of retry attempts for failed requests. Ignored if
                *retry_config* is provided.
            retry_config: Advanced retry configuration. Overrides *max_retries*.
            app_user_id: End-user identifier sent as ``x-app-user-id`` on every request.
                Scopes server-side ownership and asset access checks to this identity.
                Omit when the caller is acting at the platform/admin level.
        """
        resolved_key = api_key if api_key is not None else os.environ.get("PROTO_API_KEY")
        if resolved_key == "":
            raise ValueError("api_key must not be empty. Pass a valid key or set PROTO_API_KEY.")
        if app_user_id == "":
            raise ValueError("app_user_id must not be empty. Pass a non-empty value or omit the argument.")

        headers: dict[str, str] = {
            "User-Agent": f"proto-client-python/{VERSION} python/{platform.python_version()}",
        }
        if resolved_key:
            headers["X-API-Key"] = resolved_key
        if app_user_id:
            headers["x-app-user-id"] = app_user_id

        cfg = retry_config or RetryConfig(max_retries=max_retries)

        tools_http = httpx.Client(
            base_url=TOOLS_BASE_URL,
            headers=headers,
            timeout=timeout,
            transport=RetryTransport(httpx.HTTPTransport(), config=cfg),
        )
        runs_http = httpx.Client(
            base_url=RUNS_BASE_URL,
            headers=headers,
            timeout=timeout,
            transport=RetryTransport(httpx.HTTPTransport(), config=cfg),
        )

        self.tools = ToolsNamespace(tools_http)
        self.runs = RunsNamespace(runs_http)
        self.assets = AssetsNamespace([tools_http, runs_http])
        set_default_assets_namespace(self.assets)
        self._runs_http = runs_http
        self._clients: list[httpx.Client] = [tools_http, runs_http]

    def me(self) -> MeResponse:
        """Return the calling key's principal info from ``GET /api/v1/me``.

        Source of truth for capability strings; intended to be called once
        at agent / client boot. Raises the same typed errors as every other
        endpoint (``ProtoAuthError`` on 401/403, etc.).
        """
        resp = self._runs_http.get("/api/v1/me")
        if resp.is_error:
            raise from_response(resp)
        return MeResponse.model_validate(resp.json())

    def export_program(
        self,
        program: Any,
        path: str | Path | None = None,
        *,
        format: str = "csv",
        project: str | None = None,
    ) -> Path:
        """Export a proto-language ``Program`` to *path*, downloading AssetRef-referenced bytes.

        ``path=None`` names the folder per the unified convention
        (``{project}__{YYYY-MM-DD_HHMMSS}``) under CWD.

        Writes::

            <path>/
            ├── sequences.<format>    constraints.<format>    constructs.<format>    optimization.<format>
            ├── sequences.fasta
            └── assets/                file names use res<result_idx>_con<construct_idx>_seg<segment_idx>:
                ├── res{i}_con{c}_seg{s}_structure.{pdb|cif}    written from Sequence.structure
                ├── res{i}_con{c}_seg{s}_logits.npy             written from Sequence.logits via np.save
                └── <asset_id>.<ext>                       downloaded AssetRefs

        AssetRef cells anywhere in constraint / generator / metadata are downloaded
        to ``assets/`` and rewritten to ``"assets/<file>"`` strings before
        proto-language writes the tables.
        """
        try:
            from proto_language.utils.io import (  # type: ignore[import-not-found, unused-ignore]
                write_results_folder,
            )
        except ImportError as e:
            raise RuntimeError("export_program requires proto-language to be installed alongside proto-client.") from e

        from proto_client._export_names import build_export_name

        out_dir = Path.cwd() / build_export_name(project=project) if path is None else Path(path)
        out_dir.mkdir(parents=True, exist_ok=True)
        assets_dir = out_dir / "assets"
        assets_dir.mkdir(exist_ok=True)

        results = program.extract_results(program.energy_scores)
        seen: dict[str, str] = {}
        results = _materialize_assetrefs(results, self.assets, assets_dir, seen)

        return Path(write_results_folder(results=results, path=out_dir, format=format))

    def close(self) -> None:
        """Close all underlying HTTP clients."""
        import proto_client.assets as _assets_mod

        if _assets_mod._default_assets is self.assets:
            _assets_mod._default_assets = None
        first_error: BaseException | None = None
        for c in self._clients:
            try:
                c.close()
            except Exception as e:  # noqa: PERF203
                if first_error is None:
                    first_error = e
        self._clients.clear()
        if first_error is not None:
            raise first_error

    def __enter__(self) -> "ProtoClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def _materialize_assetrefs(
    value: Any,
    assets_ns: AssetsNamespace,
    assets_dir: Path,
    seen: dict[str, str],
) -> Any:
    """Recursively replace AssetRef-shaped dicts (or typed AssetRef instances) with ``"assets/<file>"`` strings.

    Downloads each unique ``asset_id`` once via *assets_ns* and writes to *assets_dir*.
    Filename collisions across distinct ids are disambiguated with a sha256 suffix.
    HTTP failures yield a 0-byte ``<name>.missing`` placeholder so a single bad asset
    doesn't abort the whole export.
    """
    ref = _coerce_to_assetref(value)
    if ref is not None:
        if ref.id in seen:
            return f"assets/{seen[ref.id]}"
        filename = _resolve_filename_collision(ref.suggested_filename(), ref.id, set(seen.values()))
        dest = assets_dir / filename
        try:
            dest.write_bytes(assets_ns.get(ref))
        except Exception:
            filename = _resolve_filename_collision(filename + ".missing", ref.id, set(seen.values()))
            dest = assets_dir / filename
            dest.write_bytes(b"")
        seen[ref.id] = filename
        return f"assets/{filename}"
    if isinstance(value, dict):
        return {k: _materialize_assetrefs(v, assets_ns, assets_dir, seen) for k, v in value.items()}
    if isinstance(value, list):
        return [_materialize_assetrefs(v, assets_ns, assets_dir, seen) for v in value]
    return value


def _coerce_to_assetref(value: Any) -> AssetRef | None:
    """Return a typed AssetRef when *value* is one already, or when its dict shape matches; else None."""
    if isinstance(value, AssetRef):
        return value
    if (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and value.get("kind") in ("output", "reference_db", "user_upload")
    ):
        return AssetRef.model_validate(value)
    return None


def _resolve_filename_collision(filename: str, asset_id: str, taken: set[str]) -> str:
    """If *filename* is already in *taken* under a different id, append an 8-hex sha256 suffix."""
    if filename not in taken:
        return filename
    stem, suffix = PurePosixPath(filename).stem, PurePosixPath(filename).suffix
    short = hashlib.sha256(asset_id.encode()).hexdigest()[:8]
    return f"{stem}_{short}{suffix}"

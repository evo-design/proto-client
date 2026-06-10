"""Sync asset download helpers."""

import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import httpx

from proto_client._assets import (
    AssetLike,
    asset_url,
    decode_asset_bytes,
    origin_of,
    redirect_location,
    strip_sensitive_redirect_headers,
)
from proto_client.errors import from_response
from proto_client.models import AssetRef

logger = logging.getLogger("proto_client.assets")


class AssetsNamespace:
    """Fetch API-readable output assets via the URL stamped on each ``AssetRef``.

    A single namespace serves refs from configured Proto API origins; routing is
    by URL origin matched against each client's ``base_url``. Refs without an
    API-readable URL are not generally fetchable through this namespace.
    """

    def __init__(self, http_clients: list[httpx.Client]) -> None:
        """Initialize with the set of authenticated httpx Clients to route over."""
        self._clients_by_origin = {origin_of(str(c.base_url)): c for c in http_clients}

    def get(self, ref: AssetLike) -> bytes:
        """Fetch exact stored asset bytes into memory."""
        buffer = BytesIO()
        self._write_to(ref, buffer)
        return buffer.getvalue()

    def decode(self, ref: AssetLike) -> object:
        """Fetch and decode an asset by MIME type.

        JSON assets become Python values, chemical/text assets become strings,
        and unknown MIME types remain bytes. This loads the full asset into
        memory.
        """
        return decode_asset_bytes(ref, self.get(ref))

    def download(self, ref: AssetLike, path: str | Path) -> Path:
        """Stream exact stored asset bytes to ``path``."""
        destination = Path(path)
        with destination.open("wb") as file:
            self._write_to(ref, file)
        return destination

    def _write_to(self, ref: AssetLike, file: BinaryIO) -> None:
        with self._stream(ref) as resp:
            file.writelines(resp.iter_bytes())

    @contextmanager
    def _stream(self, ref: AssetLike) -> Iterator[httpx.Response]:
        url = asset_url(ref)
        client = self._client_for(url)
        with client.stream("GET", url, follow_redirects=False) as resp:
            if not resp.is_redirect:
                if resp.is_error:
                    resp.read()
                    raise from_response(resp)
                yield resp
                return
            location = redirect_location(resp, url)

        # Strip auth on every redirect (safe default — same-origin redirects don't exist today).
        request = client.build_request("GET", location)
        strip_sensitive_redirect_headers(request)
        redirected = client.send(request, stream=True, follow_redirects=True)
        try:
            if redirected.is_error:
                redirected.read()
                raise RuntimeError(
                    f"Storage backend HTTP {redirected.status_code} at {location!r} (not a Proto API error)"
                ) from from_response(redirected)
            yield redirected
        finally:
            redirected.close()

    def _client_for(self, url: str) -> httpx.Client:
        origin = origin_of(url)
        client = self._clients_by_origin.get(origin)
        if client is None:
            raise ValueError(
                f"AssetRef URL {url!r} doesn't match any configured base URL "
                f"({sorted(self._clients_by_origin)})."
            )
        return client


# Module-level default so AssetRef.{resolve,bytes,decode} can reach the client.
_default_assets: AssetsNamespace | None = None


def set_default_assets_namespace(ns: AssetsNamespace) -> None:
    """Register *ns* as the default; last-writer-wins, with a warning when overwriting a different namespace."""
    global _default_assets  # noqa: PLW0603 — module-level singleton is the design
    if _default_assets is not None and _default_assets is not ns:
        logger.warning(
            "Replacing existing default AssetsNamespace. AssetRef.resolve/bytes/decode "
            "will now route through the newly-registered namespace.",
        )
    _default_assets = ns


def get_default_assets_namespace() -> AssetsNamespace:
    """Return the registered default namespace, or raise if none is set."""
    if _default_assets is None:
        raise RuntimeError(
            "No default AssetsNamespace registered. AssetRef.resolve/bytes/decode "
            "need a sync ProtoClient() to register itself; AsyncProtoClient does not "
            "(use `await client.assets.download(ref, path)` directly), or call "
            "set_default_assets_namespace(...) manually."
        )
    return _default_assets


def default_cache_dir() -> Path:
    """Cache root: ``$PROTO_ASSET_CACHE`` or ``~/.cache/evo-design/assets``."""
    return Path(os.environ.get("PROTO_ASSET_CACHE", str(Path.home() / ".cache" / "proto-bio" / "assets")))


def download_to_cache(ref: AssetLike, cache_dir: Path | None = None) -> Path:
    """Download *ref* to a content-addressed local cache (atomic write); return the path."""
    if isinstance(ref, dict):
        ref = AssetRef.model_validate(ref)
    target_dir = cache_dir if cache_dir is not None else default_cache_dir()
    target_dir.mkdir(parents=True, exist_ok=True)
    dest = target_dir / ref.suggested_filename()
    if not dest.exists():
        tmp = dest.with_suffix(dest.suffix + f".tmp.{os.getpid()}")
        try:
            get_default_assets_namespace().download(ref, tmp)
            tmp.replace(dest)
        finally:
            tmp.unlink(missing_ok=True)
    return dest

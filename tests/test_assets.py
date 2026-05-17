"""AssetRef and lazy asset download tests."""

import gzip
import json
from pathlib import Path

import httpx
import pytest
from helpers import make_sync_tools_ns
from pydantic import BaseModel, ValidationError

from proto_client import AssetRef
from proto_client._async.assets import AsyncAssetsNamespace
from proto_client.assets import AssetsNamespace
from proto_client.errors import ProtoNotFoundError


def _sync(handler, base_url: str = "https://api.test") -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=base_url,
        headers={"X-API-Key": "secret"},
    )


def _ref(url: str = "https://api.test/api/v1/assets/asset_x") -> dict:
    return {"id": "asset_x", "kind": "output", "url": url}


def test_asset_ref_requires_nonempty_id() -> None:
    AssetRef(id="asset_x", kind="output")
    with pytest.raises(ValidationError):
        AssetRef(id="", kind="output")


def test_decode_json_gzip_asset_explicitly() -> None:
    ref = {
        "id": "asset_x",
        "kind": "output",
        "mime_type": "application/json+gzip",
        "url": "https://api.test/api/v1/assets/asset_x",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/assets/asset_x"
        return httpx.Response(200, content=gzip.compress(json.dumps([[1.0, 2.0]]).encode(), mtime=0))

    with _sync(handler) as http:
        assert AssetsNamespace([http]).decode(ref) == [[1.0, 2.0]]


async def test_async_decode_text_asset_explicitly() -> None:
    ref = {
        "id": "asset_x",
        "kind": "output",
        "mime_type": "chemical/x-pdb",
        "url": "https://api.test/api/v1/assets/asset_x",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/assets/asset_x"
        return httpx.Response(200, content=b"ATOM      1\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test") as http:
        assert await AsyncAssetsNamespace([http]).decode(ref) == "ATOM      1\n"


def test_download_follows_redirect_and_strips_auth(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.test":
            assert request.headers["x-api-key"] == "secret"
            return httpx.Response(307, headers={"location": "https://files.test/x"})
        assert "x-api-key" not in request.headers
        return httpx.Response(200, content=b"bytes")

    with _sync(handler) as http:
        out = AssetsNamespace([http]).download(_ref(), tmp_path / "x")
    assert out.read_bytes() == b"bytes"


def test_routes_by_url_origin_across_clients() -> None:
    def tools_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"from-tools")

    def runs_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"from-runs")

    with _sync(tools_handler, "https://tools.test") as t, _sync(runs_handler, "https://runs.test") as r:
        ns = AssetsNamespace([t, r])
        assert ns.get(_ref("https://tools.test/api/v1/assets/a")) == b"from-tools"
        assert ns.get(_ref("https://runs.test/api/v1/assets/b")) == b"from-runs"


def test_unknown_origin_raises_clear_error() -> None:
    with _sync(lambda _r: httpx.Response(200)) as http:
        with pytest.raises(ValueError, match="doesn't match any configured base URL"):
            AssetsNamespace([http]).get(_ref("https://other.test/x"))


def test_missing_url_raises_clear_error() -> None:
    with _sync(lambda _r: httpx.Response(200)) as http:
        with pytest.raises(ValueError, match="no `url`"):
            AssetsNamespace([http]).get({"id": "asset_x", "kind": "output"})


def test_404_raises_typed_error() -> None:
    with _sync(lambda _r: httpx.Response(404, json={"detail": "not found"})) as http:
        with pytest.raises(ProtoNotFoundError):
            AssetsNamespace([http]).get(_ref())


def test_origin_match_ignores_default_ports() -> None:
    """URL with explicit :443 must match a client whose base_url has no port."""
    from proto_client._assets import origin_of

    assert origin_of("https://api.test:443/api/v1/assets/x") == "https://api.test"
    assert origin_of("http://api.test:80/x") == "http://api.test"
    assert origin_of("https://api.test:8443/x") == "https://api.test:8443"


def test_redirect_target_error_raises_storage_error_not_auth_error() -> None:
    """A redirected asset fetch failure must not surface as ProtoAuthError."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.test":
            return httpx.Response(307, headers={"location": "https://files.test/expired"})
        return httpx.Response(403, content=b"<Error>AccessDenied</Error>")

    with _sync(handler) as http:
        with pytest.raises(RuntimeError, match="not a Proto API error"):
            AssetsNamespace([http]).get(_ref())


def test_user_output_model_parses_asset_refs_in_results() -> None:
    """Users define typed output models with ``AssetRef`` fields; pydantic parses dict shapes."""

    class Score(BaseModel):
        logits: AssetRef

    class Output(BaseModel):
        scores: list[Score]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(202, json={"job_id": "j1", "status": "pending"})
        return httpx.Response(
            200,
            json={
                "job_id": "j1",
                "tool_key": "evo2-score",
                "status": "completed",
                "result": {"scores": [{"logits": {"id": "asset_x", "kind": "output"}}]},
                "error": None,
                "created_at": "2026-04-05T12:00:00",
                "completed_at": "2026-04-05T12:00:05",
            },
        )

    result = make_sync_tools_ns(handler).run("evo2-score", {}, poll_interval=0.01, output_model=Output)
    assert result.result.scores[0].logits == AssetRef(id="asset_x", kind="output")


def test_output_model_does_not_materialize_asset_refs_implicitly() -> None:
    class Score(BaseModel):
        logits: list[list[float]]

    class Output(BaseModel):
        scores: list[Score]

    ref = {
        "id": "asset_x",
        "kind": "output",
        "mime_type": "application/json+gzip",
        "url": "https://api.test/api/v1/assets/asset_x",
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/tools/evo2-score/run":
            return httpx.Response(202, json={"job_id": "j1", "status": "pending"})
        assert request.url.path != "/api/v1/assets/asset_x"
        return httpx.Response(
            200,
            json={
                "job_id": "j1",
                "tool_key": "evo2-score",
                "status": "completed",
                "result": {"scores": [{"logits": ref}]},
                "error": None,
                "created_at": "2026-04-05T12:00:00",
                "completed_at": "2026-04-05T12:00:05",
            },
        )

    with pytest.raises(TypeError, match="does not conform"):
        make_sync_tools_ns(handler).run("evo2-score", {}, poll_interval=0.01, output_model=Output)


async def test_async_download_parity(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"async-bytes")

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url="https://api.test",
        headers={"X-API-Key": "secret"},
    ) as http:
        out = await AsyncAssetsNamespace([http]).download(_ref(), tmp_path / "x")
    assert out.read_bytes() == b"async-bytes"


# =============================================================================
# AssetRef instance methods + default-namespace plumbing
# =============================================================================


def test_suggested_filename_prefers_filename_field_then_mime_ext() -> None:
    explicit = AssetRef(id="asset_x", kind="output", filename="my.pdb")
    assert explicit.suggested_filename() == "my.pdb"

    pdb = AssetRef(id="asset_x", kind="output", mime_type="chemical/x-pdb")
    assert pdb.suggested_filename() == "asset_x.pdb"

    unknown = AssetRef(id="asset_x", kind="output", mime_type="x/unknown")
    assert unknown.suggested_filename() == "asset_x"

    # Path traversal via the filename field is neutralized.
    traversal = AssetRef(id="asset_x", kind="output", filename="../../etc/passwd", mime_type="chemical/x-pdb")
    assert traversal.suggested_filename() == "passwd"

    # Bare `.` / `..` fall back to the id-based name.
    bare = AssetRef(id="asset_x", kind="output", filename="..", mime_type="chemical/x-pdb")
    assert bare.suggested_filename() == "asset_x.pdb"


def test_ext_for_mime_covers_common_types() -> None:
    from proto_client._assets import ext_for_mime

    assert ext_for_mime("chemical/x-pdb") == ".pdb"
    assert ext_for_mime("chemical/x-cif") == ".cif"
    assert ext_for_mime("application/json+gzip") == ".json.gz"
    assert ext_for_mime("application/vnd.foo+json") == ".json"
    assert ext_for_mime("application/x-bar+gzip") == ".gz"
    assert ext_for_mime(None) == ""
    assert ext_for_mime("x/unknown") == ""


def test_repr_html_includes_id_mime_and_size_and_escapes_against_xss() -> None:
    ref = AssetRef(
        id="asset_abc",
        kind="output",
        mime_type="chemical/x-pdb",
        size_bytes=12_345,
        url="https://api.test/api/v1/assets/asset_abc",
    )
    rendered = ref._repr_html_()
    assert "asset_abc" in rendered
    assert "chemical/x-pdb" in rendered
    assert "12.3 KB" in rendered
    assert 'href="https://api.test' in rendered

    # XSS: a tampered URL must not break out of the href attribute.
    malicious = AssetRef(
        id="<script>alert(1)</script>",
        kind="output",
        url='" onclick="alert(1)',
    )
    rendered = malicious._repr_html_()
    assert "<script>" not in rendered
    assert '" onclick=' not in rendered
    assert "&lt;script&gt;" in rendered


def test_assetref_methods_require_default_namespace(tmp_path: Path) -> None:
    """Without ProtoClient() / set_default_assets_namespace(), AssetRef.* raises clearly."""
    import proto_client.assets as assets_mod

    saved = assets_mod._default_assets
    assets_mod._default_assets = None
    try:
        ref = AssetRef(id="asset_x", kind="output", url="https://api.test/api/v1/assets/asset_x")
        with pytest.raises(RuntimeError, match="No default AssetsNamespace"):
            ref.bytes()
        with pytest.raises(RuntimeError, match="No default AssetsNamespace"):
            ref.resolve(cache_dir=tmp_path)
    finally:
        assets_mod._default_assets = saved


def test_resolve_uses_cache_dir_and_skips_redownload(tmp_path: Path) -> None:
    """Second resolve() reuses the cached file — no second HTTP fetch."""
    import proto_client.assets as assets_mod

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, content=b"PDB-BYTES")

    saved = assets_mod._default_assets
    with _sync(handler) as http:
        ns = AssetsNamespace([http])
        assets_mod.set_default_assets_namespace(ns)
        try:
            ref = AssetRef(
                id="asset_x",
                kind="output",
                mime_type="chemical/x-pdb",
                url="https://api.test/api/v1/assets/asset_x",
            )
            first = ref.resolve(cache_dir=tmp_path)
            second = ref.resolve(cache_dir=tmp_path)
        finally:
            assets_mod._default_assets = saved

    assert first == second == tmp_path / "asset_x.pdb"
    assert first.read_bytes() == b"PDB-BYTES"
    assert calls["n"] == 1  # cache hit on the second call


def test_bytes_and_decode_route_through_default_namespace() -> None:
    import proto_client.assets as assets_mod

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b'{"k":1}')

    saved = assets_mod._default_assets
    with _sync(handler) as http:
        assets_mod.set_default_assets_namespace(AssetsNamespace([http]))
        try:
            ref = AssetRef(
                id="asset_x",
                kind="output",
                mime_type="application/json",
                url="https://api.test/api/v1/assets/asset_x",
            )
            assert ref.bytes() == b'{"k":1}'
            assert ref.decode() == {"k": 1}
        finally:
            assets_mod._default_assets = saved


def test_download_to_cache_validates_dict_input(tmp_path: Path) -> None:
    """download_to_cache accepts the JSON-dict form of an AssetRef, not just the model."""
    import proto_client.assets as assets_mod

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"raw-bytes")

    saved = assets_mod._default_assets
    with _sync(handler) as http:
        assets_mod.set_default_assets_namespace(AssetsNamespace([http]))
        try:
            ref_dict = {
                "id": "asset_y",
                "kind": "output",
                "mime_type": "chemical/x-pdb",
                "url": "https://api.test/api/v1/assets/asset_y",
            }
            path = assets_mod.download_to_cache(ref_dict, cache_dir=tmp_path)
        finally:
            assets_mod._default_assets = saved

    assert path == tmp_path / "asset_y.pdb"
    assert path.read_bytes() == b"raw-bytes"


def test_default_cache_dir_honours_env(monkeypatch, tmp_path: Path) -> None:
    """PROTO_ASSET_CACHE env var overrides the default ~/.cache/evo-design/assets location."""
    import proto_client.assets as assets_mod

    monkeypatch.setenv("PROTO_ASSET_CACHE", str(tmp_path / "custom"))
    assert assets_mod.default_cache_dir() == tmp_path / "custom"

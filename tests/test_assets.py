"""AssetRef and lazy asset download tests."""

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
    """S3 403 (expired presigned URL) must not surface as ProtoAuthError."""

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

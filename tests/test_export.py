"""Tests for ProtoClient.export_program: walks the in-memory dict for AssetRefs, downloads bytes, delegates to proto-language."""

import pytest

pytest.importorskip("numpy")
pytest.importorskip("proto_language")

from pathlib import Path
from types import SimpleNamespace

import httpx
import numpy as np

from proto_client import AsyncProtoClient, ProtoClient
from proto_client._async.assets import AsyncAssetsNamespace
from proto_client._async.client import _amaterialize_assetrefs
from proto_client.assets import AssetsNamespace
from proto_client.client import _materialize_assetrefs
from proto_client.models import AssetRef
from proto_client.utils.asset_helpers import coerce_assetref, resolve_filename_collision


def _mock_http(handler, base_url: str = "https://api.test") -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url=base_url,
        headers={"X-API-Key": "secret"},
    )


def _fake_structure(pdb_text: str = "ATOM      1\n", fmt: str = "pdb") -> SimpleNamespace:
    """Duck-typed stand-in for proto_tools Structure: needs ``.structure`` and ``.structure_format``."""
    return SimpleNamespace(structure=pdb_text, structure_format=fmt)


def _make_results_with_payloads() -> dict:
    """One result, two segments: seg0 with _structure/_logits + AssetRef-shaped cell; seg1 plain."""
    asset_dict = {
        "id": "asset_extra",
        "kind": "output",
        "mime_type": "chemical/x-pdb",
        "url": "https://api.test/api/v1/assets/asset_extra",
    }
    return {
        "results": [
            {
                "result_idx": 0,
                "energy_score": 0.42,
                "constructs": [
                    {
                        "label": "c0",
                        "type": "protein",
                        "segments": [
                            {
                                "label": "seg0",
                                "sequence": "EVQLV",
                                "constraints": {
                                    "esmfold": {
                                        "score": 0.9,
                                        "weight": 1.0,
                                        "weighted_score": 0.9,
                                        "data": {"extra_struct": asset_dict},
                                    },
                                },
                                "generators": {},
                                "metadata": {},
                                "_structure": _fake_structure(),
                                "_logits": np.zeros((5, 20), dtype=np.float32),
                            },
                            {
                                "label": "seg1",
                                "sequence": "MKTAY",
                                "constraints": {},
                                "generators": {},
                                "metadata": {},
                            },
                        ],
                    }
                ],
            }
        ],
        "best_result_idx": 0,
    }


def test_coerce_to_assetref_recognizes_typed_and_dict_forms() -> None:
    """Typed AssetRef passes through; dict-shaped values validate; non-AssetRef shapes return None."""
    typed = AssetRef(id="asset_x", kind="output")
    assert coerce_assetref(typed) is typed
    assert coerce_assetref({"id": "asset_x", "kind": "output"}) == typed
    # Rejection branches that protect constraint cells.
    assert coerce_assetref({"id": "asset_x", "kind": "bogus"}) is None
    assert coerce_assetref({"score": 0.5, "data": {}}) is None
    assert coerce_assetref({"id": 42, "kind": "output"}) is None
    assert coerce_assetref(None) is None


def test_resolve_filename_collision_adds_sha_suffix() -> None:
    """Distinct asset ids sharing a filename get an 8-hex sha256 suffix on the second."""
    assert resolve_filename_collision("a.pdb", "asset_x", set()) == "a.pdb"
    out = resolve_filename_collision("a.pdb", "asset_x", {"a.pdb"})
    assert out.startswith("a_") and out.endswith(".pdb") and len(out) == len("a_xxxxxxxx.pdb")


def test_materialize_assetrefs_dedupes_by_id_and_writes_bytes(tmp_path: Path) -> None:
    """Same asset id seen twice yields one file; bytes are fetched once."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=b"BYTES")

    ref = {"id": "asset_x", "kind": "output", "url": "https://api.test/api/v1/assets/asset_x"}
    payload = {"a": ref, "nested": [ref, {"unrelated": 1.2}]}

    with _mock_http(handler) as http:
        out = _materialize_assetrefs(payload, AssetsNamespace([http]), tmp_path, {})

    assert out == {"a": "assets/asset_x", "nested": ["assets/asset_x", {"unrelated": 1.2}]}
    assert (tmp_path / "asset_x").read_bytes() == b"BYTES"
    assert len(calls) == 1


def test_materialize_assetrefs_writes_placeholder_on_http_error(tmp_path: Path) -> None:
    """A 5xx during the fetch becomes a ``<name>.missing`` 0-byte placeholder, not an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"boom")

    ref = {
        "id": "asset_x",
        "kind": "output",
        "mime_type": "chemical/x-pdb",
        "url": "https://api.test/api/v1/assets/asset_x",
    }

    with _mock_http(handler) as http:
        out = _materialize_assetrefs({"r": ref}, AssetsNamespace([http]), tmp_path, {})

    assert out == {"r": "assets/asset_x.pdb.missing"}
    assert (tmp_path / "asset_x.pdb.missing").stat().st_size == 0


class _FakeProgram:
    """Minimal duck-type for ProtoClient.export_program (skips the real Program/Construct graph)."""

    def __init__(self, results: dict) -> None:
        self._results = results
        self.energy_scores = [r.get("energy_score") for r in results.get("results", [])]

    def extract_results(self, energy_scores: list[float]) -> dict:
        import copy

        return copy.deepcopy(self._results)


@pytest.mark.timeout(30)  # generous: first call pays the one-time proto-language import cost
def test_export_program_writes_folder_layout(tmp_path: Path) -> None:
    """End-to-end: structures + logits + downloaded AssetRef + all 4 tables under *path*."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"REMOTE-PDB")

    client = ProtoClient(api_key="x")
    mock_http = _mock_http(handler)
    try:
        client.assets = AssetsNamespace([mock_http])
        program = _FakeProgram(_make_results_with_payloads())
        out = client.export_program(program, tmp_path / "out", format="csv")
    finally:
        mock_http.close()
        client.close()

    assert out == tmp_path / "out"
    for name in ("sequences", "constraints", "constructs", "optimization"):
        assert (out / f"{name}.csv").exists()
    assert (out / "sequences.fasta").exists()
    assert (out / "assets" / "res0_con0_seg0_structure.pdb").exists()
    assert (out / "assets" / "res0_con0_seg0_logits.npy").exists()
    assert (out / "assets" / "asset_extra.pdb").read_bytes() == b"REMOTE-PDB"

    constraints_csv = (out / "constraints.csv").read_text()
    assert "assets/asset_extra.pdb" in constraints_csv
    sequences_csv = (out / "sequences.csv").read_text()
    assert "structure_path" in sequences_csv
    assert "assets/res0_con0_seg0_structure.pdb" in sequences_csv


async def test_amaterialize_assetrefs_dedupes_by_id_and_writes_bytes(tmp_path: Path) -> None:
    """Async materializer: same asset id seen twice yields one file; bytes fetched once."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, content=b"BYTES")

    ref = {"id": "asset_x", "kind": "output", "url": "https://api.test/api/v1/assets/asset_x"}
    payload = {"a": ref, "nested": [ref, {"unrelated": 1.2}]}

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test") as http:
        out = await _amaterialize_assetrefs(payload, AsyncAssetsNamespace([http]), tmp_path, {})

    assert out == {"a": "assets/asset_x", "nested": ["assets/asset_x", {"unrelated": 1.2}]}
    assert (tmp_path / "asset_x").read_bytes() == b"BYTES"
    assert len(calls) == 1


@pytest.mark.timeout(30)  # generous: first call pays the one-time proto-language import cost
async def test_async_export_program_writes_folder_layout(tmp_path: Path) -> None:
    """Async export_program produces the same folder layout as the sync version."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"REMOTE-PDB")

    client = AsyncProtoClient(api_key="x")
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://api.test")
    try:
        client.assets = AsyncAssetsNamespace([http])
        program = _FakeProgram(_make_results_with_payloads())
        out = await client.export_program(program, tmp_path / "out", format="csv")
    finally:
        await http.aclose()
        await client.aclose()

    assert out == tmp_path / "out"
    for name in ("sequences", "constraints", "constructs", "optimization"):
        assert (out / f"{name}.csv").exists()
    assert (out / "sequences.fasta").exists()
    assert (out / "assets" / "res0_con0_seg0_structure.pdb").exists()
    assert (out / "assets" / "asset_extra.pdb").read_bytes() == b"REMOTE-PDB"

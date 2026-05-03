"""Tests for MCP resource implementations and registration."""

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastmcp import FastMCP

from proto_client.errors import ProtoNotFoundError
from proto_client.mcp.resources import (
    constraint_doc_impl,
    generator_doc_impl,
    optimizer_doc_impl,
    register_resources,
    tool_citation_resource,
    tool_citation_resource_impl,
    tool_doc,
    tool_doc_impl,
    tool_schema_resource,
    tool_schema_resource_impl,
)
from proto_client.models import (
    ConstraintSpec,
    GeneratorSpec,
    OptimizerSpec,
    ToolExample,
    ToolInfo,
    ToolSchema,
)


@pytest.fixture
def client_with_specs():
    client = AsyncMock()
    client.runs.list_constraints.return_value = [
        ConstraintSpec(
            key="gc-content",
            label="GC Content",
            description="Filter by GC%",
            uses_gpu=False,
            config_model={"properties": {"min_gc": {"type": "number"}}},
            tools_called=[],
            supported_sequence_types=["dna"],
            category="composition",
        ),
    ]
    client.runs.list_generators.return_value = [
        GeneratorSpec(
            key="random-dna",
            label="Random DNA",
            description="Random nucleotides",
            uses_gpu=False,
            config_model={"properties": {"length": {"type": "integer"}}},
            category="mutation",
            tools_called=[],
            supported_sequence_types=["dna"],
        ),
    ]
    client.runs.list_optimizers.return_value = [
        OptimizerSpec(
            key="mcmc",
            label="MCMC",
            description="Markov chain Monte Carlo",
            uses_gpu=False,
            config_model={"properties": {"steps": {"type": "integer"}}},
            targets_single_segment=True,
        ),
    ]
    return client


# Identifies (impl function, valid key, schema field, expected component_type label)
# for each of the three doc resources.
_DOC_CASES = [
    pytest.param(constraint_doc_impl, "gc-content", "min_gc", "constraint", id="constraint"),
    pytest.param(generator_doc_impl, "random-dna", "length", "generator", id="generator"),
    pytest.param(optimizer_doc_impl, "mcmc", "steps", "optimizer", id="optimizer"),
]


@pytest.mark.parametrize(("impl", "key", "schema_field", "kind"), _DOC_CASES)
async def test_doc_renders_label_type_and_schema(client_with_specs, impl, key, schema_field, kind):
    """Each resource renders its spec's label, kind, description, and config schema."""
    doc = await impl(client_with_specs, key)
    assert key in doc
    assert f"Type: {kind}" in doc
    assert schema_field in doc  # JSON schema embedded


@pytest.mark.parametrize(("impl", "_key", "_schema_field", "kind"), _DOC_CASES)
async def test_doc_unknown_key_raises_proto_not_found(client_with_specs, impl, _key, _schema_field, kind):
    """``ProtoNotFoundError`` (not ``ValueError``) so ``_handle_proto_errors`` maps it to ``ResourceError``."""
    with pytest.raises(ProtoNotFoundError, match=f"Unknown {kind} 'missing'"):
        await impl(client_with_specs, "missing")


@pytest.fixture
def client_with_tools():
    client = AsyncMock()
    client.tools.list.return_value = [
        ToolInfo(
            key="esmfold-prediction",
            service="EsmFoldService",
            method="predict",
            label="ESMFold",
            category="structure_prediction",
            description="Predict protein structure",
            uses_gpu=True,
            citation="@article{esm2}",
            github_url="https://github.com/foo/bar",
        ),
    ]
    client.tools.get_schema.return_value = ToolSchema(
        inputs={"type": "object", "properties": {"sequences": {"type": "array"}}},
        config={"type": "object", "properties": {}},
        output={"type": "object", "properties": {"plddt": {"type": "number"}}},
    )
    client.tools.get_example.return_value = ToolExample(example_input={"sequences": ["MKTL"]})
    return client


async def test_tool_doc_renders_metadata_schemas_example_citation(client_with_tools):
    doc = await tool_doc_impl(client_with_tools, "esmfold-prediction")
    assert "esmfold-prediction" in doc
    assert "structure_prediction" in doc
    assert "## Input schema" in doc and "sequences" in doc
    assert "## Example input" in doc and "MKTL" in doc
    assert "## Citation" in doc and "esm2" in doc
    assert "GitHub" in doc  # link rendered


async def test_tool_schema_resource_returns_valid_json(client_with_tools):
    raw = await tool_schema_resource_impl(client_with_tools, "esmfold-prediction")
    parsed = json.loads(raw)
    assert set(parsed) == {"inputs", "config", "output"}


async def test_tool_citation_resource_returns_bibtex(client_with_tools):
    assert "esm2" in await tool_citation_resource_impl(client_with_tools, "esmfold-prediction")


async def test_tool_doc_unknown_key_raises_proto_not_found(client_with_tools):
    with pytest.raises(ProtoNotFoundError, match="Unknown tool 'missing'"):
        await tool_doc_impl(client_with_tools, "missing")


async def test_register_resources_attaches_full_surface():
    fresh_mcp = FastMCP("test-server")
    register_resources(fresh_mcp)
    registered = {t.uri_template for t in await fresh_mcp.list_resource_templates()}
    assert registered == {
        "bio://constraints/{key}",
        "bio://generators/{key}",
        "bio://optimizers/{key}",
        "proto-tools://tools/{key}",
        "proto-tools://schemas/{key}",
        "proto-tools://citations/{key}",
    }


@pytest.mark.parametrize("wrapper", [tool_doc, tool_schema_resource, tool_citation_resource])
async def test_proto_tools_resource_wrapper_routes_through_get_client(client_with_tools, wrapper):
    """Each new proto-tools:// wrapper routes through _get_client and returns a string."""

    @asynccontextmanager
    async def fake_get_client(_ctx):
        yield client_with_tools

    with patch("proto_client.mcp.resources._get_client", fake_get_client):
        result = await wrapper("esmfold-prediction", MagicMock())

    assert isinstance(result, str) and result

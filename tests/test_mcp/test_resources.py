"""Tests for MCP resource implementations and registration."""

from unittest.mock import AsyncMock

import pytest
from fastmcp import FastMCP

from proto_client.errors import ProtoNotFoundError
from proto_client.mcp.resources import (
    constraint_doc_impl,
    generator_doc_impl,
    optimizer_doc_impl,
    register_resources,
)
from proto_client.models import ConstraintSpec, GeneratorSpec, OptimizerSpec


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


async def test_register_resources_attaches_all_three_uri_templates():
    fresh_mcp = FastMCP("test-server")
    register_resources(fresh_mcp)
    registered = {t.uri_template for t in await fresh_mcp.list_resource_templates()}
    assert registered == {
        "bio://constraints/{key}",
        "bio://generators/{key}",
        "bio://optimizers/{key}",
    }

"""MCP prompts — reusable templates for program design, components, and tools.

- ``design_program`` embeds the live component catalog fetched via the API.
- ``implement_constraint`` and ``implement_generator`` are static code templates.
- ``find_tool`` and ``tool_walkthrough`` guide an LLM through tool discovery.
"""

import asyncio
from typing import Any

from fastmcp import Context, FastMCP
from fastmcp.exceptions import PromptError
from fastmcp.prompts import Message

from proto_client._async.client import AsyncProtoClient
from proto_client.mcp.tools import _get_client, _handle_proto_errors


async def _build_component_summary(client: AsyncProtoClient) -> str:
    """Render a markdown summary of every constraint/generator/optimizer."""
    constraints, generators, optimizers = await asyncio.gather(
        client.runs.list_constraints(),
        client.runs.list_generators(),
        client.runs.list_optimizers(),
    )

    def _render_section(label: str, specs: list[Any]) -> str:
        items: list[str] = []
        for spec in sorted(specs, key=lambda s: s.key):
            meta_parts: list[str] = []
            category = getattr(spec, "category", None)
            if category:
                meta_parts.append(f"category={category}")
            if spec.uses_gpu:
                meta_parts.append("GPU")
            meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
            items.append(f"  - **{spec.key}** — {spec.label}{meta}: {spec.description}")
        return f"### {label}\n" + "\n".join(items)

    sections = [
        _render_section("Optimizers", list(optimizers)),
        _render_section("Generators", list(generators)),
        _render_section("Constraints", list(constraints)),
    ]
    return "\n\n".join(sections)


# --- Prompt implementations ---


async def design_program_impl(client: AsyncProtoClient, goal: str, sequence_type: str = "dna") -> list[Message]:
    """Build the design-program prompt with the live component catalog."""
    component_summary = await _build_component_summary(client)

    # MCP's Message only supports user/assistant; the first acts as a preamble.
    preamble_content = f"""\
You are an expert biological programmer designing an optimization program.

# SYSTEM ARCHITECTURE

Proto Language is a constraint-based optimization framework for biological sequences.

**Object hierarchy:** Program > Optimizer stages > (Generators + Constraints) operating on Constructs > Segments > Sequences.

**Optimization loop:** Generate → Filter → Score → Select, repeated for N steps.

**JSON structure:**
```json
{{
  "num_results": 10,
  "constructs": [
    {{"id": "c1", "type": "{sequence_type}", "segments": [{{"id": "s1", "length": 100}}]}}
  ],
  "optimization_stages": [
    {{
      "generators": [{{"key": "...", "targets": ["s1"], "config": {{}}}}],
      "constraints": [{{"key": "...", "targets": ["s1"], "config": {{}}}}],
      "optimizer": {{"method": "...", "config": {{}}}}
    }}
  ]
}}
```

# AVAILABLE COMPONENTS

{component_summary}

# DESIGN WORKFLOW

1. **Decompose** the goal into constructs and segments.
2. **Choose optimizer**: rejection-sampling (exploration), mcmc (refinement), beam-search (autoregressive).
3. **Select generators** matching the sequence type and strategy.
4. **Layer constraints**: filters first (with threshold), then scoring constraints (with weights).
5. **Use list_components + get_tool_schema** to verify keys, parameters, and schemas.
6. **Use validate_program** to check the JSON before submission.
"""

    user_content = (
        f"Design a proto-language optimization program for the following goal:\n\n"
        f"**Goal:** {goal}\n"
        f"**Sequence type:** {sequence_type}\n\n"
        f"Follow the design workflow step by step. Use list_components, "
        f"get_tool_schema, and validate_program to verify your choices."
    )

    return [
        Message(preamble_content, role="user"),
        Message(user_content, role="user"),
    ]


def implement_constraint_impl(name: str, description: str, sequence_type: str = "dna") -> list[Message]:
    """Code template for a custom constraint."""
    config_class = name.replace("-", " ").title().replace(" ", "") + "Config"
    func_name = name.replace("-", "_")
    label = name.replace("-", " ").title()

    template = f"""\
Implement a custom constraint for the proto-language framework.

**Name:** {name}
**Description:** {description}
**Sequence type:** {sequence_type}
**Config class:** {config_class}

## Template

```python

import logging

from proto_language.utils.base import BaseConfig, ConfigField
from proto_language.core import Sequence
from proto_language.constraint.constraint_registry import constraint
from proto_language.utils import MAX_ENERGY

logger = logging.getLogger(__name__)


class {config_class}(BaseConfig):
    \"\"\"Configuration for {name} constraint.\"\"\"
    # Add config fields with ConfigField(default=..., description="...")
    pass


@constraint(
    key="{name}",
    label="{label}",
    config={config_class},
    description="{description}",
    supported_sequence_types=["{sequence_type}"],
    uses_gpu=False,
    tools_called=[],
)
def {func_name}_constraint(
    input_sequences: list[tuple[Sequence, ...]],
    config: {config_class},
) -> list[float]:
    \"\"\"
    Evaluate sequences for {description.lower()}.

    Scoring: 0.0 = perfect, 1.0 = worst, MAX_ENERGY = complete failure.
    \"\"\"
    scores = []
    for seq_tuple in input_sequences:
        seq = seq_tuple[0]
        
        score = 0.0
        seq._metadata["{func_name}"] = score
        scores.append(score)
    return scores
```

## Conventions
- Scores: 0.0 = perfect, 1.0 = worst, MAX_ENERGY for failure
- Store computed values in `seq._metadata["metric_name"]`
- Use `ConfigField` (not `Field`) for config parameters
- File goes in `proto_language/constraint/`
"""

    return [Message(template, role="user")]


def find_tool_impl(task: str) -> list[Message]:
    """Workflow prompt: pick the right bioinformatics tool for a task."""
    template = f"""\
Find the right bioinformatics tool for this task and explain how to call it.

**Task:** {task}

## Workflow

1. **Search** — call `search_tools(query="{task}")` for relevance-ranked candidates.
2. **Narrow (optional)** — call `list_tools(category=...)` or `list_tools(uses_gpu=...)` to
   browse a category or filter by compute.
3. **Inspect** — for the top 1-3 results, call `get_tool_schema(tool_key)` to see the
   input/config/output contract.
4. **Try** — call `get_tool_example(tool_key)` for a runnable input dict.
5. **Recommend** — pick the best tool and show the user a Python snippet using
   `client.tools.run(tool_key, inputs)` or the `run_tool` MCP tool.

If no tool matches, say so explicitly rather than recommending a poor fit.
"""
    return [Message(template, role="user")]


def tool_walkthrough_impl(tool_key: str) -> list[Message]:
    """Workflow prompt: walk a user through a single bioinformatics tool."""
    template = f"""\
Give a complete walkthrough of `{tool_key}`.

## Workflow

1. Call `get_tool_schema("{tool_key}")` to fetch the input, config, and output
   JSON Schemas.
2. Call `get_tool_example("{tool_key}")` for a minimal runnable input.
3. Read `proto-tools://citations/{tool_key}` for the BibTeX entry (may be a placeholder).
4. Read `proto-tools://tools/{tool_key}` for an assembled metadata view (label,
   schemas, example, citation, and links).

Then present the walkthrough:

- One-sentence purpose.
- Required vs optional input fields, with types.
- Config fields with their defaults.
- A runnable Python example calling `client.tools.run("{tool_key}", inputs, config)`.
- Citation, if available.
"""
    return [Message(template, role="user")]


_CATEGORY_TO_INPUT_TYPE: dict[str, str] = {
    "mutation": "STARTING_SEQUENCE",
    "autoregressive": "PROMPT",
    "inverse_folding": "STRUCTURE",
    "gradient": "LOGITS",
}


def implement_generator_impl(name: str, description: str, category: str = "mutation") -> list[Message]:
    """Code template for a custom generator class."""
    config_class = name.replace("-", " ").title().replace(" ", "") + "Config"
    class_name = name.replace("-", " ").title().replace(" ", "") + "Generator"
    label = name.replace("-", " ").title()
    input_type_member = _CATEGORY_TO_INPUT_TYPE.get(category, "STARTING_SEQUENCE")

    template = f"""\
Implement a custom generator for the proto-language framework.

**Name:** {name}
**Description:** {description}
**Category:** {category} (input_type = `GeneratorInputType.{input_type_member}`)
**Config class:** {config_class}
**Generator class:** {class_name}

## Template

```python

import logging
from typing import final

from proto_language.utils.base import BaseConfig, ConfigField
from proto_language.core import Generator, GeneratorInputType, Segment
from proto_language.generator.generator_registry import generator

logger = logging.getLogger(__name__)


class {config_class}(BaseConfig):
    \"\"\"Configuration for {name} generator.\"\"\"
    # Add config fields with ConfigField(default=..., description="...")
    pass


@generator(
    key="{name}",
    label="{label}",
    config={config_class},
    description="{description}",
    uses_gpu=False,
    tools_called=[],
)
@final
class {class_name}(Generator):
    \"\"\"
    {description}
    \"\"\"

    input_type = GeneratorInputType.{input_type_member}

    def __init__(self, config: {config_class}):
        super().__init__(config)

    def _sample(self) -> None:
        \"\"\"Generate new proposal sequences.\"\"\"
        segment = self.segment
        for seq in segment.proposal_sequences:
            
            pass
```

## Conventions
- Implement `_sample()`, not `sample()`; the base class validates assignment and calls `_sample()`.
- Use `self.segment` for single-target generators, or `self.segments` for tied multi-target generators.
- `_sample()` modifies `proposal_sequences` **in-place**, returns None.
- Use `@final` decorator to prevent subclassing.
- Declare `input_type` as a classvar; category is auto-derived. Map category → input_type:
  - `"mutation"` → `GeneratorInputType.STARTING_SEQUENCE` (segment must carry a starting sequence)
  - `"autoregressive"` → `GeneratorInputType.PROMPT` (config.prompts or pipeline-supplied)
  - `"inverse_folding"` → `GeneratorInputType.STRUCTURE` (config.structure_inputs or pipeline-supplied)
  - `"gradient"` → `GeneratorInputType.LOGITS` (consumed from an upstream GradientOptimizer stage)
- For generators that take dynamic conditioning data via CyclingOptimizer, the conditioning kwarg
  must be the first non-self positional argument of `_sample()`.
- File goes in `proto_language/generator/`.
"""

    return [Message(template, role="user")]


# --- Prompt handlers ---


@_handle_proto_errors(error_cls=PromptError)
async def design_program(goal: str, ctx: Context, sequence_type: str = "dna") -> list[Message]:
    """Design a proto-language optimization program with live components."""
    async with _get_client(ctx) as client:
        return await design_program_impl(client, goal, sequence_type)


def implement_constraint(name: str, description: str, sequence_type: str = "dna") -> list[Message]:
    """Code template for a custom constraint."""
    return implement_constraint_impl(name, description, sequence_type)


def implement_generator(name: str, description: str, category: str = "mutation") -> list[Message]:
    """Code template for a custom generator class."""
    return implement_generator_impl(name, description, category)


def find_tool(task: str) -> list[Message]:
    """Workflow prompt: pick the right bioinformatics tool for a task."""
    return find_tool_impl(task)


def tool_walkthrough(tool_key: str) -> list[Message]:
    """Workflow prompt: walk a user through a single bioinformatics tool."""
    return tool_walkthrough_impl(tool_key)


# --- Registration ---


def register_prompts(mcp: FastMCP) -> None:
    """Register MCP prompts on the given FastMCP instance."""
    mcp.prompt(
        description=(
            "Guide an LLM through designing a proto-language optimization program. "
            "Returns a structured prompt with system architecture, the live "
            "components catalog, and a step-by-step design workflow."
        ),
    )(design_program)

    mcp.prompt(
        description=(
            "Template for implementing a custom constraint function with all "
            "proto-language conventions (decorator, config class, scoring)."
        ),
    )(implement_constraint)

    mcp.prompt(
        description=(
            "Template for implementing a custom generator class with all "
            "proto-language conventions (ABC contract, decorator, categories)."
        ),
    )(implement_generator)

    mcp.prompt(
        description=(
            "Workflow for finding the right bioinformatics tool for a user's task. "
            "Guides through list_categories, search_tools, get_tool_schema, get_tool_example."
        ),
    )(find_tool)

    mcp.prompt(
        description=(
            "Workflow for walking a user through a single bioinformatics tool — "
            "schema, example input, citation, and a runnable Python snippet."
        ),
    )(tool_walkthrough)

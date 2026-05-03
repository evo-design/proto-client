"""MCP prompts — reusable templates for program design and component implementation.

- ``design_program`` embeds the live component catalog fetched via the API.
- ``implement_constraint`` and ``implement_generator`` are static code templates.
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
      "generators": [{{"key": "...", "target": "s1", "config": {{}}}}],
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

from proto_language.base_config import BaseConfig, ConfigField
from proto_language.language.core import Sequence
from proto_language.language.constraint.constraint_registry import constraint
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
- File goes in `proto_language/language/constraint/`
"""

    return [Message(template, role="user")]


def implement_generator_impl(name: str, description: str, category: str = "mutation") -> list[Message]:
    """Code template for a custom generator class."""
    config_class = name.replace("-", " ").title().replace(" ", "") + "Config"
    class_name = name.replace("-", " ").title().replace(" ", "") + "Generator"
    label = name.replace("-", " ").title()

    template = f"""\
Implement a custom generator for the proto-language framework.

**Name:** {name}
**Description:** {description}
**Category:** {category}
**Config class:** {config_class}
**Generator class:** {class_name}

## Template

```python

import logging
from typing import final

from proto_language.base_config import BaseConfig, ConfigField
from proto_language.language.core import Generator, Segment
from proto_language.language.generator.generator_registry import generator

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
    category="{category}",
    uses_gpu=False,
    tools_called=[],
)
@final
class {class_name}(Generator):
    \"\"\"
    {description}
    \"\"\"

    def __init__(self, config: {config_class}):
        super().__init__(config)

    def sample(self) -> None:
        \"\"\"Generate new proposal sequences.\"\"\"
        self._validate_generator()
        segment = self._assigned_segment
        for seq in segment.proposal_sequences:
            
            pass
```

## Conventions
- `sample()` modifies `proposal_sequences` **in-place**, returns None
- Call `self._validate_generator()` at the start of `sample()`
- Use `@final` decorator to prevent subclassing
- Categories: "mutation" (refine), "autoregressive" (generate), "inverse_folding" (structure→sequence)
- File goes in `proto_language/language/generator/`
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

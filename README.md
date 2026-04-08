[![Unit Tests](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/unit-tests.yml)
[![Checks](https://github.com/evo-design/proto-client/actions/workflows/checks.yml/badge.svg)](https://github.com/evo-design/proto-client/actions/workflows/checks.yml)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?logo=discord&logoColor=white)](https://discord.gg/evs3Unkegv)

# proto-client

Python SDK for Proto Bio APIs.

## Related Repositories

- [`proto-language`](https://github.com/evo-design/proto-language) – Core language framework (constraints, generators, optimizers)
- [`proto-tools`](https://github.com/evo-design/proto-tools) – Bioinformatics tool wrappers with isolated environments

## Install

```bash
pip install proto-client
```

## Usage

```python
from proto_client import ProtoClient

client = ProtoClient(api_key="...")

# Run a tool (the tools API)
result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})

# Submit an optimization run and poll to completion (the runs API)
run = client.runs.run(program_data={...})
```

### Async

```python
from proto_client import AsyncProtoClient

async with AsyncProtoClient(api_key="...") as client:
    run = await client.runs.create(program_data={...})
    status = await client.runs.get(run["run_id"])
```

Set `PROTO_API_KEY` to skip passing `api_key=` each time.

## Development: async-first with unasync

`AsyncRunsNamespace` (in `proto_client/_async/runs.py`) is the source of
truth. The sync `RunsNamespace` (`proto_client/runs.py`) is **generated**
from it via [unasync](https://github.com/python-trio/unasync) — a
token-level transform configured in `scripts/gen_sync.py`. The generated
file is committed to the repo, and a CI check verifies it stays in sync.
To regenerate manually:

```bash
python scripts/gen_sync.py
```

Do not edit `proto_client/runs.py` directly — your changes will be
overwritten on the next regen.

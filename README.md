# proto-client

Python SDK for Proto Bio APIs.

## Install

```bash
pip install proto-client
```

## Usage

```python
from proto_client import ProtoClient

client = ProtoClient(api_key="...")

# Run a tool
result = client.tools.run("esmfold-prediction", {"sequences": ["MKTL"]})

# List available tools
tools = client.tools.list()
```

Set `PROTO_API_KEY` environment variable to skip passing `api_key=` each time.

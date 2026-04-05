"""Async-first implementation. Sync counterparts are generated via unasync.

The modules in this package are the source of truth. The build step in
``scripts/gen_sync.py`` rewrites ``_async/runs.py`` into ``proto_client/runs.py``
using token-level substitutions (``async def`` → ``def``, ``AsyncClient`` →
``Client``, ``asyncio.sleep`` → ``time.sleep``, etc.).

``_async/client.py`` and ``_async/tools.py`` are hand-written and NOT fed
through unasync — they coexist with the hand-written sync ``client.py`` /
``tools.py``.
"""

from proto_client._async.client import AsyncProtoClient
from proto_client._async.runs import AsyncRunsNamespace
from proto_client._async.tools import AsyncToolsNamespace

__all__ = ["AsyncProtoClient", "AsyncRunsNamespace", "AsyncToolsNamespace"]

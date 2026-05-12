"""Async asset download helpers."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import httpx

from proto_client._assets import AssetLike, asset_url, origin_of, redirect_location, strip_sensitive_redirect_headers
from proto_client.errors import from_response


class AsyncAssetsNamespace:
    """Async sibling of :class:`AssetsNamespace` — same routing semantics."""

    def __init__(self, http_clients: list[httpx.AsyncClient]) -> None:
        """Initialize with the set of authenticated httpx AsyncClients."""
        self._clients_by_origin = {origin_of(str(c.base_url)): c for c in http_clients}

    async def get(self, ref: AssetLike) -> bytes:
        """Fetch asset bytes into memory."""
        buffer = BytesIO()
        await self._write_to(ref, buffer)
        return buffer.getvalue()

    async def download(self, ref: AssetLike, path: str | Path) -> Path:
        """Stream asset bytes to ``path``."""
        destination = Path(path)
        file = await asyncio.to_thread(destination.open, "wb")
        try:
            await self._write_to(ref, file)
        finally:
            await asyncio.to_thread(file.close)
        return destination

    async def _write_to(self, ref: AssetLike, file: BinaryIO) -> None:
        async with self._stream(ref) as resp:
            async for chunk in resp.aiter_bytes():
                await asyncio.to_thread(file.write, chunk)

    @asynccontextmanager
    async def _stream(self, ref: AssetLike) -> AsyncIterator[httpx.Response]:
        url = asset_url(ref)
        client = self._client_for(url)
        async with client.stream("GET", url, follow_redirects=False) as resp:
            if not resp.is_redirect:
                if resp.is_error:
                    await resp.aread()
                    raise from_response(resp)
                yield resp
                return
            location = redirect_location(resp, url)

        # Strip auth on every redirect (safe default — same-origin redirects don't exist today).
        request = client.build_request("GET", location)
        strip_sensitive_redirect_headers(request)
        redirected = await client.send(request, stream=True, follow_redirects=True)
        try:
            if redirected.is_error:
                await redirected.aread()
                raise RuntimeError(
                    f"Storage backend HTTP {redirected.status_code} at {location!r} (not a Proto API error)"
                ) from from_response(redirected)
            yield redirected
        finally:
            await redirected.aclose()

    def _client_for(self, url: str) -> httpx.AsyncClient:
        origin = origin_of(url)
        client = self._clients_by_origin.get(origin)
        if client is None:
            raise ValueError(
                f"AssetRef URL {url!r} doesn't match any configured base URL "
                f"({sorted(self._clients_by_origin)}); check the client's "
                "`tools_base_url` / `runs_base_url` settings."
            )
        return client

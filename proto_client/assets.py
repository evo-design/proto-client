"""Sync asset download helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

import httpx

from proto_client._assets import AssetLike, asset_url, origin_of, redirect_location, strip_sensitive_redirect_headers
from proto_client.errors import from_response


class AssetsNamespace:
    """Download API-managed asset bytes via the URL stamped on each ``AssetRef``.

    A single namespace serves refs from any configured backend; routing is by
    URL origin (matched against each client's ``base_url``).
    """

    def __init__(self, http_clients: list[httpx.Client]) -> None:
        """Initialize with the set of authenticated httpx Clients to route over."""
        self._clients_by_origin = {origin_of(str(c.base_url)): c for c in http_clients}

    def get(self, ref: AssetLike) -> bytes:
        """Fetch asset bytes into memory."""
        buffer = BytesIO()
        self._write_to(ref, buffer)
        return buffer.getvalue()

    def download(self, ref: AssetLike, path: str | Path) -> Path:
        """Stream asset bytes to ``path``."""
        destination = Path(path)
        with destination.open("wb") as file:
            self._write_to(ref, file)
        return destination

    def _write_to(self, ref: AssetLike, file: BinaryIO) -> None:
        with self._stream(ref) as resp:
            file.writelines(resp.iter_bytes())

    @contextmanager
    def _stream(self, ref: AssetLike) -> Iterator[httpx.Response]:
        url = asset_url(ref)
        client = self._client_for(url)
        with client.stream("GET", url, follow_redirects=False) as resp:
            if not resp.is_redirect:
                if resp.is_error:
                    resp.read()
                    raise from_response(resp)
                yield resp
                return
            location = redirect_location(resp, url)

        # Strip auth on every redirect (safe default — same-origin redirects don't exist today).
        request = client.build_request("GET", location)
        strip_sensitive_redirect_headers(request)
        redirected = client.send(request, stream=True, follow_redirects=True)
        try:
            if redirected.is_error:
                redirected.read()
                raise RuntimeError(
                    f"Storage backend HTTP {redirected.status_code} at {location!r} (not a Proto API error)"
                ) from from_response(redirected)
            yield redirected
        finally:
            redirected.close()

    def _client_for(self, url: str) -> httpx.Client:
        origin = origin_of(url)
        client = self._clients_by_origin.get(origin)
        if client is None:
            raise ValueError(
                f"AssetRef URL {url!r} doesn't match any configured base URL "
                f"({sorted(self._clients_by_origin)}); check the client's "
                "`tools_base_url` / `runs_base_url` settings."
            )
        return client

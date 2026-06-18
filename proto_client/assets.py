"""Sync asset download helpers."""

from collections.abc import Iterator
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
from typing import BinaryIO
from uuid import uuid4

import httpx

from proto_client.errors import from_response
from proto_client.utils.asset_helpers import (
    AssetLike,
    asset_url,
    decode_asset_bytes,
    origin_of,
    redirect_location,
    strip_sensitive_redirect_headers,
)


class AssetsNamespace:
    """Fetch API-readable output assets via the URL stamped on each ``AssetRef``.

    A single namespace serves refs from configured Proto API origins; routing is
    by URL origin matched against each client's ``base_url``. Refs without an
    API-readable URL are not generally fetchable through this namespace.
    """

    def __init__(self, http_clients: list[httpx.Client]) -> None:
        """Initialize with the set of authenticated httpx Clients to route over."""
        self._clients_by_origin = {origin_of(str(c.base_url)): c for c in http_clients}

    def get(self, ref: AssetLike) -> bytes:
        """Fetch exact stored asset bytes into memory."""
        buffer = BytesIO()
        self._write_to(ref, buffer)
        return buffer.getvalue()

    def decode(self, ref: AssetLike) -> object:
        """Fetch and decode an asset by MIME type.

        JSON assets become Python values, chemical/text assets become strings,
        and unknown MIME types remain bytes. This loads the full asset into
        memory.
        """
        return decode_asset_bytes(ref, self.get(ref))

    def download(self, ref: AssetLike, path: str | Path) -> Path:
        """Stream stored asset bytes to ``path`` atomically (temp file + ``os.replace``)."""
        destination = Path(path)
        tmp = destination.with_name(f"{destination.name}.tmp.{uuid4().hex}")
        try:
            with tmp.open("wb") as file:
                self._write_to(ref, file)
            tmp.replace(destination)
        finally:
            tmp.unlink(missing_ok=True)
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

        # Strip auth before following an asset redirect (storage origins differ from the API origin).
        request = client.build_request("GET", location)
        strip_sensitive_redirect_headers(request)
        redirected = client.send(request, stream=True, follow_redirects=True)
        try:
            if redirected.is_error:
                redirected.read()
                raise RuntimeError(
                    f"Storage backend returned HTTP {redirected.status_code} at {location!r}: {redirected.text[:200]}"
                )
            yield redirected
        finally:
            redirected.close()

    def _client_for(self, url: str) -> httpx.Client:
        origin = origin_of(url)
        client = self._clients_by_origin.get(origin)
        if client is None:
            raise ValueError(
                f"AssetRef URL {url!r} doesn't match any configured base URL ({sorted(self._clients_by_origin)})."
            )
        return client

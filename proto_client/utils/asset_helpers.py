"""Shared helpers for the assets namespace."""

import gzip
import json
from typing import Any
from urllib.parse import urlparse

import httpx

from proto_client.models import AssetRef

# Accept the typed model or the raw dict pulled out of ``job.result`` /
# ``run.stage_results[...]`` — both carry the canonical ``url`` field
# stamped by the backend.
AssetLike = AssetRef | dict[str, Any]
SENSITIVE_REDIRECT_HEADERS = ("authorization", "proxy-authorization", "x-api-key", "cookie")


def asset_url(ref_or_dict: AssetLike) -> str:
    """Return the canonical fetch URL the backend stamped on the ref."""
    if isinstance(ref_or_dict, dict):
        ref_or_dict = AssetRef.model_validate(ref_or_dict)
    if not ref_or_dict.url:
        raise ValueError(
            f"AssetRef {ref_or_dict.id!r} has no `url` — backend did not stamp a fetch URL "
            "(legacy server, or this is a `reference_db` / user-upload-allocation ref)."
        )
    return ref_or_dict.url


def decode_asset_bytes(ref_or_dict: AssetLike, data: bytes) -> Any:
    """Decode raw asset bytes by MIME type: (gzipped) JSON to an object, chemical/text to str, else bytes."""
    if isinstance(ref_or_dict, dict):
        ref_or_dict = AssetRef.model_validate(ref_or_dict)
    mime_type = ref_or_dict.mime_type or ""
    if mime_type == "application/json+gzip":
        return json.loads(gzip.decompress(data).decode("utf-8"))
    if mime_type == "application/json" or mime_type.endswith("+json"):
        return json.loads(data.decode("utf-8"))
    if mime_type.startswith(("chemical/", "text/")):
        return data.decode("utf-8")
    return data


_EXT_BY_MIME = {
    "chemical/x-pdb": ".pdb",
    "chemical/x-cif": ".cif",
    "chemical/x-mmcif": ".cif",
    "chemical/x-fasta": ".fasta",
    "application/json": ".json",
    "application/json+gzip": ".json.gz",
    "text/csv": ".csv",
    "text/plain": ".txt",
}


def ext_for_mime(mime_type: str | None) -> str:
    """Best-effort filename extension for an asset MIME type.

    Returns ``""`` (empty) for unknown types so callers can fall back to the
    asset id alone.
    """
    if not mime_type:
        return ""
    if mime_type in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime_type]
    if mime_type.endswith("+json"):
        return ".json"
    if mime_type.endswith("+gzip"):
        return ".gz"
    return ""


_DEFAULT_PORTS = {"http": 80, "https": 443}


def origin_of(url: str) -> str:
    """Return ``scheme://host[:port]``, stripping default ports (httpx does the same on base_url)."""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    port = parsed.port
    netloc = host if port is None or port == _DEFAULT_PORTS.get(parsed.scheme) else f"{host}:{port}"
    return f"{parsed.scheme}://{netloc}"


def redirect_location(response: httpx.Response, url: str) -> str:
    """Return the redirect ``Location`` header value, or raise if the redirect omitted it."""
    location = response.headers.get("location")
    if isinstance(location, str) and location:
        return location
    raise RuntimeError(f"Asset GET {url} redirect did not include a Location header")


def strip_sensitive_redirect_headers(request: httpx.Request) -> None:
    """Drop auth/cookie headers from *request* before it follows a redirect off a Proto origin."""
    for name in SENSITIVE_REDIRECT_HEADERS:
        request.headers.pop(name, None)

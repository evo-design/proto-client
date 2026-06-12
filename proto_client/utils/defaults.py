"""Built-in API endpoints and base-URL resolution.

The packaged defaults point at Proto's hosted services. Each can be overridden
per service for testing, via a constructor
argument or environment variable; see :func:`resolve_base_url`.
"""

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

TOOLS_BASE_URL = "https://proto-tools.evodesign.org"

RUNS_BASE_URL = "https://proto-language.evodesign.org"

# Loopback hosts never leave the machine, so http is safe there; every other
# non-default host must use https so the API key is never sent in plaintext.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def resolve_base_url(explicit: str | None, *, env_var: str, default: str) -> str:
    """Resolve a service base URL via ``explicit arg → env var → packaged default``.

    A non-default URL must use ``https://`` so the API key is never sent over
    plaintext, except loopback hosts (``localhost`` / ``127.0.0.1`` / ``::1``),
    which stay on the machine and may use ``http://`` for local development.
    Logs at INFO whenever a non-default URL is in effect, so a misconfigured
    override surfaces instead of silently redirecting traffic.

    Args:
        explicit: Base URL passed directly to the client, or ``None``.
        env_var: Environment variable consulted when *explicit* is unset.
        default: Packaged default used when neither *explicit* nor *env_var* is set.

    Raises:
        ValueError: if a non-default, non-loopback URL does not use https.
    """
    url = explicit or os.environ.get(env_var) or default
    if url == default:
        return url
    parsed = urlparse(url)
    if parsed.scheme != "https" and parsed.hostname not in _LOOPBACK_HOSTS:
        raise ValueError(
            f"Base URL {url!r} must use https:// (only loopback hosts may use http://). "
            f"Set it via the constructor argument or {env_var}."
        )
    logger.info("Using non-default base URL: %s", url)
    return url

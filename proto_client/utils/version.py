"""Package version -- single source of truth for User-Agent and __version__."""

from importlib.metadata import PackageNotFoundError, version

try:
    VERSION: str = version("proto-client")
except PackageNotFoundError:
    VERSION = "0.0.0-dev"

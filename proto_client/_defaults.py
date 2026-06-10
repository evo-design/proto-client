"""Built-in API endpoints.

``TOOLS_BASE_URL`` is fixed — the tools service is hosted exclusively by Proto.
``DEFAULT_RUNS_BASE_URL`` is overridable via ``PROTO_RUNS_BASE_URL`` or the
``runs_base_url`` constructor arg.
"""


TOOLS_BASE_URL = "https://proto-tools.evodesign.org"

DEFAULT_RUNS_BASE_URL = "https://proto-language.evodesign.org"

"""Runs namespace — stub for future the runs API integration."""


class RunsNamespace:
    """Stub — will connect to the runs API when it ships."""

    def __getattr__(self, name: str) -> object:
        raise NotImplementedError(
            "The runs API is not yet available. See https://github.com/evo-design/proto-client for updates."
        )

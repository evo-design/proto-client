"""Runs namespace — stub for future the runs API integration."""

from __future__ import annotations


class RunsNamespace:
    """Stub — will connect to the runs API when it ships."""

    def __getattr__(self, name: str):
        raise NotImplementedError(
            "The runs API is not yet available. "
            "See https://github.com/evo-design/proto-client for updates."
        )

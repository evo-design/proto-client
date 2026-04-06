"""Tests for PROTO_LOG environment variable."""

import importlib
import logging

import pytest

import proto_client


def test_proto_log_debug(monkeypatch: pytest.MonkeyPatch) -> None:
    """PROTO_LOG=debug configures the library logger at DEBUG level."""
    monkeypatch.setenv("PROTO_LOG", "debug")
    importlib.reload(proto_client)

    logger = logging.getLogger("proto_client")
    assert logger.level == logging.DEBUG
    # At least the NullHandler + the StreamHandler added by PROTO_LOG
    assert any(isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler) for h in logger.handlers)

    # Clean up: reload without env var to restore defaults
    monkeypatch.delenv("PROTO_LOG")
    importlib.reload(proto_client)


def test_proto_log_info(monkeypatch: pytest.MonkeyPatch) -> None:
    """PROTO_LOG=info configures the library logger at INFO level."""
    monkeypatch.setenv("PROTO_LOG", "INFO")
    importlib.reload(proto_client)

    logger = logging.getLogger("proto_client")
    assert logger.level == logging.INFO

    monkeypatch.delenv("PROTO_LOG")
    importlib.reload(proto_client)


def test_proto_log_unset_no_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without PROTO_LOG, only the NullHandler is present."""
    monkeypatch.delenv("PROTO_LOG", raising=False)
    importlib.reload(proto_client)

    logger = logging.getLogger("proto_client")
    stream_handlers = [
        h for h in logger.handlers if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.NullHandler)
    ]
    assert stream_handlers == []

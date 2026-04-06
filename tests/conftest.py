"""Shared pytest fixtures."""

from unittest.mock import MagicMock

import httpx
import pytest


@pytest.fixture
def mock_http() -> MagicMock:
    """Mocked sync httpx.Client for namespace tests."""
    return MagicMock(spec=httpx.Client)

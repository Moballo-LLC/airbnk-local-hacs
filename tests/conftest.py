"""Pytest fixtures for Airbnk BLE."""

from __future__ import annotations

import sys
from collections.abc import Generator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(
    enable_custom_integrations,
) -> Generator[None]:
    """Enable custom integrations defined in this repository."""

    yield

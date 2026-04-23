"""Diagnostics tests for Airbnk BLE."""

from __future__ import annotations

from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble.diagnostics import async_get_config_entry_diagnostics


async def test_diagnostics_redact_sensitive_fields(
    hass: HomeAssistant,
) -> None:
    """Diagnostics should redact keys and identifiers."""

    mock_config_entry = MockConfigEntry(
        domain="airbnk_ble",
        title="Front Gate",
        data={
            "name": "Front Gate",
            "lock_sn": "SECRET-SN",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "manufacturer_key": "deadbeef",
            "binding_key": "beefdead",
        },
    )
    runtime = MagicMock()
    runtime.bootstrap.lock_model = "B100"
    runtime.bootstrap.profile = "b100"
    runtime.state.available = True
    runtime.state.reachable = True
    runtime.state.lock_state = 1
    runtime.state.battery_percent = 80.0
    runtime.state.voltage = 2.8
    runtime.state.last_error = "ok"
    runtime.state.firmware_version = "1.0.0"
    runtime.state.board_model = 1
    runtime.state.opens_clockwise = False
    runtime.connectivity_probe_interval = 0

    mock_config_entry.runtime_data = runtime

    diagnostics = await async_get_config_entry_diagnostics(hass, mock_config_entry)

    assert diagnostics["entry"]["lock_sn"] == "**REDACTED**"
    assert diagnostics["entry"]["mac_address"] == "**REDACTED**"
    assert diagnostics["entry"]["binding_key"] == "**REDACTED**"
    assert diagnostics["entry"]["manufacturer_key"] == "**REDACTED**"

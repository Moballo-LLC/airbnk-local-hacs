"""Diagnostics tests for Airbnk BLE."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock

from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble.diagnostics import (
    async_get_config_entry_diagnostics,
    async_get_device_diagnostics,
)


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


async def test_device_diagnostics_include_device_metadata(
    hass: HomeAssistant,
) -> None:
    """Device diagnostics should wrap device metadata around entry diagnostics."""

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

    device = DeviceEntry(
        area_id=None,
        config_entries={mock_config_entry.entry_id},
        config_entries_subentries={},
        connections=set(),
        created_at=datetime.now(UTC),
        disabled_by=None,
        entry_type=None,
        hw_version=None,
        id="device-id",
        identifiers=set(),
        labels=set(),
        manufacturer="Airbnk",
        model="B100",
        model_id=None,
        modified_at=datetime.now(UTC),
        name="Front Gate",
        name_by_user=None,
        primary_config_entry=mock_config_entry.entry_id,
        serial_number=None,
        suggested_area=None,
        sw_version=None,
        via_device_id=None,
    )

    diagnostics = await async_get_device_diagnostics(hass, mock_config_entry, device)

    assert diagnostics["device"]["id"] == "device-id"
    assert diagnostics["config_entry"]["entry"]["lock_sn"] == "**REDACTED**"

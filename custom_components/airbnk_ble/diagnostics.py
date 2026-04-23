"""Diagnostics support for Airbnk BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntry

from .const import (
    CONF_BINDING_KEY,
    CONF_LOCK_SN,
    CONF_MAC_ADDRESS,
    CONF_MANUFACTURER_KEY,
)

_REDACT_CONFIG = {
    CONF_BINDING_KEY,
    CONF_MAC_ADDRESS,
    CONF_MANUFACTURER_KEY,
    CONF_LOCK_SN,
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""

    runtime = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), _REDACT_CONFIG),
        "runtime": {
            "available": runtime.state.available,
            "reachable": runtime.state.reachable,
            "lock_model": runtime.bootstrap.lock_model,
            "profile": runtime.bootstrap.profile,
            "lock_state": runtime.state.lock_state,
            "battery_percent": runtime.state.battery_percent,
            "voltage": runtime.state.voltage,
            "last_error": runtime.state.last_error,
            "firmware_version": runtime.state.firmware_version,
            "board_model": runtime.state.board_model,
            "opens_clockwise": runtime.state.opens_clockwise,
            "connectivity_probe_interval": runtime.connectivity_probe_interval,
        },
    }


async def async_get_device_diagnostics(
    hass: HomeAssistant,
    entry: ConfigEntry,
    device: DeviceEntry,
) -> dict[str, Any]:
    """Return diagnostics for a device entry."""

    return {
        "device": {
            "id": device.id,
            "model": device.model,
            "manufacturer": device.manufacturer,
            "name": device.name,
        },
        "config_entry": await async_get_config_entry_diagnostics(hass, entry),
    }

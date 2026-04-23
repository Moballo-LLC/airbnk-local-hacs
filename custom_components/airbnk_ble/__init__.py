"""Airbnk BLE integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .airbnk import validate_entry_data
from .const import DOMAIN, PLATFORMS
from .device import AirbnkLockRuntime


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Airbnk BLE integration."""

    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Airbnk BLE from a config entry."""

    normalized, bootstrap = validate_entry_data(entry.data)
    if normalized != dict(entry.data):
        hass.config_entries.async_update_entry(
            entry,
            data=normalized,
            title=normalized["name"],
        )

    runtime = AirbnkLockRuntime(hass, entry, bootstrap)
    entry.runtime_data = runtime
    await runtime.async_start()
    entry.async_on_unload(runtime.async_stop)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload a config entry after options or reconfigure changes."""

    await hass.config_entries.async_reload(entry.entry_id)

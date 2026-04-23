"""Airbnk BLE integration."""

from __future__ import annotations

from homeassistant.components import bluetooth
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv

from .airbnk import validate_entry
from .const import CONF_MAC_ADDRESS, DOMAIN, PLATFORMS
from .device import AirbnkLockRuntime

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, _config: dict) -> bool:
    """Set up the Airbnk BLE integration."""

    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Airbnk BLE from a config entry."""

    normalized_data, normalized_options, bootstrap = validate_entry(
        entry.data,
        entry.options,
    )
    if normalized_data != dict(entry.data) or normalized_options != dict(entry.options):
        hass.config_entries.async_update_entry(
            entry,
            data=normalized_data,
            options=normalized_options,
            title=normalized_options["name"],
        )

    runtime = AirbnkLockRuntime(hass, entry, bootstrap)
    entry.runtime_data = runtime
    await runtime.async_start()
    entry.async_on_unload(runtime.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Trigger Bluetooth rediscovery when an entry is removed."""

    bluetooth.async_rediscover_address(hass, str(entry.data[CONF_MAC_ADDRESS]))

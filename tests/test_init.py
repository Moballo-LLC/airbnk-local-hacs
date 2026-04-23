"""Integration lifecycle tests for Airbnk BLE."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble import (
    async_remove_entry,
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.airbnk_ble.const import DOMAIN

from .common import build_bootstrap_fixture


async def test_async_setup_initializes_domain_storage(hass: HomeAssistant) -> None:
    """Top-level setup should initialize hass.data for the domain."""

    assert await async_setup(hass, {}) is True
    assert DOMAIN in hass.data


async def test_async_setup_entry_normalizes_legacy_entry_data(
    hass: HomeAssistant,
) -> None:
    """Entry setup should normalize older entry data before runtime startup."""

    fixture = build_bootstrap_fixture()
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Gate",
        data={
            "name": "Front Gate",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "lock_sn": fixture["lock_sn"],
            "new_sninfo": fixture["new_sninfo"],
            "app_key": fixture["app_key"],
            "voltage_thresholds": [2.5, 2.6, 2.9],
            "reverse_commands": False,
            "supports_remote_lock": False,
            "retry_count": 3,
            "command_timeout": 15,
            "connectivity_probe_interval": 0,
            "unavailable_after": 60,
        },
    )
    runtime = MagicMock()
    runtime.async_start = AsyncMock()
    runtime.async_stop = MagicMock()

    with (
        patch(
            "custom_components.airbnk_ble.AirbnkLockRuntime",
            return_value=runtime,
        ) as runtime_cls,
        patch.object(
            hass.config_entries,
            "async_forward_entry_setups",
            AsyncMock(return_value=None),
        ),
        patch.object(hass.config_entries, "async_update_entry") as update_entry,
    ):
        assert await async_setup_entry(hass, entry) is True

    runtime.async_start.assert_awaited_once()
    runtime_cls.assert_called_once()
    update_entry.assert_called_once()
    assert update_entry.call_args.kwargs["options"]["name"] == "Front Gate"
    assert (
        update_entry.call_args.kwargs["options"]["publish_diagnostic_entities"]
        is False
    )
    assert entry.runtime_data is runtime


async def test_async_unload_entry_delegates_to_config_entries(
    hass: HomeAssistant,
) -> None:
    """Unload helper should delegate to the HA config manager."""

    entry = MockConfigEntry(domain=DOMAIN, title="Front Gate", data={})

    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        AsyncMock(return_value=True),
    ) as unload_platforms:
        assert await async_unload_entry(hass, entry) is True

    unload_platforms.assert_awaited_once()


async def test_async_remove_entry_triggers_bluetooth_rediscovery(
    hass: HomeAssistant,
) -> None:
    """Removing an entry should allow Bluetooth discovery to fire again."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Gate",
        data={"mac_address": "AA:BB:CC:DD:EE:FF"},
    )

    with patch(
        "custom_components.airbnk_ble.bluetooth.async_rediscover_address"
    ) as async_rediscover_address:
        await async_remove_entry(hass, entry)

    async_rediscover_address.assert_called_once_with(hass, "AA:BB:CC:DD:EE:FF")

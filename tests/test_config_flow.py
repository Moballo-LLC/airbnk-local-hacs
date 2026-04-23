"""Config flow tests for Airbnk BLE."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble.cloud_api import AirbnkCloudLock, AirbnkCloudSession
from custom_components.airbnk_ble.const import (
    CONF_LOCK_SN,
    CONF_MAC_ADDRESS,
    DOMAIN,
)

from .common import build_advertisement_payload, build_bootstrap_fixture


async def test_manual_flow_creates_entry_without_raw_bootstrap_secrets(
    hass: HomeAssistant,
) -> None:
    """Manual setup should store only derived values."""

    fixture = build_bootstrap_fixture()

    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new=AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] == "menu"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "manual"},
        )
        assert result["type"] == "form"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Front Gate",
                "lock_sn": fixture["lock_sn"],
                "new_sninfo": fixture["new_sninfo"],
                "app_key": fixture["app_key"],
            },
        )
        assert result["step_id"] == "confirm_lock"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Front Gate",
                "mac_address": "AA:BB:CC:DD:EE:FF",
                "reverse_commands": False,
                "supports_remote_lock": False,
                "retry_count": 3,
                "command_timeout": 15,
                "connectivity_probe_interval": 0,
                "unavailable_after": 60,
            },
        )
        assert result["type"] == "create_entry"
        assert "app_key" not in result["data"]
        assert "new_sninfo" not in result["data"]
        assert "name" not in result["data"]
        assert result["options"]["name"] == "Front Gate"


async def test_cloud_flow_prefers_matching_discovered_lock(
    hass: HomeAssistant,
) -> None:
    """Cloud setup should auto-select the lock that matches discovery."""

    fixture = build_bootstrap_fixture()
    discovery = SimpleNamespace(
        address="AA:BB:CC:DD:EE:FF",
        manufacturer_data={
            0xBABA: build_advertisement_payload(serial_fragment=fixture["lock_sn"][:9])
        },
        rssi=-60,
    )

    fake_session = AirbnkCloudSession(
        email="user@example.com",
        user_id="user-id",
        token="token",
    )
    fake_lock = AirbnkCloudLock(
        serial_number=fixture["lock_sn"],
        device_name="Front Gate",
        lock_model=fixture["lock_model"],
        hardware_version="1",
        app_key=fixture["app_key"],
        new_sninfo=fixture["new_sninfo"],
    )

    with (
        patch(
            "homeassistant.config_entries.async_process_deps_reqs",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "custom_components.airbnk_ble.config_flow.async_discovered_service_info",
            return_value=[discovery],
        ),
        patch(
            "custom_components.airbnk_ble.config_flow.AirbnkCloudClient.async_request_verification_code"
        ),
        patch(
            "custom_components.airbnk_ble.config_flow.AirbnkCloudClient.async_authenticate",
            return_value=fake_session,
        ),
        patch(
            "custom_components.airbnk_ble.config_flow.AirbnkCloudClient.async_get_locks",
            return_value=[fake_lock],
        ),
        patch(
            "custom_components.airbnk_ble.config_flow.AirbnkCloudClient.async_get_battery_profile",
            return_value=None,
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )
        assert result["type"] == "menu"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "cloud"},
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {CONF_EMAIL: "user@example.com"},
        )
        assert result["step_id"] == "cloud_verify"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"auth_code": "123456"},
        )
        assert result["step_id"] == "confirm_lock"
        assert result["description_placeholders"]["serial"] == fixture["lock_sn"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                "name": "Front Gate",
                "discovered_address": "AA:BB:CC:DD:EE:FF",
                "mac_address": "",
                "reverse_commands": False,
                "supports_remote_lock": False,
                "retry_count": 3,
                "command_timeout": 15,
                "connectivity_probe_interval": 0,
                "unavailable_after": 60,
            },
        )
        assert result["type"] == "create_entry"
        assert result["data"][CONF_LOCK_SN] == fixture["lock_sn"]
        assert result["data"][CONF_MAC_ADDRESS] == "AA:BB:CC:DD:EE:FF"
        assert result["options"]["name"] == "Front Gate"


async def test_bluetooth_discovery_prefills_manual_setup(
    hass: HomeAssistant,
) -> None:
    """Bluetooth discovery should carry the detected lock into manual setup."""

    fixture = build_bootstrap_fixture()
    discovery = SimpleNamespace(
        address="AA:BB:CC:DD:EE:FF",
        manufacturer_data={
            0xBABA: build_advertisement_payload(serial_fragment=fixture["lock_sn"][:9])
        },
        rssi=-60,
    )

    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new=AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=discovery,
        )
        assert result["type"] == "menu"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "manual"},
        )

        assert result["type"] == "form"
        assert result["step_id"] == "manual"
        lock_sn_field = next(
            field
            for field in result["data_schema"].schema
            if getattr(field, "schema", None) == "lock_sn"
        )
        assert lock_sn_field.default() == fixture["lock_sn"][:9]


async def test_options_flow_updates_entry_options_without_touching_connection_data(
    hass: HomeAssistant,
) -> None:
    """Runtime tuning belongs in entry options, not connection data."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Front Gate",
        data={
            "lock_sn": "B100LOCK00000001",
            "lock_model": "B100",
            "profile": "b100",
            "mac_address": "AA:BB:CC:DD:EE:FF",
            "manufacturer_key": "fixture-manufacturer-key",
            "binding_key": "fixture-binding-key",
            "battery_profile": [
                {"voltage": 2.3, "percent": 0.0},
                {"voltage": 2.9, "percent": 100.0},
            ],
            "hardware_version": "",
        },
        options={
            "name": "Front Gate",
            "reverse_commands": False,
            "supports_remote_lock": False,
            "retry_count": 3,
            "command_timeout": 15,
            "connectivity_probe_interval": 0,
            "unavailable_after": 60,
        },
        unique_id="B100LOCK00000001",
    )
    entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new=AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"

    with (
        patch(
            "homeassistant.config_entries.async_process_deps_reqs",
            new=AsyncMock(return_value=None),
        ),
        patch.object(
            hass.config_entries,
            "async_reload",
            AsyncMock(return_value=True),
        ),
    ):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "name": "Front Door",
                "reverse_commands": True,
                "supports_remote_lock": False,
                "retry_count": 5,
                "command_timeout": 20,
                "connectivity_probe_interval": 30,
                "unavailable_after": 120,
            },
        )

    assert result["type"] == "create_entry"
    assert entry.data["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert entry.options["name"] == "Front Door"
    assert entry.options["retry_count"] == 5
    assert entry.title == "Front Door"

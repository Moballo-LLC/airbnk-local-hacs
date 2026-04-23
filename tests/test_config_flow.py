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
    LEGACY_DOMAIN,
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


async def test_import_morcos_flow_converts_legacy_entry_without_raw_secrets(
    hass: HomeAssistant,
) -> None:
    """Legacy Morcos entries should import cleanly into Airbnk BLE."""

    fixture = build_bootstrap_fixture()
    legacy_entry = MockConfigEntry(
        domain=LEGACY_DOMAIN,
        title="Mailbox",
        unique_id=fixture["lock_sn"],
        data={
            "name": "Mailbox",
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
    legacy_entry.add_to_hass(hass)

    with patch(
        "homeassistant.config_entries.async_process_deps_reqs",
        new=AsyncMock(return_value=None),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
        )
        assert result["type"] == "menu"
        assert "import_morcos" in result["menu_options"]

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"next_step_id": "import_morcos"},
        )
        assert result["type"] == "form"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {"selected_legacy_entry": legacy_entry.entry_id},
        )

        assert result["type"] == "create_entry"
        assert result["title"] == "Mailbox"
        assert result["data"][CONF_LOCK_SN] == fixture["lock_sn"]
        assert result["data"][CONF_MAC_ADDRESS] == "AA:BB:CC:DD:EE:FF"
        assert "app_key" not in result["data"]
        assert "new_sninfo" not in result["data"]

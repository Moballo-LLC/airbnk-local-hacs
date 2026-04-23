"""Entity and platform tests for Airbnk BLE."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.const import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble import binary_sensor, lock, sensor
from custom_components.airbnk_ble.const import DOMAIN, LOCK_STATE_LOCKED


def _build_runtime():
    state = SimpleNamespace(
        available=False,
        reachable=True,
        lock_state=LOCK_STATE_LOCKED,
        voltage=2.8,
        battery_percent=80.0,
        rssi=-62,
        lock_events=7,
        is_low_battery=False,
        last_error="ok",
        last_source="advertisement",
        firmware_version="1.2.3",
        board_model=1,
        opens_clockwise=False,
        advert_state_flags=0x10,
        advert_state_bits=0x01,
        advert_state_label="locked",
        advert_battery_flags=0x10,
        status_state_byte=0x10,
        status_state_nibble=0x01,
        status_state_label="locked",
        status_trailing_byte=0x01,
        command_in_progress="unlocking",
        last_requested_operation=1,
        last_wire_operation=2,
        restored=True,
        last_advert_monotonic=time.monotonic() - 2,
        last_contact_monotonic=time.monotonic() - 2,
        last_probe_monotonic=time.monotonic() - 5,
        last_probe_successful=True,
        last_advert_payload_hex="BABA",
        last_status_payload_hex="AA0000",
    )
    return SimpleNamespace(
        lock_sn="B100LOCK00000001",
        lock_icon="",
        publish_diagnostic_entities=False,
        device_info={"identifiers": {(DOMAIN, "B100LOCK00000001")}},
        state=state,
        supports_remote_lock=False,
        connectivity_probe_interval=300,
        has_advertisement=True,
        last_advert_age_seconds=2.4,
        is_locked=True,
        is_jammed=False,
        register_callback=MagicMock(return_value=lambda: None),
        async_lock=AsyncMock(),
        async_unlock=AsyncMock(),
        async_open=AsyncMock(),
    )


async def test_platform_setup_creates_expected_entities() -> None:
    """Useful battery entities should remain even with extra diagnostics off."""

    runtime = _build_runtime()
    entry = MockConfigEntry(domain=DOMAIN, title="Front Gate", data={})
    entry.runtime_data = runtime

    added_binary = []
    await binary_sensor.async_setup_entry(
        None,
        entry,
        lambda entities: added_binary.extend(entities),
    )
    assert len(added_binary) == 1

    added_lock = []
    await lock.async_setup_entry(
        None,
        entry,
        lambda entities: added_lock.extend(entities),
    )
    assert len(added_lock) == 1

    added_sensor = []
    await sensor.async_setup_entry(
        None,
        entry,
        lambda entities: added_sensor.extend(entities),
    )
    assert len(added_sensor) == 1
    assert added_sensor[0]._description.key == "battery"  # noqa: SLF001


async def test_platform_setup_creates_diagnostic_entities_when_enabled() -> None:
    """Opting in should publish the diagnostic sensor and binary-sensor surface."""

    runtime = _build_runtime()
    runtime.publish_diagnostic_entities = True
    entry = MockConfigEntry(domain=DOMAIN, title="Front Gate", data={})
    entry.runtime_data = runtime

    added_binary = []
    await binary_sensor.async_setup_entry(
        None,
        entry,
        lambda entities: added_binary.extend(entities),
    )
    assert len(added_binary) == 2

    added_sensor = []
    await sensor.async_setup_entry(
        None,
        entry,
        lambda entities: added_sensor.extend(entities),
    )
    assert len(added_sensor) == len(sensor.SENSORS)
    assert [entity._description.key for entity in added_sensor] == [  # noqa: SLF001
        "battery",
        "battery_voltage",
        "signal_strength",
    ]
    assert [entity._attr_name for entity in added_binary] == [  # noqa: SLF001
        "Battery Low",
        "Connectivity",
    ]


def test_sensor_catalog_stays_minimal_and_excludes_raw_debug_entities() -> None:
    """Only the trimmed battery and extra BLE health sensors should remain."""

    assert [description.key for description in sensor.SENSORS] == [
        "battery",
        "battery_voltage",
        "signal_strength",
    ]


async def test_entities_expose_runtime_state_and_commands() -> None:
    """Entity properties should reflect runtime state and forward commands."""

    runtime = _build_runtime()

    low_battery = binary_sensor.AirbnkBatteryLowBinarySensor(runtime)
    assert low_battery.available is True
    assert low_battery.is_on is False

    connectivity = binary_sensor.AirbnkConnectivityBinarySensor(runtime)
    assert connectivity.available is True
    assert connectivity.is_on is True
    assert connectivity.extra_state_attributes["fresh_state_available"] is False
    assert connectivity.extra_state_attributes["last_probe_successful"] is True

    battery_description = next(
        description for description in sensor.SENSORS if description.key == "battery"
    )
    battery_sensor = sensor.AirbnkBleSensor(runtime, battery_description)
    assert battery_sensor.device_info == runtime.device_info
    assert battery_sensor.available is True
    assert battery_sensor.native_value == 80.0
    assert battery_sensor.entity_category == EntityCategory.DIAGNOSTIC

    signal_strength_description = next(
        description
        for description in sensor.SENSORS
        if description.key == "signal_strength"
    )
    signal_strength_sensor = sensor.AirbnkBleSensor(
        runtime, signal_strength_description
    )
    assert signal_strength_sensor.entity_registry_enabled_default is False

    lock_entity = lock.AirbnkBleLock(runtime)
    assert lock_entity.available is True
    assert lock_entity.is_locked is True
    assert lock_entity.icon == "mdi:lock-outline"
    assert lock_entity.extra_state_attributes["remote_lock_supported"] is False
    assert lock_entity.extra_state_attributes["restored_until_first_advert"] is True
    assert lock_entity.extra_state_attributes["state_is_stale"] is True

    await lock_entity.async_lock()
    await lock_entity.async_unlock()
    await lock_entity.async_open()

    runtime.async_lock.assert_awaited_once()
    runtime.async_unlock.assert_awaited_once()
    runtime.async_open.assert_awaited_once()


async def test_lock_entity_supports_mailbox_and_custom_icons() -> None:
    """Lock entities should honor configured icon styles per lock."""

    runtime = _build_runtime()
    lock_entity = lock.AirbnkBleLock(runtime)

    runtime.lock_icon = "mdi:mailbox-up-outline"
    runtime.is_locked = True
    assert lock_entity.icon == "mdi:mailbox-up-outline"

    runtime.is_locked = False
    assert lock_entity.icon == "mdi:mailbox-open-up-outline"

    runtime.is_locked = None
    assert lock_entity.icon == "mdi:mailbox-outline"

    runtime.lock_icon = "mdi:package-variant-closed"
    runtime.is_locked = True
    assert lock_entity.icon == "mdi:package-variant-closed"

    runtime.is_locked = False
    assert lock_entity.icon == "mdi:package-variant-closed"


async def test_base_entity_subscribes_on_added_to_hass() -> None:
    """Base entities should subscribe to runtime callbacks when added."""

    runtime = _build_runtime()
    battery_description = next(
        description for description in sensor.SENSORS if description.key == "battery"
    )
    battery_sensor = sensor.AirbnkBleSensor(runtime, battery_description)
    battery_sensor.async_on_remove = MagicMock()

    with patch(
        "homeassistant.helpers.entity.Entity.async_added_to_hass",
        AsyncMock(return_value=None),
    ):
        await battery_sensor.async_added_to_hass()

    runtime.register_callback.assert_called_once()
    battery_sensor.async_on_remove.assert_called_once()

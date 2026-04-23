"""Runtime tests for Airbnk BLE."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble.airbnk import (
    BootstrapData,
    build_entry_data,
    parse_advertisement_data,
    parse_status_response,
)
from custom_components.airbnk_ble.const import OPERATION_LOCK, OPERATION_UNLOCK
from custom_components.airbnk_ble.device import AirbnkLockRuntime
from custom_components.airbnk_ble.profiles import get_model_profile

from .common import build_advertisement_payload, build_status_payload


async def test_runtime_applies_advertisement_and_status_updates(
    hass: HomeAssistant,
) -> None:
    """Runtime should apply parsed advert and status data to state."""

    profile = get_model_profile("B100")
    bootstrap = BootstrapData(
        lock_sn="B100LOCK00000001",
        lock_model="B100",
        profile=profile.key,
        manufacturer_key=b"0123456789ABCDEF",
        binding_key=b"FEDCBA9876543210",
    )
    entry = MockConfigEntry(
        domain="airbnk_ble",
        title="Front Gate",
        data=build_entry_data(
            name="Front Gate",
            mac_address="AA:BB:CC:DD:EE:FF",
            bootstrap=bootstrap,
            battery_profile=[
                {"voltage": 2.3, "percent": 0.0},
                {"voltage": 2.5, "percent": 30.0},
                {"voltage": 2.6, "percent": 60.0},
                {"voltage": 2.9, "percent": 100.0},
            ],
        ),
    )
    runtime = AirbnkLockRuntime(hass, entry, bootstrap)

    advert = parse_advertisement_data(
        build_advertisement_payload(serial_fragment=bootstrap.lock_sn[:9]),
        expected_lock_sn=bootstrap.lock_sn,
    )
    runtime._apply_advertisement(  # noqa: SLF001
        advert,
        SimpleNamespace(rssi=-60, source="local", connectable=False, device=None),
        payload_hex=build_advertisement_payload(serial_fragment=bootstrap.lock_sn[:9])
        .hex()
        .upper(),
    )

    assert runtime.state.available is True
    assert runtime.state.lock_events == 1
    assert runtime.state.battery_percent is not None

    status = parse_status_response(build_status_payload())
    runtime._apply_status_response(status)  # noqa: SLF001

    assert runtime.state.lock_events == 1
    assert runtime.state.voltage == 3.0


async def test_runtime_rejects_lock_when_remote_lock_is_disabled(
    hass: HomeAssistant,
) -> None:
    """Unlock-only profiles should reject remote lock commands immediately."""

    profile = get_model_profile("B100")
    bootstrap = BootstrapData(
        lock_sn="B100LOCK00000001",
        lock_model="B100",
        profile=profile.key,
        manufacturer_key=b"0123456789ABCDEF",
        binding_key=b"FEDCBA9876543210",
    )
    entry = MockConfigEntry(
        domain="airbnk_ble",
        title="Front Gate",
        data=build_entry_data(
            name="Front Gate",
            mac_address="AA:BB:CC:DD:EE:FF",
            bootstrap=bootstrap,
            battery_profile=[
                {"voltage": 2.3, "percent": 0.0},
                {"voltage": 2.5, "percent": 30.0},
                {"voltage": 2.6, "percent": 60.0},
                {"voltage": 2.9, "percent": 100.0},
            ],
            supports_remote_lock=False,
        ),
    )
    runtime = AirbnkLockRuntime(hass, entry, bootstrap)
    runtime.state.lock_events = 5

    with pytest.raises(HomeAssistantError, match="Remote locking is not supported"):
        await runtime.async_lock()

    assert runtime.state.last_requested_operation == OPERATION_LOCK
    assert runtime.state.last_wire_operation is None


async def test_runtime_requires_advert_before_command(
    hass: HomeAssistant,
) -> None:
    """Commands should fail until the lock counter has been discovered."""

    profile = get_model_profile("B100")
    bootstrap = BootstrapData(
        lock_sn="B100LOCK00000001",
        lock_model="B100",
        profile=profile.key,
        manufacturer_key=b"0123456789ABCDEF",
        binding_key=b"FEDCBA9876543210",
    )
    entry = MockConfigEntry(
        domain="airbnk_ble",
        title="Front Gate",
        data=build_entry_data(
            name="Front Gate",
            mac_address="AA:BB:CC:DD:EE:FF",
            bootstrap=bootstrap,
            battery_profile=[
                {"voltage": 2.3, "percent": 0.0},
                {"voltage": 2.5, "percent": 30.0},
                {"voltage": 2.6, "percent": 60.0},
                {"voltage": 2.9, "percent": 100.0},
            ],
            supports_remote_lock=True,
        ),
    )
    runtime = AirbnkLockRuntime(hass, entry, bootstrap)

    with pytest.raises(HomeAssistantError, match="lock counter is unknown"):
        await runtime.async_unlock()


async def test_runtime_helper_logic_for_reverse_restore_and_transient_status(
    hass: HomeAssistant,
) -> None:
    """Small runtime helpers should preserve lock semantics."""

    profile = get_model_profile("B100")
    bootstrap = BootstrapData(
        lock_sn="B100LOCK00000001",
        lock_model="B100",
        profile=profile.key,
        manufacturer_key=b"0123456789ABCDEF",
        binding_key=b"FEDCBA9876543210",
    )
    entry = MockConfigEntry(
        domain="airbnk_ble",
        title="Front Gate",
        data=build_entry_data(
            name="Front Gate",
            mac_address="AA:BB:CC:DD:EE:FF",
            bootstrap=bootstrap,
            battery_profile=[
                {"voltage": 2.3, "percent": 0.0},
                {"voltage": 2.5, "percent": 30.0},
                {"voltage": 2.6, "percent": 60.0},
                {"voltage": 2.9, "percent": 100.0},
            ],
            reverse_commands=True,
            supports_remote_lock=True,
        ),
    )
    runtime = AirbnkLockRuntime(hass, entry, bootstrap)

    assert runtime._wire_operation_for(OPERATION_LOCK) == OPERATION_UNLOCK  # noqa: SLF001
    assert runtime._wire_operation_for(OPERATION_UNLOCK) == OPERATION_LOCK  # noqa: SLF001

    runtime.restore_lock_state(1)
    assert runtime.state.restored is True
    assert runtime.state.last_source == "restored_state"

    transient = parse_status_response(build_status_payload(trailing_byte=0x00))
    runtime._remember_status_debug(transient, payload_hex="AA00")  # noqa: SLF001
    assert runtime._status_response_is_transient(transient) is True  # noqa: SLF001
    assert runtime.state.last_status_payload_hex == "AA00"


async def test_runtime_probe_failure_marks_reachability_false(
    hass: HomeAssistant,
) -> None:
    """Stale locks should mark reachability false when the probe fails."""

    profile = get_model_profile("B100")
    bootstrap = BootstrapData(
        lock_sn="B100LOCK00000001",
        lock_model="B100",
        profile=profile.key,
        manufacturer_key=b"0123456789ABCDEF",
        binding_key=b"FEDCBA9876543210",
    )
    entry = MockConfigEntry(
        domain="airbnk_ble",
        title="Front Gate",
        data=build_entry_data(
            name="Front Gate",
            mac_address="AA:BB:CC:DD:EE:FF",
            bootstrap=bootstrap,
            battery_profile=[
                {"voltage": 2.3, "percent": 0.0},
                {"voltage": 2.5, "percent": 30.0},
                {"voltage": 2.6, "percent": 60.0},
                {"voltage": 2.9, "percent": 100.0},
            ],
            connectivity_probe_interval=30,
        ),
    )
    runtime = AirbnkLockRuntime(hass, entry, bootstrap)
    runtime.state.available = False
    runtime.state.reachable = True
    runtime.state.last_contact_monotonic = 0.0

    with patch(
        "custom_components.airbnk_ble.device.establish_connection",
        AsyncMock(side_effect=HomeAssistantError("probe failed")),
    ):
        await runtime._async_probe_connectivity()  # noqa: SLF001

    assert runtime.state.reachable is False
    assert runtime.state.last_probe_successful is False

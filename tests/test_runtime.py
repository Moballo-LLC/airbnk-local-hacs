"""Runtime tests for Airbnk BLE."""

from __future__ import annotations

from types import SimpleNamespace

from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airbnk_ble.airbnk import (
    BootstrapData,
    build_entry_data,
    parse_advertisement_data,
    parse_status_response,
)
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

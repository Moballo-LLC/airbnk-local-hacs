"""Protocol and storage tests for Airbnk BLE."""

from __future__ import annotations

from custom_components.airbnk_ble.airbnk import (
    build_entry_data,
    calculate_battery_percentage,
    decrypt_bootstrap,
    generate_operation_code,
    parse_advertisement_data,
    parse_status_response,
    validate_entry_data,
)
from custom_components.airbnk_ble.profiles import BatteryBreakpoint

from .common import (
    build_advertisement_payload,
    build_bootstrap_fixture,
    build_status_payload,
)


def test_battery_percentage_uses_piecewise_profile() -> None:
    """Interpolate battery values against an arbitrary profile."""

    profile = (
        BatteryBreakpoint(2.3, 0.0),
        BatteryBreakpoint(2.5, 20.0),
        BatteryBreakpoint(2.7, 75.0),
        BatteryBreakpoint(2.9, 100.0),
    )

    assert calculate_battery_percentage(2.2, profile) == 0.0
    assert calculate_battery_percentage(2.6, profile) == 47.5
    assert calculate_battery_percentage(2.95, profile) == 100.0


def test_bootstrap_can_be_decrypted_and_stored_without_raw_secrets() -> None:
    """Build entry data from a manual bootstrap and validate stored values."""

    fixture = build_bootstrap_fixture()
    bootstrap = decrypt_bootstrap(
        fixture["lock_sn"],
        fixture["new_sninfo"],
        fixture["app_key"],
    )

    entry_data = build_entry_data(
        name="Front Gate",
        mac_address="AA:BB:CC:DD:EE:FF",
        bootstrap=bootstrap,
        battery_profile=[
            {"voltage": 2.3, "percent": 0.0},
            {"voltage": 2.5, "percent": 30.0},
            {"voltage": 2.6, "percent": 60.0},
            {"voltage": 2.9, "percent": 100.0},
        ],
    )

    assert "app_key" not in entry_data
    assert "new_sninfo" not in entry_data

    normalized, validated_bootstrap = validate_entry_data(entry_data)

    assert normalized["lock_sn"] == fixture["lock_sn"]
    assert validated_bootstrap.manufacturer_key == fixture["manufacturer_key"]
    assert validated_bootstrap.binding_key == fixture["binding_key"]


def test_operation_code_generation_is_stable() -> None:
    """Generate a raw operation frame from a valid bootstrap."""

    fixture = build_bootstrap_fixture()
    bootstrap = decrypt_bootstrap(
        fixture["lock_sn"],
        fixture["new_sninfo"],
        fixture["app_key"],
    )

    operation = generate_operation_code(1, 42, bootstrap, timestamp=1_700_000_000)

    assert len(operation) == 36
    assert operation[:3] == b"\xaa\x10\x1a"


def test_parsers_decode_advert_and_status_frames() -> None:
    """Parse synthetic advert and status frames."""

    advert = build_advertisement_payload()
    parsed_advert = parse_advertisement_data(advert)
    assert parsed_advert.serial_number == "B100LOCK0"
    assert parsed_advert.voltage == 3.0

    status = build_status_payload()
    parsed_status = parse_status_response(status)
    assert parsed_status.lock_events == 1
    assert parsed_status.voltage == 3.0


def test_advertisement_matching_accepts_shorter_serial_fragment() -> None:
    """A BLE advert fragment should still match the configured full serial."""

    advert = build_advertisement_payload(serial_fragment="B100LOCK0")
    parsed_advert = parse_advertisement_data(
        advert,
        expected_lock_sn="B100LOCK00000001",
    )

    assert parsed_advert.serial_number == "B100LOCK0"

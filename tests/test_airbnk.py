"""Protocol and storage tests for Airbnk BLE."""

from __future__ import annotations

from custom_components.airbnk_ble.airbnk import (
    battery_profile_from_legacy_thresholds,
    build_entry_data,
    build_entry_options,
    calculate_battery_percentage,
    decrypt_bootstrap,
    generate_operation_code,
    migrate_legacy_entry,
    migrate_legacy_entry_data,
    parse_advertisement_data,
    parse_status_response,
    validate_entry,
    validate_entry_data,
    validate_entry_options,
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
    assert "name" not in entry_data

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


def test_legacy_entry_data_migrates_without_changing_b100_curve() -> None:
    """Older local entries should normalize into the public storage format."""

    fixture = build_bootstrap_fixture()
    legacy_data = {
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
    }

    migrated = migrate_legacy_entry_data(legacy_data)
    normalized, bootstrap = validate_entry_data(legacy_data)
    migrated_data, migrated_options = migrate_legacy_entry(legacy_data, {})
    normalized_data, normalized_options, _validated_bootstrap = validate_entry(
        legacy_data,
        {},
    )

    assert normalized == migrated
    assert normalized_data == migrated_data
    assert normalized_options == migrated_options
    assert "app_key" not in normalized
    assert "new_sninfo" not in normalized
    assert normalized["battery_profile"] == [
        {"voltage": 2.5, "percent": 0.0},
        {"voltage": 2.6, "percent": 50.0},
        {"voltage": 2.9, "percent": 100.0},
    ]
    assert (
        calculate_battery_percentage(
            2.55,
            battery_profile_from_legacy_thresholds([2.5, 2.6, 2.9]),
        )
        == 25.0
    )
    assert bootstrap.lock_model == fixture["lock_model"]
    assert bootstrap.manufacturer_key == fixture["manufacturer_key"]


def test_entry_options_prefer_options_but_fall_back_to_legacy_data() -> None:
    """Options should migrate cleanly out of older entry data."""

    normalized = validate_entry_options(
        {
            "name": "Front Door",
            "retry_count": 5,
        },
        lock_model="B100",
        legacy_data={
            "name": "Legacy Name",
            "lock_icon": "mdi:mailbox-up-outline",
            "reverse_commands": True,
            "supports_remote_lock": True,
            "retry_count": 3,
            "command_timeout": 20,
            "connectivity_probe_interval": 10,
            "unavailable_after": 120,
        },
    )

    assert normalized["name"] == "Front Door"
    assert normalized["lock_icon"] == "mdi:mailbox-up-outline"
    assert normalized["publish_diagnostic_entities"] is False
    assert normalized["retry_count"] == 5
    assert normalized["reverse_commands"] is True
    assert normalized["supports_remote_lock"] is True
    assert normalized["command_timeout"] == 20
    assert normalized["connectivity_probe_interval"] == 10
    assert normalized["unavailable_after"] == 120


def test_build_entry_options_normalizes_defaults_for_model() -> None:
    """New options should validate and fill model-aware defaults."""

    options = build_entry_options(
        name="Front Gate",
        lock_model="B100",
    )

    assert options["name"] == "Front Gate"
    assert options["lock_icon"] == ""
    assert options["publish_diagnostic_entities"] is False
    assert options["reverse_commands"] is False
    assert options["supports_remote_lock"] is False
    assert options["retry_count"] == 3


def test_build_entry_options_normalizes_custom_icon() -> None:
    """Custom icons should normalize into lowercase mdi names."""

    options = build_entry_options(
        name="Front Gate",
        lock_model="B100",
        lock_icon=" MDI:Mailbox-Up-Outline ",
    )

    assert options["lock_icon"] == "mdi:mailbox-up-outline"


def test_build_entry_options_can_enable_diagnostic_entities() -> None:
    """Diagnostic entities should be opt-in and persist in options."""

    options = build_entry_options(
        name="Front Gate",
        lock_model="B100",
        publish_diagnostic_entities=True,
    )

    assert options["publish_diagnostic_entities"] is True


def test_validate_entry_options_rejects_invalid_custom_icon() -> None:
    """Only valid mdi icons should be accepted for the optional custom icon."""

    try:
        validate_entry_options(
            {"lock_icon": "mailbox"},
            lock_model="B100",
        )
    except ValueError as err:
        assert "lock_icon" in str(err)
    else:
        raise AssertionError("invalid icon should raise")


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

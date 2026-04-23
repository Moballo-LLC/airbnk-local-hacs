"""Constants for the Airbnk BLE integration."""

from __future__ import annotations

from homeassistant.const import Platform

DOMAIN = "airbnk_ble"

PLATFORMS: list[Platform] = [
    Platform.LOCK,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]

CONF_BATTERY_PROFILE = "battery_profile"
CONF_BINDING_KEY = "binding_key"
CONF_COMMAND_TIMEOUT = "command_timeout"
CONF_CONNECTIVITY_PROBE_INTERVAL = "connectivity_probe_interval"
CONF_DISCOVERED_ADDRESS = "discovered_address"
CONF_HARDWARE_VERSION = "hardware_version"
CONF_LOCK_MODEL = "lock_model"
CONF_LOCK_SN = "lock_sn"
CONF_MAC_ADDRESS = "mac_address"
CONF_MANUFACTURER_KEY = "manufacturer_key"
CONF_NEW_SNINFO = "new_sninfo"
CONF_PROFILE = "profile"
CONF_REVERSE_COMMANDS = "reverse_commands"
CONF_RETRY_COUNT = "retry_count"
CONF_SETUP_MODE = "setup_mode"
CONF_SUPPORTS_REMOTE_LOCK = "supports_remote_lock"
CONF_UNAVAILABLE_AFTER = "unavailable_after"

DEFAULT_NAME = "Airbnk Lock"
DEFAULT_COMMAND_TIMEOUT = 15
DEFAULT_CONNECTIVITY_PROBE_INTERVAL = 0
DEFAULT_RETRY_COUNT = 3
DEFAULT_REVERSE_COMMANDS = False
DEFAULT_SUPPORTS_REMOTE_LOCK = False
DEFAULT_UNAVAILABLE_AFTER = 60

SETUP_MODE_CLOUD = "cloud"
SETUP_MODE_MANUAL = "manual"

DISCOVERED_ADDRESS_MANUAL = "__manual__"

MANUFACTURER_ID_AIRBNK = 0xBABA
AIRBNK_ADV_SERVICE_UUID = "0000abab-0000-1000-8000-00805f9b34fb"
AIRBNK_GATT_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
AIRBNK_WRITE_CHARACTERISTIC_UUID = "0000fff2-0000-1000-8000-00805f9b34fb"
AIRBNK_STATUS_CHARACTERISTIC_UUID = "0000fff3-0000-1000-8000-00805f9b34fb"

# AirBnk lock advertisements report the physical state in a nibble that can be
# inverted by the door orientation flag. Status responses also expose alias
# values 4/5 for those same states, so all runtime callers should normalize raw
# values through the protocol helpers rather than assuming a simple 0/1 field.
LOCK_STATE_LOCKED = 1
LOCK_STATE_UNLOCKED = 0
LOCK_STATE_JAMMED = 2

OPERATION_UNLOCK = 1
OPERATION_LOCK = 2

HIDDEN_BY_DEFAULT_SENSOR_KEYS = frozenset(
    {
        "state_source",
        "lock_events_counter",
    }
)

DISABLED_BY_DEFAULT_SENSOR_KEYS = frozenset(
    {
        "advert_state_byte",
        "advert_state_bits",
        "advert_state_meaning",
        "status_state_byte",
        "status_state_bits",
        "status_state_meaning",
        "status_tail_byte",
    }
)

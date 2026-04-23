"""Pure Airbnk protocol and config helpers."""

from __future__ import annotations

import base64
import binascii
import hashlib
import string
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .const import (
    CONF_BATTERY_PROFILE,
    CONF_BINDING_KEY,
    CONF_COMMAND_TIMEOUT,
    CONF_CONNECTIVITY_PROBE_INTERVAL,
    CONF_HARDWARE_VERSION,
    CONF_LOCK_MODEL,
    CONF_LOCK_SN,
    CONF_MAC_ADDRESS,
    CONF_MANUFACTURER_KEY,
    CONF_PROFILE,
    CONF_RETRY_COUNT,
    CONF_REVERSE_COMMANDS,
    CONF_SUPPORTS_REMOTE_LOCK,
    CONF_UNAVAILABLE_AFTER,
    DEFAULT_COMMAND_TIMEOUT,
    DEFAULT_CONNECTIVITY_PROBE_INTERVAL,
    DEFAULT_NAME,
    DEFAULT_RETRY_COUNT,
    DEFAULT_REVERSE_COMMANDS,
    DEFAULT_UNAVAILABLE_AFTER,
    LOCK_STATE_JAMMED,
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNLOCKED,
    OPERATION_LOCK,
    OPERATION_UNLOCK,
)
from .profiles import (
    SUPPORTED_MODELS,
    BatteryBreakpoint,
    get_model_profile,
)


class AirbnkProtocolError(ValueError):
    """Raised when Airbnk data cannot be parsed or validated."""


@dataclass(frozen=True, slots=True)
class BootstrapData:
    """Derived Airbnk bootstrap data used at runtime."""

    lock_sn: str
    lock_model: str
    profile: str
    manufacturer_key: bytes
    binding_key: bytes


@dataclass(frozen=True, slots=True)
class AdvertisementData:
    """Decoded Airbnk advertisement payload."""

    serial_number: str
    board_model: int
    firmware_version: str
    voltage: float
    lock_events: int
    lock_state: int
    raw_state_bits: int
    raw_state_label: str
    opens_clockwise: bool
    is_low_battery: bool
    state_flags: int
    battery_flags: int


@dataclass(frozen=True, slots=True)
class StatusResponseData:
    """Decoded Airbnk command status payload."""

    lock_events: int
    voltage: float
    lock_state: int
    raw_state_nibble: int
    raw_state_label: str
    state_byte: int
    trailing_byte: int


class _AESCipher:
    """AES ECB helper matching the Airbnk reference implementation."""

    def __init__(self, key: bytes) -> None:
        self._cipher = Cipher(algorithms.AES(key), modes.ECB(), default_backend())
        self._block_size = 16

    def encrypt(self, raw: bytes, use_base64: bool = True) -> bytes:
        """Encrypt data."""
        encryptor = self._cipher.encryptor()
        encrypted = encryptor.update(self._pad(raw)) + encryptor.finalize()
        return base64.b64encode(encrypted) if use_base64 else encrypted

    def decrypt(self, enc: bytes, use_base64: bool = True) -> bytes:
        """Decrypt data."""
        payload = base64.b64decode(enc) if use_base64 else enc
        decryptor = self._cipher.decryptor()
        return self._unpad(decryptor.update(payload) + decryptor.finalize())

    def _pad(self, data: bytes) -> bytes:
        pad_count = self._block_size - (len(data) % self._block_size)
        return data + bytes([pad_count]) * pad_count

    @staticmethod
    def _unpad(data: bytes) -> bytes:
        return data[: -data[-1]]


def normalize_mac_address(value: str) -> str:
    """Normalize a MAC address to uppercase colon-separated form."""

    compact = value.replace(":", "").replace("-", "").strip().upper()
    if len(compact) != 12 or any(
        char not in string.hexdigits.upper() for char in compact
    ):
        raise AirbnkProtocolError(f"Invalid MAC address: {value}")
    return ":".join(compact[index : index + 2] for index in range(0, 12, 2))


def serial_numbers_match(expected_lock_sn: str, observed_lock_sn: str) -> bool:
    """Return whether two Airbnk serial identifiers refer to the same lock.

    BLE advertisements may expose only a shorter serial fragment while the
    cloud/bootstrap payload keeps the full serial number. Treat a prefix match
    as equivalent so setup and runtime state can still associate the lock.
    """

    expected = expected_lock_sn.strip().upper()
    observed = observed_lock_sn.strip().upper()
    if not expected or not observed:
        return False
    return (
        expected == observed
        or expected.startswith(observed)
        or observed.startswith(expected)
    )


def normalize_battery_profile(value: Any) -> tuple[BatteryBreakpoint, ...]:
    """Validate and normalize a battery interpolation profile."""

    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise AirbnkProtocolError("battery_profile must be a list of breakpoints")

    points: list[BatteryBreakpoint] = []
    for item in value:
        if isinstance(item, BatteryBreakpoint):
            voltage = item.voltage
            percent = item.percent
        elif isinstance(item, Mapping):
            try:
                voltage = float(item["voltage"])
                percent = float(item["percent"])
            except (KeyError, TypeError, ValueError) as err:
                raise AirbnkProtocolError(
                    "battery_profile breakpoints must contain voltage and percent"
                ) from err
        elif (
            isinstance(item, Sequence)
            and not isinstance(item, (str, bytes))
            and len(item) == 2
        ):
            try:
                voltage = float(item[0])
                percent = float(item[1])
            except (TypeError, ValueError) as err:
                raise AirbnkProtocolError(
                    "battery_profile breakpoints must contain numeric "
                    "voltage and percent"
                ) from err
        else:
            raise AirbnkProtocolError(
                "battery_profile breakpoints must be [voltage, percent] "
                "pairs or mappings"
            )

        if not 0.0 <= percent <= 100.0:
            raise AirbnkProtocolError(
                "battery_profile percent values must be between 0 and 100"
            )
        points.append(BatteryBreakpoint(round(voltage, 3), round(percent, 1)))

    if len(points) < 2:
        raise AirbnkProtocolError("battery_profile must contain at least 2 breakpoints")

    previous_voltage = points[0].voltage
    previous_percent = points[0].percent
    for point in points[1:]:
        if point.voltage <= previous_voltage:
            raise AirbnkProtocolError(
                "battery_profile voltages must be strictly increasing"
            )
        if point.percent < previous_percent:
            raise AirbnkProtocolError(
                "battery_profile percentages must be monotonic increasing"
            )
        previous_voltage = point.voltage
        previous_percent = point.percent

    return tuple(points)


def battery_profile_to_storage(
    profile: Sequence[BatteryBreakpoint],
) -> list[dict[str, float]]:
    """Convert a battery profile into JSON-serializable storage."""

    return [
        {
            "voltage": float(point.voltage),
            "percent": float(point.percent),
        }
        for point in profile
    ]


def battery_profile_from_voltage_points(
    values: Sequence[Any],
) -> tuple[BatteryBreakpoint, ...]:
    """Build an evenly distributed battery profile from cloud voltage points."""

    if not values:
        raise AirbnkProtocolError(
            "Cloud battery profile did not include any voltage values"
        )

    total_points = len(values)
    if total_points < 2:
        raise AirbnkProtocolError(
            "Cloud battery profile must include at least 2 voltage values"
        )

    breakpoints = []
    for index, raw_voltage in enumerate(values):
        percent = round((index / (total_points - 1)) * 100.0, 1)
        breakpoints.append(
            BatteryBreakpoint(
                float(raw_voltage),
                percent,
            )
        )
    return normalize_battery_profile(breakpoints)


def calculate_battery_percentage(
    voltage: float, battery_profile: Sequence[BatteryBreakpoint]
) -> float:
    """Calculate battery percentage by piecewise linear interpolation."""

    profile = normalize_battery_profile(battery_profile)

    if voltage <= profile[0].voltage:
        return profile[0].percent
    if voltage >= profile[-1].voltage:
        return profile[-1].percent

    for lower, upper in zip(profile, profile[1:], strict=False):
        if lower.voltage <= voltage <= upper.voltage:
            if voltage == lower.voltage:
                return lower.percent
            if voltage == upper.voltage:
                return upper.percent
            span = upper.voltage - lower.voltage
            if span <= 0:
                raise AirbnkProtocolError(
                    "battery_profile contains an invalid voltage span"
                )
            ratio = (voltage - lower.voltage) / span
            return round(lower.percent + ((upper.percent - lower.percent) * ratio), 1)

    return profile[-1].percent


def decrypt_bootstrap(lock_sn: str, new_sninfo: str, app_key: str) -> BootstrapData:
    """Decrypt Airbnk bootstrap data and extract the working keys."""

    try:
        decoded = base64.b64decode(new_sninfo)
    except binascii.Error as err:
        raise AirbnkProtocolError("new_sninfo is not valid base64") from err

    if len(app_key) < 20:
        raise AirbnkProtocolError("app_key is unexpectedly short")
    if len(decoded) <= 10:
        raise AirbnkProtocolError("new_sninfo payload is unexpectedly short")

    encrypted_payload = decoded[:-10]
    decrypted = _AESCipher(app_key[:-4].encode("utf-8")).decrypt(
        encrypted_payload,
        use_base64=False,
    )

    decrypted_lock_sn = decrypted[0:16].decode("utf-8").rstrip("\x00")
    if decrypted_lock_sn != lock_sn:
        raise AirbnkProtocolError(
            "lock_sn "
            f"'{lock_sn}' does not match decrypted bootstrap data "
            f"'{decrypted_lock_sn}'"
        )

    lock_model = decrypted[80:88].decode("utf-8").rstrip("\x00")
    try:
        profile = get_model_profile(lock_model)
    except KeyError as err:
        supported = ", ".join(sorted(SUPPORTED_MODELS))
        raise AirbnkProtocolError(
            f"Unsupported Airbnk lock model '{lock_model}'. "
            f"Supported models: {supported}"
        ) from err

    digest = hashlib.sha1(f"{decrypted_lock_sn}{app_key}".encode()).hexdigest()
    aes_key = bytes.fromhex(digest[0:32])

    manufacturer_key = _AESCipher(aes_key).decrypt(
        decrypted[16:48],
        use_base64=False,
    )
    binding_key = _AESCipher(aes_key).decrypt(
        decrypted[48:80],
        use_base64=False,
    )

    if len(manufacturer_key) < 16:
        raise AirbnkProtocolError("Decrypted manufacturer key is shorter than 16 bytes")
    if len(binding_key) < 16:
        raise AirbnkProtocolError("Decrypted binding key is shorter than 16 bytes")

    return BootstrapData(
        lock_sn=decrypted_lock_sn,
        lock_model=lock_model,
        profile=profile.key,
        manufacturer_key=manufacturer_key,
        binding_key=binding_key,
    )


def build_entry_data(
    *,
    name: str | None,
    mac_address: str,
    bootstrap: BootstrapData,
    battery_profile: Sequence[BatteryBreakpoint] | Sequence[Mapping[str, float]],
    reverse_commands: bool = DEFAULT_REVERSE_COMMANDS,
    supports_remote_lock: bool | None = None,
    retry_count: int = DEFAULT_RETRY_COUNT,
    command_timeout: int = DEFAULT_COMMAND_TIMEOUT,
    connectivity_probe_interval: int = DEFAULT_CONNECTIVITY_PROBE_INTERVAL,
    unavailable_after: int = DEFAULT_UNAVAILABLE_AFTER,
    hardware_version: str | None = None,
) -> dict[str, Any]:
    """Build stored config-entry data from bootstrap and user choices."""

    model_profile = get_model_profile(bootstrap.lock_model)
    normalized_battery_profile = normalize_battery_profile(battery_profile)

    resolved_name = (name or DEFAULT_NAME).strip() or DEFAULT_NAME
    resolved_supports_remote_lock = (
        model_profile.supports_remote_lock
        if supports_remote_lock is None
        else bool(supports_remote_lock)
    )

    return {
        CONF_LOCK_SN: bootstrap.lock_sn,
        CONF_LOCK_MODEL: bootstrap.lock_model,
        CONF_PROFILE: model_profile.key,
        CONF_MAC_ADDRESS: normalize_mac_address(mac_address),
        CONF_MANUFACTURER_KEY: bootstrap.manufacturer_key.hex(),
        CONF_BINDING_KEY: bootstrap.binding_key.hex(),
        CONF_BATTERY_PROFILE: battery_profile_to_storage(normalized_battery_profile),
        CONF_REVERSE_COMMANDS: bool(reverse_commands),
        CONF_SUPPORTS_REMOTE_LOCK: resolved_supports_remote_lock,
        CONF_RETRY_COUNT: int(retry_count),
        CONF_COMMAND_TIMEOUT: int(command_timeout),
        CONF_CONNECTIVITY_PROBE_INTERVAL: int(connectivity_probe_interval),
        CONF_UNAVAILABLE_AFTER: int(unavailable_after),
        CONF_HARDWARE_VERSION: (hardware_version or "").strip(),
        "name": resolved_name,
    }


def validate_entry_data(
    data: Mapping[str, Any],
) -> tuple[dict[str, Any], BootstrapData]:
    """Normalize and validate stored config-entry data."""

    lock_sn = str(data[CONF_LOCK_SN]).strip()
    if not lock_sn:
        raise AirbnkProtocolError("lock_sn is required")

    lock_model = str(data[CONF_LOCK_MODEL]).strip()
    if not lock_model:
        raise AirbnkProtocolError("lock_model is required")

    try:
        model_profile = get_model_profile(lock_model)
    except KeyError as err:
        supported = ", ".join(sorted(SUPPORTED_MODELS))
        raise AirbnkProtocolError(
            f"Unsupported Airbnk lock model '{lock_model}'. "
            f"Supported models: {supported}"
        ) from err

    normalized: dict[str, Any] = {
        "name": str(data.get("name") or DEFAULT_NAME).strip() or DEFAULT_NAME,
        CONF_MAC_ADDRESS: normalize_mac_address(str(data[CONF_MAC_ADDRESS])),
        CONF_LOCK_SN: lock_sn,
        CONF_LOCK_MODEL: lock_model,
        CONF_PROFILE: str(data.get(CONF_PROFILE) or model_profile.key),
        CONF_MANUFACTURER_KEY: _normalize_key_hex(
            data[CONF_MANUFACTURER_KEY], "manufacturer_key"
        ),
        CONF_BINDING_KEY: _normalize_key_hex(data[CONF_BINDING_KEY], "binding_key"),
        CONF_BATTERY_PROFILE: battery_profile_to_storage(
            normalize_battery_profile(data[CONF_BATTERY_PROFILE])
        ),
        CONF_REVERSE_COMMANDS: bool(
            data.get(CONF_REVERSE_COMMANDS, DEFAULT_REVERSE_COMMANDS)
        ),
        CONF_SUPPORTS_REMOTE_LOCK: bool(
            data.get(CONF_SUPPORTS_REMOTE_LOCK, model_profile.supports_remote_lock)
        ),
        CONF_RETRY_COUNT: int(data.get(CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT)),
        CONF_COMMAND_TIMEOUT: int(
            data.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT)
        ),
        CONF_CONNECTIVITY_PROBE_INTERVAL: int(
            data.get(
                CONF_CONNECTIVITY_PROBE_INTERVAL, DEFAULT_CONNECTIVITY_PROBE_INTERVAL
            )
        ),
        CONF_UNAVAILABLE_AFTER: int(
            data.get(CONF_UNAVAILABLE_AFTER, DEFAULT_UNAVAILABLE_AFTER)
        ),
        CONF_HARDWARE_VERSION: str(data.get(CONF_HARDWARE_VERSION, "")).strip(),
    }

    if normalized[CONF_PROFILE] != model_profile.key:
        raise AirbnkProtocolError(
            f"profile '{normalized[CONF_PROFILE]}' does not match "
            f"lock model '{lock_model}'"
        )
    if normalized[CONF_RETRY_COUNT] < 0:
        raise AirbnkProtocolError("retry_count must be 0 or greater")
    if normalized[CONF_COMMAND_TIMEOUT] < 1:
        raise AirbnkProtocolError("command_timeout must be at least 1 second")
    if normalized[CONF_CONNECTIVITY_PROBE_INTERVAL] < 0:
        raise AirbnkProtocolError("connectivity_probe_interval must be 0 or greater")
    if normalized[CONF_UNAVAILABLE_AFTER] < 1:
        raise AirbnkProtocolError("unavailable_after must be at least 1 second")

    bootstrap = BootstrapData(
        lock_sn=lock_sn,
        lock_model=lock_model,
        profile=model_profile.key,
        manufacturer_key=bytes.fromhex(normalized[CONF_MANUFACTURER_KEY]),
        binding_key=bytes.fromhex(normalized[CONF_BINDING_KEY]),
    )
    return normalized, bootstrap


def parse_advertisement_data(
    payload: bytes,
    *,
    expected_lock_sn: str | None = None,
) -> AdvertisementData:
    """Parse Airbnk manufacturer data as exposed by Home Assistant Bluetooth."""

    if payload.startswith(b"\xba\xba"):
        payload = payload[2:]

    if len(payload) < 22:
        raise AirbnkProtocolError("Airbnk manufacturer payload is too short")

    serial_number = payload[5:14].decode("utf-8").rstrip("\x00")
    if expected_lock_sn and not serial_numbers_match(expected_lock_sn, serial_number):
        raise AirbnkProtocolError(
            f"Advertisement serial '{serial_number}' does not match "
            f"configured lock '{expected_lock_sn}'"
        )

    voltage = int.from_bytes(payload[14:16], byteorder="big") * 0.01
    lock_events = int.from_bytes(payload[16:20], byteorder="big")
    state_flags = payload[20]
    battery_flags = payload[21]
    raw_state_bits = (state_flags >> 4) & 0x03
    lock_state = raw_state_bits
    opens_clockwise = bool(state_flags & 0x80)

    if opens_clockwise and lock_state in (LOCK_STATE_LOCKED, LOCK_STATE_UNLOCKED):
        lock_state = 1 - lock_state

    return AdvertisementData(
        serial_number=serial_number,
        board_model=payload[0],
        firmware_version=f"{payload[2]}.{payload[3]}.{payload[4]}",
        voltage=voltage,
        lock_events=lock_events,
        lock_state=lock_state,
        raw_state_bits=raw_state_bits,
        raw_state_label=describe_advert_state_bits(raw_state_bits, opens_clockwise),
        opens_clockwise=opens_clockwise,
        is_low_battery=bool(battery_flags & 0x10),
        state_flags=state_flags,
        battery_flags=battery_flags,
    )


def parse_status_response(payload: bytes) -> StatusResponseData:
    """Parse the status response returned after a command write."""

    if len(payload) < 17:
        raise AirbnkProtocolError("Status response is too short")
    if payload[0] != 0xAA or payload[3] != 0x02 or payload[4] != 0x04:
        raise AirbnkProtocolError(
            f"Unexpected status response header: {payload.hex().upper()}"
        )

    raw_state_nibble = (payload[16] >> 4) & 0x07

    return StatusResponseData(
        lock_events=int.from_bytes(payload[10:14], byteorder="big"),
        voltage=int.from_bytes(payload[14:16], byteorder="big") * 0.01,
        lock_state=_normalize_status_state(raw_state_nibble),
        raw_state_nibble=raw_state_nibble,
        raw_state_label=describe_status_state_nibble(raw_state_nibble),
        state_byte=payload[16],
        trailing_byte=payload[-1],
    )


def generate_operation_code(
    operation: int,
    current_lock_events: int,
    bootstrap: BootstrapData,
    *,
    timestamp: int | None = None,
) -> bytes:
    """Generate the raw Airbnk operation payload."""

    if operation not in (OPERATION_UNLOCK, OPERATION_LOCK):
        raise AirbnkProtocolError(f"Unsupported operation: {operation}")

    command_time = int(time.time() if timestamp is None else timestamp)
    code = bytearray(36)
    code[0] = 0xAA
    code[1] = 0x10
    code[2] = 0x1A
    code[3] = 0x03
    code[4] = 0x03
    code[5] = 0x10 + operation
    code[8] = 0x01

    encoded_time = command_time
    code[12] = encoded_time & 0xFF
    encoded_time >>= 8
    code[11] = encoded_time & 0xFF
    encoded_time >>= 8
    code[10] = encoded_time & 0xFF
    encoded_time >>= 8
    code[9] = encoded_time & 0xFF

    encrypted = _AESCipher(bootstrap.manufacturer_key[:16]).encrypt(
        bytes(code[4:18]),
        use_base64=False,
    )
    code[4:20] = encrypted

    working_key = _generate_working_key(bootstrap.binding_key, 0)
    signature = _generate_signature_v2(
        working_key, current_lock_events, bytes(code[3:20])
    )
    code[20 : 20 + len(signature)] = signature
    code[28] = _checksum(code, 3, 28)
    return bytes(code)


def split_operation_frames(operation_code: bytes) -> tuple[bytes, bytes]:
    """Split the raw operation payload into the two FFF2 frames."""

    if len(operation_code) != 36:
        raise AirbnkProtocolError("Operation payload must be exactly 36 bytes")
    return (b"\xff\x00" + operation_code[:18], b"\xff\x01" + operation_code[18:])


def _normalize_status_state(raw_state_nibble: int) -> int:
    """Normalize the raw FFF3 state nibble into the canonical Airbnk lock state."""

    return {
        0x00: LOCK_STATE_UNLOCKED,
        0x01: LOCK_STATE_LOCKED,
        0x02: LOCK_STATE_JAMMED,
        0x03: LOCK_STATE_JAMMED,
        0x04: LOCK_STATE_LOCKED,
        0x05: LOCK_STATE_UNLOCKED,
        0x06: LOCK_STATE_JAMMED,
        0x07: LOCK_STATE_JAMMED,
    }.get(raw_state_nibble & 0x07, LOCK_STATE_JAMMED)


def describe_status_state_nibble(raw_state_nibble: int) -> str:
    """Return a human-readable description for the raw FFF3 state nibble."""

    return {
        0x00: "unlocked",
        0x01: "locked",
        0x02: "jammed_or_unknown_2",
        0x03: "jammed_or_unknown_3",
        0x04: "locked_alias_4",
        0x05: "unlocked_alias_5",
        0x06: "jammed_or_unknown_6",
        0x07: "jammed_or_unknown_7",
    }.get(raw_state_nibble & 0x07, f"unknown_{raw_state_nibble & 0x07}")


def describe_advert_state_bits(raw_state_bits: int, opens_clockwise: bool) -> str:
    """Return a human-readable description for the raw advert state bits."""

    normalized_map = {
        0x00: "locked" if opens_clockwise else "unlocked",
        0x01: "unlocked" if opens_clockwise else "locked",
        0x02: "jammed",
        0x03: "operating_or_unknown_3",
    }
    return normalized_map.get(raw_state_bits & 0x03, f"unknown_{raw_state_bits & 0x03}")


def _normalize_key_hex(value: Any, label: str) -> str:
    """Normalize a stored hex key."""

    text = str(value).strip().lower()
    if len(text) < 32 or len(text) % 2:
        raise AirbnkProtocolError(f"{label} must be an even-length hex string")
    try:
        bytes.fromhex(text)
    except ValueError as err:
        raise AirbnkProtocolError(f"{label} is not valid hex") from err
    return text


def _xor_64_buffer(buffer: bytearray, value: int) -> bytearray:
    for index in range(64):
        buffer[index] ^= value
    return buffer


def _generate_working_key(binding_key: bytes, value: int) -> bytes:
    padded = bytearray(72)
    padded[0 : len(binding_key)] = binding_key
    padded = _xor_64_buffer(padded, 0x36)
    encoded_value = value
    padded[71] = encoded_value & 0xFF
    encoded_value >>= 8
    padded[70] = encoded_value & 0xFF
    encoded_value >>= 8
    padded[69] = encoded_value & 0xFF
    encoded_value >>= 8
    padded[68] = encoded_value & 0xFF
    inner_hash = hashlib.sha1(padded).digest()

    outer = bytearray(84)
    outer[0 : len(binding_key)] = binding_key
    outer = _xor_64_buffer(outer, 0x5C)
    outer[64:84] = inner_hash
    return hashlib.sha1(outer).digest()


def _generate_password_v2(buffer: bytes) -> bytes:
    password = bytearray(8)
    for index in range(4):
        byte = buffer[index + 16]
        password_index = index * 2
        password[password_index] = buffer[(byte >> 4) & 0x0F]
        password[password_index + 1] = buffer[byte & 0x0F]
    return bytes(password)


def _generate_signature_v2(key: bytes, value: int, payload: bytes) -> bytes:
    inner = bytearray(len(payload) + 68)
    inner[0:20] = key[0:20]
    inner = _xor_64_buffer(inner, 0x36)
    inner[64 : 64 + len(payload)] = payload

    encoded_value = value
    inner[len(payload) + 67] = encoded_value & 0xFF
    encoded_value >>= 8
    inner[len(payload) + 66] = encoded_value & 0xFF
    encoded_value >>= 8
    inner[len(payload) + 65] = encoded_value & 0xFF
    encoded_value >>= 8
    inner[len(payload) + 64] = encoded_value & 0xFF
    inner_hash = hashlib.sha1(inner).digest()

    outer = bytearray(84)
    outer[0:20] = key[0:20]
    outer = _xor_64_buffer(outer, 0x5C)
    outer[64 : 64 + len(inner_hash)] = inner_hash
    return _generate_password_v2(hashlib.sha1(outer).digest())


def _checksum(buffer: bytes, start: int, end: int) -> int:
    return sum(buffer[start:end]) & 0xFF

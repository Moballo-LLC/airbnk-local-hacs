"""Shared Airbnk BLE test helpers."""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from custom_components.airbnk_ble.airbnk import _AESCipher


def build_bootstrap_fixture(
    *,
    lock_sn: str = "B100LOCK00000001",
    lock_model: str = "B100",
    app_key: str = "ABCDEFGHIJKLMNOPQRST",
    manufacturer_key: bytes = b"0123456789ABCDEF",
    binding_key: bytes = b"FEDCBA9876543210",
) -> dict[str, Any]:
    """Build a consistent synthetic bootstrap fixture."""

    digest = hashlib.sha1(f"{lock_sn}{app_key}".encode()).hexdigest()
    aes_key = bytes.fromhex(digest[0:32])

    decrypted = bytearray(88)
    decrypted[0:16] = lock_sn.encode("utf-8")
    decrypted[16:48] = _AESCipher(aes_key).encrypt(manufacturer_key, use_base64=False)
    decrypted[48:80] = _AESCipher(aes_key).encrypt(binding_key, use_base64=False)
    decrypted[80:88] = lock_model.encode("utf-8").ljust(8, b"\x00")

    encrypted_payload = _AESCipher(app_key[:-4].encode("utf-8")).encrypt(
        bytes(decrypted),
        use_base64=False,
    )
    new_sninfo = base64.b64encode(encrypted_payload + b"1234567890").decode("utf-8")

    return {
        "lock_sn": lock_sn,
        "lock_model": lock_model,
        "app_key": app_key,
        "new_sninfo": new_sninfo,
        "manufacturer_key": manufacturer_key,
        "binding_key": binding_key,
    }


def build_advertisement_payload(
    *,
    serial_fragment: str = "B100LOCK0",
    voltage: float = 3.0,
    lock_events: int = 1,
    raw_state_bits: int = 1,
    battery_flags: int = 0x00,
    board_model: int = 0x01,
    firmware_version: tuple[int, int, int] = (1, 2, 3),
    opens_clockwise: bool = False,
) -> bytes:
    """Build a synthetic Airbnk advertisement payload."""

    serial = serial_fragment.encode("utf-8")[:9].ljust(9, b"\x00")
    state_flags = ((raw_state_bits & 0x03) << 4) | (0x80 if opens_clockwise else 0x00)
    payload = bytearray()
    payload.extend(b"\xba\xba")
    payload.append(board_model)
    payload.append(0x00)
    payload.extend(bytes(firmware_version))
    payload.extend(serial)
    payload.extend(int(round(voltage * 100)).to_bytes(2, byteorder="big"))
    payload.extend(int(lock_events).to_bytes(4, byteorder="big"))
    payload.append(state_flags)
    payload.append(battery_flags)
    return bytes(payload)


def build_status_payload(
    *,
    lock_events: int = 1,
    voltage: float = 3.0,
    raw_state_nibble: int = 1,
    trailing_byte: int = 0x01,
) -> bytes:
    """Build a synthetic Airbnk status response payload."""

    payload = bytearray(b"\xaa\x00\x00\x02\x04")
    payload.extend(b"\x00" * 5)
    payload.extend(int(lock_events).to_bytes(4, byteorder="big"))
    payload.extend(int(round(voltage * 100)).to_bytes(2, byteorder="big"))
    payload.append((raw_state_nibble & 0x07) << 4)
    payload.append(trailing_byte)
    return bytes(payload)

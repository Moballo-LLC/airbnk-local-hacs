"""Runtime device wrapper for Airbnk BLE."""

from __future__ import annotations

import asyncio
import logging
import time
from asyncio import Lock
from asyncio import timeout as asyncio_timeout
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection
from homeassistant.components import bluetooth
from homeassistant.const import CONF_NAME
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.event import async_track_time_interval

from .airbnk import (
    AdvertisementData,
    AirbnkProtocolError,
    BootstrapData,
    StatusResponseData,
    calculate_battery_percentage,
    generate_operation_code,
    normalize_battery_profile,
    parse_advertisement_data,
    parse_status_response,
    split_operation_frames,
    validate_entry_options,
)
from .const import (
    AIRBNK_STATUS_CHARACTERISTIC_UUID,
    AIRBNK_WRITE_CHARACTERISTIC_UUID,
    CONF_BATTERY_PROFILE,
    CONF_COMMAND_TIMEOUT,
    CONF_CONNECTIVITY_PROBE_INTERVAL,
    CONF_LOCK_ICON,
    CONF_LOCK_SN,
    CONF_MAC_ADDRESS,
    CONF_PUBLISH_DIAGNOSTIC_ENTITIES,
    CONF_RETRY_COUNT,
    CONF_REVERSE_COMMANDS,
    CONF_SUPPORTS_REMOTE_LOCK,
    CONF_UNAVAILABLE_AFTER,
    DOMAIN,
    LOCK_STATE_JAMMED,
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNLOCKED,
    MANUFACTURER_ID_AIRBNK,
    OPERATION_LOCK,
    OPERATION_UNLOCK,
)

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice
    from bleak.backends.scanner import AdvertisementData as BleakAdvertisementData
    from homeassistant.components.bluetooth import (
        BluetoothChange,
        BluetoothServiceInfoBleak,
    )
    from homeassistant.config_entries import ConfigEntry

_LOGGER = logging.getLogger(__name__)

AGE_UPDATE_INTERVAL_SECONDS = 15
READ_STATUS_RETRY_DELAY_SECONDS = 0.1
SLOW_COMMAND_LOG_SECONDS = 5.0
CONNECTIVITY_PROBE_TIMEOUT_SECONDS = 10.0
COMMAND_RETRY_DELAY_SECONDS = 0.5


@dataclass(slots=True)
class AirbnkLockState:
    """Current runtime state for the lock."""

    available: bool = False
    reachable: bool = False
    lock_state: int | None = None
    voltage: float | None = None
    battery_percent: float | None = None
    rssi: int | None = None
    lock_events: int | None = None
    is_low_battery: bool | None = None
    last_error: str = "ok"
    last_source: str | None = None
    firmware_version: str | None = None
    board_model: int | None = None
    opens_clockwise: bool | None = None
    advert_state_flags: int | None = None
    advert_state_bits: int | None = None
    advert_state_label: str | None = None
    advert_battery_flags: int | None = None
    status_state_byte: int | None = None
    status_state_nibble: int | None = None
    status_state_label: str | None = None
    status_trailing_byte: int | None = None
    command_in_progress: str | None = None
    last_requested_operation: int | None = None
    last_wire_operation: int | None = None
    restored: bool = False
    last_advert_monotonic: float | None = None
    last_contact_monotonic: float | None = None
    last_probe_monotonic: float | None = None
    last_probe_successful: bool | None = None
    last_advert_payload_hex: str | None = None
    last_status_payload_hex: str | None = None


class AirbnkLockRuntime:
    """Manage BLE advertisement state and active lock commands."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        bootstrap: BootstrapData,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.bootstrap = bootstrap
        options = validate_entry_options(
            entry.options,
            lock_model=bootstrap.lock_model,
            legacy_data=entry.data,
        )
        self.address = str(entry.data[CONF_MAC_ADDRESS])
        self.lock_sn = str(entry.data[CONF_LOCK_SN])
        self.name = str(options[CONF_NAME])
        self.lock_icon = str(options[CONF_LOCK_ICON])
        self.publish_diagnostic_entities = bool(
            options[CONF_PUBLISH_DIAGNOSTIC_ENTITIES]
        )
        self.reverse_commands = bool(options[CONF_REVERSE_COMMANDS])
        self.supports_remote_lock = bool(options[CONF_SUPPORTS_REMOTE_LOCK])
        self.retry_count = int(options[CONF_RETRY_COUNT])
        self.command_timeout = int(options[CONF_COMMAND_TIMEOUT])
        self.connectivity_probe_interval = int(
            options[CONF_CONNECTIVITY_PROBE_INTERVAL]
        )
        self.unavailable_after = int(options[CONF_UNAVAILABLE_AFTER])
        self.battery_profile = normalize_battery_profile(
            entry.data[CONF_BATTERY_PROFILE]
        )
        self.state = AirbnkLockState()

        self._callbacks: set[Callable[[], None]] = set()
        self._command_lock = Lock()
        self._operation: str | None = None
        self._last_known_ble_device: BLEDevice | None = None
        self._probe_task: asyncio.Task[None] | None = None
        self._unsub_ble_callback: CALLBACK_TYPE | None = None
        self._unsub_unavailable: CALLBACK_TYPE | None = None
        self._unsub_interval: CALLBACK_TYPE | None = None

    @property
    def device_info(self) -> DeviceInfo:
        """Build device registry info."""

        info: DeviceInfo = {
            "identifiers": {(DOMAIN, self.lock_sn)},
            "connections": {(CONNECTION_BLUETOOTH, self.address)},
            "name": self.name,
            "manufacturer": "Airbnk",
            "model": self.bootstrap.lock_model,
            "serial_number": self.lock_sn,
        }
        if self.state.firmware_version:
            info["sw_version"] = self.state.firmware_version
        return info

    @property
    def is_locked(self) -> bool | None:
        """Return the normalized locked state."""

        if self.state.lock_state is None:
            return None
        if self.state.lock_state == LOCK_STATE_LOCKED:
            return True
        if self.state.lock_state == LOCK_STATE_UNLOCKED:
            return False
        return None

    @property
    def is_locking(self) -> bool:
        """Return whether a lock command is in progress."""

        return self._operation == "locking"

    @property
    def is_unlocking(self) -> bool:
        """Return whether an unlock command is in progress."""

        return self._operation == "unlocking"

    @property
    def is_jammed(self) -> bool:
        """Return whether the lock is jammed."""

        return self.state.lock_state == LOCK_STATE_JAMMED

    @property
    def has_advertisement(self) -> bool:
        """Return whether at least one advertisement has been seen."""

        return self.state.last_advert_monotonic is not None

    @property
    def last_advert_age_seconds(self) -> float | None:
        """Return the age of the last advertisement in seconds."""

        if self.state.last_advert_monotonic is None:
            return None
        return max(0.0, time.monotonic() - self.state.last_advert_monotonic)

    async def async_start(self) -> None:
        """Start runtime subscriptions."""

        self._unsub_ble_callback = bluetooth.async_register_callback(
            self.hass,
            self._async_handle_bluetooth_event,
            {"address": self.address},
            bluetooth.BluetoothScanningMode.ACTIVE,
        )
        self._unsub_unavailable = bluetooth.async_track_unavailable(
            self.hass,
            self._async_handle_unavailable,
            self.address,
            connectable=True,
        )
        self._unsub_interval = async_track_time_interval(
            self.hass,
            self._async_handle_interval,
            timedelta(seconds=AGE_UPDATE_INTERVAL_SECONDS),
        )

        service_info = bluetooth.async_last_service_info(
            self.hass,
            self.address,
            connectable=True,
        ) or bluetooth.async_last_service_info(
            self.hass,
            self.address,
            connectable=False,
        )
        if service_info is not None:
            self._async_handle_bluetooth_event(service_info, None)
            return

        _LOGGER.info(
            "No cached Airbnk advertisement yet for %s; keeping the lock "
            "in unknown state until the first advert arrives",
            self.address,
        )

    @callback
    def async_stop(self) -> None:
        """Stop runtime subscriptions."""

        if self._unsub_ble_callback is not None:
            self._unsub_ble_callback()
            self._unsub_ble_callback = None
        if self._unsub_unavailable is not None:
            self._unsub_unavailable()
            self._unsub_unavailable = None
        if self._unsub_interval is not None:
            self._unsub_interval()
            self._unsub_interval = None
        if self._probe_task is not None:
            self._probe_task.cancel()
            self._probe_task = None

    @callback
    def register_callback(self, callback_func: Callable[[], None]) -> CALLBACK_TYPE:
        """Register a state callback."""

        self._callbacks.add(callback_func)

        @callback
        def _remove_callback() -> None:
            self._callbacks.discard(callback_func)

        return _remove_callback

    async def async_lock(self) -> None:
        """Lock the Airbnk device."""

        await self._async_execute_operation(OPERATION_LOCK)

    async def async_unlock(self) -> None:
        """Unlock the Airbnk device."""

        await self._async_execute_operation(OPERATION_UNLOCK)

    async def async_open(self) -> None:
        """Release the latch without relying on the current lock state."""

        await self._async_execute_operation(OPERATION_UNLOCK)

    @callback
    def _async_handle_bluetooth_event(
        self,
        service_info: BluetoothServiceInfoBleak,
        _change: BluetoothChange | None,
    ) -> None:
        """Handle an incoming Bluetooth advertisement."""

        manufacturer_payload = self._extract_airbnk_payload(service_info.advertisement)
        if manufacturer_payload is None:
            return

        try:
            parsed = parse_advertisement_data(
                manufacturer_payload,
                expected_lock_sn=self.lock_sn,
            )
        except AirbnkProtocolError as err:
            _LOGGER.debug(
                "Ignoring non-matching AirBnk advertisement for %s: %s",
                self.address,
                err,
            )
            return

        self._apply_advertisement(
            parsed,
            service_info,
            payload_hex=manufacturer_payload.hex().upper(),
        )

    @callback
    def _async_handle_unavailable(
        self,
        _service_info: BluetoothServiceInfoBleak,
    ) -> None:
        """Mark the lock unavailable when HA Bluetooth stops seeing it."""

        if not self._has_stale_contact():
            return
        changed = False
        if self.state.available:
            self.state.available = False
            changed = True
        if self.connectivity_probe_interval > 0:
            self._async_schedule_connectivity_probe()
        elif self.state.reachable:
            self.state.reachable = False
            changed = True
        if changed:
            self._notify_callbacks()

    @callback
    def _async_handle_interval(self, _now) -> None:
        """Refresh age-based sensors and enforce availability timeout."""

        changed = False
        is_stale = self._has_stale_contact()
        if is_stale and self.state.available:
            self.state.available = False
            changed = True
        if is_stale:
            if self.connectivity_probe_interval > 0:
                self._async_schedule_connectivity_probe()
            elif self.state.reachable:
                self.state.reachable = False
                changed = True

        if self.has_advertisement or changed:
            self._notify_callbacks()

    async def _async_execute_operation(self, requested_operation: int) -> None:
        """Serialize an active command to the lock."""

        await self._async_cancel_connectivity_probe()
        if self._command_lock.locked():
            raise HomeAssistantError("An Airbnk lock command is already in progress")
        if self.state.lock_events is None:
            raise HomeAssistantError(
                "No Airbnk advertisement has been seen yet from "
                f"{self.address}; lock counter is unknown"
            )

        wire_operation = self._wire_operation_for(requested_operation)
        if requested_operation == OPERATION_LOCK and not self.supports_remote_lock:
            self.state.last_requested_operation = requested_operation
            self.state.last_wire_operation = None
            self.state.last_error = (
                "Remote locking is not supported for this Airbnk profile."
            )
            _LOGGER.warning(
                "Rejected remote lock command for %s because this Airbnk "
                "profile is configured as unlock-only",
                self.address,
            )
            self._notify_callbacks()
            raise HomeAssistantError(self.state.last_error)

        async with self._command_lock:
            self._operation = (
                "locking" if requested_operation == OPERATION_LOCK else "unlocking"
            )
            self.state.command_in_progress = self._operation
            self.state.last_error = "ok"
            self.state.last_requested_operation = requested_operation
            self.state.last_wire_operation = wire_operation
            self._notify_callbacks()

            last_error = "Unknown AirBnk command failure"
            total_attempts = self.retry_count + 1
            operation_name = self._operation_name(requested_operation)
            for attempt in range(total_attempts):
                _LOGGER.debug(
                    "Starting AirBnk %s command attempt %s/%s for %s",
                    operation_name,
                    attempt + 1,
                    total_attempts,
                    self.address,
                )
                try:
                    await self._async_send_operation_once(
                        requested_operation, wire_operation
                    )
                except Exception as err:  # noqa: BLE001
                    last_error = str(err)
                    self.state.last_error = last_error
                    self._notify_callbacks()
                    if attempt < self.retry_count:
                        _LOGGER.warning(
                            "Airbnk %s command attempt %s/%s failed for %s: "
                            "%s; retrying in %.1fs",
                            operation_name,
                            attempt + 1,
                            total_attempts,
                            self.address,
                            err,
                            COMMAND_RETRY_DELAY_SECONDS,
                        )
                        await asyncio.sleep(COMMAND_RETRY_DELAY_SECONDS)
                        continue
                else:
                    self.state.last_error = "ok"
                    self._operation = None
                    self.state.command_in_progress = None
                    self._notify_callbacks()
                    return

            _LOGGER.error(
                "AirBnk %s command failed after %s/%s attempts for %s: %s",
                operation_name,
                total_attempts,
                total_attempts,
                self.address,
                last_error,
            )
            self._operation = None
            self.state.command_in_progress = None
            self._notify_callbacks()
            raise HomeAssistantError(last_error)

    async def _async_send_operation_once(
        self,
        requested_operation: int,
        wire_operation: int,
    ) -> None:
        """Connect to the lock and send one command attempt."""

        ble_device = self._current_connectable_ble_device()
        if ble_device is None:
            raise HomeAssistantError(
                "No connectable Bluetooth device is currently available for "
                f"{self.address}"
            )
        self._last_known_ble_device = ble_device

        operation_started = time.monotonic()
        operation_code = generate_operation_code(
            wire_operation,
            self.state.lock_events or 0,
            self.bootstrap,
        )
        frame_one, frame_two = split_operation_frames(operation_code)
        connect_started = time.monotonic()
        client = await establish_connection(
            BleakClientWithServiceCache,
            ble_device,
            self.name,
            max_attempts=1,
            ble_device_callback=self._ble_device_callback,
        )
        connect_elapsed = time.monotonic() - connect_started
        frame_one_elapsed = 0.0
        frame_two_elapsed = 0.0
        status_elapsed = 0.0

        try:
            async with asyncio_timeout(self.command_timeout):
                frame_one_started = time.monotonic()
                await client.write_gatt_char(
                    AIRBNK_WRITE_CHARACTERISTIC_UUID,
                    frame_one,
                    response=True,
                )
                frame_one_elapsed = time.monotonic() - frame_one_started
                frame_two_started = time.monotonic()
                await client.write_gatt_char(
                    AIRBNK_WRITE_CHARACTERISTIC_UUID,
                    frame_two,
                    response=True,
                )
                frame_two_elapsed = time.monotonic() - frame_two_started
                status_started = time.monotonic()
                await self._async_read_status_until_valid(client)
                status_elapsed = time.monotonic() - status_started
        except BleakError as err:
            raise HomeAssistantError(
                f"Bluetooth error while commanding {self.name}: {err}"
            ) from err
        finally:
            if client.is_connected:
                await client.disconnect()

        total_elapsed = time.monotonic() - operation_started
        self._log_command_timing(
            requested_operation=requested_operation,
            wire_operation=wire_operation,
            total_elapsed=total_elapsed,
            connect_elapsed=connect_elapsed,
            frame_one_elapsed=frame_one_elapsed,
            frame_two_elapsed=frame_two_elapsed,
            status_elapsed=status_elapsed,
        )

    async def _async_read_status_until_valid(self, client: Any) -> None:
        """Read FFF3 until the lock returns a valid status frame or timeout expires."""

        deadline = time.monotonic() + self.command_timeout
        last_payload_hex: str | None = None
        last_error: Exception | None = None

        while time.monotonic() < deadline:
            payload = bytes(
                await client.read_gatt_char(AIRBNK_STATUS_CHARACTERISTIC_UUID)
            )
            if payload:
                last_payload_hex = payload.hex().upper()
                try:
                    parsed = parse_status_response(payload)
                except AirbnkProtocolError as err:
                    last_error = err
                else:
                    self._remember_status_debug(parsed, payload_hex=last_payload_hex)
                    if self._status_response_is_transient(parsed):
                        last_error = AirbnkProtocolError(
                            "Transient AirBnk status response "
                            f"(state={parsed.state_byte:02X}, "
                            f"tail={parsed.trailing_byte:02X})"
                        )
                        continue
                    self._apply_status_response(parsed)
                    return
            await asyncio.sleep(READ_STATUS_RETRY_DELAY_SECONDS)

        detail = ""
        if last_payload_hex:
            detail = f" Last payload: {last_payload_hex}."
        if last_error:
            detail += f" Last parse error: {last_error}."
        raise HomeAssistantError(
            f"Timed out waiting for a valid AirBnk status response.{detail}"
        )

    def _apply_advertisement(
        self,
        parsed: AdvertisementData,
        service_info: BluetoothServiceInfoBleak,
        *,
        payload_hex: str,
    ) -> None:
        """Apply a parsed advertisement to the runtime state."""

        now = time.monotonic()
        previous_state = self.state.lock_state
        previous_events = self.state.lock_events
        previous_flags = self.state.advert_state_flags
        previous_available = self.state.available
        self.state.available = True
        self.state.reachable = True
        self.state.lock_state = parsed.lock_state
        self.state.voltage = parsed.voltage
        self.state.battery_percent = calculate_battery_percentage(
            parsed.voltage,
            self.battery_profile,
        )
        self.state.rssi = service_info.rssi
        self.state.lock_events = parsed.lock_events
        self.state.is_low_battery = parsed.is_low_battery
        self.state.last_source = getattr(service_info, "source", None)
        self.state.firmware_version = parsed.firmware_version
        self.state.board_model = parsed.board_model
        self.state.opens_clockwise = parsed.opens_clockwise
        self.state.advert_state_flags = parsed.state_flags
        self.state.advert_state_bits = parsed.raw_state_bits
        self.state.advert_state_label = parsed.raw_state_label
        self.state.advert_battery_flags = parsed.battery_flags
        self.state.last_advert_payload_hex = payload_hex
        self.state.restored = False
        self.state.last_advert_monotonic = now
        self.state.last_contact_monotonic = now
        if getattr(service_info, "connectable", False):
            self._last_known_ble_device = service_info.device
        if (
            not previous_available
            or previous_state != parsed.lock_state
            or previous_events != parsed.lock_events
            or previous_flags != parsed.state_flags
        ):
            _LOGGER.info(
                (
                    "Airbnk advert for %s: normalized=%s raw=0x%02X bits=0x%X "
                    "meaning=%s "
                    "events=%s voltage=%.2f rssi=%s source=%s"
                ),
                self.address,
                self._lock_state_label(parsed.lock_state),
                parsed.state_flags,
                parsed.raw_state_bits,
                parsed.raw_state_label,
                parsed.lock_events,
                parsed.voltage,
                service_info.rssi,
                getattr(service_info, "source", None),
            )
        self._notify_callbacks()

    def _apply_status_response(self, parsed: StatusResponseData) -> None:
        """Apply an active command response to the runtime state."""

        previous_state = self.state.lock_state
        self.state.available = True
        self.state.reachable = True
        self.state.lock_state = parsed.lock_state
        self.state.voltage = parsed.voltage
        self.state.battery_percent = calculate_battery_percentage(
            parsed.voltage,
            self.battery_profile,
        )
        self.state.lock_events = max(self.state.lock_events or 0, parsed.lock_events)
        self.state.status_state_byte = parsed.state_byte
        self.state.status_state_nibble = parsed.raw_state_nibble
        self.state.status_state_label = parsed.raw_state_label
        self.state.status_trailing_byte = parsed.trailing_byte
        self.state.last_source = "status_response"
        self.state.restored = False
        self.state.last_contact_monotonic = time.monotonic()
        _LOGGER.info(
            (
                "AirBnk status response for %s: normalized=%s previous=%s "
                "raw=0x%02X bits=0x%X meaning=%s tail=0x%02X events=%s voltage=%.2f"
            ),
            self.address,
            self._lock_state_label(parsed.lock_state),
            self._lock_state_label(previous_state),
            parsed.state_byte,
            parsed.raw_state_nibble,
            parsed.raw_state_label,
            parsed.trailing_byte,
            parsed.lock_events,
            parsed.voltage,
        )
        self._notify_callbacks()

    @callback
    def restore_lock_state(self, lock_state: int) -> None:
        """Restore the last known HA lock state until a fresh advert arrives."""

        if self.has_advertisement:
            return
        self.state.lock_state = lock_state
        self.state.last_source = "restored_state"
        self.state.restored = True

    def _extract_airbnk_payload(
        self,
        advertisement: BleakAdvertisementData,
    ) -> bytes | None:
        """Extract the AirBnk manufacturer payload from a BLE advertisement."""

        if payload := advertisement.manufacturer_data.get(MANUFACTURER_ID_AIRBNK):
            return bytes(payload)

        for payload in advertisement.manufacturer_data.values():
            raw = bytes(payload)
            if raw.startswith(b"\xba\xba"):
                return raw
        return None

    def _current_connectable_ble_device(self) -> BLEDevice | None:
        """Return the best currently connectable BLE device for this lock."""

        device = bluetooth.async_ble_device_from_address(
            self.hass,
            self.address,
            connectable=True,
        )
        return device if device is not None else self._last_known_ble_device

    def _ble_device_callback(self) -> BLEDevice:
        """Provide a BLE device to the retry connector."""

        device = self._current_connectable_ble_device()
        if device is None:
            raise RuntimeError(
                f"No connectable BLE device available for {self.address}"
            )
        return device

    def _wire_operation_for(self, requested_operation: int) -> int:
        """Map requested lock/unlock intents to the on-wire AirBnk opcode."""

        if not self.reverse_commands:
            return requested_operation
        if requested_operation == OPERATION_LOCK:
            return OPERATION_UNLOCK
        if requested_operation == OPERATION_UNLOCK:
            return OPERATION_LOCK
        return requested_operation

    def _log_command_timing(
        self,
        *,
        requested_operation: int,
        wire_operation: int,
        total_elapsed: float,
        connect_elapsed: float,
        frame_one_elapsed: float,
        frame_two_elapsed: float,
        status_elapsed: float,
    ) -> None:
        """Log per-stage timing for successful AirBnk commands."""

        operation_name = self._operation_name(requested_operation)
        wire_name = self._operation_name(wire_operation)
        log = (
            _LOGGER.info if total_elapsed >= SLOW_COMMAND_LOG_SECONDS else _LOGGER.debug
        )
        log(
            (
                "AirBnk %s command for %s completed in %.2fs "
                "(connect=%.2fs, frame1=%.2fs, frame2=%.2fs, status=%.2fs, "
                "wire=%s, source=%s, state=%s, status_bits=%s, rssi=%s)"
            ),
            operation_name,
            self.address,
            total_elapsed,
            connect_elapsed,
            frame_one_elapsed,
            frame_two_elapsed,
            status_elapsed,
            wire_name,
            self.state.last_source,
            self._lock_state_label(self.state.lock_state),
            self._format_hex_nibble(self.state.status_state_nibble),
            self.state.rssi,
        )

    @staticmethod
    def _operation_name(operation: int) -> str:
        """Return a human-readable operation name."""

        if operation == OPERATION_LOCK:
            return "lock"
        if operation == OPERATION_UNLOCK:
            return "unlock"
        return str(operation)

    @staticmethod
    def _status_response_is_transient(parsed: StatusResponseData) -> bool:
        """Return whether the lock is still reporting a placeholder payload."""

        # The AirBnk gateway reference keeps polling FFF3 until the *final byte
        # of the raw payload* is no longer 0x00. A legitimate unlocked response
        # can still have a state byte of 0x00, so using the decoded state byte
        # here suppresses real unlock confirmations and breaks history/state
        # updates in Home Assistant.
        return parsed.trailing_byte == 0x00

    def _remember_status_debug(
        self, parsed: StatusResponseData, *, payload_hex: str
    ) -> None:
        """Persist raw FFF3 diagnostics even before the payload is final."""

        changed = (
            self.state.status_state_byte != parsed.state_byte
            or self.state.status_state_nibble != parsed.raw_state_nibble
            or self.state.status_state_label != parsed.raw_state_label
            or self.state.status_trailing_byte != parsed.trailing_byte
            or self.state.last_status_payload_hex != payload_hex
        )
        self.state.status_state_byte = parsed.state_byte
        self.state.status_state_nibble = parsed.raw_state_nibble
        self.state.status_state_label = parsed.raw_state_label
        self.state.status_trailing_byte = parsed.trailing_byte
        self.state.last_status_payload_hex = payload_hex
        if changed:
            self._notify_callbacks()

    def _has_stale_contact(self) -> bool:
        """Return whether the last BLE contact is older than the configured timeout."""

        if self.state.last_contact_monotonic is None:
            return True
        return (
            time.monotonic() - self.state.last_contact_monotonic
            > self.unavailable_after
        )

    @callback
    def _async_schedule_connectivity_probe(self) -> None:
        """Schedule a rare active reachability probe while BLE state is stale."""

        if self._probe_task is not None and not self._probe_task.done():
            return
        if self._command_lock.locked():
            return
        now = time.monotonic()
        if (
            self.state.last_probe_monotonic is not None
            and (now - self.state.last_probe_monotonic)
            < self.connectivity_probe_interval
        ):
            return
        if (
            self._current_connectable_ble_device() is None
            and self._last_known_ble_device is None
        ):
            return

        self._probe_task = self._create_background_task(
            self._async_probe_connectivity(),
            name=f"{DOMAIN}_{self.lock_sn}_connectivity_probe",
        )
        self._probe_task.add_done_callback(self._async_handle_probe_done)

    async def _async_probe_connectivity(self) -> None:
        """Attempt a lightweight connect/disconnect probe without touching state."""

        self.state.last_probe_monotonic = time.monotonic()

        try:
            async with self._command_lock:
                if not self._has_stale_contact():
                    return
                ble_device = self._current_connectable_ble_device()
                if ble_device is None:
                    raise HomeAssistantError(
                        "No connectable Bluetooth device is currently "
                        f"available for {self.address}"
                    )
                self._last_known_ble_device = ble_device
                probe_timeout = min(
                    float(self.command_timeout), CONNECTIVITY_PROBE_TIMEOUT_SECONDS
                )
                async with asyncio_timeout(probe_timeout):
                    client = await establish_connection(
                        BleakClientWithServiceCache,
                        ble_device,
                        self.name,
                        max_attempts=1,
                        ble_device_callback=self._ble_device_callback,
                    )
                try:
                    self.state.last_probe_successful = True
                    if not self.state.reachable:
                        self.state.reachable = True
                        _LOGGER.info(
                            "Airbnk connectivity probe succeeded for %s after "
                            "a stale advert gap",
                            self.address,
                        )
                        self._notify_callbacks()
                finally:
                    if client.is_connected:
                        await client.disconnect()
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self.state.last_probe_successful = False
            if self._has_stale_contact() and self.state.reachable:
                self.state.reachable = False
                _LOGGER.warning(
                    "Airbnk connectivity probe failed for %s after a stale "
                    "advert gap: %s",
                    self.address,
                    err,
                )
                self._notify_callbacks()
            else:
                _LOGGER.debug(
                    "AirBnk connectivity probe failed for %s: %s", self.address, err
                )

    async def _async_cancel_connectivity_probe(self) -> None:
        """Cancel a background reachability probe before running a command."""

        task = self._probe_task
        if task is None or task.done():
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task

    @callback
    def _async_handle_probe_done(self, task: asyncio.Task[None]) -> None:
        """Clear the probe task handle and surface unexpected errors."""

        if self._probe_task is task:
            self._probe_task = None
        if task.cancelled():
            return
        with suppress(Exception):
            task.result()

    def _create_background_task(self, coro, *, name: str) -> asyncio.Task[None]:
        """Create a background task via Home Assistant when available."""

        async_create_task = getattr(self.hass, "async_create_task", None)
        if callable(async_create_task):
            return async_create_task(coro, name=name)
        return asyncio.create_task(coro, name=name)

    @staticmethod
    def _lock_state_label(lock_state: int | None) -> str:
        """Render a human-readable normalized lock state."""

        if lock_state == LOCK_STATE_LOCKED:
            return "locked"
        if lock_state == LOCK_STATE_UNLOCKED:
            return "unlocked"
        if lock_state == LOCK_STATE_JAMMED:
            return "jammed"
        return "unknown"

    @staticmethod
    def _format_hex_nibble(value: int | None) -> str:
        """Render a raw nibble value for logs and diagnostics."""

        if value is None:
            return "unknown"
        return f"0x{value:X}"

    @callback
    def _notify_callbacks(self) -> None:
        """Dispatch a state update to all listeners."""

        for callback_func in tuple(self._callbacks):
            callback_func()

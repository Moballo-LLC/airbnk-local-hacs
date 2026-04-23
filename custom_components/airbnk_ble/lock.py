"""Lock platform for Airbnk BLE."""

from __future__ import annotations

from typing import Any

from homeassistant.components.lock import LockEntity, LockEntityFeature, LockState
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    LOCK_STATE_JAMMED,
    LOCK_STATE_LOCKED,
    LOCK_STATE_UNLOCKED,
    OPERATION_LOCK,
    OPERATION_UNLOCK,
)
from .entity import AirbnkBaseEntity

_LOCK_ICON_FAMILY = {
    "locked": "mdi:lock-outline",
    "unlocked": "mdi:lock-open-variant-outline",
    "unknown": "mdi:lock-question",
}

_MAILBOX_ICON_FAMILY = {
    "locked": "mdi:mailbox-up-outline",
    "unlocked": "mdi:mailbox-open-up-outline",
    "unknown": "mdi:mailbox-outline",
}

_ICON_FAMILY_ALIASES = {
    "mdi:lock-outline": _LOCK_ICON_FAMILY,
    "mdi:lock-open-variant-outline": _LOCK_ICON_FAMILY,
    "mdi:lock-question": _LOCK_ICON_FAMILY,
    "mdi:mailbox-up-outline": _MAILBOX_ICON_FAMILY,
    "mdi:mailbox-open-up-outline": _MAILBOX_ICON_FAMILY,
    "mdi:mailbox-outline": _MAILBOX_ICON_FAMILY,
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Airbnk lock entity."""

    async_add_entities([AirbnkBleLock(entry.runtime_data)])


class AirbnkBleLock(AirbnkBaseEntity, LockEntity, RestoreEntity):
    """Native lock entity for an Airbnk device."""

    _attr_name = "Lock"
    _attr_has_entity_name = True
    _attr_supported_features = LockEntityFeature.OPEN

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.lock_sn}_lock"

    async def async_added_to_hass(self) -> None:
        """Restore the last known lock state until fresh BLE data arrives."""

        if (
            not self._runtime.has_advertisement
            and self._runtime.state.lock_state is None
        ):
            if last_state := await self.async_get_last_state():
                restored_state = _lock_state_from_restored_state(last_state.state)
                if restored_state is not None:
                    self._runtime.restore_lock_state(restored_state)
        await super().async_added_to_hass()

    @property
    def available(self) -> bool:
        """Return true when the lock has been seen recently enough."""

        return (
            self._runtime.state.lock_state is not None
            or (not self._runtime.has_advertisement)
            or self._runtime.state.available
        )

    @property
    def is_locked(self) -> bool | None:
        """Return whether the lock is locked."""

        return self._runtime.is_locked

    @property
    def is_jammed(self) -> bool:
        """Return whether the lock is jammed."""

        return self._runtime.is_jammed

    @property
    def icon(self) -> str:
        """Return the configured icon, preserving supported icon families."""

        if self._runtime.is_jammed:
            return "mdi:lock-alert-outline"

        configured_icon = str(getattr(self._runtime, "lock_icon", "") or "")
        icon_family = _ICON_FAMILY_ALIASES.get(configured_icon, None)
        if icon_family is None:
            if configured_icon:
                return configured_icon
            icon_family = _LOCK_ICON_FAMILY

        if self._runtime.is_locked is False:
            return icon_family["unlocked"]
        if self._runtime.is_locked is True:
            return icon_family["locked"]
        return icon_family["unknown"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra AirBnk diagnostics on the primary lock entity."""

        attrs: dict[str, Any] = {}
        if self._runtime.state.last_source:
            attrs["state_source"] = self._runtime.state.last_source
        attrs["remote_lock_supported"] = self._runtime.supports_remote_lock
        if self._runtime.state.firmware_version:
            attrs["firmware_version"] = self._runtime.state.firmware_version
        if self._runtime.state.board_model is not None:
            attrs["board_model"] = self._runtime.state.board_model
        if self._runtime.state.opens_clockwise is not None:
            attrs["opens_clockwise"] = self._runtime.state.opens_clockwise
        if self._runtime.state.advert_state_flags is not None:
            attrs["advert_state_flags_hex"] = (
                f"0x{self._runtime.state.advert_state_flags:02X}"
            )
            attrs["advert_state_bits_hex"] = (
                f"0x{((self._runtime.state.advert_state_flags >> 4) & 0x03):X}"
            )
        if self._runtime.state.advert_state_label is not None:
            attrs["advert_state_meaning"] = self._runtime.state.advert_state_label
        if self._runtime.state.advert_battery_flags is not None:
            attrs["advert_battery_flags_hex"] = (
                f"0x{self._runtime.state.advert_battery_flags:02X}"
            )
        if self._runtime.state.status_state_byte is not None:
            attrs["status_state_byte_hex"] = (
                f"0x{self._runtime.state.status_state_byte:02X}"
            )
        if self._runtime.state.status_state_nibble is not None:
            attrs["status_state_bits_hex"] = (
                f"0x{self._runtime.state.status_state_nibble:X}"
            )
        if self._runtime.state.status_state_label is not None:
            attrs["status_state_meaning"] = self._runtime.state.status_state_label
        if self._runtime.state.status_trailing_byte is not None:
            attrs["status_trailing_byte_hex"] = (
                f"0x{self._runtime.state.status_trailing_byte:02X}"
            )
        if self._runtime.state.last_advert_payload_hex:
            attrs["last_advert_payload_hex"] = (
                self._runtime.state.last_advert_payload_hex
            )
        if self._runtime.state.last_status_payload_hex:
            attrs["last_status_payload_hex"] = (
                self._runtime.state.last_status_payload_hex
            )
        if self._runtime.state.command_in_progress:
            attrs["command_in_progress"] = self._runtime.state.command_in_progress
        if self._runtime.state.last_requested_operation is not None:
            attrs["last_requested_operation"] = _operation_name(
                self._runtime.state.last_requested_operation
            )
        if self._runtime.state.last_wire_operation is not None:
            attrs["last_wire_operation"] = _operation_name(
                self._runtime.state.last_wire_operation
            )
        if self._runtime.state.restored:
            attrs["restored_until_first_advert"] = True
        if (
            self._runtime.state.lock_state is not None
            and not self._runtime.state.available
        ):
            attrs["state_is_stale"] = True
        return attrs

    async def async_lock(self, **kwargs: Any) -> None:
        """Lock the Airbnk device."""

        await self._runtime.async_lock()

    async def async_unlock(self, **kwargs: Any) -> None:
        """Unlock the Airbnk device."""

        await self._runtime.async_unlock()

    async def async_open(self, **kwargs: Any) -> None:
        """Release the Airbnk latch without depending on current lock state."""

        await self._runtime.async_open()


def _lock_state_from_restored_state(state: str | None) -> int | None:
    """Translate the previous HA state string into the runtime lock state."""

    if state == LockState.LOCKED:
        return LOCK_STATE_LOCKED
    if state == LockState.UNLOCKED:
        return LOCK_STATE_UNLOCKED
    if state == LockState.JAMMED:
        return LOCK_STATE_JAMMED
    return None


def _operation_name(operation: int) -> str:
    """Render a human-readable operation name for diagnostics."""

    if operation == OPERATION_LOCK:
        return "lock"
    if operation == OPERATION_UNLOCK:
        return "unlock"
    return str(operation)

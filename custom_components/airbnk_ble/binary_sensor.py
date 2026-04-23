"""Binary sensor platform for Airbnk BLE."""

from __future__ import annotations

import time
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .entity import AirbnkBaseEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Airbnk binary sensors."""

    runtime = entry.runtime_data
    entities: list[BinarySensorEntity] = [AirbnkBatteryLowBinarySensor(runtime)]
    if runtime.publish_diagnostic_entities:
        entities.append(AirbnkConnectivityBinarySensor(runtime))
    async_add_entities(entities)


class AirbnkBatteryLowBinarySensor(AirbnkBaseEntity, BinarySensorEntity):
    """Battery-low diagnostic sensor for the Airbnk lock."""

    _attr_name = "Battery Low"
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.lock_sn}_battery_low"

    @property
    def available(self) -> bool:
        """Return whether the battery-low flag has been populated."""

        return self._runtime.state.is_low_battery is not None

    @property
    def is_on(self) -> bool | None:
        """Return whether the lock is reporting a low battery."""

        return self._runtime.state.is_low_battery


class AirbnkConnectivityBinarySensor(AirbnkBaseEntity, BinarySensorEntity):
    """Connectivity sensor for the Airbnk BLE path."""

    _attr_name = "Connectivity"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, runtime) -> None:
        super().__init__(runtime)
        self._attr_unique_id = f"{runtime.lock_sn}_connectivity"

    @property
    def available(self) -> bool:
        """Keep the connectivity entity visible even while disconnected."""

        return True

    @property
    def is_on(self) -> bool:
        """Return whether the lock still appears reachable over BLE."""

        return bool(self._runtime.state.reachable)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose freshness versus reachability for quiet-advert locks."""

        attrs: dict[str, Any] = {
            "fresh_state_available": bool(self._runtime.state.available),
        }
        if self._runtime.last_advert_age_seconds is not None:
            attrs["last_advert_age_seconds"] = round(
                self._runtime.last_advert_age_seconds, 1
            )
        if self._runtime.connectivity_probe_interval > 0:
            attrs["connectivity_probe_interval_seconds"] = (
                self._runtime.connectivity_probe_interval
            )
        if self._runtime.state.last_probe_monotonic is not None:
            attrs["last_probe_age_seconds"] = round(
                max(0.0, time.monotonic() - self._runtime.state.last_probe_monotonic),
                1,
            )
        if self._runtime.state.last_probe_successful is not None:
            attrs["last_probe_successful"] = self._runtime.state.last_probe_successful
        return attrs

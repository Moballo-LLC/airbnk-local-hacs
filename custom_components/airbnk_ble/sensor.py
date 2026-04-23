"""Sensor platform for Airbnk BLE."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
    UnitOfElectricPotential,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import DISABLED_BY_DEFAULT_SENSOR_KEYS, HIDDEN_BY_DEFAULT_SENSOR_KEYS
from .entity import AirbnkBaseEntity


@dataclass(frozen=True, slots=True)
class AirbnkSensorDescription:
    """Describe one AirBnk sensor entity."""

    key: str
    name: str
    native_value: Callable
    available: Callable
    device_class: SensorDeviceClass | None = None
    native_unit_of_measurement: str | None = None
    state_class: SensorStateClass | None = None
    icon: str | None = None
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True


_SENSOR_DESCRIPTIONS: tuple[AirbnkSensorDescription, ...] = (
    AirbnkSensorDescription(
        key="state_source",
        name="State Source",
        native_value=lambda runtime: runtime.state.last_source,
        available=lambda runtime: runtime.state.last_source is not None,
        icon="mdi:source-branch",
    ),
    AirbnkSensorDescription(
        key="battery",
        name="Battery",
        native_value=lambda runtime: runtime.state.battery_percent,
        available=lambda runtime: runtime.state.battery_percent is not None,
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AirbnkSensorDescription(
        key="battery_voltage",
        name="Battery Voltage",
        native_value=lambda runtime: runtime.state.voltage,
        available=lambda runtime: runtime.state.voltage is not None,
        device_class=SensorDeviceClass.VOLTAGE,
        native_unit_of_measurement=UnitOfElectricPotential.VOLT,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    AirbnkSensorDescription(
        key="signal_strength",
        name="Signal Strength",
        native_value=lambda runtime: runtime.state.rssi,
        available=lambda runtime: runtime.state.rssi is not None,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:signal",
    ),
    AirbnkSensorDescription(
        key="last_advert_age",
        name="Last Advert Age",
        native_value=lambda runtime: (
            round(runtime.last_advert_age_seconds, 1)
            if runtime.last_advert_age_seconds is not None
            else None
        ),
        available=lambda runtime: runtime.last_advert_age_seconds is not None,
        native_unit_of_measurement=UnitOfTime.SECONDS,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:timer-outline",
    ),
    AirbnkSensorDescription(
        key="lock_events_counter",
        name="Lock Events Counter",
        native_value=lambda runtime: runtime.state.lock_events,
        available=lambda runtime: runtime.state.lock_events is not None,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
    ),
    AirbnkSensorDescription(
        key="advert_state_byte",
        name="Advert State Byte",
        native_value=lambda runtime: (
            f"0x{runtime.state.advert_state_flags:02X}"
            if runtime.state.advert_state_flags is not None
            else None
        ),
        available=lambda runtime: runtime.state.advert_state_flags is not None,
        icon="mdi:hexadecimal",
    ),
    AirbnkSensorDescription(
        key="advert_state_bits",
        name="Advert State Bits",
        native_value=lambda runtime: (
            f"0x{((runtime.state.advert_state_flags >> 4) & 0x03):X}"
            if runtime.state.advert_state_flags is not None
            else None
        ),
        available=lambda runtime: runtime.state.advert_state_flags is not None,
        icon="mdi:lock-outline",
    ),
    AirbnkSensorDescription(
        key="advert_state_meaning",
        name="Advert State Meaning",
        native_value=lambda runtime: runtime.state.advert_state_label,
        available=lambda runtime: runtime.state.advert_state_label is not None,
        icon="mdi:text-box-search-outline",
    ),
    AirbnkSensorDescription(
        key="status_state_byte",
        name="Status State Byte",
        native_value=lambda runtime: (
            f"0x{runtime.state.status_state_byte:02X}"
            if runtime.state.status_state_byte is not None
            else None
        ),
        available=lambda runtime: runtime.state.status_state_byte is not None,
        icon="mdi:hexadecimal",
    ),
    AirbnkSensorDescription(
        key="status_state_bits",
        name="Status State Bits",
        native_value=lambda runtime: (
            f"0x{runtime.state.status_state_nibble:X}"
            if runtime.state.status_state_nibble is not None
            else None
        ),
        available=lambda runtime: runtime.state.status_state_nibble is not None,
        icon="mdi:lock-outline",
    ),
    AirbnkSensorDescription(
        key="status_state_meaning",
        name="Status State Meaning",
        native_value=lambda runtime: runtime.state.status_state_label,
        available=lambda runtime: runtime.state.status_state_label is not None,
        icon="mdi:text-box-search-outline",
    ),
    AirbnkSensorDescription(
        key="status_tail_byte",
        name="Status Tail Byte",
        native_value=lambda runtime: (
            f"0x{runtime.state.status_trailing_byte:02X}"
            if runtime.state.status_trailing_byte is not None
            else None
        ),
        available=lambda runtime: runtime.state.status_trailing_byte is not None,
        icon="mdi:hexadecimal",
    ),
    AirbnkSensorDescription(
        key="last_error",
        name="Last Error",
        native_value=lambda runtime: runtime.state.last_error,
        available=lambda runtime: True,
        icon="mdi:alert-circle-outline",
    ),
)


SENSORS = tuple(
    replace(
        description,
        entity_registry_enabled_default=description.key
        not in DISABLED_BY_DEFAULT_SENSOR_KEYS,
        entity_registry_visible_default=description.key
        not in HIDDEN_BY_DEFAULT_SENSOR_KEYS,
    )
    for description in _SENSOR_DESCRIPTIONS
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Airbnk sensors."""

    runtime = entry.runtime_data
    async_add_entities(
        [AirbnkBleSensor(runtime, description) for description in SENSORS]
    )


class AirbnkBleSensor(AirbnkBaseEntity, SensorEntity):
    """Diagnostic sensor backed by the AirBnk runtime."""

    def __init__(self, runtime, description: AirbnkSensorDescription) -> None:
        super().__init__(runtime)
        self._description = description
        self._attr_unique_id = f"{runtime.lock_sn}_{description.key}"
        self._attr_name = description.name
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_class = description.device_class
        self._attr_native_unit_of_measurement = description.native_unit_of_measurement
        self._attr_state_class = description.state_class
        self._attr_icon = description.icon
        self._attr_entity_registry_enabled_default = (
            description.entity_registry_enabled_default
        )
        self._attr_entity_registry_visible_default = (
            description.entity_registry_visible_default
        )

    @property
    def available(self) -> bool:
        """Return whether the sensor currently has data to show."""

        return bool(self._description.available(self._runtime))

    @property
    def native_value(self):
        """Return the current sensor value."""

        return self._description.native_value(self._runtime)

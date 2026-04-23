"""Entity helpers for Airbnk BLE."""

from __future__ import annotations

from homeassistant.helpers.entity import Entity

from .device import AirbnkLockRuntime


class AirbnkBaseEntity(Entity):
    """Base entity shared by all AirBnk entities."""

    _attr_should_poll = False
    _attr_has_entity_name = True

    def __init__(self, runtime: AirbnkLockRuntime) -> None:
        self._runtime = runtime

    @property
    def device_info(self):
        """Return the device info for the shared Airbnk device."""

        return self._runtime.device_info

    async def async_added_to_hass(self) -> None:
        """Subscribe to runtime updates."""

        self.async_on_remove(self._runtime.register_callback(self.async_write_ha_state))
        await super().async_added_to_hass()

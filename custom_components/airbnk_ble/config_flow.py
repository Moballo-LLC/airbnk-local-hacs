"""Config flow for Airbnk BLE."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.const import CONF_EMAIL, CONF_NAME
from homeassistant.core import callback

from .airbnk import (
    AirbnkProtocolError,
    BootstrapData,
    build_entry_data,
    decrypt_bootstrap,
    normalize_mac_address,
    parse_advertisement_data,
    serial_numbers_match,
    validate_entry_data,
)
from .cloud_api import (
    AirbnkCloudClient,
    AirbnkCloudError,
    AirbnkCloudLock,
    AirbnkCloudSession,
)
from .const import (
    CONF_APP_KEY,
    CONF_BATTERY_PROFILE,
    CONF_COMMAND_TIMEOUT,
    CONF_CONNECTIVITY_PROBE_INTERVAL,
    CONF_DISCOVERED_ADDRESS,
    CONF_HARDWARE_VERSION,
    CONF_LOCK_SN,
    CONF_MAC_ADDRESS,
    CONF_NEW_SNINFO,
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
    DISCOVERED_ADDRESS_MANUAL,
    DOMAIN,
    LEGACY_DOMAIN,
    MANUFACTURER_ID_AIRBNK,
    SETUP_MODE_CLOUD,
    SETUP_MODE_IMPORT_MORCOS,
    SETUP_MODE_MANUAL,
)
from .profiles import MODEL_PROFILE_BY_KEY, get_model_profile

CONF_AUTH_CODE = "auth_code"
CONF_SELECTED_LEGACY_ENTRY = "selected_legacy_entry"
CONF_SELECTED_LOCK = "selected_lock"

_LOGGER = logging.getLogger(__name__)


class AirbnkBleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle config flow for Airbnk BLE."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""

        self._cloud_client: AirbnkCloudClient | None = None
        self._cloud_email: str | None = None
        self._cloud_session: AirbnkCloudSession | None = None
        self._cloud_locks: dict[str, AirbnkCloudLock] = {}
        self._preferred_address: str | None = None
        self._preferred_lock_sn: str | None = None
        self._prepared_bootstrap: BootstrapData | None = None
        self._prepared_battery_profile: list[dict[str, float]] | None = None
        self._prepared_hardware_version: str = ""
        self._prepared_name: str | None = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AirbnkBleOptionsFlow:
        """Return the options flow."""

        return AirbnkBleOptionsFlow(config_entry)

    async def async_step_bluetooth(
        self,
        discovery_info: BluetoothServiceInfoBleak,
    ):
        """Handle Bluetooth discovery."""

        parsed = _parse_discovery_info(discovery_info)
        if parsed is None:
            return self.async_abort(reason="not_airbnk_device")

        self._preferred_address = normalize_mac_address(discovery_info.address)
        self._preferred_lock_sn = parsed.serial_number
        for entry in self._async_current_entries():
            if (
                str(entry.data.get(CONF_MAC_ADDRESS, "")).upper()
                == self._preferred_address
            ):
                return self.async_abort(reason="already_configured")
        return await self.async_step_user()

    async def async_step_user(self, _user_input: dict[str, Any] | None = None):
        """Show the setup-mode menu."""

        menu_options = [SETUP_MODE_CLOUD, SETUP_MODE_MANUAL]
        if self._async_legacy_entries():
            menu_options.append(SETUP_MODE_IMPORT_MORCOS)
        return self.async_show_menu(step_id="user", menu_options=menu_options)

    async def async_step_import_morcos(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Import a legacy Morcos Airbnk BLE entry."""

        legacy_entries = self._async_legacy_entries()
        if not legacy_entries:
            return self.async_abort(reason="no_legacy_entries")

        if user_input is not None:
            selected_entry_id = str(user_input[CONF_SELECTED_LEGACY_ENTRY])
            legacy_entry = next(
                (
                    entry
                    for entry in legacy_entries
                    if entry.entry_id == selected_entry_id
                ),
                None,
            )
            if legacy_entry is None:
                return self.async_abort(reason="no_legacy_entries")
            return await self._async_import_legacy_entry(legacy_entry)

        options = {
            entry.entry_id: (
                f"{entry.title or entry.data.get(CONF_NAME, DEFAULT_NAME)} "
                f"({entry.data.get(CONF_LOCK_SN, 'unknown serial')})"
            )
            for entry in legacy_entries
        }
        return self.async_show_form(
            step_id=SETUP_MODE_IMPORT_MORCOS,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED_LEGACY_ENTRY): vol.In(options),
                }
            ),
        )

    async def async_step_cloud(self, user_input: dict[str, Any] | None = None):
        """Start cloud-assisted onboarding."""

        errors: dict[str, str] = {}
        if user_input is not None:
            email = str(user_input[CONF_EMAIL]).strip()
            try:
                await self._get_cloud_client().async_request_verification_code(email)
            except AirbnkCloudError:
                errors["base"] = "code_request_failed"
            else:
                self._cloud_email = email
                return await self.async_step_cloud_verify()

        return self.async_show_form(
            step_id=SETUP_MODE_CLOUD,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_EMAIL, default=self._cloud_email or ""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_cloud_verify(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Verify the email code and fetch cloud devices."""

        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input[CONF_AUTH_CODE]).strip()
            try:
                session = await self._get_cloud_client().async_authenticate(
                    self._cloud_email or "",
                    code,
                )
                cloud_locks = await self._get_cloud_client().async_get_locks(session)
            except AirbnkCloudError:
                errors["base"] = "token_retrieval_failed"
            else:
                self._cloud_locks = {}
                for lock in cloud_locks:
                    try:
                        get_model_profile(lock.lock_model)
                    except KeyError:
                        continue
                    self._cloud_locks[lock.serial_number] = lock

                if not self._cloud_locks:
                    return self.async_abort(reason="no_supported_locks")

                expected_serial = self._preferred_lock_sn
                matching_serials = [
                    serial_number
                    for serial_number in self._cloud_locks
                    if expected_serial
                    and serial_numbers_match(serial_number, expected_serial)
                ]
                if expected_serial and not matching_serials:
                    return self.async_abort(reason="lock_not_found")
                if len(matching_serials) == 1:
                    return await self._async_prepare_cloud_lock(
                        matching_serials[0], session
                    )
                if len(self._cloud_locks) == 1:
                    return await self._async_prepare_cloud_lock(
                        next(iter(self._cloud_locks)),
                        session,
                    )

                self._cloud_session = session
                return await self.async_step_cloud_lock()

        return self.async_show_form(
            step_id="cloud_verify",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_AUTH_CODE): str,
                }
            ),
            description_placeholders={"email": self._cloud_email or ""},
            errors=errors,
        )

    async def async_step_cloud_lock(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Select a lock from the authenticated account."""

        if user_input is not None:
            if self._cloud_session is None:
                return self.async_abort(reason="cannot_connect")
            return await self._async_prepare_cloud_lock(
                user_input[CONF_SELECTED_LOCK],
                self._cloud_session,
            )

        options = {
            serial_number: f"{lock.device_name} ({lock.lock_model}, {serial_number})"
            for serial_number, lock in sorted(self._cloud_locks.items())
        }
        return self.async_show_form(
            step_id="cloud_lock",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SELECTED_LOCK): vol.In(options),
                }
            ),
        )

    async def async_step_manual(self, user_input: dict[str, Any] | None = None):
        """Handle manual bootstrap entry."""

        errors: dict[str, str] = {}
        if user_input is not None:
            lock_sn = str(user_input[CONF_LOCK_SN]).strip()
            if self._preferred_lock_sn and not serial_numbers_match(
                lock_sn,
                self._preferred_lock_sn,
            ):
                errors["base"] = "lock_mismatch"
            else:
                try:
                    bootstrap = decrypt_bootstrap(
                        lock_sn,
                        str(user_input[CONF_NEW_SNINFO]).strip(),
                        str(user_input[CONF_APP_KEY]).strip(),
                    )
                except AirbnkProtocolError:
                    errors["base"] = "invalid_airbnk_bootstrap"
                else:
                    await self.async_set_unique_id(
                        bootstrap.lock_sn, raise_on_progress=False
                    )
                    self._abort_if_unique_id_configured()
                    self._prepared_bootstrap = bootstrap
                    self._prepared_name = str(
                        user_input.get(CONF_NAME) or DEFAULT_NAME
                    ).strip()
                    self._prepared_battery_profile = [
                        {"voltage": point.voltage, "percent": point.percent}
                        for point in get_model_profile(
                            bootstrap.lock_model
                        ).default_battery_profile
                    ]
                    self._prepared_hardware_version = ""
                    return await self.async_step_confirm_lock()

        return self.async_show_form(
            step_id=SETUP_MODE_MANUAL,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_NAME, default=self._prepared_name or DEFAULT_NAME
                    ): str,
                    vol.Required(
                        CONF_LOCK_SN, default=self._preferred_lock_sn or ""
                    ): str,
                    vol.Required(CONF_NEW_SNINFO): str,
                    vol.Required(CONF_APP_KEY): str,
                }
            ),
            errors=errors,
        )

    async def async_step_confirm_lock(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Confirm the selected lock and choose its Bluetooth address."""

        if self._prepared_bootstrap is None or self._prepared_battery_profile is None:
            return self.async_abort(reason="cannot_connect")

        errors: dict[str, str] = {}
        candidates = self._async_matching_discovered_addresses(
            self._prepared_bootstrap.lock_sn
        )
        if user_input is not None:
            try:
                entry_data = build_entry_data(
                    name=str(user_input[CONF_NAME]).strip(),
                    mac_address=self._resolve_address_from_form(user_input, candidates),
                    bootstrap=self._prepared_bootstrap,
                    battery_profile=self._prepared_battery_profile,
                    reverse_commands=bool(user_input[CONF_REVERSE_COMMANDS]),
                    supports_remote_lock=bool(user_input[CONF_SUPPORTS_REMOTE_LOCK]),
                    retry_count=int(user_input[CONF_RETRY_COUNT]),
                    command_timeout=int(user_input[CONF_COMMAND_TIMEOUT]),
                    connectivity_probe_interval=int(
                        user_input[CONF_CONNECTIVITY_PROBE_INTERVAL]
                    ),
                    unavailable_after=int(user_input[CONF_UNAVAILABLE_AFTER]),
                    hardware_version=self._prepared_hardware_version,
                )
            except AirbnkProtocolError:
                errors["base"] = "invalid_address"
            else:
                await self.async_set_unique_id(
                    entry_data[CONF_LOCK_SN], raise_on_progress=False
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=entry_data[CONF_NAME],
                    data=entry_data,
                )

        return self.async_show_form(
            step_id="confirm_lock",
            data_schema=_confirm_lock_schema(
                user_input=user_input,
                candidates=candidates,
                name=self._prepared_name or DEFAULT_NAME,
                profile_key=self._prepared_bootstrap.profile,
                preferred_address=self._preferred_address,
            ),
            description_placeholders={
                "serial": self._prepared_bootstrap.lock_sn,
                "model": self._prepared_bootstrap.lock_model,
            },
            errors=errors,
        )

    async def async_step_reconfigure(
        self,
        _user_input: dict[str, Any] | None = None,
    ):
        """Handle the reconfigure menu."""

        return self.async_show_menu(
            step_id="reconfigure",
            menu_options=["rediscover_bluetooth", "refresh_bootstrap"],
        )

    async def async_step_rediscover_bluetooth(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Rediscover the BLE address for the configured lock."""

        entry = self._get_reconfigure_entry()
        candidates = self._async_matching_discovered_addresses(entry.data[CONF_LOCK_SN])
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                address = self._resolve_address_from_form(user_input, candidates)
            except AirbnkProtocolError:
                errors["base"] = "invalid_address"
            else:
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_MAC_ADDRESS: normalize_mac_address(address)},
                )

        return self.async_show_form(
            step_id="rediscover_bluetooth",
            data_schema=_rediscover_schema(
                user_input=user_input,
                candidates=candidates,
                current_address=entry.data[CONF_MAC_ADDRESS],
            ),
            description_placeholders={"device_name": entry.title},
            errors=errors,
        )

    async def async_step_refresh_bootstrap(
        self,
        _user_input: dict[str, Any] | None = None,
    ):
        """Choose how to refresh bootstrap data."""

        return self.async_show_menu(
            step_id="refresh_bootstrap",
            menu_options=["cloud_refresh", "manual_refresh"],
        )

    async def async_step_cloud_refresh(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Start a cloud bootstrap refresh."""

        errors: dict[str, str] = {}
        if user_input is not None:
            email = str(user_input[CONF_EMAIL]).strip()
            try:
                await self._get_cloud_client().async_request_verification_code(email)
            except AirbnkCloudError:
                errors["base"] = "code_request_failed"
            else:
                self._cloud_email = email
                return await self.async_step_cloud_refresh_verify()

        return self.async_show_form(
            step_id="cloud_refresh",
            data_schema=vol.Schema(
                {vol.Required(CONF_EMAIL, default=self._cloud_email or ""): str}
            ),
            errors=errors,
        )

    async def async_step_cloud_refresh_verify(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Verify code and refresh bootstrap for the existing lock."""

        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                session = await self._get_cloud_client().async_authenticate(
                    self._cloud_email or "",
                    str(user_input[CONF_AUTH_CODE]).strip(),
                )
                locks = await self._get_cloud_client().async_get_locks(session)
            except AirbnkCloudError:
                errors["base"] = "token_retrieval_failed"
            else:
                matching_lock = next(
                    (
                        lock
                        for lock in locks
                        if serial_numbers_match(
                            lock.serial_number,
                            str(entry.data[CONF_LOCK_SN]),
                        )
                    ),
                    None,
                )
                if matching_lock is None:
                    return self.async_abort(reason="lock_not_found")
                self._cloud_locks = {matching_lock.serial_number: matching_lock}
                return await self._async_prepare_cloud_lock(
                    matching_lock.serial_number,
                    session,
                    refresh_entry=entry,
                )

        return self.async_show_form(
            step_id="cloud_refresh_verify",
            data_schema=vol.Schema({vol.Required(CONF_AUTH_CODE): str}),
            description_placeholders={"email": self._cloud_email or ""},
            errors=errors,
        )

    async def async_step_manual_refresh(
        self,
        user_input: dict[str, Any] | None = None,
    ):
        """Refresh bootstrap using manually entered app data."""

        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                bootstrap = decrypt_bootstrap(
                    entry.data[CONF_LOCK_SN],
                    str(user_input[CONF_NEW_SNINFO]).strip(),
                    str(user_input[CONF_APP_KEY]).strip(),
                )
            except AirbnkProtocolError:
                errors["base"] = "invalid_airbnk_bootstrap"
            else:
                await self.async_set_unique_id(bootstrap.lock_sn)
                self._abort_if_unique_id_mismatch(reason="another_device")
                self._prepared_bootstrap = bootstrap
                self._prepared_battery_profile = list(entry.data[CONF_BATTERY_PROFILE])
                self._prepared_hardware_version = entry.data.get(
                    CONF_HARDWARE_VERSION, ""
                )
                return await self._async_update_reconfigure_entry(entry)

        return self.async_show_form(
            step_id="manual_refresh",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_NEW_SNINFO): str,
                    vol.Required(CONF_APP_KEY): str,
                }
            ),
            description_placeholders={"serial": entry.data[CONF_LOCK_SN]},
            errors=errors,
        )

    async def _async_prepare_cloud_lock(
        self,
        serial_number: str,
        session: AirbnkCloudSession,
        *,
        refresh_entry: config_entries.ConfigEntry | None = None,
    ):
        """Fetch cloud battery data and derive local bootstrap for a lock."""

        lock = self._cloud_locks.get(serial_number)
        if lock is None:
            return self.async_abort(reason="lock_not_found")

        try:
            bootstrap = decrypt_bootstrap(
                lock.serial_number, lock.new_sninfo, lock.app_key
            )
        except AirbnkProtocolError:
            return self.async_abort(reason="invalid_airbnk_bootstrap")

        try:
            battery_profile = await self._get_cloud_client().async_get_battery_profile(
                session,
                lock_model=lock.lock_model,
                hardware_version=lock.hardware_version,
            )
        except AirbnkCloudError:
            battery_profile = None

        if battery_profile is None:
            battery_profile = [
                {"voltage": point.voltage, "percent": point.percent}
                for point in get_model_profile(
                    bootstrap.lock_model
                ).default_battery_profile
            ]

        self._prepared_bootstrap = bootstrap
        self._prepared_battery_profile = battery_profile
        self._prepared_hardware_version = lock.hardware_version
        self._prepared_name = lock.device_name

        if refresh_entry is not None:
            return await self._async_update_reconfigure_entry(refresh_entry)
        return await self.async_step_confirm_lock()

    async def _async_update_reconfigure_entry(
        self,
        entry: config_entries.ConfigEntry,
    ):
        """Apply prepared bootstrap data to an existing entry."""

        if self._prepared_bootstrap is None or self._prepared_battery_profile is None:
            return self.async_abort(reason="cannot_connect")

        updated = build_entry_data(
            name=entry.data[CONF_NAME],
            mac_address=entry.data[CONF_MAC_ADDRESS],
            bootstrap=self._prepared_bootstrap,
            battery_profile=self._prepared_battery_profile,
            reverse_commands=bool(entry.data[CONF_REVERSE_COMMANDS]),
            supports_remote_lock=bool(entry.data[CONF_SUPPORTS_REMOTE_LOCK]),
            retry_count=int(entry.data[CONF_RETRY_COUNT]),
            command_timeout=int(entry.data[CONF_COMMAND_TIMEOUT]),
            connectivity_probe_interval=int(
                entry.data[CONF_CONNECTIVITY_PROBE_INTERVAL]
            ),
            unavailable_after=int(entry.data[CONF_UNAVAILABLE_AFTER]),
            hardware_version=self._prepared_hardware_version,
        )
        return self.async_update_reload_and_abort(entry, data_updates=updated)

    def _resolve_address_from_form(
        self,
        user_input: Mapping[str, Any],
        candidates: Mapping[str, str],
    ) -> str:
        """Resolve the chosen Bluetooth address from a form submission."""

        if candidates:
            discovered_address = str(
                user_input.get(CONF_DISCOVERED_ADDRESS, "")
            ).strip()
            if discovered_address and discovered_address != DISCOVERED_ADDRESS_MANUAL:
                return discovered_address
        manual_address = str(user_input.get(CONF_MAC_ADDRESS, "")).strip()
        if not manual_address:
            raise AirbnkProtocolError("A manual MAC address is required")
        return manual_address

    @callback
    def _async_matching_discovered_addresses(self, lock_sn: str) -> dict[str, str]:
        """Return discovered Airbnk addresses that match a serial number."""

        candidates: dict[str, str] = {}
        try:
            discoveries = async_discovered_service_info(self.hass)
        except RuntimeError:
            _LOGGER.debug(
                "Bluetooth manager is not ready while matching "
                "Airbnk discovery candidates"
            )
            return candidates

        for discovery_info in discoveries:
            parsed = _parse_discovery_info(discovery_info)
            if parsed is None or not serial_numbers_match(
                lock_sn, parsed.serial_number
            ):
                continue
            address = normalize_mac_address(discovery_info.address)
            label = f"{address} (RSSI {discovery_info.rssi}, {parsed.firmware_version})"
            candidates[address] = label

        if self._preferred_address and self._preferred_address in candidates:
            ordered = {self._preferred_address: candidates[self._preferred_address]}
            for address, label in candidates.items():
                if address == self._preferred_address:
                    continue
                ordered[address] = label
            return ordered

        return dict(sorted(candidates.items()))

    def _get_cloud_client(self) -> AirbnkCloudClient:
        """Return the cloud client."""

        if self._cloud_client is None:
            self._cloud_client = AirbnkCloudClient(self.hass)
        return self._cloud_client

    @callback
    def _async_legacy_entries(self) -> list[config_entries.ConfigEntry]:
        """Return importable legacy Morcos config entries."""

        configured_serials = {
            str(entry.unique_id or entry.data.get(CONF_LOCK_SN, "")).strip()
            for entry in self._async_current_entries()
        }
        legacy_entries: list[config_entries.ConfigEntry] = []
        for entry in self.hass.config_entries.async_entries(LEGACY_DOMAIN):
            serial = str(entry.unique_id or entry.data.get(CONF_LOCK_SN, "")).strip()
            if serial and serial in configured_serials:
                continue
            legacy_entries.append(entry)
        return legacy_entries

    async def _async_import_legacy_entry(
        self,
        legacy_entry: config_entries.ConfigEntry,
    ):
        """Convert a legacy Morcos entry into the public Airbnk BLE format."""

        try:
            entry_data, _bootstrap = validate_entry_data(legacy_entry.data)
        except AirbnkProtocolError:
            return self.async_abort(reason="invalid_legacy_entry")

        await self.async_set_unique_id(
            entry_data[CONF_LOCK_SN],
            raise_on_progress=False,
        )
        self._abort_if_unique_id_configured()
        return self.async_create_entry(
            title=entry_data[CONF_NAME],
            data=entry_data,
        )


class AirbnkBleOptionsFlow(config_entries.OptionsFlow):
    """Handle Airbnk BLE options."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize the options flow."""

        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        """Update name and runtime tuning."""

        if user_input is not None:
            updated_data = {
                **self._config_entry.data,
                CONF_NAME: str(user_input[CONF_NAME]).strip()
                or self._config_entry.data[CONF_NAME],
                CONF_REVERSE_COMMANDS: bool(user_input[CONF_REVERSE_COMMANDS]),
                CONF_SUPPORTS_REMOTE_LOCK: bool(user_input[CONF_SUPPORTS_REMOTE_LOCK]),
                CONF_RETRY_COUNT: int(user_input[CONF_RETRY_COUNT]),
                CONF_COMMAND_TIMEOUT: int(user_input[CONF_COMMAND_TIMEOUT]),
                CONF_CONNECTIVITY_PROBE_INTERVAL: int(
                    user_input[CONF_CONNECTIVITY_PROBE_INTERVAL]
                ),
                CONF_UNAVAILABLE_AFTER: int(user_input[CONF_UNAVAILABLE_AFTER]),
            }
            self.hass.config_entries.async_update_entry(
                self._config_entry,
                data=updated_data,
                title=updated_data[CONF_NAME],
            )
            return self.async_create_entry(title="", data={})

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_NAME, default=self._config_entry.data[CONF_NAME]
                    ): str,
                    vol.Optional(
                        CONF_REVERSE_COMMANDS,
                        default=self._config_entry.data[CONF_REVERSE_COMMANDS],
                    ): bool,
                    vol.Optional(
                        CONF_SUPPORTS_REMOTE_LOCK,
                        default=self._config_entry.data[CONF_SUPPORTS_REMOTE_LOCK],
                    ): bool,
                    vol.Optional(
                        CONF_RETRY_COUNT,
                        default=self._config_entry.data[CONF_RETRY_COUNT],
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
                    vol.Optional(
                        CONF_COMMAND_TIMEOUT,
                        default=self._config_entry.data[CONF_COMMAND_TIMEOUT],
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
                    vol.Optional(
                        CONF_CONNECTIVITY_PROBE_INTERVAL,
                        default=self._config_entry.data[
                            CONF_CONNECTIVITY_PROBE_INTERVAL
                        ],
                    ): vol.All(vol.Coerce(int), vol.Range(min=0, max=604800)),
                    vol.Optional(
                        CONF_UNAVAILABLE_AFTER,
                        default=self._config_entry.data[CONF_UNAVAILABLE_AFTER],
                    ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
                }
            ),
        )


def _confirm_lock_schema(
    *,
    user_input: Mapping[str, Any] | None,
    candidates: Mapping[str, str],
    name: str,
    profile_key: str,
    preferred_address: str | None,
) -> vol.Schema:
    """Build the confirmation schema for a new lock entry."""

    user_input = user_input or {}
    model_profile = MODEL_PROFILE_BY_KEY[profile_key]

    schema: dict[Any, Any] = {
        vol.Required(CONF_NAME, default=user_input.get(CONF_NAME, name)): str,
    }

    if candidates:
        address_options = dict(candidates)
        address_options[DISCOVERED_ADDRESS_MANUAL] = "Enter a MAC address manually"
        default_address = user_input.get(CONF_DISCOVERED_ADDRESS)
        if not default_address:
            default_address = (
                preferred_address
                if preferred_address in candidates
                else next(iter(candidates))
            )
        schema[vol.Required(CONF_DISCOVERED_ADDRESS, default=default_address)] = vol.In(
            address_options
        )
        schema[
            vol.Optional(
                CONF_MAC_ADDRESS,
                default=user_input.get(CONF_MAC_ADDRESS, ""),
            )
        ] = str
    else:
        schema[
            vol.Required(
                CONF_MAC_ADDRESS,
                default=user_input.get(CONF_MAC_ADDRESS, preferred_address or ""),
            )
        ] = str

    schema.update(
        {
            vol.Optional(
                CONF_REVERSE_COMMANDS,
                default=user_input.get(CONF_REVERSE_COMMANDS, DEFAULT_REVERSE_COMMANDS),
            ): bool,
            vol.Optional(
                CONF_SUPPORTS_REMOTE_LOCK,
                default=user_input.get(
                    CONF_SUPPORTS_REMOTE_LOCK,
                    model_profile.supports_remote_lock,
                ),
            ): bool,
            vol.Optional(
                CONF_RETRY_COUNT,
                default=user_input.get(CONF_RETRY_COUNT, DEFAULT_RETRY_COUNT),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=10)),
            vol.Optional(
                CONF_COMMAND_TIMEOUT,
                default=user_input.get(CONF_COMMAND_TIMEOUT, DEFAULT_COMMAND_TIMEOUT),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=120)),
            vol.Optional(
                CONF_CONNECTIVITY_PROBE_INTERVAL,
                default=user_input.get(
                    CONF_CONNECTIVITY_PROBE_INTERVAL,
                    DEFAULT_CONNECTIVITY_PROBE_INTERVAL,
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=0, max=604800)),
            vol.Optional(
                CONF_UNAVAILABLE_AFTER,
                default=user_input.get(
                    CONF_UNAVAILABLE_AFTER, DEFAULT_UNAVAILABLE_AFTER
                ),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=3600)),
        }
    )
    return vol.Schema(schema)


def _rediscover_schema(
    *,
    user_input: Mapping[str, Any] | None,
    candidates: Mapping[str, str],
    current_address: str,
) -> vol.Schema:
    """Build the rediscovery schema for reconfigure."""

    user_input = user_input or {}
    schema: dict[Any, Any] = {}
    if candidates:
        address_options = dict(candidates)
        address_options[DISCOVERED_ADDRESS_MANUAL] = "Enter a MAC address manually"
        schema[
            vol.Required(
                CONF_DISCOVERED_ADDRESS,
                default=user_input.get(CONF_DISCOVERED_ADDRESS, current_address),
            )
        ] = vol.In(address_options)
        schema[
            vol.Optional(
                CONF_MAC_ADDRESS,
                default=user_input.get(CONF_MAC_ADDRESS, ""),
            )
        ] = str
    else:
        schema[
            vol.Required(
                CONF_MAC_ADDRESS,
                default=user_input.get(CONF_MAC_ADDRESS, current_address),
            )
        ] = str
    return vol.Schema(schema)


def _parse_discovery_info(
    discovery_info: BluetoothServiceInfoBleak,
):
    """Parse Bluetooth discovery info into an Airbnk advert when possible."""

    manufacturer_payload = discovery_info.manufacturer_data.get(MANUFACTURER_ID_AIRBNK)
    if manufacturer_payload is None:
        for payload in discovery_info.manufacturer_data.values():
            raw = bytes(payload)
            if raw.startswith(b"\xba\xba"):
                manufacturer_payload = raw
                break
    if manufacturer_payload is None:
        return None

    try:
        return parse_advertisement_data(bytes(manufacturer_payload))
    except AirbnkProtocolError:
        return None

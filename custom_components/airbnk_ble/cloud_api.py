"""Airbnk cloud helpers for bootstrap acquisition."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

from aiohttp import ClientError
from homeassistant.const import CONF_EMAIL
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .airbnk import AirbnkProtocolError, battery_profile_from_voltage_points

_LOGGER = logging.getLogger(__name__)

AIRBNK_CLOUD_URL = "https://wehereapi.seamooncloud.com"
AIRBNK_LANGUAGE = "2"
AIRBNK_VERSION = "A_FD_1.8.0"
AIRBNK_HEADERS = {
    "user-agent": "okhttp/3.12.0",
    "Accept-Encoding": "gzip, deflate",
}


class AirbnkCloudError(RuntimeError):
    """Raised when the Airbnk cloud flow cannot proceed."""


@dataclass(frozen=True, slots=True)
class AirbnkCloudSession:
    """Authenticated cloud session details."""

    email: str
    user_id: str
    token: str


@dataclass(frozen=True, slots=True)
class AirbnkCloudLock:
    """Lock details returned from the Airbnk cloud."""

    serial_number: str
    device_name: str
    lock_model: str
    hardware_version: str
    app_key: str
    new_sninfo: str


class AirbnkCloudClient:
    """Fetch bootstrap data from the Airbnk cloud."""

    def __init__(self, hass) -> None:
        self._session = async_get_clientsession(hass)

    async def async_request_verification_code(self, email: str) -> None:
        """Request an email verification code."""

        await self._async_call(
            "POST",
            "/api/lock/sms",
            {
                "loginAcct": email,
                "language": AIRBNK_LANGUAGE,
                "version": AIRBNK_VERSION,
                "mark": "10",
                "userId": "",
            },
            expect_data=False,
        )

    async def async_authenticate(self, email: str, code: str) -> AirbnkCloudSession:
        """Authenticate and return a short-lived session."""

        payload = await self._async_call(
            "GET",
            "/api/lock/loginByAuthcode",
            {
                "loginAcct": email,
                "authCode": code,
                "systemCode": "Android",
                "language": AIRBNK_LANGUAGE,
                "version": AIRBNK_VERSION,
                "deviceID": "123456789012345",
                "mark": "1",
            },
        )

        try:
            data = payload["data"]
            return AirbnkCloudSession(
                email=str(data[CONF_EMAIL]),
                user_id=str(data["userId"]),
                token=str(data["token"]),
            )
        except (KeyError, TypeError) as err:
            raise AirbnkCloudError(
                "The Airbnk login response was missing required fields"
            ) from err

    async def async_get_locks(
        self, session: AirbnkCloudSession
    ) -> list[AirbnkCloudLock]:
        """Return supported locks for the authenticated account."""

        payload = await self._async_call(
            "GET",
            "/api/v2/lock/getAllDevicesNew",
            {
                "language": AIRBNK_LANGUAGE,
                "userId": session.user_id,
                "version": AIRBNK_VERSION,
                "token": session.token,
            },
        )

        locks: list[AirbnkCloudLock] = []
        for raw_lock in payload.get("data") or []:
            try:
                lock = AirbnkCloudLock(
                    serial_number=str(raw_lock["sn"]),
                    device_name=str(raw_lock.get("deviceName") or raw_lock["sn"]),
                    lock_model=str(raw_lock["deviceType"]),
                    hardware_version=str(raw_lock.get("hardwareVersion") or ""),
                    app_key=str(raw_lock["appKey"]),
                    new_sninfo=str(raw_lock["newSninfo"]),
                )
            except (KeyError, TypeError) as err:
                _LOGGER.debug("Skipping incomplete Airbnk cloud record: %s", raw_lock)
                _LOGGER.debug("Incomplete Airbnk cloud record error: %s", err)
                continue
            if lock.lock_model.startswith(("W", "F")):
                continue
            locks.append(lock)

        return locks

    async def async_get_battery_profile(
        self,
        session: AirbnkCloudSession,
        *,
        lock_model: str,
        hardware_version: str,
    ) -> list[dict[str, float]] | None:
        """Fetch the cloud voltage config and convert it into a battery profile."""

        payload = await self._async_call(
            "GET",
            "/api/lock/getAllInfo1",
            {
                "language": AIRBNK_LANGUAGE,
                "userId": session.user_id,
                "version": AIRBNK_VERSION,
                "token": session.token,
            },
        )

        voltage_configs = (payload.get("data") or {}).get("voltageCfg") or []
        for raw_profile in voltage_configs:
            if (
                str(raw_profile.get("fdeviceType")) != lock_model
                or str(raw_profile.get("fhardwareVersion")) != hardware_version
            ):
                continue
            try:
                profile = battery_profile_from_voltage_points(
                    [
                        float(raw_profile[f"fvoltage{index}"])
                        for index in range(1, 5)
                        if raw_profile.get(f"fvoltage{index}") is not None
                    ]
                )
            except (AirbnkProtocolError, ValueError, TypeError):
                return None
            return [
                {"voltage": point.voltage, "percent": point.percent}
                for point in profile
            ]

        return None

    async def _async_call(
        self,
        method: str,
        path: str,
        params: dict[str, str],
        *,
        expect_data: bool = True,
    ) -> dict[str, Any]:
        """Call an Airbnk cloud endpoint and validate the response."""

        url = f"{AIRBNK_CLOUD_URL}{path}?{urlencode(params)}"
        try:
            response = await self._session.request(method, url, headers=AIRBNK_HEADERS)
        except ClientError as err:
            raise AirbnkCloudError(f"Could not reach the Airbnk cloud: {err}") from err

        async with response:
            if response.status != 200:
                raise AirbnkCloudError(
                    f"Airbnk cloud request failed with HTTP {response.status}"
                )
            payload = await response.json(content_type=None)

        if payload.get("code") != 200:
            raise AirbnkCloudError(
                str(
                    payload.get("msg")
                    or payload.get("message")
                    or "Airbnk cloud rejected the request"
                )
            )
        if expect_data and "data" not in payload:
            raise AirbnkCloudError("Airbnk cloud response did not include any data")
        return payload

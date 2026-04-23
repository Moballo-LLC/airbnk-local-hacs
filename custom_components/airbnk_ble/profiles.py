"""Supported Airbnk model profiles."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BatteryBreakpoint:
    """One battery interpolation point."""

    voltage: float
    percent: float


@dataclass(frozen=True, slots=True)
class ModelProfile:
    """Describe one supported Airbnk lock family."""

    key: str
    models: tuple[str, ...]
    default_battery_profile: tuple[BatteryBreakpoint, ...]
    supports_remote_lock: bool = False
    validated: bool = False


_B100_BATTERY_PROFILE = (
    BatteryBreakpoint(2.30, 0.0),
    BatteryBreakpoint(2.50, 30.0),
    BatteryBreakpoint(2.60, 60.0),
    BatteryBreakpoint(2.90, 100.0),
)

_M_SERIES_BATTERY_PROFILE = (
    BatteryBreakpoint(4.80, 0.0),
    BatteryBreakpoint(5.20, 30.0),
    BatteryBreakpoint(5.80, 70.0),
    BatteryBreakpoint(6.20, 100.0),
)

MODEL_PROFILES: tuple[ModelProfile, ...] = (
    ModelProfile(
        key="b100",
        models=("B100",),
        default_battery_profile=_B100_BATTERY_PROFILE,
        supports_remote_lock=False,
        validated=True,
    ),
    ModelProfile(
        key="m300",
        models=("M300",),
        default_battery_profile=_M_SERIES_BATTERY_PROFILE,
        supports_remote_lock=False,
        validated=False,
    ),
    ModelProfile(
        key="m500",
        models=("M500",),
        default_battery_profile=_M_SERIES_BATTERY_PROFILE,
        supports_remote_lock=False,
        validated=False,
    ),
    ModelProfile(
        key="m510",
        models=("M510",),
        default_battery_profile=_M_SERIES_BATTERY_PROFILE,
        supports_remote_lock=False,
        validated=False,
    ),
    ModelProfile(
        key="m530",
        models=("M530",),
        default_battery_profile=_M_SERIES_BATTERY_PROFILE,
        supports_remote_lock=False,
        validated=False,
    ),
    ModelProfile(
        key="m531",
        models=("M531",),
        default_battery_profile=_M_SERIES_BATTERY_PROFILE,
        supports_remote_lock=False,
        validated=False,
    ),
)

MODEL_PROFILE_BY_KEY = {profile.key: profile for profile in MODEL_PROFILES}
MODEL_PROFILE_BY_MODEL = {
    model: profile for profile in MODEL_PROFILES for model in profile.models
}
SUPPORTED_MODELS = frozenset(MODEL_PROFILE_BY_MODEL)


def get_model_profile(lock_model: str) -> ModelProfile:
    """Return the profile for a lock model or raise KeyError."""

    return MODEL_PROFILE_BY_MODEL[lock_model]

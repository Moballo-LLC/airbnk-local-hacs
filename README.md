# Airbnk BLE

Local Bluetooth control for supported Airbnk locks in Home Assistant.

This custom integration keeps lock operation local over Home Assistant Bluetooth. The Airbnk or WeHere cloud is used only to acquire bootstrap material during setup or explicit refresh, and the integration stores only derived local keys after setup completes.

## Status

- `B100` is the only live-tested and validated model today.
- `M300`, `M500`, `M510`, `M530`, and `M531` are included through shared protocol and fixture coverage, but should still be treated as community-validated until more live testing lands.

## Installation

1. In HACS, add this repository as a custom integration.
2. Install `Airbnk BLE`.
3. Restart Home Assistant.
4. Add the integration from Settings -> Devices & Services.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Moballo-LLC&repository=airbnk-ble&category=integration)

## Setup Modes

### Cloud

Use an Airbnk or WeHere account email, request a verification code, then choose a supported lock from the account. The integration derives the local operating keys and does not keep the raw cloud token, raw `appKey`, or raw `newSninfo`.

Important: the Airbnk cloud may sign the mobile app out if the same account is reused. A separate shared-access account is safer.

### Manual

Provide `lock_sn`, `newSninfo`, and `appKey` directly. The raw values are used only during setup to derive local keys and are not stored afterwards.

## Features

- Native `lock` entity with `open` support
- Bluetooth discovery support for matching lock adverts to setup flows
- Per-lock config entries
- Arbitrary battery interpolation profiles stored as voltage/percent breakpoints
- Reconfigure flows for Bluetooth rediscovery and bootstrap refresh
- Sanitized diagnostics output

## Attribution

This project builds on two streams of prior work:

- The local BLE runtime and lock behavior started from the original private `morcos_airbnk_ble` custom component and was generalized into this standalone integration.
- The cloud login and bootstrap acquisition flow was adapted from [rospogrigio/airbnk_mqtt](https://github.com/rospogrigio/airbnk_mqtt), which helped validate the Airbnk / WeHere auth path and bootstrap handling. This repository stays local-first and stores only derived local keys after setup.

## Support Scope

Only the `B100` has been tested end to end against real hardware so far.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
ruff check .
mypy custom_components/airbnk_ble
pytest
```

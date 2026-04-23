# Airbnk BLE

Local Bluetooth control for supported Airbnk locks in Home Assistant.

This custom integration keeps lock operation local over Home Assistant Bluetooth. The Airbnk or WeHere cloud is used only to acquire bootstrap material during setup or explicit refresh, and the integration stores only derived local keys after setup completes.

## Status

- `B100` is the only live-tested and validated model today.
- `M300`, `M500`, `M510`, `M530`, and `M531` are included through shared protocol and fixture coverage, but should still be treated as community-validated until more live testing lands.

## What You Need

Before you install this integration, make sure you have all of the following:

1. A working Home Assistant installation.
2. A working Home Assistant Bluetooth path.
   You need one of these:
   - a local Bluetooth adapter connected to your Home Assistant machine
   - an ESPHome Bluetooth proxy near the lock
3. The lock must be close enough to that adapter or proxy for reliable BLE communication.
4. One supported Airbnk lock.
5. Either:
   - an Airbnk or WeHere account email that can access the lock
   - or the manual bootstrap values for the lock: `lock_sn`, `newSninfo`, and `appKey`

You do not need both a local adapter and a BLE proxy. One working Bluetooth path is enough.

If you do not already have Bluetooth working in Home Assistant, stop here and get that working first:

- [Home Assistant Bluetooth integration docs](https://www.home-assistant.io/integrations/bluetooth/)
- [ESPHome Bluetooth Proxy docs](https://esphome.io/components/bluetooth_proxy/)
- [ESPHome ready-made Bluetooth Proxy projects](https://esphome.io/projects/?type=bluetooth)

## Choose Your Bluetooth Path

This integration will not work unless Home Assistant already has a reliable BLE path to the lock.

### Option 1: Local Bluetooth Adapter

Use this if your Home Assistant machine is physically close enough to the lock.

Basic checklist:

1. Plug in a supported Bluetooth adapter if your Home Assistant hardware does not already have one.
2. In Home Assistant, go to `Settings -> Devices & Services -> Add Integration -> Bluetooth`.
3. Confirm Home Assistant sees the adapter.
4. If the adapter is unreliable, use a short USB extension cable and move it away from USB 3 ports, metal enclosures, and other radio noise.
5. Put the adapter as close to the lock as practical.

Important:

- Home Assistant OS is usually the easiest local-adapter path.
- Home Assistant Container needs extra Bluetooth and D-Bus setup. Follow the official Bluetooth docs above before trying this integration.

### Option 2: ESPHome Bluetooth Proxy

Use this if Home Assistant is not close to the lock, is virtualized, or you want better BLE coverage.

Basic checklist:

1. Get an ESP32 board.
2. Flash it as an ESPHome Bluetooth proxy.
3. Add that ESPHome device to Home Assistant.
4. In Home Assistant, open `Settings -> Devices & Services -> Bluetooth` and confirm the proxy appears there.
5. Place the proxy near the lock, not inside a metal rack and not right next to Wi-Fi gear, switches, or routers.

Notes:

- A Bluetooth proxy is often the better choice for BLE locks.
- Ethernet-based proxies are usually the most reliable.
- Wi-Fi proxies work too, but placement matters more.

## Installation

1. Open HACS.
2. Add this repository as a custom integration.
3. Install `Airbnk BLE`.
4. Restart Home Assistant.
5. Go to `Settings -> Devices & Services`.
6. Select `Add Integration`.
7. Search for `Airbnk BLE`.

[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=Moballo-LLC&repository=airbnk-ble&category=integration)

## Setup Walkthrough

### Step 1: Confirm Bluetooth Works First

Before adding `Airbnk BLE`, make sure Home Assistant already has Bluetooth working.

You should be able to open `Settings -> Devices & Services -> Bluetooth` and see at least one usable adapter or proxy there.

If you cannot do that yet, fix Bluetooth first. This integration depends on Home Assistant Bluetooth and does not replace it.

If Bluetooth is healthy and your lock is nearby, Home Assistant may also discover the lock automatically and show `Airbnk BLE` in the discovered integrations list. That auto-discovery only helps when Home Assistant has a connectable BLE path to the lock.

### Step 2: Add `Airbnk BLE`

Once Bluetooth is working:

1. Go to `Settings -> Devices & Services`.
2. Select `Add Integration`.
3. Choose `Airbnk BLE`.
4. Pick one of the setup modes below.

## Setup Modes

### Cloud

Use this if you can log in to Airbnk or WeHere and the account can access the lock.

What you do:

1. Enter the Airbnk or WeHere account email.
2. Request the verification code.
3. Enter the verification code from email.
4. Pick the lock from the list.
5. Let the integration derive the local operating keys.
6. Choose the discovered Bluetooth address for the lock, if Home Assistant found it.
7. Save the entry.

What the integration stores:

- derived local operating keys
- lock serial number
- Bluetooth address
- model/profile information
- battery profile and runtime options

What the integration does not keep after setup:

- raw cloud token
- raw `appKey`
- raw `newSninfo`
- verification code

Important: the Airbnk cloud may sign the mobile app out if the same account is reused. A separate shared-access account is safer.

Plus-address email aliases such as `name+airbnk@example.com` are supported for cloud login.

### Manual

Use this if you already have the lock's manual bootstrap values.

Most people should use `Cloud` setup. `Manual` is for advanced users who already have these values from earlier tooling or reverse-engineering work.

What you need:

- `lock_sn`
- `newSninfo`
- `appKey`

What you do:

1. Enter the lock name.
2. Enter `lock_sn`, `newSninfo`, and `appKey`.
3. Let the integration derive the local keys.
4. Choose the discovered Bluetooth address for the lock, or enter the MAC address manually if discovery did not find it.
5. Save the entry.

The raw manual values are used only during setup to derive local keys and are not stored afterwards.

### Step 3: Test the Lock

After setup finishes:

1. Open the new lock entity in Home Assistant.
2. Try `Unlock`.
3. Try `Lock`.
4. If your lock exposes latch-release behavior, try `Open`.

If commands are slow, fail, or the state does not update reliably, the problem is usually BLE coverage or interference rather than the setup flow.

## Features

- Native `lock` entity with `open` support
- Bluetooth discovery support for matching lock adverts to setup flows
- Per-lock config entries
- Arbitrary battery interpolation profiles stored as voltage/percent breakpoints
- Reconfigure flows for Bluetooth rediscovery and bootstrap refresh
- Sanitized diagnostics output

## Removal

If you want to remove `Airbnk BLE` cleanly:

1. Go to `Settings -> Devices & Services`.
2. Open the `Airbnk BLE` entry for the lock.
3. Choose `Delete`.
4. If you no longer want the package installed at all, remove it from HACS too.
5. Restart Home Assistant if you also removed the integration package from HACS.

Removing the config entry does not modify the lock itself. It only removes Home Assistant's local configuration for that lock.

## Attribution

This project builds on two streams of prior work:

- The local BLE runtime and lock behavior started from an earlier private BLE integration and was generalized into this standalone integration.
- The cloud login and bootstrap acquisition flow was adapted from [rospogrigio/airbnk_mqtt](https://github.com/rospogrigio/airbnk_mqtt), which helped validate the Airbnk / WeHere auth path and bootstrap handling. This repository stays local-first and stores only derived local keys after setup.

## Support Scope

Only the `B100` has been tested end to end against real hardware so far.

## Troubleshooting

### Home Assistant Cannot Find The Lock

Check these first:

1. Confirm `Bluetooth` is working in Home Assistant before blaming this integration.
2. Move the Bluetooth adapter or BLE proxy closer to the lock.
3. Wake the lock if it sleeps aggressively.
4. Refresh the Airbnk BLE setup flow and try again.
5. If using a local USB adapter, move it away from USB 3 ports and noisy hardware.

### The Lock Shows Up, But Commands Fail

This usually means BLE connectivity is weak or unstable.

Try:

1. Moving the adapter or proxy closer to the lock.
2. Using an ESPHome BLE proxy instead of a distant USB adapter.
3. Using an Ethernet-based BLE proxy if possible.
4. Reducing radio interference by moving the adapter or proxy away from routers, switches, and metal enclosures.

### Home Assistant Container Users

If you run Home Assistant in a container, Bluetooth needs extra host and container setup. If Bluetooth itself is not healthy, this integration will not be healthy either.

Use the official Bluetooth docs:

- [Home Assistant Bluetooth integration docs](https://www.home-assistant.io/integrations/bluetooth/)

### Cloud Login Works But The Mobile App Gets Signed Out

That can happen with Airbnk or WeHere.

The safest approach is to use a separate shared-access account for Home Assistant if possible.

### I Have A `B100`

`B100` is the model we have validated end to end on real hardware so far, so it currently has the strongest real-world coverage.

## Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
ruff check .
mypy custom_components/airbnk_ble
pytest
```

## Core Integration Roadmap

This repository is now shaped to make a future Home Assistant core submission easier:

- Bluetooth discovery is wired through Home Assistant's Bluetooth matcher model.
- User-tunable behavior now lives in `ConfigEntry.options`, while connection/bootstrap data stays in `ConfigEntry.data`.
- Removing an entry triggers Bluetooth rediscovery so the lock can be found again without restarting Home Assistant.
- `quality_scale.yaml` is included to track bronze-level core readiness work.
- Local custom-integration brand assets now live in `custom_components/airbnk_ble/brand/`, which matches the current custom-integration/HACS packaging guidance. If this project moves into Home Assistant Core, those local brand files should be removed and submitted to `home-assistant/brands` instead.

The main remaining blocker for a real core PR is dependency transparency. Home Assistant's core submission docs require the Airbnk communication layer to live in a separately published, reusable Python library on PyPI rather than inside the integration repo itself. Until that library exists, this project is best treated as a polished custom integration/HACS package that is intentionally being kept close to core expectations.

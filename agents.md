# Repository Guidance

## Product Intent

- This repository publishes the standalone `Airbnk BLE` Home Assistant custom integration.
- Runtime lock control is local-first over Home Assistant Bluetooth.
- Airbnk or WeHere cloud access is allowed only for bootstrap acquisition during setup or explicit refresh.

## Security Boundaries

- Never commit real account emails, verification codes, tokens, `appKey`, `newSninfo`, MAC addresses, serial numbers, or captured payloads from a live home environment.
- The integration may accept raw bootstrap values during setup, but it must only persist derived local keys and other non-sensitive runtime metadata afterwards.
- Diagnostics, fixtures, screenshots, and docs must stay sanitized.

## Hardware Support

- `B100` is the only live-validated model right now.
- `M300`, `M500`, `M510`, `M530`, and `M531` are supported through shared protocol logic plus fixture coverage, but should not be documented as equally field-validated.

## Implementation Preferences

- Prefer the existing private component's BLE runtime decisions unless there is a strong reason to change them.
- Keep per-lock config entries.
- Prefer Bluetooth discovery and serial matching over manual MAC entry whenever possible.
- Preserve the richer battery-profile model; do not collapse it back to a simple 3-point curve.

## Repo Workflow

- Keep the repo HACS-ready: `hacs.json`, CI, Hassfest, and secret scanning should continue to pass.
- Update tests with behavior changes; protocol, config flow, and diagnostics coverage are all important here.
- Small commits are fine when they help keep the refactor organized.

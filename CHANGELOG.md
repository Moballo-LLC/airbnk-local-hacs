# Changelog

## Unreleased

## 1.0.2 - 2026-04-23

- Updated the Airbnk cloud client signature to match current app-version requirements when requesting verification codes
- Improved cloud error handling so server-side `info` messages surface in logs and tests instead of collapsing into a generic rejection
- Preserved the entered email address in the setup flow when verification-code requests fail, making retries less frustrating
- Clarified in the cloud setup UI that Airbnk cloud access is needed only for setup or bootstrap refresh and normal lock control remains local over Bluetooth
- Broadened Bluetooth discovery matching so locks can still be discovered when they advertise the Airbnk payload under alternate company IDs but keep the expected Airbnk service UUID or model/brand local name
- Clarified the docs and setup wording so both Airbnk- and WeHere-branded users can find the integration and know to search for `Airbnk BLE`

## 1.0.1 - 2026-04-23

- Fixed the Bluetooth auto-discovery setup dialog so the `Cloud` and `Manual` setup options render correctly instead of showing a blank menu
- Improved Bluetooth discovery naming so newly discovered locks show a more specific lock title during setup
- Normalized local brand assets for current Home Assistant custom-integration packaging and added brand-asset regression tests

## 1.0.0 - 2026-04-23

- Initial standalone `Airbnk BLE` custom integration scaffold
- Local BLE runtime ported from the original private Home Assistant component
- Cloud-assisted bootstrap flow, manual bootstrap flow, diagnostics, tests, and CI scaffolding
- Bluetooth auto-discovery and rediscovery support for connectable Airbnk locks
- Plus-address cloud login compatibility
- Public docs, branding, HACS packaging, and CI validation for first release

# Changelog

## Unreleased

## 1.0.4 - 2026-04-23

- Restored narrow Bluetooth auto-discovery matching for Airbnk / WeHere locks by matching the Airbnk vendor ID or the known Airbnk advert service UUID instead of requiring a stricter manufacturer payload prefix
- Removed the redundant `requests` manifest requirement so the custom integration only declares non-Core runtime dependencies
- Documented the remaining Home Assistant Core blockers in the repo guidance and `quality_scale.yaml`, including the future external async library extraction and brand migration path

## 1.0.3 - 2026-04-23

- Switched the Airbnk / WeHere cloud bootstrap flow onto an executor-backed HTTP transport, matching the older working integration style more closely than the previous `aiohttp` path
- Updated the cloud app signature used for verification-code requests and auth to `A_FD_2.1.8`, which the live Airbnk / WeHere endpoints no longer reject as an outdated app version
- Added retry handling for transient cloud transport failures during verification-code requests and authentication
- Sanitized cloud transport errors so timeout logs no longer echo the full request URL or the account email address
- Declared the runtime/test dependencies needed for the new cloud transport path

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

# Contributing

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements_test.txt
ruff check .
mypy custom_components/airbnk_ble
pytest
```

## Standards Notes

- Keep `custom_components/airbnk_ble/manifest.json` aligned with current Home Assistant custom-integration guidance.
- Do not add runtime requirements to the manifest when Home Assistant Core already ships them.
- Keep the repo HACS-valid first, while documenting any remaining Home Assistant Core blockers in `custom_components/airbnk_ble/quality_scale.yaml`.

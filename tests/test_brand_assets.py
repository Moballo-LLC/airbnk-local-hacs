"""Brand asset tests for Airbnk BLE."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

BRAND_DIR = Path("custom_components/airbnk_ble/brand")
SUPPORTED_FILES = {
    "icon.png",
    "icon@2x.png",
    "dark_icon.png",
    "dark_icon@2x.png",
    "logo.png",
    "logo@2x.png",
    "dark_logo.png",
    "dark_logo@2x.png",
}
EXPECTED_SIZES = {
    "icon.png": (256, 256),
    "dark_icon.png": (256, 256),
    "icon@2x.png": (512, 512),
    "dark_icon@2x.png": (512, 512),
}


def test_brand_assets_use_supported_home_assistant_filenames() -> None:
    """The brand folder should only contain documented asset filenames."""

    files = {path.name for path in BRAND_DIR.glob("*.png")}
    assert "icon.png" in files
    assert files <= SUPPORTED_FILES


def test_brand_icons_are_valid_pngs_with_expected_sizes() -> None:
    """The shipped icon assets should match the Home Assistant brand spec."""

    for name, expected_size in EXPECTED_SIZES.items():
        path = BRAND_DIR / name
        assert path.exists()
        with Image.open(path) as image:
            assert image.format == "PNG"
            assert image.size == expected_size
            assert image.mode in {"RGBA", "LA"}

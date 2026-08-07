"""
PySNES settings loader.

Settings are loaded from settings.json in the current working directory.
Missing keys fall back to defaults. Settings can also be passed directly
as a dict to PySNES() for programmatic use (e.g. tests).

Example settings.json:
{
    "headless": true,
    "rom": "roms/mygame.sfc"
}
"""

import json
from pathlib import Path

DEFAULTS = {
    "headless": False,
    "rom": None,
    "mesen_bin": (
        "submodules/Mesen2/bin/linux-x64/Release/linux-x64/publish/Mesen"
    ),
}

SETTINGS_FILE = "settings.json"


def load(path=None) -> dict:
    """Load settings from a JSON file, falling back to defaults for missing
    keys."""
    result = dict(DEFAULTS)
    settings_path = Path(path or SETTINGS_FILE)
    if settings_path.exists():
        with open(settings_path) as f:
            result.update(json.load(f))
    return result

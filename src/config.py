"""Read /config.json and surface settings to the rest of the app.

Thin wrapper for now — Phase 3 will grow this as more sections (heater
PID, thermistor calibration, transport selection) become consumed.

The file is loaded fresh on each accessor call so changes made via the
web API (PUT /config) take effect at the next read without an explicit
reload step.  Reads are cheap (small JSON, fast flash) so this is fine
for the few callers that exist.
"""

import json

CONFIG_PATH = "/config.json"

DEFAULT_DEVICE_NAME = "klipper-micro"
DEFAULT_QUICK_TEMPS = [45.0, 50.0, 55.0, 60.0]


def load():
    """Return the parsed config dict, or ``{}`` on any error.

    Never raises; missing or malformed config falls back to defaults so
    the device always boots into a usable state.
    """
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    return {}


def device_name():
    """Top-bar title.  Set via ``"device_name"`` in /config.json."""
    name = load().get("device_name")
    if isinstance(name, str) and name.strip():
        return name.strip()
    return DEFAULT_DEVICE_NAME


def quick_temps():
    """List of preset temperatures shown as one-tap buttons on the main screen.

    Configured via ``"quick_temps": [45, 50, 55, 60]`` in /config.json.
    Capped at 4 entries to fit the layout; defaults to 45/50/55/60.
    """
    raw = load().get("quick_temps")
    if isinstance(raw, list):
        out = []
        for v in raw:
            if isinstance(v, (int, float)) and 0 <= v <= 200:
                out.append(float(v))
        if out:
            return out[:4]
    return list(DEFAULT_QUICK_TEMPS)

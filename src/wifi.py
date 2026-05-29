"""WiFi connection helpers.

Wraps MicroPython's ``network.WLAN`` for use from main.py and the WiFi
settings screen.  All functions import ``network`` lazily so the module is
safely importable on CPython (it will just never find a real interface).

Credentials are persisted to ``/config.json`` under a ``"wifi"`` key.
"""

import json
import time

CONFIG_PATH = "/config.json"

# MicroPython scan() result tuple indices
_SCAN_SSID = 0
_SCAN_RSSI = 3


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sta():
    """Return an active STA WLAN interface."""
    import network  # MicroPython only
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        sta.active(True)
    return sta


def _decode(value):
    """Return *value* as a str; bytes are decoded as UTF-8."""
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", "replace")
    return value


# ---------------------------------------------------------------------------
# Status queries
# ---------------------------------------------------------------------------

def is_connected():
    """Return True if the STA interface is up and associated."""
    try:
        import network
        sta = network.WLAN(network.STA_IF)
        return sta.active() and sta.isconnected()
    except Exception:
        return False


def current_ssid():
    """Return the SSID of the current connection, or None."""
    try:
        sta = _sta()
        if sta.isconnected():
            return _decode(sta.config("essid"))
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan():
    """Scan for nearby access points.

    Returns a list of ``(ssid, rssi)`` tuples sorted by signal strength
    (strongest first).  Empty SSIDs and duplicates are suppressed.

    Blocks for ~2-3 s on ESP32.  The LVGL FreeRTOS task continues
    rendering during the scan; only Python callbacks are paused.
    """
    try:
        sta = _sta()
        results = sta.scan()
        seen = set()
        nets = []
        for r in results:
            ssid = _decode(r[_SCAN_SSID])
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            nets.append((ssid, r[_SCAN_RSSI]))
        nets.sort(key=lambda x: x[1], reverse=True)
        return nets
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def start_connect(ssid, password):
    """Begin connecting to *ssid*.

    Non-blocking: returns immediately.  Call :func:`check_connected` on a
    timer to poll for success.

    Returns True if the connect call was issued, False on error.
    """
    try:
        sta = _sta()
        if sta.isconnected():
            sta.disconnect()
            time.sleep(0.3)
        sta.connect(ssid, password)
        return True
    except Exception:
        return False


def check_connected():
    """Return True if the STA interface has successfully associated."""
    try:
        return _sta().isconnected()
    except Exception:
        return False


def disconnect():
    """Drop the current WiFi connection."""
    try:
        _sta().disconnect()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Credential persistence
# ---------------------------------------------------------------------------

def load_creds():
    """Load ``(ssid, password)`` from ``/config.json``.

    Returns ``(None, None)`` if the file is absent or has no ``wifi`` key.
    """
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
        w = cfg.get("wifi", {})
        return w.get("ssid"), w.get("password")
    except Exception:
        return None, None


def save_creds(ssid, password):
    """Write ``(ssid, password)`` into the ``wifi`` section of ``/config.json``.

    Preserves all other top-level keys.  Returns True on success.
    """
    try:
        try:
            with open(CONFIG_PATH) as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        cfg["wifi"] = {"ssid": ssid, "password": password}
        with open(CONFIG_PATH, "w") as f:
            json.dump(cfg, f)
        return True
    except Exception:
        return False

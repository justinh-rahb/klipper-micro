"""WiFi connection helpers.

Wraps MicroPython's ``network.WLAN`` for use from main.py and the WiFi
settings screen.  All functions import ``network`` lazily so the module is
safely importable on CPython (it will just never find a real interface).

Credentials are persisted to ``/config.json`` under a ``"wifi"`` key.

Logging
-------
Every public function prints a one-line ``[wifi]`` event to the REPL on
entry and on failure, so hooking ``mpremote connect`` while the device
runs gives a paper trail of what happened.  Errors are still caught (the
UI shouldn't crash on a transient WiFi failure), but the exception type
and message are logged before being swallowed — no more silent failures.
"""

import json
import sys
import time

CONFIG_PATH = "/config.json"
LOG_PATH = "/wifi.log"
LOG_MAX_BYTES = 8192   # truncate log when it grows beyond this

# MicroPython scan() result tuple indices
_SCAN_SSID = 0
_SCAN_RSSI = 3

# Tracks whether _sta() has activated the interface in this Python session.
# We add a one-shot 200 ms settle delay after the first activation so the
# very first scan() doesn't race the radio coming up.
_activated_at = None

# Cached scan results from preheat().  WiFi scan is reliable only BEFORE
# LVGL's framebuffer is set up — once LVGL is rendering, scan() blocks for
# 2-3 s then returns ESP_ERR_INVALID_ARG (0x0102), apparently due to a
# coexistence problem between LVGL DMA and WiFi DMA on plain ESP32.
# Workaround: we scan once at boot and cache the results.
_cached_networks = []
_cached_at = None

# network.STAT_* codes that we want human-readable names for.  Populated
# lazily on first failure so the module imports cleanly on CPython.
_STATUS_NAMES = None


def _status_name(code):
    """Return a short human description of a network.STAT_* code."""
    global _STATUS_NAMES
    if _STATUS_NAMES is None:
        try:
            import network
            _STATUS_NAMES = {
                network.STAT_IDLE: "idle",
                network.STAT_CONNECTING: "connecting",
                network.STAT_GOT_IP: "connected",
                network.STAT_NO_AP_FOUND: "no AP found",
                network.STAT_WRONG_PASSWORD: "wrong password",
                network.STAT_ASSOC_FAIL: "association failed",
                network.STAT_BEACON_TIMEOUT: "beacon timeout",
                network.STAT_HANDSHAKE_TIMEOUT: "handshake timeout",
                network.STAT_CONNECT_FAIL: "connect failed",
            }
        except Exception:
            _STATUS_NAMES = {}
    return _STATUS_NAMES.get(code, "code %d" % (code,))


def _log(msg):
    line = "[wifi] " + msg
    print(line)
    _log_to_file(line)


def _log_exc(prefix, exc):
    line = "[wifi] %s: %s: %s" % (prefix, type(exc).__name__, exc)
    print(line)
    _log_to_file(line)


def _log_to_file(line):
    """Append a line to /wifi.log; truncate if it grows too large."""
    try:
        # Cheap rotation: if the file is bigger than LOG_MAX_BYTES, replace
        # with just this line.  Keeps recent history without unbounded growth.
        try:
            import os
            size = os.stat(LOG_PATH)[6]
        except Exception:
            size = 0
        mode = "w" if size > LOG_MAX_BYTES else "a"
        with open(LOG_PATH, mode) as f:
            f.write(line + "\n")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _sta():
    """Return an active STA WLAN interface.

    First activation in a session blocks for ~200 ms after ``active(True)``
    so the radio has time to come up before the caller's first ``scan()``.
    Subsequent calls are immediate.

    **Heap ordering matters on plain ESP32.**  The WiFi driver allocates
    ~50 KB of contiguous heap on ``active(True)``; LVGL's framebuffer
    consumes ~150 KB.  Total RAM is ~520 KB and after firmware overhead
    only ~165 KB is free at fresh boot — not enough for both unless WiFi
    is brought up *before* LVGL.  See :func:`preheat`.
    """
    global _activated_at
    import gc
    import network  # MicroPython only
    sta = network.WLAN(network.STA_IF)
    if not sta.active():
        # Defrag before the big allocation so the WiFi driver has a
        # contiguous block to work with.
        gc.collect()
        free = gc.mem_free()
        _log("activating STA interface (heap free: %d B)" % free)
        sta.active(True)
        _activated_at = time.ticks_ms()
        # Block briefly so the radio is ready when the caller invokes scan().
        time.sleep_ms(200)
    return sta


def preheat(with_scan=True):
    """Activate the STA interface — and optionally scan once — before LVGL.

    Two reasons activation must happen at boot before ``display.init()``:

    1. **Activation memory**: ``network.WLAN.active(True)`` needs a
       ~50 KB contiguous heap block.  Once LVGL's framebuffer (~150 KB)
       is allocated, only ~15 KB remains free on plain ESP32 and the
       WiFi activation fails with ``OSError: WiFi Out of Memory``.

    2. **Scan coexistence**: even with WiFi pre-activated, calling
       ``sta.scan()`` after LVGL widgets are built fails with
       ``RuntimeError: Wifi Unknown Error 0x0102`` (ESP_ERR_INVALID_ARG)
       — apparently a DMA / scheduler conflict between the LVGL
       framebuffer pump and the WiFi scan.  Bisected on the de-dh
       LVGL9 build for the CYD.

    When *with_scan* is True we also scan during preheat and cache the
    result for later use by the WiFi screen; set False to skip the scan
    (saves ~2.5 s of boot time and avoids any side-effects the scan may
    have on subsequent peripheral init).
    """
    global _cached_networks, _cached_at
    try:
        _sta()  # activates the interface
    except Exception as e:
        _log_exc("preheat", e)
        return 0

    if not with_scan:
        _log("preheat: STA activated (no scan)")
        return 0

    # Now scan — this works because LVGL hasn't allocated yet.
    nets = scan()
    _cached_networks = nets
    _cached_at = time.time()
    _log("preheat: cached %d networks for the session" % len(nets))
    return len(nets)


def cached_networks():
    """Return the list of networks captured at boot.

    Each entry is an ``(ssid, rssi)`` tuple, strongest first.
    """
    return list(_cached_networks)


def cached_at():
    """Return the epoch time at which preheat() cached the networks,
    or ``None`` if preheat() hasn't run."""
    return _cached_at


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
    except Exception as e:
        _log_exc("is_connected", e)
        return False


def current_ssid():
    """Return the SSID of the current connection, or None."""
    try:
        sta = _sta()
        if sta.isconnected():
            return _decode(sta.config("essid"))
    except Exception as e:
        _log_exc("current_ssid", e)
    return None


def status_code():
    """Return the raw ``sta.status()`` integer, or ``None`` on error.

    Use :func:`status_text` for a human-readable form.
    """
    try:
        return _sta().status()
    except Exception as e:
        _log_exc("status_code", e)
        return None


def status_text():
    """Human-readable form of :func:`status_code`."""
    c = status_code()
    return _status_name(c) if c is not None else "unavailable"


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def scan():
    """Scan for nearby access points.

    Returns a list of ``(ssid, rssi)`` tuples sorted by signal strength
    (strongest first).  Empty SSIDs and duplicates are suppressed.

    **Blocks for ~2-3 s on ESP32**.  Callers on the LVGL thread should
    schedule this via :func:`lv.timer_create` so the screen renders first;
    see ``ui/screens/wifi.py``.
    """
    import gc
    try:
        sta = _sta()
    except Exception as e:
        _log_exc("scan/_sta", e)
        return []

    # Defragment before scan so result allocations have a contiguous block.
    gc.collect()
    free_before = gc.mem_free()
    try:
        is_active = sta.active()
        status = sta.status()
    except Exception as e:
        is_active = "?"
        status = "?"
        _log_exc("scan/state-probe", e)

    _log("scan() begin: active=%s status=%s heap=%d" %
         (is_active, status, free_before))
    t0 = time.ticks_ms()

    try:
        results = sta.scan()
        elapsed = time.ticks_diff(time.ticks_ms(), t0)
        _log("scan() got %d raw results in %d ms" % (len(results), elapsed))
        seen = set()
        nets = []
        for r in results:
            ssid = _decode(r[_SCAN_SSID])
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            nets.append((ssid, r[_SCAN_RSSI]))
        nets.sort(key=lambda x: x[1], reverse=True)
        _log("scan() found %d unique networks" % (len(nets),))
        return nets
    except Exception as e:
        elapsed = time.ticks_diff(time.ticks_ms(), t0)
        _log_exc("scan(after %d ms)" % elapsed, e)
        return []


# ---------------------------------------------------------------------------
# Connection management
# ---------------------------------------------------------------------------

def start_connect(ssid, password):
    """Begin connecting to *ssid*.  Non-blocking.

    Returns True if the connect call was issued, False on error.

    The caller should poll :func:`check_connected` (or read
    :func:`status_text`) periodically to determine the outcome.
    """
    _log("start_connect ssid=%r" % (ssid,))
    try:
        sta = _sta()
        if sta.isconnected():
            sta.disconnect()
            # MicroPython needs a brief pause for the disconnect to settle
            # before a new connect() will reliably succeed.  300 ms is
            # blocking but only happens on re-association, not first boot.
            time.sleep(0.3)
        sta.connect(ssid, password)
        return True
    except Exception as e:
        _log_exc("start_connect", e)
        return False


def check_connected():
    """Return True if the STA interface has successfully associated."""
    try:
        return _sta().isconnected()
    except Exception as e:
        _log_exc("check_connected", e)
        return False


def disconnect():
    """Drop the current WiFi connection."""
    _log("disconnect()")
    try:
        _sta().disconnect()
    except Exception as e:
        _log_exc("disconnect", e)


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
    except Exception as e:
        _log_exc("load_creds", e)
        return None, None


def save_creds(ssid, password):
    """Write ``(ssid, password)`` into the ``wifi`` section of ``/config.json``.

    Preserves all other top-level keys.  Returns True on success.
    """
    _log("save_creds ssid=%r" % (ssid,))
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
    except Exception as e:
        _log_exc("save_creds", e)
        return False

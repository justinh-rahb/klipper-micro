"""Persistent application entry point.

MicroPython executes this file automatically after boot.py on every reset.
Brings up the LVGL display and launches the main status screen.

Phase 3 note
------------
MockState currently drives the UI so the interface can be exercised without
a wired Klipper MCU.  When Phase 3 lands, replace MockState with the real
``app.State`` that connects to the MCU via the transport configured in
``/config.json`` and bridges live temperature/heater data into the UI.
"""

import sys
import time


# ---------------------------------------------------------------------------
# Panic banner — rendered if anything in main() raises.
# Defined before main() so it is available even if the import inside main
# fails partway through.
# ---------------------------------------------------------------------------

def _show_panic(msg):
    """Draw a red error message on the active LVGL screen."""
    try:
        import lvgl as lv  # type: ignore[import-not-found]
        scr = lv.screen_active()
        scr.set_style_bg_color(lv.color_hex(0x1A0000), 0)
        scr.set_style_bg_opa(255, 0)
        lbl = lv.label(scr)
        lbl.set_text(msg)
        lbl.set_style_text_color(lv.color_hex(0xFF4444), 0)
        lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        lbl.set_width(300)
        lbl.set_long_mode(lv.label.LONG_MODE.WRAP)
        lbl.center()
    except Exception:
        pass  # LVGL not up yet; exception already printed to REPL


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def main():
    # --- Programming window ------------------------------------------------
    # Sleep briefly so mpremote can enter raw REPL before LVGL starts.
    # Once display.init() runs the FreeRTOS task handler intercepts Ctrl+C
    # and the REPL becomes unreachable.  3 s is imperceptible at boot but
    # long enough for upload.sh to connect on any machine.
    time.sleep(3)

    # --- Display + touch ---------------------------------------------------
    from ui import display
    display.init(backlight_pct=80, with_touch=True)

    # --- State -------------------------------------------------------------
    from ui.mock_state import MockState
    state = MockState()
    state.set_mcu_connected(False)
    state.set_wifi_connected(False)

    # Load presentation defaults from /config.json (device name, quick-temp
    # presets).  Errors are silent: invalid/missing config falls back to
    # MockState's own defaults so the device always boots.
    try:
        import config as _config
        state.set_device_name(_config.device_name())
        state.set_quick_temps(_config.quick_temps())
    except Exception:
        pass

    # --- WiFi (best-effort at boot) ----------------------------------------
    # Load saved credentials from /config.json and attempt to connect.
    # Non-critical: if this fails the app still boots; the user can configure
    # WiFi via the W button on the main screen.
    try:
        import wifi as _wifi
        ssid, password = _wifi.load_creds()
        if ssid and password:
            _wifi.start_connect(ssid, password)
            # Poll for up to 10 s before continuing; display init already ran
            # so LVGL keeps the screen alive during the wait.
            deadline = time.time() + 10
            while time.time() < deadline:
                if _wifi.check_connected():
                    state.set_wifi_connected(True)
                    break
                time.sleep(0.5)
    except Exception:
        pass  # no wifi module on CPython / connect error — silently skip

    # --- Screens -----------------------------------------------------------
    from ui.manager import ScreenManager
    from ui.screens.main import MainScreen
    mgr = ScreenManager()
    mgr.show(MainScreen, state=state)

    # --- Keep alive --------------------------------------------------------
    # LVGL's task handler (TaskHandler, started inside display.init) runs
    # from a FreeRTOS background task in the de-dh firmware, so this loop
    # only needs to prevent main() from returning.
    while True:
        time.sleep(1)


# ---------------------------------------------------------------------------
# Top-level guard
# ---------------------------------------------------------------------------

try:
    main()
except Exception as exc:
    sys.print_exception(exc)
    _show_panic("BOOT ERROR\n\n" + str(exc))
    # Stay alive so the panic banner remains visible; don't tight-loop.
    while True:
        time.sleep(5)

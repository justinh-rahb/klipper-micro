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
        lbl.set_long_mode(lv.label.LONG.WRAP)
        lbl.center()
    except Exception:
        pass  # LVGL not up yet; exception already printed to REPL


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------

def main():
    # --- Display + touch ---------------------------------------------------
    from ui import display
    display.init(backlight_pct=80, with_touch=True)

    # --- State -------------------------------------------------------------
    from ui.mock_state import MockState
    state = MockState()
    # Default: not yet connected to MCU or WiFi.
    # Phase 3 will replace this with real device state.
    state.set_mcu_connected(False)
    state.set_wifi_connected(False)

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

"""Display + LVGL smoke test.

Brings up the panel, draws a centered label, and idles. Used to verify the
display init sequence works on this specific CYD before we layer screens on
top.

Run with:
    mpremote connect port:/dev/tty.usbserial-3110 run src/ui_smoketest.py
"""

import time
import lvgl as lv  # type: ignore[import-not-found]

from ui import display


def main():
    # Display only — touch comes online once the main app is ready.
    display.init(backlight_pct=80, with_touch=False)
    scr = lv.screen_active()

    # Background colour: dark grey
    scr.set_style_bg_color(lv.color_hex(0x1A1A1A), 0)
    scr.set_style_bg_opa(255, 0)

    # Centered label
    label = lv.label(scr)
    label.set_text("klipper-micro\nLVGL OK")
    label.set_style_text_color(lv.color_hex(0xFFFFFF), 0)
    label.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
    label.center()

    # The lvgl_micropython firmware runs LVGL's task handler from a
    # background FreeRTOS task, so we just keep the Python script alive.
    print("display smoketest running; reset the board to exit")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()

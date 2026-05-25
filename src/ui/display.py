"""Display + touch bootstrap for the CYD running de-dh's LVGL9 firmware.

Pin assignments are specific to the ESP32-2432S028R; see docs/HARDWARE.md.
The high-level lvgl_micropython modules (ili9341, xpt2046, lcd_bus) do all
the SPI plumbing for us.

Call ``init()`` once during boot. After that, LVGL is alive and any code can
use ``lv.screen_active()`` to draw on it.
"""

import lvgl as lv  # type: ignore[import-not-found]
import lcd_bus  # type: ignore[import-not-found]
import ili9341  # type: ignore[import-not-found]
import xpt2046  # type: ignore[import-not-found]
import task_handler  # type: ignore[import-not-found]
import machine


# Display pins (SPI host 1)
DISPLAY_MOSI = 13
DISPLAY_MISO = 12
DISPLAY_SCK = 14
DISPLAY_DC = 2
DISPLAY_CS = 15
DISPLAY_BACKLIGHT = 21
DISPLAY_FREQ = 24_000_000

# Touch pins (SPI host 2)
TOUCH_MOSI = 32
TOUCH_MISO = 39
TOUCH_SCK = 25
TOUCH_CS = 33
TOUCH_FREQ = 2_000_000

# Logical resolution after rotation. Native panel is 240x320 portrait;
# we run landscape so the screen is wider than tall — better for a temperature
# readout + side controls.
WIDTH = 320
HEIGHT = 240


_display = None
_touch = None
_task_handler = None


def init(backlight_pct=80, with_touch=True):
    """Bring up display and (optionally) touch.

    Idempotent — subsequent calls return the cached instances.

    Set ``with_touch=False`` to skip touch init; useful early in bring-up or
    on a board with a damaged touch panel.
    """
    global _display, _touch, _task_handler
    if _display is not None:
        return _display, _touch

    spi_bus = machine.SPI.Bus(
        host=1, mosi=DISPLAY_MOSI, miso=DISPLAY_MISO, sck=DISPLAY_SCK
    )
    display_bus = lcd_bus.SPIBus(
        spi_bus=spi_bus, freq=DISPLAY_FREQ, dc=DISPLAY_DC, cs=DISPLAY_CS
    )
    _display = ili9341.ILI9341(
        data_bus=display_bus,
        display_width=WIDTH,
        display_height=HEIGHT,
        backlight_pin=DISPLAY_BACKLIGHT,
        backlight_on_state=ili9341.STATE_PWM,
        color_space=lv.COLOR_FORMAT.RGB565,
        color_byte_order=ili9341.BYTE_ORDER_BGR,
        rgb565_byte_swap=1,
    )
    # Landscape orientation; rotation table from the de-dh CYD test script.
    _display._ORIENTATION_TABLE = (0x20, 0x0, 0x0, 0x0)
    _display.set_rotation(lv.DISPLAY_ROTATION._0)
    _display.set_power(True)
    _display.init(1)
    _display.set_backlight(backlight_pct)

    if with_touch:
        indev_bus = machine.SPI.Bus(
            host=2, mosi=TOUCH_MOSI, miso=TOUCH_MISO, sck=TOUCH_SCK
        )
        indev_device = machine.SPI.Device(
            spi_bus=indev_bus, freq=TOUCH_FREQ, cs=TOUCH_CS
        )
        _touch = xpt2046.XPT2046(device=indev_device)
        if not _touch.is_calibrated:
            # The xpt2046 driver shows its own LVGL-rendered calibration UI;
            # the user taps four corner targets.
            _touch.calibrate()
            _touch._cal.save()

    # task_handler.TaskHandler() registers the periodic LVGL processing job.
    # Without this LVGL never flushes pixels — the de-dh test script depends
    # on it and so do we. Construct once; reference held so it doesn't get
    # garbage-collected.
    _task_handler = task_handler.TaskHandler()

    return _display, _touch


def get():
    """Return (display, touch). Raises if init() hasn't been called."""
    if _display is None:
        raise RuntimeError("display.init() not called")
    return _display, _touch

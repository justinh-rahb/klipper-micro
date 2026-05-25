"""Shared colors, fonts, and small style helpers.

Keeping them centralised so we can re-skin without hunting through every
screen file.
"""

import lvgl as lv  # type: ignore[import-not-found]


# Palette — dark UI, bright accents.
COLOR_BG = 0x121212
COLOR_PANEL = 0x1E1E1E
COLOR_BORDER = 0x2A2A2A
COLOR_TEXT = 0xFFFFFF
COLOR_TEXT_DIM = 0x9E9E9E
COLOR_ACCENT = 0xFFC107      # amber — primary brand colour for klipper-micro
COLOR_HEATING = 0xFF5722     # warm orange
COLOR_HOLDING = 0x4CAF50     # green
COLOR_OVERSHOOT = 0xFF1744   # red
COLOR_OFF = 0x616161
COLOR_OK = 0x4CAF50
COLOR_ERROR = 0xF44336
COLOR_FAN = 0x29B6F6         # light blue


def font(size):
    """Return the Montserrat font at the given size, or None if not built in."""
    attr = "font_montserrat_%d" % (size,)
    return getattr(lv, attr, None)


def apply_panel_style(obj, radius=8):
    """Standard panel styling: dark background, subtle border, rounded."""
    obj.set_style_bg_color(lv.color_hex(COLOR_PANEL), 0)
    obj.set_style_bg_opa(255, 0)
    obj.set_style_border_color(lv.color_hex(COLOR_BORDER), 0)
    obj.set_style_border_width(1, 0)
    obj.set_style_radius(radius, 0)
    obj.set_style_pad_all(8, 0)


def apply_screen_style(scr):
    scr.set_style_bg_color(lv.color_hex(COLOR_BG), 0)
    scr.set_style_bg_opa(255, 0)
    scr.set_style_pad_all(0, 0)


def heater_state_color(state):
    return {
        "off": COLOR_OFF,
        "heating": COLOR_HEATING,
        "holding": COLOR_HOLDING,
        "overshoot": COLOR_OVERSHOOT,
    }.get(state, COLOR_TEXT_DIM)

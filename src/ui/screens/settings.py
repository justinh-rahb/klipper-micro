"""Settings screen — PID tuning and limits.

Layout (320x240 landscape):

    +-------------------------------------------------+
    | < back   Settings                               |
    +-------------------------------------------------+
    | Kp        22.20       [ - ] [ + ]               |
    | Ki         1.08       [ - ] [ + ]               |
    | Kd       114.00       [ - ] [ + ]               |
    | max °C    80.0        [ - ] [ + ]               |
    +-------------------------------------------------+

Each row is a fixed-height label + value + two stepper buttons. Tap the
back button to return to the main screen.
"""

import lvgl as lv  # type: ignore[import-not-found]

from .. import theme


ROW_HEIGHT = 40
ROW_TOP = 32  # below the status bar
LABEL_W = 70
VALUE_W = 110
BTN_W = 50
BTN_GAP = 4


class SettingsScreen:
    def __init__(self, state, manager=None):
        self.state = state
        self.manager = manager
        self.scr = lv.screen_active()
        theme.apply_screen_style(self.scr)
        self._rows = []
        self._build()

    def dispose(self):
        # No timer on this screen; nothing to do.
        pass

    # ------------------------------------------------------------------

    def _build(self):
        self._build_header()
        self._build_row(0, "Kp", "pid_kp", step=1.0, fmt="%.2f")
        self._build_row(1, "Ki", "pid_ki", step=0.1, fmt="%.2f")
        self._build_row(2, "Kd", "pid_kd", step=5.0, fmt="%.1f")
        self._build_row(3, "max°C", "max_temp", step=5.0, fmt="%.0f")

    def _build_header(self):
        bar = lv.obj(self.scr)
        bar.set_size(320, 28)
        bar.set_pos(0, 0)
        bar.set_style_bg_color(lv.color_hex(theme.COLOR_PANEL), 0)
        bar.set_style_bg_opa(255, 0)
        bar.set_style_border_width(0, 0)
        bar.set_style_radius(0, 0)
        bar.set_style_pad_all(2, 0)

        back = lv.button(bar)
        back.set_size(50, 22)
        back.align(lv.ALIGN.LEFT_MID, 4, 0)
        bl = lv.label(back)
        bl.set_text("< back")
        bl.center()
        f = theme.font(12)
        if f is not None:
            bl.set_style_text_font(f, 0)
        back.add_event_cb(self._on_back, lv.EVENT.CLICKED, None)

        title = lv.label(bar)
        title.set_text("Settings")
        title.set_style_text_color(lv.color_hex(theme.COLOR_ACCENT), 0)
        f = theme.font(14)
        if f is not None:
            title.set_style_text_font(f, 0)
        title.center()

    def _build_row(self, idx, label_text, attr, step, fmt):
        y = ROW_TOP + idx * (ROW_HEIGHT + 4)

        row = lv.obj(self.scr)
        row.set_size(316, ROW_HEIGHT)
        row.set_pos(2, y)
        theme.apply_panel_style(row, radius=6)
        row.set_style_pad_all(4, 0)

        name = lv.label(row)
        name.set_text(label_text)
        name.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(14)
        if f is not None:
            name.set_style_text_font(f, 0)
        name.align(lv.ALIGN.LEFT_MID, 2, 0)

        value = lv.label(row)
        value.set_style_text_color(lv.color_hex(theme.COLOR_TEXT), 0)
        f = theme.font(18) or theme.font(16)
        if f is not None:
            value.set_style_text_font(f, 0)
        value.align(lv.ALIGN.LEFT_MID, LABEL_W + 12, 0)
        value.set_text(fmt % (getattr(self.state, attr),))

        minus = lv.button(row)
        minus.set_size(BTN_W, ROW_HEIGHT - 8)
        minus.align(lv.ALIGN.RIGHT_MID, -(BTN_W + BTN_GAP + 2), 0)
        ml = lv.label(minus)
        ml.set_text("-")
        ml.center()

        plus = lv.button(row)
        plus.set_size(BTN_W, ROW_HEIGHT - 8)
        plus.align(lv.ALIGN.RIGHT_MID, -2, 0)
        pl = lv.label(plus)
        pl.set_text("+")
        pl.center()

        spec = (attr, step, fmt, value)
        # Use closures so each row has its own state reference
        minus.add_event_cb(
            lambda e, s=spec: self._step(s, -1), lv.EVENT.CLICKED, None
        )
        plus.add_event_cb(
            lambda e, s=spec: self._step(s, +1), lv.EVENT.CLICKED, None
        )
        self._rows.append(spec)

    # ------------------------------------------------------------------

    def _step(self, spec, direction):
        attr, step, fmt, value_lbl = spec
        cur = getattr(self.state, attr)
        new = cur + step * direction
        if new < 0:
            new = 0
        setattr(self.state, attr, new)
        value_lbl.set_text(fmt % (new,))

    def _on_back(self, _evt):
        if self.manager is None:
            return
        from .main import MainScreen
        self.manager.show(MainScreen, state=self.state)

"""Setpoint adjustment modal.

Big touch-friendly stepper that takes over the screen while the user dials
in a target temperature.  The current working value is shown in huge digits
between two rows of step buttons:

    +-----------------------------------------------+
    | x  cancel       Set target              OK    |  28
    +-----------------------------------------------+
    |                                               |
    |   [   -10   ]              [   -1   ]         |  56
    |                                               |
    |                  60                           |
    |                   °C                          |
    |                                               |
    |   [   +10   ]              [   +1   ]         |  56
    +-----------------------------------------------+

Step buttons fire both LV_EVENT_CLICKED (tap → single step) and
LV_EVENT_LONG_PRESSED_REPEAT (hold → continuous steps), so values can be
dialled in quickly without spam-tapping.

The working value lives in `self._value` and is only committed to
`state.set_target()` on OK.  Cancel discards.
"""

import lvgl as lv  # type: ignore[import-not-found]

from .. import theme


HEADER_H = 28
BTN_W = 110
BTN_H = 56
ROW_TOP_Y = 36
ROW_BOTTOM_Y = 240 - BTN_H - 4   # 180
LEFT_X = 20
RIGHT_X = 320 - BTN_W - 20       # 190


class SetpointScreen:
    def __init__(self, state, manager=None):
        self.state = state
        self.manager = manager
        self.scr = lv.screen_active()
        theme.apply_screen_style(self.scr)

        # Working copy — committed to state only when OK is tapped.
        self._value = float(state.target)
        self._max = float(getattr(state, "max_temp", 100))
        self._min = 0.0

        self._build()
        self._refresh()

    def dispose(self):
        pass

    # ------------------------------------------------------------------

    def _build(self):
        self._build_header()
        self._build_value()
        # Decrement row (above the value)
        self._mk_step(LEFT_X,  ROW_TOP_Y, "-10", -10)
        self._mk_step(RIGHT_X, ROW_TOP_Y,  "-1",  -1)
        # Increment row (below the value, thumb-reachable)
        self._mk_step(LEFT_X,  ROW_BOTTOM_Y, "+10", +10)
        self._mk_step(RIGHT_X, ROW_BOTTOM_Y,  "+1",  +1)

    def _build_header(self):
        bar = lv.obj(self.scr)
        bar.set_size(320, HEADER_H)
        bar.set_pos(0, 0)
        bar.set_style_bg_color(lv.color_hex(theme.COLOR_PANEL), 0)
        bar.set_style_bg_opa(255, 0)
        bar.set_style_border_width(0, 0)
        bar.set_style_radius(0, 0)
        bar.set_style_pad_all(2, 0)

        cancel = lv.button(bar)
        cancel.set_size(76, 22)
        cancel.align(lv.ALIGN.LEFT_MID, 4, 0)
        cl = lv.label(cancel)
        cl.set_text(lv.SYMBOL.CLOSE + " cancel")
        cl.center()
        f = theme.font(12)
        if f:
            cl.set_style_text_font(f, 0)
        cancel.add_event_cb(self._on_cancel, lv.EVENT.CLICKED, None)

        title = lv.label(bar)
        title.set_text("Set target")
        title.set_style_text_color(lv.color_hex(theme.COLOR_ACCENT), 0)
        f = theme.font(14)
        if f:
            title.set_style_text_font(f, 0)
        title.center()

        ok = lv.button(bar)
        ok.set_size(56, 22)
        ok.align(lv.ALIGN.RIGHT_MID, -4, 0)
        ol = lv.label(ok)
        ol.set_text(lv.SYMBOL.OK + " OK")
        ol.center()
        f = theme.font(12)
        if f:
            ol.set_style_text_font(f, 0)
        ok.add_event_cb(self._on_ok, lv.EVENT.CLICKED, None)

    def _build_value(self):
        # Centered between the two button rows
        self._val_lbl = lv.label(self.scr)
        self._val_lbl.set_text("--")
        self._val_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT), 0)
        f = theme.font(48) or theme.font(40) or theme.font(36)
        if f:
            self._val_lbl.set_style_text_font(f, 0)
        self._val_lbl.set_width(320)
        self._val_lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        self._val_lbl.set_pos(0, 100)

        self._unit_lbl = lv.label(self.scr)
        self._unit_lbl.set_text("°C")
        self._unit_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(18) or theme.font(16)
        if f:
            self._unit_lbl.set_style_text_font(f, 0)
        self._unit_lbl.set_width(320)
        self._unit_lbl.set_style_text_align(lv.TEXT_ALIGN.CENTER, 0)
        self._unit_lbl.set_pos(0, 152)

    def _mk_step(self, x, y, label, delta):
        btn = lv.button(self.scr)
        btn.set_size(BTN_W, BTN_H)
        btn.set_pos(x, y)
        lbl = lv.label(btn)
        lbl.set_text(label)
        lbl.center()
        f = theme.font(28) or theme.font(24) or theme.font(20)
        if f:
            lbl.set_style_text_font(f, 0)
        # Tap → single step
        btn.add_event_cb(
            lambda e, d=delta: self._step(d), lv.EVENT.CLICKED, None
        )
        # Hold → repeat at LVGL's long-press repeat rate (~100 ms default)
        btn.add_event_cb(
            lambda e, d=delta: self._step(d), lv.EVENT.LONG_PRESSED_REPEAT, None
        )

    # ------------------------------------------------------------------

    def _step(self, delta):
        new = self._value + delta
        if new < self._min:
            new = self._min
        if new > self._max:
            new = self._max
        if new != self._value:
            self._value = new
            self._refresh()

    def _refresh(self):
        if self._value <= 0:
            self._val_lbl.set_text("OFF")
        else:
            self._val_lbl.set_text("%d" % int(round(self._value)))

    # ------------------------------------------------------------------

    def _on_ok(self, _evt):
        self.state.set_target(self._value)
        if self.manager:
            from .main import MainScreen
            self.manager.show(MainScreen, state=self.state)

    def _on_cancel(self, _evt):
        if self.manager:
            from .main import MainScreen
            self.manager.show(MainScreen, state=self.state)

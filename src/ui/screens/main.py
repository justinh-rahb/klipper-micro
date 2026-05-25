"""Main status screen.

Layout (320x240 landscape):

    +-------------------------------------------------+
    | klipper-micro                          [W] [M]  |  status bar
    +-----------------------------+-------------------+
    |                             |  SET    60 °C    |
    |     42.3                    |                   |
    |       °C                    |  [ -- ]   [ ++ ]  |
    |                             |                   |
    |  ● heating                  |  FAN   [###---]   |
    +-----------------------------+-------------------+

The screen polls ``state`` on a timer and refreshes the affected widgets.
Touch on either temp side opens setpoint adjustment; bottom-right region
hosts fan control.
"""

import lvgl as lv  # type: ignore[import-not-found]

from .. import theme


STATUS_HEIGHT = 24
LEFT_WIDTH = 195
PADDING = 4


class MainScreen:
    REFRESH_MS = 250  # quarter-second update is plenty for thermal data

    def __init__(self, state, manager=None):
        self.state = state
        self.manager = manager
        # Use the currently active screen instead of constructing a new one —
        # constructing screens before LVGL's task handler is fully warm has
        # crashed the firmware in testing.
        self.scr = lv.screen_active()
        theme.apply_screen_style(self.scr)
        self._build()
        self._refresh(None)
        # Timer registers AFTER initial build so the first refresh runs from
        # the foreground.
        self._timer = lv.timer_create(self._refresh, self.REFRESH_MS, None)

    def dispose(self):
        if self._timer is not None:
            self._timer.delete()
            self._timer = None

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def _build(self):
        self._build_status_bar()
        self._build_temp_panel()
        self._build_control_panel()

    def _build_status_bar(self):
        bar = lv.obj(self.scr)
        bar.set_size(320, STATUS_HEIGHT)
        bar.set_pos(0, 0)
        bar.set_style_bg_color(lv.color_hex(theme.COLOR_PANEL), 0)
        bar.set_style_bg_opa(255, 0)
        bar.set_style_border_width(0, 0)
        bar.set_style_radius(0, 0)
        bar.set_style_pad_all(2, 0)

        title = lv.label(bar)
        title.set_text("klipper-micro")
        title.set_style_text_color(lv.color_hex(theme.COLOR_ACCENT), 0)
        f = theme.font(14)
        if f is not None:
            title.set_style_text_font(f, 0)
        title.align(lv.ALIGN.LEFT_MID, 6, 0)

        self.wifi_dot = lv.label(bar)
        self.wifi_dot.set_text("W")
        self.wifi_dot.set_style_text_color(lv.color_hex(theme.COLOR_OFF), 0)
        self.wifi_dot.align(lv.ALIGN.RIGHT_MID, -36, 0)

        self.mcu_dot = lv.label(bar)
        self.mcu_dot.set_text("M")
        self.mcu_dot.set_style_text_color(lv.color_hex(theme.COLOR_OFF), 0)
        self.mcu_dot.align(lv.ALIGN.RIGHT_MID, -56, 0)

        # Settings button — small gear-style label in the corner
        settings_btn = lv.button(bar)
        settings_btn.set_size(40, 20)
        settings_btn.align(lv.ALIGN.RIGHT_MID, -2, 0)
        sl = lv.label(settings_btn)
        sl.set_text("SET")
        sl.center()
        f = theme.font(10) or theme.font(12)
        if f is not None:
            sl.set_style_text_font(f, 0)
        settings_btn.add_event_cb(self._on_settings, lv.EVENT.CLICKED, None)

    def _build_temp_panel(self):
        panel = lv.obj(self.scr)
        panel.set_size(LEFT_WIDTH, 240 - STATUS_HEIGHT - PADDING)
        panel.set_pos(PADDING, STATUS_HEIGHT + PADDING)
        theme.apply_panel_style(panel)
        panel.set_style_pad_all(4, 0)

        # Big temperature
        self.temp_lbl = lv.label(panel)
        self.temp_lbl.set_text("--.-")
        self.temp_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT), 0)
        big = theme.font(48) or theme.font(40) or theme.font(36)
        if big is not None:
            self.temp_lbl.set_style_text_font(big, 0)
        self.temp_lbl.align(lv.ALIGN.TOP_MID, 0, 4)

        self.unit_lbl = lv.label(panel)
        self.unit_lbl.set_text("°C")
        self.unit_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(20)
        if f is not None:
            self.unit_lbl.set_style_text_font(f, 0)
        self.unit_lbl.align_to(self.temp_lbl, lv.ALIGN.OUT_BOTTOM_MID, 0, -8)

        # Heater state row
        self.state_lbl = lv.label(panel)
        self.state_lbl.set_text("●  off")
        self.state_lbl.set_style_text_color(lv.color_hex(theme.COLOR_OFF), 0)
        f = theme.font(16)
        if f is not None:
            self.state_lbl.set_style_text_font(f, 0)
        self.state_lbl.align(lv.ALIGN.BOTTOM_LEFT, 4, -4)

    def _build_control_panel(self):
        right_x = LEFT_WIDTH + PADDING * 2
        right_w = 320 - right_x - PADDING
        panel = lv.obj(self.scr)
        panel.set_size(right_w, 240 - STATUS_HEIGHT - PADDING)
        panel.set_pos(right_x, STATUS_HEIGHT + PADDING)
        theme.apply_panel_style(panel)
        panel.set_style_pad_all(4, 0)

        # SET label + target value
        set_caption = lv.label(panel)
        set_caption.set_text("SET")
        set_caption.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f is not None:
            set_caption.set_style_text_font(f, 0)
        set_caption.align(lv.ALIGN.TOP_LEFT, 2, 2)

        self.target_lbl = lv.label(panel)
        self.target_lbl.set_text("--")
        self.target_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT), 0)
        f = theme.font(28) or theme.font(24)
        if f is not None:
            self.target_lbl.set_style_text_font(f, 0)
        self.target_lbl.align(lv.ALIGN.TOP_MID, 0, 18)

        # -- / ++ buttons for setpoint
        self.minus_btn = lv.button(panel)
        self.minus_btn.set_size(48, 40)
        self.minus_btn.align(lv.ALIGN.LEFT_MID, 2, 0)
        ml = lv.label(self.minus_btn)
        ml.set_text("-5")
        ml.center()
        self.minus_btn.add_event_cb(self._on_minus, lv.EVENT.CLICKED, None)

        self.plus_btn = lv.button(panel)
        self.plus_btn.set_size(48, 40)
        self.plus_btn.align(lv.ALIGN.RIGHT_MID, -2, 0)
        pl = lv.label(self.plus_btn)
        pl.set_text("+5")
        pl.center()
        self.plus_btn.add_event_cb(self._on_plus, lv.EVENT.CLICKED, None)

        # FAN bar
        fan_caption = lv.label(panel)
        fan_caption.set_text("FAN")
        fan_caption.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f is not None:
            fan_caption.set_style_text_font(f, 0)
        fan_caption.align(lv.ALIGN.BOTTOM_LEFT, 2, -22)

        self.fan_bar = lv.bar(panel)
        self.fan_bar.set_size(right_w - 12, 14)
        self.fan_bar.set_range(0, 100)
        self.fan_bar.set_value(0, 0)
        self.fan_bar.set_style_bg_color(lv.color_hex(theme.COLOR_BORDER), 0)
        self.fan_bar.set_style_bg_color(
            lv.color_hex(theme.COLOR_FAN), lv.PART.INDICATOR
        )
        self.fan_bar.set_style_bg_opa(255, lv.PART.INDICATOR)
        self.fan_bar.align(lv.ALIGN.BOTTOM_MID, 0, -2)
        # Tap the fan bar to cycle 0 → 50 → 100 → 0
        self.fan_bar.add_flag(lv.obj.FLAG.CLICKABLE)
        self.fan_bar.add_event_cb(self._on_fan, lv.EVENT.CLICKED, None)

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_minus(self, _evt):
        self.state.set_target(max(0.0, self.state.target - 5.0))
        self._refresh(None)

    def _on_plus(self, _evt):
        self.state.set_target(self.state.target + 5.0)
        self._refresh(None)

    def _on_settings(self, _evt):
        if self.manager is None:
            return
        # Lazy import to avoid a circular reference between screens
        from .settings import SettingsScreen
        self.manager.show(SettingsScreen, state=self.state)

    def _on_fan(self, _evt):
        cur = self.state.fan_speed
        if cur < 0.25:
            self.state.set_fan(0.5)
        elif cur < 0.75:
            self.state.set_fan(1.0)
        else:
            self.state.set_fan(0.0)
        self._refresh(None)

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _refresh(self, _timer):
        temp = self.state.temperature
        target = self.state.target
        state_name = self.state.heater_state
        fan = self.state.fan_speed
        mcu_ok = self.state.mcu_connected
        wifi_ok = self.state.wifi_connected

        self.temp_lbl.set_text("%.1f" % (temp,))
        if target > 0:
            self.target_lbl.set_text("%d °C" % (int(round(target)),))
        else:
            self.target_lbl.set_text("OFF")

        self.state_lbl.set_text("●  " + state_name)
        self.state_lbl.set_style_text_color(
            lv.color_hex(theme.heater_state_color(state_name)), 0
        )

        self.fan_bar.set_value(int(fan * 100), 0)

        self.mcu_dot.set_style_text_color(
            lv.color_hex(theme.COLOR_OK if mcu_ok else theme.COLOR_ERROR), 0
        )
        self.wifi_dot.set_style_text_color(
            lv.color_hex(theme.COLOR_OK if wifi_ok else theme.COLOR_OFF), 0
        )

    # ------------------------------------------------------------------

    def show(self):
        # When using screen_active() in __init__, there's nothing to load.
        pass

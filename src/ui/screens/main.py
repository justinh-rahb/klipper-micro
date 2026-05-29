"""Main status screen.

Layout (320x240 landscape):

    +-------------------------------------------------+
    | klipper-micro                  [!]   [W]   [⚙]  |  status bar
    +-----------------------------+-------------------+
    |                             |  SET              |
    |     42.3                    |   60              |  ← tap to open
    |       °C                    |   °C                  setpoint picker
    |                             |                   |
    |  ● heating                  |  FAN  [###---]    |
    +-----------------------------+-------------------+

Header
    klipper-micro       brand title
    [!]                 MCU disconnect warning — hidden when connected
    [W]                 WiFi icon — tappable, opens WifiScreen
    [⚙]                 Settings gear — tappable, opens SettingsScreen

Right panel
    The whole SET / value area is a tap target; tapping it opens
    SetpointScreen for precise +/- adjustment.  The FAN bar still cycles
    0 → 50 → 100 → 0 on tap.

The screen polls ``state`` on a timer and refreshes the affected widgets.
"""

import lvgl as lv  # type: ignore[import-not-found]

from .. import theme


STATUS_HEIGHT = 24
LEFT_WIDTH = 195
PADDING = 4

# Safe-area inset from the right edge — the case bezel on the test rig
# clips a few pixels off the right side, so all right-aligned interactive
# elements pull in by this much.
RIGHT_INSET = 18

# Same idea for the bottom — keep the fan bar away from the bezel.
BOTTOM_INSET = 12


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

        # Title — pulled from state.device_name (set from /config.json at
        # boot, default "klipper-micro").
        title = lv.label(bar)
        title.set_text(self.state.device_name)
        title.set_style_text_color(lv.color_hex(theme.COLOR_ACCENT), 0)
        f = theme.font(14)
        if f is not None:
            title.set_style_text_font(f, 0)
        title.align(lv.ALIGN.LEFT_MID, 6, 0)

        # --- Settings (gear), far right -----------------------------------
        self._settings_btn = lv.button(bar)
        self._settings_btn.set_size(32, 22)
        self._settings_btn.align(lv.ALIGN.RIGHT_MID, -RIGHT_INSET, 0)
        sl = lv.label(self._settings_btn)
        sl.set_text(lv.SYMBOL.SETTINGS)
        sl.center()
        f = theme.font(14)
        if f is not None:
            sl.set_style_text_font(f, 0)
        self._settings_btn.add_event_cb(self._on_settings, lv.EVENT.CLICKED, None)

        # --- WiFi icon, just left of the gear ------------------------------
        self._wifi_btn = lv.button(bar)
        self._wifi_btn.set_size(32, 22)
        self._wifi_btn.align(lv.ALIGN.RIGHT_MID, -RIGHT_INSET - 38, 0)
        self._wifi_lbl = lv.label(self._wifi_btn)
        self._wifi_lbl.set_text(lv.SYMBOL.WIFI)
        self._wifi_lbl.set_style_text_color(lv.color_hex(theme.COLOR_OFF), 0)
        self._wifi_lbl.center()
        f = theme.font(14)
        if f is not None:
            self._wifi_lbl.set_style_text_font(f, 0)
        self._wifi_btn.add_event_cb(self._on_wifi, lv.EVENT.CLICKED, None)

        # --- MCU warning — only shown when the link is down ---------------
        # No button background; just a coloured warning glyph that stays out
        # of the way when everything is fine.
        self._mcu_warn = lv.label(bar)
        self._mcu_warn.set_text(lv.SYMBOL.WARNING)
        self._mcu_warn.set_style_text_color(lv.color_hex(theme.COLOR_ERROR), 0)
        f = theme.font(14)
        if f is not None:
            self._mcu_warn.set_style_text_font(f, 0)
        self._mcu_warn.align(lv.ALIGN.RIGHT_MID, -RIGHT_INSET - 78, 0)

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

        # Heater state row — a real circle (drawn by LVGL) next to the state
        # text.  Using a "●" text glyph fell back to tofu because Montserrat
        # doesn't ship U+25CF; an lv.obj sized 10×10 with radius=5 gives us a
        # proper filled circle that can also recolor with the state.
        self.state_dot = lv.obj(panel)
        self.state_dot.set_size(10, 10)
        self.state_dot.set_style_radius(5, 0)
        self.state_dot.set_style_bg_color(lv.color_hex(theme.COLOR_OFF), 0)
        self.state_dot.set_style_bg_opa(255, 0)
        self.state_dot.set_style_border_width(0, 0)
        self.state_dot.set_style_pad_all(0, 0)
        self.state_dot.align(lv.ALIGN.BOTTOM_LEFT, 6, -BOTTOM_INSET - 4)

        self.state_lbl = lv.label(panel)
        self.state_lbl.set_text("off")
        self.state_lbl.set_style_text_color(lv.color_hex(theme.COLOR_OFF), 0)
        f = theme.font(16)
        if f is not None:
            self.state_lbl.set_style_text_font(f, 0)
        self.state_lbl.align_to(self.state_dot, lv.ALIGN.OUT_RIGHT_MID, 6, 0)

    def _build_control_panel(self):
        right_x = LEFT_WIDTH + PADDING * 2
        right_w = 320 - right_x - PADDING
        panel = lv.obj(self.scr)
        panel.set_size(right_w, 240 - STATUS_HEIGHT - PADDING)
        panel.set_pos(right_x, STATUS_HEIGHT + PADDING)
        theme.apply_panel_style(panel)
        panel.set_style_pad_all(4, 0)

        # --- SET / target value (tappable region) --------------------------
        # Container is a transparent clickable; tapping anywhere opens the
        # SetpointScreen for precise +/- adjustment.  Quick-temp preset
        # buttons sit just below for one-tap common values.
        target_inner_w = right_w - 16
        set_area = lv.obj(panel)
        set_area.set_size(target_inner_w, 86)
        set_area.set_pos(0, 0)
        set_area.set_style_bg_opa(0, 0)
        set_area.set_style_border_width(0, 0)
        set_area.set_style_pad_all(0, 0)
        set_area.add_flag(lv.obj.FLAG.CLICKABLE)
        set_area.add_event_cb(self._on_open_setpoint, lv.EVENT.CLICKED, None)

        set_caption = lv.label(set_area)
        set_caption.set_text("SET")
        set_caption.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f is not None:
            set_caption.set_style_text_font(f, 0)
        set_caption.align(lv.ALIGN.TOP_LEFT, 4, 2)

        self.target_lbl = lv.label(set_area)
        self.target_lbl.set_text("--")
        self.target_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT), 0)
        f = theme.font(36) or theme.font(32) or theme.font(28)
        if f is not None:
            self.target_lbl.set_style_text_font(f, 0)
        self.target_lbl.align(lv.ALIGN.CENTER, 0, 6)

        self.target_unit_lbl = lv.label(set_area)
        self.target_unit_lbl.set_text("°C")
        self.target_unit_lbl.set_style_text_color(
            lv.color_hex(theme.COLOR_TEXT_DIM), 0
        )
        f = theme.font(14)
        if f is not None:
            self.target_unit_lbl.set_style_text_font(f, 0)
        self.target_unit_lbl.align_to(
            self.target_lbl, lv.ALIGN.OUT_BOTTOM_MID, 0, -4
        )

        # --- Quick-temp preset buttons (2×2 grid) --------------------------
        # Reads state.quick_temps (configured via /config.json, default
        # 45/50/55/60).  Tapping a preset jumps the target directly — no
        # picker, no confirmation.
        self._build_quick_buttons(panel, target_inner_w, top_y=92)

        # --- FAN section ---------------------------------------------------
        fan_caption = lv.label(panel)
        fan_caption.set_text("FAN")
        fan_caption.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f is not None:
            fan_caption.set_style_text_font(f, 0)
        fan_caption.align(lv.ALIGN.BOTTOM_LEFT, 2, -(BOTTOM_INSET + 18))

        self.fan_bar = lv.bar(panel)
        self.fan_bar.set_size(right_w - 16, 16)
        self.fan_bar.set_range(0, 100)
        self.fan_bar.set_value(0, 0)
        self.fan_bar.set_style_bg_color(lv.color_hex(theme.COLOR_BORDER), 0)
        self.fan_bar.set_style_bg_color(
            lv.color_hex(theme.COLOR_FAN), lv.PART.INDICATOR
        )
        self.fan_bar.set_style_bg_opa(255, lv.PART.INDICATOR)
        self.fan_bar.align(lv.ALIGN.BOTTOM_MID, 0, -BOTTOM_INSET)
        # Tap the fan bar to cycle 0 → 50 → 100 → 0
        self.fan_bar.add_flag(lv.obj.FLAG.CLICKABLE)
        self.fan_bar.add_event_cb(self._on_fan, lv.EVENT.CLICKED, None)

    def _build_quick_buttons(self, parent, inner_w, top_y):
        """Lay out up to 4 quick-temp buttons in a 2×2 grid.

        Parent is the right control panel; inner_w is the usable width
        inside the panel's padding; top_y is the y of the first row.
        """
        temps = list(self.state.quick_temps)[:4]
        col_gap = 4
        row_gap = 4
        btn_w = (inner_w - col_gap) // 2
        btn_h = 22

        for i, temp in enumerate(temps):
            col = i % 2
            row = i // 2
            x = col * (btn_w + col_gap)
            y = top_y + row * (btn_h + row_gap)

            btn = lv.button(parent)
            btn.set_size(btn_w, btn_h)
            btn.set_pos(x, y)
            btn.set_style_pad_all(0, 0)
            lbl = lv.label(btn)
            lbl.set_text("%d" % int(round(temp)))
            lbl.center()
            f = theme.font(14) or theme.font(12)
            if f is not None:
                lbl.set_style_text_font(f, 0)
            btn.add_event_cb(
                lambda e, t=temp: self._on_quick_temp(t),
                lv.EVENT.CLICKED,
                None,
            )

    # ------------------------------------------------------------------
    # Event handlers
    # ------------------------------------------------------------------

    def _on_quick_temp(self, temp):
        self.state.set_target(temp)
        self._refresh(None)

    def _on_open_setpoint(self, _evt):
        if self.manager is None:
            return
        from .setpoint import SetpointScreen
        self.manager.show(SetpointScreen, state=self.state)

    def _on_settings(self, _evt):
        if self.manager is None:
            return
        from .settings import SettingsScreen
        self.manager.show(SettingsScreen, state=self.state)

    def _on_wifi(self, _evt):
        if self.manager is None:
            return
        from .wifi import WifiScreen
        self.manager.show(WifiScreen, state=self.state)

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
            self.target_lbl.set_text("%d" % (int(round(target)),))
            self.target_unit_lbl.remove_flag(lv.obj.FLAG.HIDDEN)
        else:
            self.target_lbl.set_text("OFF")
            self.target_unit_lbl.add_flag(lv.obj.FLAG.HIDDEN)

        state_color = lv.color_hex(theme.heater_state_color(state_name))
        self.state_lbl.set_text(state_name)
        self.state_lbl.set_style_text_color(state_color, 0)
        self.state_dot.set_style_bg_color(state_color, 0)

        self.fan_bar.set_value(int(fan * 100), 0)

        # MCU warning glyph — visible only when the MCU link is down.
        if mcu_ok:
            self._mcu_warn.add_flag(lv.obj.FLAG.HIDDEN)
        else:
            self._mcu_warn.remove_flag(lv.obj.FLAG.HIDDEN)

        # WiFi icon colour reflects connection state.
        self._wifi_lbl.set_style_text_color(
            lv.color_hex(theme.COLOR_OK if wifi_ok else theme.COLOR_OFF), 0
        )

    # ------------------------------------------------------------------

    def show(self):
        # When using screen_active() in __init__, there's nothing to load.
        pass

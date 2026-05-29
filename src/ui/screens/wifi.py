"""WiFi configuration screen.

Two logical views are managed within a single screen by toggling container
visibility — this avoids creating and destroying LVGL objects on each
navigation step.

List view (320x240):

    +--------------------------------------------------+
    | < back  WiFi                           [Scan]    |  28px
    +--------------------------------------------------+
    | Connected: MySSID          or  Not connected     |  28px
    +--------------------------------------------------+
    |  ● MySSID (current)                              |
    |  ○ Network2                                      |  scrollable
    |  ○ Network3                                      |
    +--------------------------------------------------+

Password view (after tapping a network):

    +--------------------------------------------------+
    | < back  <SSID name>                              |  28px
    +--------------------------------------------------+
    | Password  [________________________________]     |  44px
    +--------------------------------------------------+
    |                                                  |
    |              LVGL keyboard                       |  ~140px
    |                                                  |
    +--------------------------------------------------+
    |  [  Connect  ]   <status>                        |  28px
    +--------------------------------------------------+
"""

import lvgl as lv  # type: ignore[import-not-found]

from .. import theme


HEADER_H = 28
STATUS_H = 28
FOOTER_H = 32
POLL_INTERVAL_MS = 500
CONNECT_TIMEOUT_TICKS = 30  # 30 × 500 ms = 15 s


class WifiScreen:
    def __init__(self, state, manager=None):
        self.state = state
        self.manager = manager
        self.scr = lv.screen_active()
        theme.apply_screen_style(self.scr)

        self._selected_ssid = None
        self._connect_timer = None
        self._connect_ticks = 0

        self._build_list_view()
        self._build_password_view()
        self._show_list()
        self._do_scan()

    def dispose(self):
        if self._connect_timer is not None:
            self._connect_timer.delete()
            self._connect_timer = None

    # ------------------------------------------------------------------
    # List view
    # ------------------------------------------------------------------

    def _build_list_view(self):
        self._list_cont = lv.obj(self.scr)
        self._list_cont.set_size(320, 240)
        self._list_cont.set_pos(0, 0)
        self._list_cont.set_style_bg_opa(0, 0)
        self._list_cont.set_style_border_width(0, 0)
        self._list_cont.set_style_pad_all(0, 0)

        # --- Header ---
        hdr = lv.obj(self._list_cont)
        hdr.set_size(320, HEADER_H)
        hdr.set_pos(0, 0)
        hdr.set_style_bg_color(lv.color_hex(theme.COLOR_PANEL), 0)
        hdr.set_style_bg_opa(255, 0)
        hdr.set_style_border_width(0, 0)
        hdr.set_style_radius(0, 0)
        hdr.set_style_pad_all(2, 0)

        back = lv.button(hdr)
        back.set_size(50, 22)
        back.align(lv.ALIGN.LEFT_MID, 4, 0)
        bl = lv.label(back)
        bl.set_text("< back")
        bl.center()
        f = theme.font(12)
        if f:
            bl.set_style_text_font(f, 0)
        back.add_event_cb(self._on_back_list, lv.EVENT.CLICKED, None)

        title = lv.label(hdr)
        title.set_text("WiFi")
        title.set_style_text_color(lv.color_hex(theme.COLOR_ACCENT), 0)
        f = theme.font(14)
        if f:
            title.set_style_text_font(f, 0)
        title.center()

        scan_btn = lv.button(hdr)
        scan_btn.set_size(44, 22)
        scan_btn.align(lv.ALIGN.RIGHT_MID, -2, 0)
        sl = lv.label(scan_btn)
        sl.set_text("Scan")
        sl.center()
        f = theme.font(12)
        if f:
            sl.set_style_text_font(f, 0)
        scan_btn.add_event_cb(self._on_scan, lv.EVENT.CLICKED, None)

        # --- Status bar ---
        self._status_lbl = lv.label(self._list_cont)
        self._status_lbl.set_size(316, STATUS_H)
        self._status_lbl.set_pos(2, HEADER_H + 2)
        self._status_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f:
            self._status_lbl.set_style_text_font(f, 0)
        self._status_lbl.set_text("Scanning…")

        # --- Network list ---
        list_y = HEADER_H + STATUS_H + 4
        list_h = 240 - list_y - 2
        self._net_list = lv.list(self._list_cont)
        self._net_list.set_size(316, list_h)
        self._net_list.set_pos(2, list_y)
        theme.apply_panel_style(self._net_list, radius=6)

    # ------------------------------------------------------------------
    # Password view
    # ------------------------------------------------------------------

    def _build_password_view(self):
        self._pwd_cont = lv.obj(self.scr)
        self._pwd_cont.set_size(320, 240)
        self._pwd_cont.set_pos(0, 0)
        self._pwd_cont.set_style_bg_opa(0, 0)
        self._pwd_cont.set_style_border_width(0, 0)
        self._pwd_cont.set_style_pad_all(0, 0)

        # --- Header ---
        hdr = lv.obj(self._pwd_cont)
        hdr.set_size(320, HEADER_H)
        hdr.set_pos(0, 0)
        hdr.set_style_bg_color(lv.color_hex(theme.COLOR_PANEL), 0)
        hdr.set_style_bg_opa(255, 0)
        hdr.set_style_border_width(0, 0)
        hdr.set_style_radius(0, 0)
        hdr.set_style_pad_all(2, 0)

        back = lv.button(hdr)
        back.set_size(50, 22)
        back.align(lv.ALIGN.LEFT_MID, 4, 0)
        bl = lv.label(back)
        bl.set_text("< back")
        bl.center()
        f = theme.font(12)
        if f:
            bl.set_style_text_font(f, 0)
        back.add_event_cb(self._on_back_pwd, lv.EVENT.CLICKED, None)

        self._ssid_title = lv.label(hdr)
        self._ssid_title.set_text("")
        self._ssid_title.set_style_text_color(lv.color_hex(theme.COLOR_ACCENT), 0)
        f = theme.font(12)
        if f:
            self._ssid_title.set_style_text_font(f, 0)
        self._ssid_title.align(lv.ALIGN.LEFT_MID, 60, 0)
        self._ssid_title.set_long_mode(lv.label.LONG_MODE.DOTS)
        self._ssid_title.set_width(200)

        # --- Password row ---
        pwd_row = lv.obj(self._pwd_cont)
        pwd_row.set_size(316, 40)
        pwd_row.set_pos(2, HEADER_H + 2)
        theme.apply_panel_style(pwd_row, radius=6)
        pwd_row.set_style_pad_all(4, 0)

        pwd_lbl = lv.label(pwd_row)
        pwd_lbl.set_text("Password")
        pwd_lbl.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f:
            pwd_lbl.set_style_text_font(f, 0)
        pwd_lbl.align(lv.ALIGN.LEFT_MID, 2, 0)

        self._pwd_ta = lv.textarea(pwd_row)
        self._pwd_ta.set_size(200, 30)
        self._pwd_ta.align(lv.ALIGN.RIGHT_MID, -2, 0)
        self._pwd_ta.set_password_mode(True)
        self._pwd_ta.set_one_line(True)
        self._pwd_ta.set_placeholder_text("password")
        f = theme.font(14)
        if f:
            self._pwd_ta.set_style_text_font(f, 0)

        # --- Keyboard ---
        kb_y = HEADER_H + 44 + 4
        kb_h = 240 - kb_y - FOOTER_H - 4
        self._kb = lv.keyboard(self._pwd_cont)
        self._kb.set_size(320, kb_h)
        self._kb.set_pos(0, kb_y)
        self._kb.set_textarea(self._pwd_ta)

        # --- Footer ---
        footer_y = 240 - FOOTER_H
        footer = lv.obj(self._pwd_cont)
        footer.set_size(320, FOOTER_H)
        footer.set_pos(0, footer_y)
        footer.set_style_bg_color(lv.color_hex(theme.COLOR_PANEL), 0)
        footer.set_style_bg_opa(255, 0)
        footer.set_style_border_width(0, 0)
        footer.set_style_radius(0, 0)
        footer.set_style_pad_all(4, 0)

        conn_btn = lv.button(footer)
        conn_btn.set_size(80, FOOTER_H - 8)
        conn_btn.align(lv.ALIGN.LEFT_MID, 4, 0)
        cl = lv.label(conn_btn)
        cl.set_text("Connect")
        cl.center()
        f = theme.font(12)
        if f:
            cl.set_style_text_font(f, 0)
        conn_btn.add_event_cb(self._on_connect, lv.EVENT.CLICKED, None)

        self._conn_status = lv.label(footer)
        self._conn_status.set_text("")
        self._conn_status.set_style_text_color(lv.color_hex(theme.COLOR_TEXT_DIM), 0)
        f = theme.font(12)
        if f:
            self._conn_status.set_style_text_font(f, 0)
        self._conn_status.align(lv.ALIGN.LEFT_MID, 94, 0)

    # ------------------------------------------------------------------
    # View switching
    # ------------------------------------------------------------------

    def _show_list(self):
        self._list_cont.remove_flag(lv.obj.FLAG.HIDDEN)
        self._pwd_cont.add_flag(lv.obj.FLAG.HIDDEN)

    def _show_password(self, ssid):
        self._selected_ssid = ssid
        self._ssid_title.set_text(ssid)
        self._pwd_ta.set_text("")
        self._conn_status.set_text("")
        self._list_cont.add_flag(lv.obj.FLAG.HIDDEN)
        self._pwd_cont.remove_flag(lv.obj.FLAG.HIDDEN)

    # ------------------------------------------------------------------
    # Scan
    # ------------------------------------------------------------------

    def _do_scan(self):
        try:
            import wifi as _wifi
        except ImportError:
            self._status_lbl.set_text("WiFi not available")
            return

        self._status_lbl.set_text("Scanning…")
        self._net_list.clean()

        nets = _wifi.scan()
        cur = _wifi.current_ssid()

        if cur:
            self._status_lbl.set_text("Connected: " + cur)
        else:
            self._status_lbl.set_text("Not connected")

        if not nets:
            self._net_list.add_text("No networks found")
            return

        for ssid, _rssi in nets:
            label = ssid + (" ✓" if ssid == cur else "")
            # lv.SYMBOL.BULLET avoids the hard crash that NULL/None causes
            # in this LVGL 9 build when passed as the icon argument.
            btn = self._net_list.add_button(lv.SYMBOL.BULLET, label)
            btn.add_event_cb(
                lambda e, s=ssid: self._show_password(s),
                lv.EVENT.CLICKED,
                None,
            )

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _on_connect(self, _evt):
        try:
            import wifi as _wifi
        except ImportError:
            self._conn_status.set_text("Not available")
            return

        password = self._pwd_ta.get_text()
        if not password:
            self._conn_status.set_text("Enter password")
            return

        self._conn_status.set_text("Connecting…")
        self._connect_ticks = 0
        _wifi.start_connect(self._selected_ssid, password)

        if self._connect_timer is not None:
            self._connect_timer.delete()
        self._connect_timer = lv.timer_create(
            self._poll_connect, POLL_INTERVAL_MS, None
        )

    def _poll_connect(self, _timer):
        try:
            import wifi as _wifi
        except ImportError:
            return

        self._connect_ticks += 1
        if _wifi.check_connected():
            self._connect_timer.delete()
            self._connect_timer = None
            _wifi.save_creds(self._selected_ssid, self._pwd_ta.get_text())
            self.state.set_wifi_connected(True)
            self._conn_status.set_text("Connected!")
            # Return to list and refresh status
            self._show_list()
            cur = _wifi.current_ssid()
            self._status_lbl.set_text("Connected: " + cur if cur else "Connected")
        elif self._connect_ticks >= CONNECT_TIMEOUT_TICKS:
            self._connect_timer.delete()
            self._connect_timer = None
            self._conn_status.set_text("Failed — check password")

    # ------------------------------------------------------------------
    # Back navigation
    # ------------------------------------------------------------------

    def _on_back_list(self, _evt):
        if self.manager:
            from .main import MainScreen
            self.manager.show(MainScreen, state=self.state)

    def _on_back_pwd(self, _evt):
        if self._connect_timer is not None:
            self._connect_timer.delete()
            self._connect_timer = None
        self._show_list()

    # ------------------------------------------------------------------

    def _on_scan(self, _evt):
        self._do_scan()

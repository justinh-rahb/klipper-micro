"""Simple screen manager.

LVGL's multi-screen API (``lv.screen_load``) is unstable in our test runs
when screens are constructed before LVGL's task handler has had time to
settle, so we instead keep one active screen and tear it down + rebuild on
each navigation.

Usage:
    mgr = ScreenManager()
    mgr.show(MainScreen, state=state)
    # later, from a button callback:
    mgr.show(SettingsScreen, state=state, manager=mgr)
"""

import lvgl as lv  # type: ignore[import-not-found]


class ScreenManager:
    def __init__(self):
        self.current = None

    def show(self, screen_class, **kwargs):
        # Dispose the existing screen (cancel timers, drop refs).
        prev = self.current
        self.current = None
        if prev is not None and hasattr(prev, "dispose"):
            prev.dispose()
        # Wipe the active screen so we get a fresh canvas.
        lv.screen_active().clean()
        # Construct the new screen. It draws into ``lv.screen_active()``.
        kwargs.setdefault("manager", self)
        self.current = screen_class(**kwargs)
        return self.current

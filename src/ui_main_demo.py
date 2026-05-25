"""Run the main screen with mock state, no Klipper MCU required.

Validates the touch UI end-to-end: temp readout updates, setpoint +/-, fan
button cycles, status icons.

Run with:
    mpremote connect port:/dev/tty.usbserial-3110 run src/ui_main_demo.py
"""

import time

from ui import display
from ui.manager import ScreenManager
from ui.mock_state import MockState
from ui.screens.main import MainScreen


def main():
    display.init(backlight_pct=80, with_touch=True)
    state = MockState()
    state.set_wifi_connected(True)
    state.set_mcu_connected(True)
    state.set_target(60.0)

    mgr = ScreenManager()
    mgr.show(MainScreen, state=state)
    print("UI demo running; tap SET (top right) to open settings")
    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()

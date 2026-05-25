"""Mock state provider for UI development.

Stands in for the real Phase 3 device layer so the touchscreen can be built
and iterated without a Klipper MCU. Implements a primitive thermal model: if
the heater is on, current_temp drifts toward target; otherwise toward ambient.

The interface — ``temperature``, ``target``, ``heater_state``, ``fan_speed``,
``mcu_connected``, ``wifi_connected`` properties plus ``set_target`` and
``set_fan`` setters — is the contract the real ``app.State`` will satisfy.
"""

import time


_AMBIENT = 22.0


class MockState:
    def __init__(self):
        self._temp = _AMBIENT
        self._target = 0.0  # 0 means heater off
        self._fan = 0.0
        self._mcu_connected = True
        self._wifi_connected = False
        self._last_tick = time.time()
        # Settings (will move to a Config object in Phase 3, but the UI
        # surface is the same)
        self.pid_kp = 22.2
        self.pid_ki = 1.08
        self.pid_kd = 114.0
        self.max_temp = 80.0

    # --- read-only properties --------------------------------------------

    @property
    def temperature(self):
        self._tick()
        return self._temp

    @property
    def target(self):
        return self._target

    @property
    def heater_state(self):
        if self._target <= 0:
            return "off"
        diff = self._target - self._temp
        if diff > 1.0:
            return "heating"
        if diff < -1.0:
            return "overshoot"
        return "holding"

    @property
    def fan_speed(self):
        return self._fan

    @property
    def mcu_connected(self):
        return self._mcu_connected

    @property
    def wifi_connected(self):
        return self._wifi_connected

    # --- mutators --------------------------------------------------------

    def set_target(self, value):
        """Setpoint in °C. 0 to turn the heater off."""
        if value < 0:
            value = 0
        if value > 100:
            value = 100
        self._target = float(value)

    def set_fan(self, value):
        """Fan duty 0.0..1.0."""
        if value < 0:
            value = 0
        if value > 1:
            value = 1
        self._fan = float(value)

    def set_mcu_connected(self, connected):
        self._mcu_connected = bool(connected)

    def set_wifi_connected(self, connected):
        self._wifi_connected = bool(connected)

    # --- thermal model ---------------------------------------------------

    def _tick(self):
        now = time.time()
        dt = now - self._last_tick
        if dt <= 0:
            return
        self._last_tick = now
        if self._target > 0 and self._mcu_connected:
            # Heating: drift toward target at ~2 °C/s with a fan-cooling penalty
            rate = 2.0 - 0.5 * self._fan
            delta = max(-1.0, min(1.0, self._target - self._temp))
            self._temp += delta * rate * dt
        else:
            # Off: drift toward ambient at ~0.3 °C/s, fan accelerates cooling
            rate = 0.3 + 1.5 * self._fan
            if self._temp > _AMBIENT:
                self._temp -= rate * dt
                if self._temp < _AMBIENT:
                    self._temp = _AMBIENT

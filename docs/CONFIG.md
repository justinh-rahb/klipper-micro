# Configuration

Runtime configuration is a JSON file at `/config.json` on the ESP32 flash.
It's loaded at boot, validated, and used to wire up the device set sent to
the MCU during the config phase.

> **Status:** This is the planned schema for Phase 3 (devices). The protocol
> layer in Phase 1 does not yet consume it.

## Schema (draft)

```json
{
  "transport": {
    "type": "uart",
    "uart_id": 2,
    "baudrate": 250000,
    "tx": 22,
    "rx": 27
  },
  "wifi": {
    "ssid": "...",
    "password": "..."
  },
  "thermistors": [
    {
      "name": "chamber",
      "pin": "PA2",
      "type": "ntc",
      "beta": 3950,
      "r0": 100000,
      "t0": 25,
      "pullup": 4700,
      "min_temp": 0,
      "max_temp": 100
    }
  ],
  "heaters": [
    {
      "name": "main",
      "pin": "PA1",
      "sensor": "chamber",
      "control": "pid",
      "pid_kp": 22.2,
      "pid_ki": 1.08,
      "pid_kd": 114,
      "max_temp": 80,
      "max_power": 1.0,
      "cycle_time": 0.1
    }
  ],
  "fans": [
    {
      "name": "circulation",
      "pin": "PA3",
      "cycle_time": 0.010,
      "off_below": 0.1,
      "kick_start_time": 0.1
    }
  ]
}
```

## Field reference

### `transport`
- `type` — `"uart"` (only supported value initially) or `"tcp"` (testing only)
- `uart_id`, `tx`, `rx`, `baudrate` — MicroPython `machine.UART` parameters
- For `tcp`: `host` and `port` instead of UART fields

### `wifi`
- `ssid`, `password` — optional; if omitted, AP mode is used for first-time setup

### `thermistors[]`
NTC β-model temperature sensor.
- `pin` — pin name as it appears in the MCU's enumerations (e.g. `"PA2"`)
- `beta`, `r0`, `t0` — Steinhart β-equation parameters
- `pullup` — pullup resistance in Ω (typically 4700)
- `min_temp`, `max_temp` — bounds; outside this range triggers emergency stop

### `heaters[]`
- `sensor` — must reference a `thermistors[].name`
- `control` — `"pid"` or `"watermark"` (bang-bang)
- `pid_kp`, `pid_ki`, `pid_kd` — PID gains (divided by 255 internally to
  match Klipper's `PID_PARAM_BASE`)
- `max_power` — clamp on output, 0..1
- `cycle_time` — PWM period in seconds

### `fans[]`
- `cycle_time` — PWM period
- `off_below` — duty cycles below this are clamped to 0 (helps fans with poor low-speed behavior)
- `kick_start_time` — run at full speed briefly when starting from 0 (helps fans spin up)

## Validation

On boot, `src/config.py` validates:
- All required fields present
- `heaters[].sensor` references exist
- Pin names exist in the MCU's enumerations (after handshake)
- `max_temp > min_temp`, `0 < max_power <= 1`, etc.

Validation failure → boot to a config-error screen; the web UI exposes
`PUT /config` to edit and `POST /config/reload` to apply.

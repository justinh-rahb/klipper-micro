# Configuration

Runtime configuration is a JSON file at `/config.json` on the ESP32 flash.
It's loaded at boot, validated, and used to wire up the device set sent to
the MCU during the config phase.

> **Status:** This is the planned schema for Phase 3 (devices). The protocol
> layer in Phase 1 does not yet consume it.

## Schema (draft)

```json
{
  "device_name": "Filament Dryer",
  "quick_temps": [45, 50, 55, 60],
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

### `device_name` (string, optional)

Title shown at the top of the main screen.  Default `"klipper-micro"`.
Useful when you have several boards on the same network and want each
one to identify itself as e.g. `"Filament Dryer"` or `"Chamber Heater"`.

Not exposed in the touch UI — edit the JSON directly (or via the web
API once Phase 5 lands).

### `quick_temps` (list of numbers, optional)

Preset temperature buttons on the main screen.  Up to 4 entries, in
°C.  Default `[45, 50, 55, 60]`.

Tapping a button sets the target directly with no confirmation; the
SET area still opens the precise +/- picker.

### `transport`

Selects the physical link between the host and the Klipper MCU.  This is a
boot-time setting; changing it requires a restart.

| `type` | Class used | Typical use case |
|---|---|---|
| `"uart"` | `UartTransport` | Standard CYD (ESP32-2432S028R) → MCU via GPIO UART pins |
| `"usb_serial"` | `SerialTransport` | CPython on a laptop → MCU via USB CDC serial |
| `"usb_cdc"` | `UsbCdcTransport` | ESP32-S2 / ESP32-S3 / RP2040 on-chip USB → MCU |
| `"tcp"` | `StreamTransport` | Testing only — mock MCU over a TCP socket |

#### `type: "uart"` fields
- `uart_id` — MicroPython UART bus number (0–2; default `2` on the CYD)
- `tx`, `rx` — GPIO pin numbers (default `22`, `27` for the CYD P1 connector)
- `baudrate` — bits per second; must match the MCU firmware (default `250000`)

#### `type: "usb_serial"` fields
- `port` — serial port path, e.g. `"/dev/ttyACM0"`, `"/dev/tty.usbmodem001"`,
  or `"COM3"` on Windows
- `baudrate` — bits per second (default `250000`)

  Used when running the full host stack from a laptop via `scripts/connect.py`
  or when the CYD is replaced by a desktop Python environment for development.
  Requires `pyserial` (`pip install pyserial`).

#### `type: "usb_cdc"` fields
No additional fields — the single native USB CDC interface is opened
automatically.

  Applicable only on boards whose SOC has an on-chip USB peripheral:
  ESP32-S2, ESP32-S3, RP2040/RP2350.  The standard CYD (ESP32-2432S028R)
  routes USB through an external CP2102/CH340 bridge chip; for that board
  use `"uart"` instead.

#### `type: "tcp"` fields
- `host` — hostname or IP (default `"127.0.0.1"`)
- `port` — TCP port (default `5555`)

  Only intended for the CPython test suite against `tests/mock_mcu.py`.

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
- `transport.type` is one of the four recognised values
- `usb_serial` requires `port` to be a non-empty string
- `usb_cdc` is rejected on standard ESP32 (plain ESP32 has no on-chip USB)
- `heaters[].sensor` references exist
- Pin names exist in the MCU's enumerations (after handshake)
- `max_temp > min_temp`, `0 < max_power <= 1`, etc.

Validation failure → boot to a config-error screen; the web UI exposes
`PUT /config` to edit and `POST /config/reload` to apply.

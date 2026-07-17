# Configuration roadmap

Persistent runtime configuration has not yet been ported to the native branch.
Board-level values currently live beside the drivers so bring-up stays
auditable:

| Setting | Current value | Source |
|---|---:|---|
| Klipper UART | UART2, 250000 baud | `main/klipper_client.c` |
| UART TX / RX | GPIO22 / GPIO27 | `main/klipper_client.c` |
| Display/touch pins | standard ESP32-2432S028R | `main/board.c` |
| Quick temperatures | 45, 50, 55, 60 C | `main/ui.c` |
| Setpoint limit | 0..100 C | `main/app_state.c` |

## Planned persistence

The native implementation will use an NVS-backed, versioned configuration
record instead of parsing `/config.json` at boot. That avoids allocating a JSON
DOM in a memory-constrained control process. Import/export through the future
HTTP API can still use JSON at the boundary.

The record will cover:

- device name and quick-temperature presets;
- WiFi credentials;
- Klipper transport pins and baud rate;
- thermistor model, MCU pin enumeration, and safety bounds;
- heater pin, PID gains, maximum power, and MCU `max_duration`;
- fan pin, PWM period, kick-start, and low-duty cutoff; and
- a schema version plus CRC for migration and corruption detection.

## Activation rule

Configuration code must not activate a heater merely because a record parses.
The client must first validate MCU pin enumerations, configure the ADC and PWM
objects, install the MCU-side output timeout, start sensor sampling, and observe
a valid in-range temperature. Only then may a non-zero UI setpoint reach the
control loop.

# Configuration roadmap

Persistent runtime configuration has not yet been implemented.
Board-level values currently live beside the drivers so bring-up stays
auditable:

| Setting | Current value | Source |
|---|---:|---|
| Klipper UART | UART2, 250000 baud | `src/klipper_client.c` |
| UART TX / RX | GPIO22 / GPIO27 | `src/klipper_client.c` |
| Display/touch pins | standard ESP32-2432S028R | `src/board.c` |
| Quick temperatures | 45, 50, 55, 60 C | `src/ui.c` |
| Setpoint limit | 0..80 C | `src/app_state.c` |
| Heater / thermistor / fan | PA1 / PA2 / PA3 | `src/klipper_client.c` |
| Thermistor | 100k, Beta 3950, 4.7k pull-up | `src/heater_control.c` |
| PID Kp / Ki / Kd | 22.2 / 1.08 / 114 (Klipper scale) | `src/heater_control.c` |
| PWM cycle / refresh | 100 ms / 250 ms | `src/klipper_client.c` |
| MCU output timeout | 3 seconds | `src/klipper_client.c` |
| Sensor bounds / stale timeout | 0..85 C / 1 second | `src/heater_control.c` |

## Planned persistence

The native implementation will use an NVS-backed, versioned configuration
record instead of parsing `/config.json` at boot. That avoids allocating a JSON
DOM in a memory-constrained control process. Import/export through the future
HTTP API can still use JSON at the boundary.

The record is expected to cover:

- device name and quick-temperature presets;
- WiFi credentials;
- Klipper transport pins and baud rate;
- thermistor model, MCU pin enumeration, and safety bounds;
- heater pin, PID gains, maximum power, and MCU `max_duration`;
- fan pin, PWM period, kick-start, and low-duty cutoff; and
- a schema version plus CRC for migration and corruption detection.

## Activation rule

Configuration code does not activate a heater merely because values parse. The
client first validates MCU pin enumerations, configures the ADC and PWM objects,
installs the MCU-side output timeout, starts sensor sampling, and observes a
valid in-range temperature. Only then may a non-zero UI setpoint reach the
control loop. The same activation rule must remain when NVS persistence lands.

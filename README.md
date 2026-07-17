# klipper-micro

A small native Klipper host for the ESP32-2432S028R (CYD). It talks to an
unmodified Klipper MCU over UART and presents appliance controls on the CYD's
ILI9341/XPT2046 touchscreen.

The application, Klipper protocol subset, clock synchronization, board drivers,
and LVGL UI are compiled as native ESP-IDF/C code.

## Why native

The CYD has 520 KB of SRAM shared by WiFi, display DMA, LVGL, and the
application. The former MicroPython image left roughly 16 KB available after
the UI initialized and introduced non-deterministic garbage collection into a
control application. The native implementation instead uses:

- fixed 64-byte Klipper wire frames;
- a 12.5 KB partial LVGL DMA buffer;
- FreeRTOS tasks with explicit stack sizes;
- streaming zlib identify parsing, retaining only used message IDs; and
- no general JSON DOM or copy of the MCU's data dictionary in RAM.

## Current firmware

- ESP-IDF project for the original dual-core ESP32 CYD
- ILI9341 display via ESP-IDF LCD and XPT2046 touch via its component driver
- LVGL 9 main status/control screen
- UART2 transport on GPIO22/GPIO27 at 250000 baud
- Klipper framing, CRC16-CCITT, signed VLQ, retry/resynchronization
- streaming identify handshake and selective command-ID discovery
- `get_uptime` / `get_clock` clock regression ported from Klippy
- Klipper-side heater/fan PWM objects with a three-second output watchdog
- periodic thermistor ADC sampling, Beta conversion, filtered PID control, and
  clock-scheduled heater/fan updates
- sensor rail/staleness and heating-rate shutdown checks
- MCU link/control/fault status and a wired long-press `emergency_stop`
- portable native tests for protocol, dictionary extraction, clock sync,
  thermistor conversion, PID, and safety behavior

WiFi setup, persistent configuration, and secondary settings/status screens
remain.

## Build

With an ESP-IDF 5.1+ environment active:

```bash
idf.py set-target esp32
idf.py build
idf.py -p /dev/tty.usbserial-3110 flash monitor
```

PlatformIO can provision the ESP-IDF toolchain and build the same project:

```bash
pio run
pio run -t upload
pio device monitor -b 115200
```

LVGL and zlib are declared through the ESP-IDF component manager in
`src/idf_component.yml`.

Run the portable C tests without an ESP toolchain:

```bash
./scripts/test-native.sh
```

## Wiring

| CYD P1 | Klipper MCU |
|---|---|
| IO22 (TX) | UART RX |
| IO27 (RX) | UART TX |
| GND | GND |

Both sides use 3.3 V signaling. The Klipper MCU remains stock firmware.

## Layout

```text
src/
  app_main.c              startup
  board.c                 CYD display, touch, backlight, LVGL task
  ui.c                    native LVGL UI
  app_state.c             synchronized application state
  heater_control.c        thermistor conversion, PID, and safety checks
  klipper_protocol.c      framing, CRC, VLQ, stream parser
  klipper_dictionary.c    streaming identify dictionary filter
  klipper_clocksync.c     Klippy clock-regression port
  klipper_client.c        UART handshake/retry/link task
tests/native/             portable C unit tests
vendor/klipper/           pinned upstream Klipper source
```

Board, state, and UI code are MIT-licensed. The `klipper_*` protocol/client
modules port behavior and algorithms from upstream Klipper and are explicitly
GPLv3-or-later; a redistributed combined firmware image must follow GPLv3.

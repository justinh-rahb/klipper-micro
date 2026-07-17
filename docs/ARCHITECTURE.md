# Native architecture

klipper-micro is an ESP-IDF application on the original ESP32 CYD. FreeRTOS
provides explicit task scheduling; LVGL remains the UI toolkit.

```text
app_main
  +-- board.c               ILI9341, XPT2046, backlight, LVGL timer/task
  +-- ui.c                  widgets and touch event handlers
  +-- app_state.c           mutex-protected UI/control state
  +-- klipper_client.c      UART link task and reconnect state machine
      +-- klipper_protocol  64-byte frames, CRC, VLQ, stream resync
      +-- klipper_dictionary streaming zlib filter for used message IDs
      +-- klipper_clocksync host-time <-> MCU-clock regression
```

## Task model

| Task | Stack | Priority | Role |
|---|---:|---:|---|
| ESP-IDF `main` | 4 KB | default | one-time initialization |
| `lvgl` | 6 KB | 5 | all LVGL timers, events, rendering |
| `klipper` | 6 KB | 8 | UART framing, handshake, retry, clock polling |

Only the LVGL task calls LVGL APIs. The protocol task publishes small state
updates through `app_state.c`; its mutex prevents torn floating-point reads.
Display completion is delivered by the ESP LCD DMA callback.

## Memory model

The runtime has no garbage collector and does not retain the MCU's data
dictionary. During identify, each 40-byte compressed response is immediately
fed to zlib. A 512-byte output window scans the JSON byte stream for the exact
command/response formats this appliance uses. Only 16 message IDs and
`CLOCK_FREQ` survive startup.

Steady-state protocol storage is one 64-byte RX frame, one 64-byte UART read
buffer, one response record, and the clock regression state. LVGL renders into
a single 320 x 20 x RGB565 DMA buffer (12,800 bytes), not a full framebuffer.

## Protocol lifecycle

1. Open UART2 at 250000 baud on GPIO22/GPIO27.
2. Fetch `identify` in 40-byte chunks using hardcoded bootstrap IDs 1/0.
3. Stream-inflate and retain the used dynamic IDs plus `CLOCK_FREQ`.
4. Seed the 64-bit clock with `get_uptime`.
5. Prime regression with eight `get_clock` samples 50 ms apart.
6. Poll at 984 ms intervals; reconnect after request/retry exhaustion.

Commands use exponential request timeouts and a four-bit frame sequence.
Malformed data is discarded through the next `0x7e` sync boundary. A long
press on OFF queues `emergency_stop` directly to the Klipper client task.

## Safety boundary

The native link and emergency-stop path are implemented. Heater configuration,
ADC sampling, PID control, and the MCU `max_duration` watchdog are the next
slice and must land together: UI setpoints must not energize output until the
hard MCU timeout and sensor safety checks are active.

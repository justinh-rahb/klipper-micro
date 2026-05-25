# Architecture

klipper-micro is a single-process MicroPython application running on an ESP32.
It speaks the standard Klipper host protocol to one MCU over UART, runs PID
control loops on the ESP32, and presents the result via an LVGL touchscreen
and a small HTTP API.

```
┌────────────────────────────────────────────────────────────┐
│  ESP32 CYD (MicroPython + LVGL)                            │
│                                                            │
│   app.py  ─────────────  asyncio event loop                │
│      │                                                     │
│      ├── proto/transport ── UART ── (wire) ── Klipper MCU  │
│      ├── proto/queue       (frames, retry, dispatch)       │
│      ├── proto/clocksync   (regression on MCU clock)       │
│      ├── devices/heater    (PID, smoothed temp)            │
│      ├── devices/fan       (PWM, optional tach)            │
│      ├── devices/safety    (runaway, sensor disconnect)    │
│      ├── ui/screens        (LVGL: status, settings)        │
│      └── web/server        (microdot HTTP)                 │
└────────────────────────────────────────────────────────────┘
```

## Protocol layers

| Layer | Module | Source |
|---|---|---|
| VLQ + CRC + identify parsing | `src/proto/msgproto.py` | **Vendored** from `vendor/klipper/klippy/msgproto.py` |
| UART / asyncio transport | `src/proto/transport.py` | New |
| Frame queue + retransmit + dispatch | `src/proto/queue.py` | **New** — replaces `chelper/serialqueue.c` |
| Bring-up handshake | `src/proto/handshake.py` | New (mirrors `klippy/serialhdl.py`) |
| Clock-sync regression | `src/proto/clocksync.py` | **Adapted** from `vendor/klipper/klippy/clocksync.py` (math copied, reactor → asyncio) |

The single piece of new code that materially matters is `proto/queue.py`. It
implements: HDLC-style framing with `0x7e` sync byte, 4-bit sequence numbers,
CRC16-CCITT, application-level retry (matching `SerialRetryCommand`), and a
register/dispatch model for responses.

## Why this works on MicroPython

Klipper's host side is split between Python (`klippy/`) and C
(`klippy/chelper/`). The C bits — `serialqueue.c`, `stepcompress.c`,
`itersolve.c` — exist for one reason: throughput. A full Klipper print
generates thousands of step commands per second; that's not viable in
interpreted Python.

For this project's workload (PID at ~10 Hz, ADC reads at the same rate, the
occasional fan speed change), pure Python is fine. Everything in `klippy/`
that's *already* pure Python — `msgproto.py`, `clocksync.py`, the PID
algorithm in `extras/heaters.py` — is either used directly or copied verbatim.

The only piece we lose is the C `serialqueue`'s ability to handle pipelined,
clock-scheduled, retransmit-tracked frame bursts. We replace it with the
single-shot retry pattern (`SerialRetryCommand`-style) for the handshake and
fire-and-forget sends for periodic traffic. RTT and retransmit are simpler
than the C version's RFC-6298 SRTT implementation.

## MicroPython portability notes

Bringing the code up on MicroPython 1.26.1 surfaced a handful of differences
from CPython's asyncio that are worth recording for future contributors. All
have been worked around inside `src/proto/queue.py`:

- **No `asyncio.Queue`** — replaced with `_AsyncFifo`, a tiny FIFO backed by a
  list and an `asyncio.Event`.
- **No `asyncio.Future`** — replaced with `_Waiter`, an Event-backed one-shot
  result holder that exposes `set_result`/`set_exception`/`done`/`wait`.
- **No `time.monotonic`** — provided as `monotonic()`, which on MicroPython
  accumulates `time.ticks_diff(ticks_ms(), last)` into a float so we get a
  stable monotonic seconds value (no wraparound concern for our timescale).
- **`del bytearray[:n]` is not supported** in every MP build — the rx and
  mock-MCU buffer code uses an explicit read-pointer plus periodic compaction
  instead of slice deletion.
- **`zlib` and `logging` are not in stock MicroPython** — both are available
  via `mip install`; `scripts/flash.sh` handles this automatically.

All four substitutions are no-ops on CPython, which is why the same `src/`
tree passes both the pytest suite *and* the on-device self-test.

## Concurrency model

One asyncio event loop. Tasks:

- `queue._rx_loop` — drains the UART, frames, dispatches
- `queue._tx_loop` — drains the send queue, writes frames
- `clocksync._poll_loop` — `get_clock` every ~1s
- `heater.control_loop` — PID tick at the thermistor sample rate
- `safety.monitor_loop` — periodic safety checks
- `web.serve` — microdot HTTP
- LVGL is ticked from a hardware timer ISR

No background threads, no locks — everything is cooperative via `await`.

## Failure modes & safety

- **MCU `max_duration` on `config_pwm_out`** is the hard backstop: if the host
  stops sending PWM updates, the MCU shuts down the pin within 3 seconds. This
  is the same mechanism real Klipper uses for the same reason.
- **Thermal runaway** is detected host-side: full power + no temp rise for N
  seconds triggers `emergency_stop`.
- **Sensor disconnect** is ADC-rail detection — full-scale or zero for K
  consecutive samples → `emergency_stop`.
- **Out-of-bounds temperature** triggers `emergency_stop` immediately.

## Forward compatibility

- Initial MCU target: **STM32** (most common Klipper MCU)
- Next: **RP2040 / RP2350**, then **AVR** (Arduino Mega class)
- The handshake discovers all command IDs at connect time, so MCU changes
  don't require host-side updates — only changes to the *set* of features we
  use would matter.
- USB serial is a future option alongside UART; the transport layer is
  already abstracted.

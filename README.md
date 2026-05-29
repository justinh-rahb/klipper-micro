# klipper-micro

A stripped-down Klipper *host* that runs on an ESP32 CYD (Cheap Yellow
Display), driving a standard Klipper MCU over UART. Built for appliance-style
use cases — filament dryers, chamber heaters, supplemental fan controllers —
where running a full Raspberry Pi + Klippy + Moonraker stack is overkill.

The CYD provides a 2.8" touchscreen UI; WiFi exposes a small HTTP API for
remote control. The Klipper MCU on the other end of the UART line runs
unmodified stock firmware.

> **Status: protocol layer and CYD UI firmware validated on real hardware.**
> Phase 1 (CPython tests, 18/18 passing against a mock MCU) and Phase 2
> (CYD bring-up with the pinned LVGL-enabled MicroPython image) are complete.
> USB serial transport added — connect to a real Klipper MCU from a laptop
> with `scripts/connect.py` before wiring to the CYD.

## What it talks to

| Layer | Software |
|---|---|
| Touch + web UI | klipper-micro (this repo), running on ESP32 CYD |
| Klipper host protocol over UART | klipper-micro (this repo) |
| Klipper MCU firmware | Stock `Klipper3d/klipper` build, target initially STM32 |

The protocol layer borrows directly from upstream Klipper via a git submodule
at [`vendor/klipper`](vendor/klipper). `msgproto.py` and the clock-sync
regression math are used as-is; the only piece we reimplement is the C
`serialqueue` (which can't run on MicroPython) — see
[`src/proto/queue.py`](src/proto/queue.py).

## Repo layout

```
src/                MicroPython app — uploaded to the ESP32
  proto/            Klipper host protocol (msgproto, transport, queue, handshake, clocksync)
  devices/          Heater, fan, thermistor, safety  (Phase 3)
  ui/               LVGL screens                      (Phase 4)
  web/              HTTP API + dashboard              (Phase 5)
tests/              CPython pytest suite + mock MCU
vendor/klipper/     Pinned submodule of Klipper3d/klipper
scripts/            sync_vendor.sh, flash.sh, upload.sh
docs/               Architecture, protocol, hardware, config
examples/           Reference JSON configs (filament dryer, chamber heater)
```

## Development

```bash
git clone --recursive https://github.com/justinh-rahb/klipper-micro.git
cd klipper-micro
./scripts/sync_vendor.sh                            # copies msgproto.py + clocksync.py from vendor/klipper
python3 -m venv .venv
.venv/bin/pip install pytest pytest-asyncio mpremote pyserial
.venv/bin/python -m pytest tests/ -v                # 18 tests against the mock MCU
```

### Bring up a real CYD

```bash
./scripts/flash.sh   /dev/tty.usbserial-3110         # erases + flashes the pinned LVGL CYD image + installs zlib/logging
./scripts/upload.sh  /dev/tty.usbserial-3110         # pushes full app (boot.py, main.py, proto/, ui/) and resets board
./scripts/selftest.sh /dev/tty.usbserial-3110        # runs device_selftest.py — 19 checks
```

After `upload.sh` completes the board soft-resets and the GUI starts automatically.
On every subsequent power-on MicroPython runs `boot.py` then `main.py` without
any host involvement.

The default firmware comes from de-dh's CYD LVGL project and is downloaded on
demand into `firmware/cache/`. Use `MP_FIRMWARE_FLAVOR=stock` if you want the
plain upstream ESP32 MicroPython image instead.

Run the mock MCU and an interactive REPL against it:

```bash
.venv/bin/python tests/mock_mcu.py --port 5555 &
# then in Python:
#   import asyncio
#   from proto.handshake import connect
#   from proto.transport import StreamTransport
#   t = await StreamTransport.connect_tcp("127.0.0.1", 5555)
#   q, cs = await connect(t)
```

### Validate a real Klipper MCU over USB serial (no CYD needed)

If your Klipper MCU is connected over USB (CDC ACM), you can run the full
handshake from your laptop without touching the CYD:

```bash
# Linux
python scripts/connect.py /dev/ttyACM0

# macOS (USB-serial adapter or native USB MCU)
python scripts/connect.py /dev/tty.usbmodem001

# Windows
python scripts/connect.py COM3

# Print the MCU's get_config response too
python scripts/connect.py /dev/ttyACM0 --query
```

`scripts/connect.py` uses `SerialTransport` (backed by pyserial) and runs the
same `connect()` handshake path as the on-device code.  If it succeeds the MCU
is ready to be wired to the CYD's UART.

**Transport classes at a glance:**

| Class | When to use |
|---|---|
| `StreamTransport` | CPython tests, TCP connection to mock MCU |
| `SerialTransport` | CPython + real MCU over USB serial (pyserial) |
| `UartTransport` | MicroPython / ESP32 hardware UART (standard CYD) |
| `UsbCdcTransport` | MicroPython on ESP32-S2/S3 or RP2040 native USB |

## License

Source files under `src/` are MIT-licensed (this project). `vendor/klipper/` is
GPLv3, used in source form per its license; any redistribution of derived
binaries needs to respect that.

# klipper-micro

A stripped-down Klipper *host* that runs on an ESP32 CYD (Cheap Yellow
Display), driving a standard Klipper MCU over UART. Built for appliance-style
use cases — filament dryers, chamber heaters, supplemental fan controllers —
where running a full Raspberry Pi + Klippy + Moonraker stack is overkill.

The CYD provides a 2.8" touchscreen UI; WiFi exposes a small HTTP API for
remote control. The Klipper MCU on the other end of the UART line runs
unmodified stock firmware.

> **Status: protocol layer validated on real hardware.** Phase 1 (CPython
> tests, 12/12 passing against a mock MCU) and Phase 2 (MicroPython 1.26.1 on
> a CYD, 19/19 checks passing in `device_selftest.py`) are complete. No
> Klipper MCU has been connected yet — that's the next step.

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
.venv/bin/pip install pytest pytest-asyncio mpremote
.venv/bin/python -m pytest tests/ -v                # 12 tests against the mock MCU
```

### Bring up a real CYD

```bash
./scripts/flash.sh   /dev/tty.usbserial-3110         # erases + flashes MP 1.26.1 + installs zlib/logging
./scripts/upload.sh  /dev/tty.usbserial-3110         # pushes src/proto/ to the device
./scripts/selftest.sh /dev/tty.usbserial-3110        # runs device_selftest.py — 19 checks
```

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

## License

Source files under `src/` are MIT-licensed (this project). `vendor/klipper/` is
GPLv3, used in source form per its license; any redistribution of derived
binaries needs to respect that.

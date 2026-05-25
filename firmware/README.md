# MicroPython firmware for the CYD

## Currently pinned

`scripts/flash.sh` flashes:

- **Stock MicroPython for ESP32**
- Version: `v1.26.1` (2025-09-11)
- URL: <https://micropython.org/resources/firmware/ESP32_GENERIC-20250911-v1.26.1.bin>

Validated on:

- Board: ESP32-2432S028R (CYD)
- Chip: ESP32-D0WD-V3 rev 3.1
- Date: 2026-05-25
- Result: 19/19 checks in `src/device_selftest.py` pass

This stock build is enough for Phase 1–3 work (protocol layer + devices). It
**does not include LVGL** — we'll switch to a custom LVGL-enabled image when
Phase 4 (touchscreen UI) begins.

## Runtime deps

Two `mip install`-able modules are required at runtime, both pulled
automatically by `scripts/flash.sh`:

- `zlib` — needed by `msgproto.process_identify` to decompress the identify
  blob. (MicroPython has `deflate` built-in but not `zlib`; `micropython-lib`
  provides a thin shim.)
- `logging` — used for stderr-style logging throughout the protocol layer.

## LVGL build (Phase 4, future)

Candidates investigated:

- [`de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL`](https://github.com/de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL)
  — Pre-built LVGL 8.x / 9.x firmware with the CYD's ILI9341 + XPT2046
  drivers wired up. Easiest path.
- [`kdschlosser/lvgl_micropython`](https://github.com/kdschlosser/lvgl_micropython)
  — Build-from-source toolchain if we need control over the LVGL version or
  feature set.

We'll pin a specific LVGL-enabled image once Phase 4 starts. The protocol
layer is firmware-agnostic — it just needs MicroPython + asyncio + zlib +
logging, all of which the LVGL builds also include.

## Manual flash (without the script)

```bash
esptool --port /dev/tty.usbserial-3110 --baud 460800 erase-flash
esptool --port /dev/tty.usbserial-3110 --baud 460800 \
    write-flash 0x1000 firmware/cache/ESP32_GENERIC-20250911-v1.26.1.bin
mpremote connect port:/dev/tty.usbserial-3110 mip install zlib
mpremote connect port:/dev/tty.usbserial-3110 mip install logging
```

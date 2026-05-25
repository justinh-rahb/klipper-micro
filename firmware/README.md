# MicroPython firmware for the CYD

## Default firmware

`scripts/flash.sh` now defaults to the tested LVGL-enabled CYD image:

- **de-dh CYD LVGL firmware**
- Source repo: <https://github.com/de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL>
- Download path: <https://raw.githubusercontent.com/de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL/main/lvgl9_firmwares/lvgl_micropy_ESP32_GENERIC-4.bin>
- Local cache name: `firmware/cache/lvgl_micropy_ESP32_GENERIC-4.bin`
- Local SHA256: `0c564b9c17ac80686e4d956e5bd4ee15632fc46c88d22090a8ebe059add9479c`

The binary itself identifies as:

- `LVGL MicroPython`
- `MicroPython-1.27.0-xtensa-IDFfcae3288-with-newlib4.3.0`
- `MicroPython 78ff170de9-dirty on 2026-04-22`
- Includes CYD-relevant `ILI9341` and `XPT2046` modules
- Built from `lvgl_micropython`; the embedded paths point at `/home/dh/lvgl_micropython/...`

Validated on:

- Board: ESP32-2432S028R (CYD)
- Chip: ESP32-D0WD-V3 rev 3.1
- Date: 2026-05-25
- Result: UI and touch stack available; `src/device_selftest.py` passes on-device

This is the firmware needed for the current touchscreen UI bring-up.

## Alternate stock firmware

If you want a non-LVGL baseline, `scripts/flash.sh` can still use upstream
stock MicroPython for ESP32:

- Version: `v1.26.1` (2025-09-11)
- URL: <https://micropython.org/resources/firmware/ESP32_GENERIC-20250911-v1.26.1.bin>
- Select it with `MP_FIRMWARE_FLAVOR=stock`

## Runtime deps

Two `mip install`-able modules are required at runtime, both pulled
automatically by `scripts/flash.sh`:

- `zlib` — needed by `msgproto.process_identify` to decompress the identify
  blob. (MicroPython has `deflate` built-in but not `zlib`; `micropython-lib`
  provides a thin shim.)
- `logging` — used for stderr-style logging throughout the protocol layer.

## Why this source

The current UI code depends on the high-level LVGL bindings and CYD drivers
that come with de-dh's prebuilt image. See `src/ui/display.py`, which imports
`lcd_bus`, `ili9341`, `xpt2046`, and `task_handler` from that firmware.

The protocol layer itself remains firmware-agnostic — it only needs
MicroPython + asyncio + zlib + logging — but the display stack does not.

If we later need a custom build, the underlying toolchain is:

- [`de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL`](https://github.com/de-dh/ESP32-Cheap-Yellow-Display-Micropython-LVGL)
  — prebuilt CYD-specific image and setup docs
- [`lvgl-micropython/lvgl_micropython`](https://github.com/lvgl-micropython/lvgl_micropython)
  — firmware build system used underneath

## Manual flash (without the script)

```bash
esptool --port /dev/tty.usbserial-3110 --baud 460800 erase-flash
esptool --port /dev/tty.usbserial-3110 --baud 460800 \
  write-flash 0x1000 firmware/cache/lvgl_micropy_ESP32_GENERIC-4.bin
mpremote connect port:/dev/tty.usbserial-3110 mip install zlib
mpremote connect port:/dev/tty.usbserial-3110 mip install logging
```

## Scripted usage

```bash
./scripts/flash.sh /dev/tty.usbserial-3110
MP_FIRMWARE_FLAVOR=stock ./scripts/flash.sh /dev/tty.usbserial-3110
MP_FIRMWARE=/path/to/custom.bin MP_FIRMWARE_URL=https://example.com/custom.bin ./scripts/flash.sh /dev/tty.usbserial-3110
```

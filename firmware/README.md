# Firmware artifacts

The firmware is built directly with ESP-IDF. PlatformIO places outputs under
`.pio/build/cyd/`:

- `firmware.bin` — application image
- `bootloader.bin` — ESP-IDF bootloader
- `partitions.bin` — project partition table

Build with `pio run` and flash all required images with
`scripts/flash.sh [PORT]`.

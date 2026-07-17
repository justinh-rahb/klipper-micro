# Native firmware artifacts

The ESP-IDF rewrite does not consume a prebuilt MicroPython image. PlatformIO
places native outputs under `.pio/build/cyd/`:

- `firmware.bin` — application image
- `bootloader.bin` — ESP-IDF bootloader
- `partitions.bin` — project partition table

Build with `pio run` and flash all required images with
`scripts/flash.sh [PORT]`. The old binaries under `firmware/cache/` are ignored
legacy development artifacts and are not used by the native build.

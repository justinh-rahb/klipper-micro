# Hardware

## ESP32 CYD (Cheap Yellow Display)

The reference target is the [ESP32-2432S028R](https://github.com/witnessmenow/ESP32-Cheap-Yellow-Display)
(a.k.a. "CYD"). ~$15 from various vendors.

| Spec | Value |
|---|---|
| MCU | ESP32-WROOM-32 (dual-core Xtensa LX6 @ 240 MHz) |
| Flash | 4 MB |
| RAM | 520 KB (16 KB usable to MicroPython after LVGL is loaded) |
| Display | 2.8" TFT, 240×320, ILI9341 |
| Touch | Resistive, XPT2046 |
| Networking | WiFi 802.11 b/g/n, Bluetooth |
| Storage | microSD slot |

### Pin assignments

The CYD has all GPIOs used for display, touch, SD, RGB LED, etc. The following
pins are exposed on connectors and free for external use:

| Connector | Pins | Notes |
|---|---|---|
| **P1** (4-pin JST) | GND, IO22, IO27, VIN (5 V in) | Best for UART — IO22/IO27 free, but VIN is **5 V**, ESP32 logic is 3.3 V |
| **P3** (4-pin JST) | GND, IO35, 3.3 V, IO22 | IO35 is input-only |
| **CN1** (header) | TX (IO1), RX (IO3), GND, 3.3 V | USB-to-UART bridge is on these — using them disconnects the USB serial console |

For the Klipper MCU connection, **P1 with IO22/IO27 as UART2 TX/RX** is the
cleanest option. You'll need a level-safe ground reference (just GND from
either side) and a way to power the MCU independently (or VIN at 5 V from
the CYD if the MCU draws very little).

## Wiring to the Klipper MCU

For an STM32-based Klipper MCU (e.g. SKR Mini, BTT Octopus, custom board):

```
CYD P1                       Klipper MCU (3.3 V logic side)
  IO22 (TX)  ────────────────  USART RX
  IO27 (RX)  ────────────────  USART TX
  GND        ────────────────  GND
  VIN (5V)   ────  optional ──  5V (if MCU accepts USB-class power)
```

Use the same baudrate on both ends. Klipper's default for stock STM32 builds
is `250000`. Configure in `src/config.json`:

```json
{
  "transport": {
    "type": "uart",
    "uart_id": 2,
    "baudrate": 250000,
    "tx": 22,
    "rx": 27
  }
}
```

## Klipper MCU firmware

The MCU runs **stock unmodified Klipper firmware**. Build with
`make menuconfig` for your specific board, flash via the usual Klipper
procedure ([upstream docs](https://www.klipper3d.org/Installation.html)).
You do not need a Raspberry Pi or a printer.cfg — klipper-micro takes over the
host role.

Recommended baseline `make menuconfig`:

```
Micro-controller Architecture (STMicroelectronics STM32)
  STM32F103 / F4 / G0  per your board
Communication interface (Serial (on USART1 PA10/PA9))
Baud rate for serial port: 250000
```

## Power

For a filament-dryer or chamber-heater appliance, expected loads:

| Component | Voltage | Typical current |
|---|---|---|
| CYD (idle, WiFi on) | 5 V | ~120 mA |
| CYD (display on, full backlight) | 5 V | ~250 mA |
| Klipper MCU (idle) | 5 V or 12/24 V | 50–150 mA |
| Heater element | 12 V or 24 V or mains | task-dependent |
| Fan | 12 V or 24 V | 100 mA – 1 A |

Use a properly rated buck converter or a sealed PSU; do **not** run the
heater through the MCU board's terminals unless they're rated for it (most
3D printer control boards are only rated for ~10 A continuous on the heater
MOSFET).

## Safety hardware

Beyond the firmware-level interlocks (`max_duration`, thermal runaway
detection, sensor-disconnect check), the physical setup should include:

- A **thermal cutoff** in series with the heater (one-shot fuse rated to a
  fixed temperature, e.g. 120 °C for filament drying)
- A **fused mains feed** if running off mains
- A separately-switched safety relay you can cut by yanking a plug

Software safety is necessary but not sufficient for anything that gets hot.

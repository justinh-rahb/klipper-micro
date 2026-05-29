#!/usr/bin/env python3
"""Connect to a real Klipper MCU over USB serial and print handshake results.

Runs the full identify + clock-sync sequence from CPython — no MicroPython or
CYD hardware needed.  Useful for validating that the protocol layer works with
a real MCU before wiring it to the ESP32.

Requirements::

    pip install pyserial

Usage::

    # Auto-detect baud rate from Klipper's default (250 000)
    python scripts/connect.py /dev/ttyACM0

    # Specify baud rate explicitly
    python scripts/connect.py /dev/ttyACM0 --baud 115200

    # macOS USB-serial adapters
    python scripts/connect.py /dev/tty.usbmodem001 --baud 250000

    # Send a get_config query after handshake and print the MCU response
    python scripts/connect.py /dev/ttyACM0 --query

The script prints:
  • All identify chunks received (total byte count)
  • The parsed MCU command dictionary size
  • The initial clock-sync frequency estimate
  • Optionally the raw params returned by get_config
"""

import argparse
import asyncio
import sys
import os

# Ensure src/ is on the path so we can import proto.*
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO_ROOT, "src"))

from proto.transport import SerialTransport
from proto.handshake import connect


async def _run(port, baud, query):
    print(f"Opening {port} at {baud} baud …")
    transport = SerialTransport.open(port, baudrate=baud)

    print("Running identify + clock sync …")
    try:
        queue, clocksync = await asyncio.wait_for(connect(transport), timeout=15.0)
    except asyncio.TimeoutError:
        print("ERROR: handshake timed out after 15 s")
        print("  • Check that the MCU is powered and running Klipper firmware.")
        print("  • Verify baud rate (Klipper default: 250000).")
        await transport.close()
        sys.exit(1)

    try:
        n_cmds = len(queue.msgparser.messages_by_name)
        print(f"  identify ok — {n_cmds} commands in MCU dictionary")

        freq_est = clocksync.clock_est[2]
        mcu_freq = clocksync.mcu_freq
        print(f"  clock sync  — mcu_freq={mcu_freq:.0f} Hz, "
              f"est={freq_est:.0f} Hz  ({100*freq_est/mcu_freq:.1f}%)")

        if query:
            print("\nSending get_config …")
            params = await asyncio.wait_for(
                queue.send_with_response("get_config", "config"), timeout=3.0
            )
            print("  get_config response:", params)

        print("\nHandshake successful ✓")
    finally:
        await clocksync.stop()
        await queue.stop()
        await transport.close()


def main():
    parser = argparse.ArgumentParser(
        description="Validate Klipper MCU handshake over USB serial"
    )
    parser.add_argument(
        "port",
        help="Serial port, e.g. /dev/ttyACM0 or /dev/tty.usbmodem001",
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=250000,
        help="Baud rate (default: 250000, matching Klipper's default)",
    )
    parser.add_argument(
        "--query",
        action="store_true",
        help="Send get_config after handshake and print the response",
    )
    args = parser.parse_args()
    asyncio.run(_run(args.port, args.baud, args.query))


if __name__ == "__main__":
    main()

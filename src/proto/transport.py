"""Transport abstraction: bytes in, bytes out.

Four implementations:

  StreamTransport
    A pair of asyncio.StreamReader / asyncio.StreamWriter. Used both for
    TCP-based connections to a mock MCU during testing, and as the bridge
    when the host-side code runs under CPython.

  SerialTransport
    CPython transport backed by pyserial.  Lets the full host stack run on a
    laptop and talk to a real Klipper MCU whose serial port appears as a USB
    CDC ACM device (e.g. /dev/ttyACM0, /dev/tty.usbserial-*, COM3).
    Requires: pip install pyserial

  UartTransport
    MicroPython UART → asyncio. Used on the standard ESP32 CYD in production
    (the USB port goes through a bridge chip, which already looks like a UART
    to the ESP32 firmware — no special CDC handling needed).

  UsbCdcTransport
    MicroPython native USB CDC. For boards with on-chip USB: ESP32-S2,
    ESP32-S3, RP2040 (Pico).  NOT needed for the standard CYD (ESP32-2432S028R)
    whose USB port is bridged via an external CP2102/CH340 chip.

All four implement the same interface that Queue depends on:

    async def read(self, n) -> bytes:
        Read up to n bytes; return b'' on EOF.
    async def write(self, data) -> None:
        Write the bytes; raise on transport failure.
    async def close(self) -> None:
        Release underlying resources.
"""

import asyncio


class StreamTransport:
    """asyncio StreamReader/StreamWriter pair."""

    def __init__(self, reader, writer):
        self._reader = reader
        self._writer = writer

    @classmethod
    async def connect_tcp(cls, host, port):
        reader, writer = await asyncio.open_connection(host, port)
        return cls(reader, writer)

    async def read(self, n):
        return await self._reader.read(n)

    async def write(self, data):
        self._writer.write(data)
        await self._writer.drain()

    async def close(self):
        self._writer.close()
        try:
            await self._writer.wait_closed()
        except Exception:
            pass


class SerialTransport:
    """CPython transport backed by pyserial.

    Wraps pyserial's blocking I/O in asyncio thread-pool executors so the
    async protocol stack works without modification.  Useful for:

    * Connecting directly from a laptop to a Klipper MCU whose USB serial port
      appears as /dev/ttyACM0 (Linux), /dev/tty.usbmodem* (macOS), or COMx
      (Windows).
    * Running the full handshake + clock-sync validation script
      (scripts/connect.py) without any MicroPython hardware.

    The serial port read timeout (``READ_TIMEOUT``) must be short enough not
    to stall the event loop but long enough to amortise syscall overhead.
    50 ms is a safe default: Klipper frames are sub-millisecond on any modern
    USB CDC driver, so the loop only blocks when the line is truly idle.

    Usage::

        import asyncio
        from proto.transport import SerialTransport
        transport = SerialTransport.open("/dev/ttyACM0")
        queue, clocksync = await connect(transport)
    """

    READ_TIMEOUT = 0.05  # seconds

    def __init__(self, ser):
        self._ser = ser

    @classmethod
    def open(cls, port, baudrate=250000, **kwargs):
        """Open *port* at *baudrate* (default 250 000 baud, matching Klipper).

        Additional keyword arguments are forwarded to ``serial.Serial``.

        Raises ``RuntimeError`` if pyserial is not installed.
        """
        try:
            import serial  # pyserial
        except ImportError as exc:
            raise RuntimeError(
                "pyserial is required for SerialTransport:\n"
                "    pip install pyserial"
            ) from exc
        ser = serial.Serial(
            port, baudrate=baudrate, timeout=cls.READ_TIMEOUT, **kwargs
        )
        return cls(ser)

    async def read(self, n):
        loop = asyncio.get_event_loop()
        while True:
            # Run the blocking pyserial read in a thread so we don't stall
            # the event loop.  The serial timeout causes this to return b''
            # when the line is idle; we yield once and retry.
            data = await loop.run_in_executor(None, self._ser.read, n)
            if data:
                return data
            await asyncio.sleep(0)

    async def write(self, data):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._ser.write, data)

    async def close(self):
        try:
            self._ser.close()
        except Exception:
            pass


class UartTransport:
    """MicroPython UART wrapped for asyncio.

    The MicroPython UART exposes ``read(n)`` and ``write(data)`` synchronously,
    and ``any()`` to check available bytes. We poll lightly and yield to the
    event loop between checks so other tasks (PID, UI, web) can progress.

    Imported lazily so the module is importable on CPython for unit tests.
    """

    POLL_INTERVAL = 0.001

    def __init__(self, uart):
        self.uart = uart

    @classmethod
    def open(cls, uart_id, baudrate=250000, tx=None, rx=None, **kwargs):
        from machine import UART  # MicroPython only

        params = {"baudrate": baudrate}
        if tx is not None:
            params["tx"] = tx
        if rx is not None:
            params["rx"] = rx
        params.update(kwargs)
        return cls(UART(uart_id, **params))

    async def read(self, n):
        # MicroPython UART.read returns None when nothing is available.
        while True:
            data = self.uart.read(n)
            if data:
                return data
            await asyncio.sleep(self.POLL_INTERVAL)

    async def write(self, data):
        # MicroPython UART.write is blocking but fast for small frames.
        # Yield once so we don't starve the loop on long bursts.
        self.uart.write(data)
        await asyncio.sleep(0)

    async def close(self):
        try:
            self.uart.deinit()
        except Exception:
            pass


class UsbCdcTransport:
    """MicroPython native USB-CDC transport.

    For boards whose ESP32/RP2040 SOC has an on-chip USB peripheral:
      * ESP32-S2 / ESP32-S3
      * RP2040 / RP2350 (Raspberry Pi Pico, Pico W, Pico 2)

    **The standard CYD (ESP32-2432S028R uses a plain ESP32 with no on-chip
    USB)** routes its USB port through an external CP2102/CH340 bridge chip.
    That bridge appears to the firmware as a UART, so use ``UartTransport``
    for that board — this class is not needed there.

    MicroPython exposes native USB CDC through the ``machine`` module.  The
    exact API varies slightly by port:

    * ``machine.USBSerial()`` — available on ESP32-S2/S3 builds shipped after
      MicroPython 1.22.
    * ``sys.stdin.buffer`` / ``sys.stdout.buffer`` bound to the CDC interface
      — available on RP2040 when the USB stack is configured in CDC mode
      (the default for most Pico builds).

    This class wraps the ``machine.USBSerial`` API.  For the
    ``sys.stdin``/``sys.stdout`` path (RP2040 REPL channel) see the docstring
    note below — sharing the REPL channel with the Klipper protocol is not
    recommended; use a second UART or a dedicated USB CDC interface instead.

    Usage::

        transport = UsbCdcTransport.open()
        queue, clocksync = await connect(transport)

    Imported lazily so this module is safely importable on CPython.
    """

    POLL_INTERVAL = 0.001  # seconds between empty-read retries

    def __init__(self, cdc):
        # *cdc* must expose .any() → int, .read(n) → bytes, .write(b) → int
        self._cdc = cdc

    @classmethod
    def open(cls):
        """Open the first USB CDC interface via ``machine.USBSerial``."""
        from machine import USBSerial  # MicroPython ≥ 1.22, ESP32-S2/S3
        return cls(USBSerial())

    async def read(self, n):
        while True:
            if self._cdc.any():
                data = self._cdc.read(n)
                if data:
                    return data
            await asyncio.sleep(self.POLL_INTERVAL)

    async def write(self, data):
        self._cdc.write(data)
        await asyncio.sleep(0)

    async def close(self):
        # USBSerial does not have a close/deinit in MicroPython 1.22.
        pass

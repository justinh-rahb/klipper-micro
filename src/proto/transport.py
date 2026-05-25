"""Transport abstraction: bytes in, bytes out.

Two implementations:

  UartTransport
    MicroPython UART → asyncio. Used on the ESP32 in production.

  StreamTransport
    A pair of asyncio.StreamReader / asyncio.StreamWriter. Used both for
    TCP-based connections to a mock MCU during testing, and as the bridge
    when the host-side code runs under CPython.

Both implement the same two-method interface that Queue depends on:

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

"""Tests for SerialTransport.

Uses a minimal fake ``serial.Serial`` object so no real port is required.
We patch ``serial.Serial`` inside the module's import scope so that
``SerialTransport.open()`` receives our stub instead of the real thing.
"""

import asyncio
import importlib
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from proto.transport import SerialTransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeSerial:
    """Minimal stand-in for serial.Serial that echoes writes back as reads."""

    def __init__(self, port, baudrate, timeout, **_kwargs):
        self.port = port
        self.baudrate = baudrate
        self.timeout = timeout
        self._buf = bytearray()
        self.closed = False

    def read(self, n):
        if self._buf:
            chunk = bytes(self._buf[:n])
            self._buf = self._buf[n:]
            return chunk
        return b""  # simulate empty-read on timeout

    def write(self, data):
        self._buf.extend(data)
        return len(data)

    def close(self):
        self.closed = True


def _make_fake_serial_module(fake_instance=None):
    """Return a fake ``serial`` module whose Serial class yields *fake_instance*."""
    mod = types.ModuleType("serial")

    def _Serial(port, baudrate=9600, timeout=None, **kwargs):
        if fake_instance is not None:
            # Patch the instance with whatever was given
            fake_instance.port = port
            fake_instance.baudrate = baudrate
            fake_instance.timeout = timeout
            return fake_instance
        return _FakeSerial(port, baudrate, timeout, **kwargs)

    mod.Serial = _Serial
    return mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_open_raises_without_pyserial(monkeypatch):
    """SerialTransport.open raises RuntimeError when pyserial is absent."""
    # Remove serial from sys.modules so the import inside open() fails
    monkeypatch.setitem(sys.modules, "serial", None)
    with pytest.raises(RuntimeError, match="pyserial is required"):
        SerialTransport.open("/dev/ttyACM0")


def test_open_constructs_transport(monkeypatch):
    """SerialTransport.open returns a transport wrapping a real Serial object."""
    fake_mod = _make_fake_serial_module()
    monkeypatch.setitem(sys.modules, "serial", fake_mod)

    t = SerialTransport.open("/dev/ttyACM0", baudrate=250000)
    assert isinstance(t, SerialTransport)
    assert t._ser.port == "/dev/ttyACM0"
    assert t._ser.baudrate == 250000
    assert t._ser.timeout == SerialTransport.READ_TIMEOUT


@pytest.mark.asyncio
async def test_write_then_read(monkeypatch):
    """Data written to the transport comes back on read (via the fake echo)."""
    fake_ser = _FakeSerial("/dev/ttyACM0", 250000, SerialTransport.READ_TIMEOUT)
    fake_mod = _make_fake_serial_module(fake_instance=fake_ser)
    monkeypatch.setitem(sys.modules, "serial", fake_mod)

    t = SerialTransport.open("/dev/ttyACM0")
    payload = b"\x01\x02\x03\x04"
    await t.write(payload)
    result = await t.read(len(payload))
    assert result == payload


@pytest.mark.asyncio
async def test_read_retries_on_empty(monkeypatch):
    """read() loops until data is available (simulating serial timeout gaps)."""
    # On the first two calls, fake_ser.read returns b''; on the third it has data.
    call_count = [0]
    original_data = b"\xAB\xCD"

    class _SlowSerial(_FakeSerial):
        def read(self, n):
            call_count[0] += 1
            if call_count[0] < 3:
                return b""  # simulate timeout with no data
            return original_data[:n]

    fake_ser = _SlowSerial("/dev/ttyACM0", 250000, SerialTransport.READ_TIMEOUT)
    fake_mod = _make_fake_serial_module(fake_instance=fake_ser)
    monkeypatch.setitem(sys.modules, "serial", fake_mod)

    t = SerialTransport.open("/dev/ttyACM0")
    result = await asyncio.wait_for(t.read(2), timeout=1.0)
    assert result == original_data[:2]
    assert call_count[0] >= 3


@pytest.mark.asyncio
async def test_close_calls_serial_close(monkeypatch):
    """close() calls serial.Serial.close()."""
    fake_ser = _FakeSerial("/dev/ttyACM0", 250000, SerialTransport.READ_TIMEOUT)
    fake_mod = _make_fake_serial_module(fake_instance=fake_ser)
    monkeypatch.setitem(sys.modules, "serial", fake_mod)

    t = SerialTransport.open("/dev/ttyACM0")
    assert not fake_ser.closed
    await t.close()
    assert fake_ser.closed


@pytest.mark.asyncio
async def test_close_tolerates_exception(monkeypatch):
    """close() does not raise if the underlying port raises."""

    class _BrokenSerial(_FakeSerial):
        def close(self):
            raise OSError("already closed")

    fake_ser = _BrokenSerial("/dev/ttyACM0", 250000, SerialTransport.READ_TIMEOUT)
    fake_mod = _make_fake_serial_module(fake_instance=fake_ser)
    monkeypatch.setitem(sys.modules, "serial", fake_mod)

    t = SerialTransport.open("/dev/ttyACM0")
    await t.close()  # must not raise

"""On-device self test for the protocol layer.

Runs under MicroPython on the ESP32. Validates that:
  - msgproto encodes / decodes round-trips
  - encode_frame produces valid frames
  - Queue + an in-memory loopback transport work end-to-end
  - send_with_response resolves correctly

There is no Klipper MCU involved; the loopback transport pipes the queue's
output back to its own input as if a perfect-RTT MCU instantly mirrored every
sent frame. This proves the host-side machinery works under MicroPython
exactly as it does under CPython.

Run with:
    mpremote connect port:/dev/tty.usbserial-3110 run src/device_selftest.py
"""

import asyncio
import sys
import time

from proto import msgproto
from proto.queue import Queue, encode_frame


PASS = "ok"
FAIL = "FAIL"


def _check(name, condition):
    label = PASS if condition else FAIL
    print("  [%s] %s" % (label, name))
    if not condition:
        raise AssertionError(name)


class _LoopbackTransport:
    """Tiny in-memory transport: writes go into a buffer that reads return."""

    def __init__(self):
        self.outbound = bytearray()
        self.inbound = bytearray()
        self._event = asyncio.Event()

    async def read(self, n):
        while not self.inbound:
            await self._event.wait()
            self._event.clear()
        data = bytes(self.inbound[:n])
        # Avoid `del bytearray[:n]` — not supported in all MicroPython builds.
        self.inbound = bytearray(self.inbound[n:])
        return data

    async def write(self, data):
        self.outbound.extend(data)

    def inject(self, data):
        self.inbound.extend(data)
        self._event.set()


def test_msgproto_basics():
    print("test_msgproto_basics:")
    mp = msgproto.MessageParser()
    _check("default messages loaded", len(mp.messages) == 2)
    _check(
        "identify command present",
        mp.messages_by_name["identify"].msgformat == "identify offset=%u count=%c",
    )
    cmd = mp.create_command("identify offset=0 count=40")
    _check("create_command returns bytes/list", len(cmd) > 0)


def test_frame_roundtrip():
    print("test_frame_roundtrip:")
    mp = msgproto.MessageParser()
    cmd = mp.create_command("identify offset=12 count=34")
    frame = encode_frame(cmd, send_seq=5)
    _check("frame length matches header byte", frame[0] == len(frame))
    _check(
        "seq byte has dest bit + low nibble",
        frame[1] == (5 & msgproto.MESSAGE_SEQ_MASK) | msgproto.MESSAGE_DEST,
    )
    _check("trailing sync byte", frame[-1] == msgproto.MESSAGE_SYNC)
    msglen = mp.check_packet(frame)
    _check("check_packet validates CRC", msglen == len(frame))
    params = mp.parse(frame)
    _check("decoded #name", params["#name"] == "identify")
    _check("decoded offset", params["offset"] == 12)
    _check("decoded count", params["count"] == 34)


async def test_queue_send_and_register_response():
    print("test_queue_send_and_register_response:")
    transport = _LoopbackTransport()
    mp = msgproto.MessageParser()
    q = Queue(transport, mp)
    q.start()
    try:
        received = []
        q.register_response(
            "identify_response", lambda p: received.append(p)
        )
        q.send("identify offset=0 count=40")
        # Drain TX
        deadline = time.ticks_add(time.ticks_ms(), 500)
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            if transport.outbound and transport.outbound[0] <= len(
                transport.outbound
            ):
                break
            await asyncio.sleep(0.005)
        _check("queue wrote a frame", len(transport.outbound) > 0)
        _check(
            "outbound frame validates",
            mp.check_packet(bytes(transport.outbound))
            == transport.outbound[0],
        )
        # Now feign an MCU response and ensure the handler fires
        resp_payload = mp.messages_by_name[
            "identify_response"
        ].encode_by_name(offset=0, data=b"hello")
        transport.inject(encode_frame(resp_payload, send_seq=0))
        deadline = time.ticks_add(time.ticks_ms(), 500)
        while not received and time.ticks_diff(deadline, time.ticks_ms()) > 0:
            await asyncio.sleep(0.005)
        _check("response handler fired", len(received) == 1)
        _check("response offset decoded", received[0]["offset"] == 0)
        _check("response data decoded", received[0]["data"] == b"hello")
    finally:
        await q.stop()


async def test_send_with_response():
    print("test_send_with_response:")
    transport = _LoopbackTransport()
    mp = msgproto.MessageParser()
    q = Queue(transport, mp)
    q.start()

    async def _responder():
        # Wait until a frame is written, then inject a matching response
        for _ in range(100):
            await asyncio.sleep(0.005)
            if transport.outbound and transport.outbound[0] <= len(
                transport.outbound
            ):
                break
        resp_payload = mp.messages_by_name[
            "identify_response"
        ].encode_by_name(offset=0, data=b"")
        transport.inject(encode_frame(resp_payload, send_seq=0))

    try:
        asyncio.create_task(_responder())
        params = await asyncio.wait_for(
            q.send_with_response(
                "identify offset=0 count=40", "identify_response"
            ),
            timeout=2.0,
        )
        _check("got identify_response", params["#name"] == "identify_response")
        _check("offset is 0", params["offset"] == 0)
        _check("data is empty", params["data"] == b"")
    finally:
        await q.stop()


async def _run():
    print("=== klipper-micro device self test ===")
    print("micropython:", sys.implementation)
    test_msgproto_basics()
    test_frame_roundtrip()
    await test_queue_send_and_register_response()
    await test_send_with_response()
    print("=== all passed ===")


asyncio.run(_run())

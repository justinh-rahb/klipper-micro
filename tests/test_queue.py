"""Tests for proto.queue using a pair of pipes (no network)."""

import asyncio

import pytest

from proto import msgproto
from proto.queue import Queue, encode_frame


class _MemTransport:
    """In-memory loopback transport. Useful for unit tests."""

    def __init__(self):
        self.outbound = bytearray()
        self.inbound = bytearray()
        self._inbound_event = asyncio.Event()

    # Queue calls these
    async def write(self, data):
        self.outbound.extend(data)

    async def read(self, n):
        while not self.inbound:
            await self._inbound_event.wait()
            self._inbound_event.clear()
        data = bytes(self.inbound[:n])
        del self.inbound[:n]
        return data

    # Test driver calls this to inject frames as if from the MCU
    def inject(self, data):
        self.inbound.extend(data)
        self._inbound_event.set()


@pytest.mark.asyncio
async def test_send_increments_seq():
    transport = _MemTransport()
    mp = msgproto.MessageParser()
    q = Queue(transport, mp)
    q.start()
    try:
        q.send("identify offset=0 count=40")
        q.send("identify offset=40 count=40")
        # Give the tx loop a chance to drain
        for _ in range(20):
            await asyncio.sleep(0.001)
            if len(transport.outbound) >= 2:
                first_len = transport.outbound[0]
                if len(transport.outbound) >= first_len + 1:
                    break
        # Two frames sent; sequence in byte 1 is (seq & 0x0f) | 0x10
        assert transport.outbound[1] == 0x10
        second_start = transport.outbound[0]
        assert transport.outbound[second_start + 1] == 0x11
    finally:
        await q.stop()


@pytest.mark.asyncio
async def test_send_with_response_resolves_on_match():
    transport = _MemTransport()
    mp = msgproto.MessageParser()
    q = Queue(transport, mp)
    q.start()
    try:
        # Kick off a send_with_response and immediately inject the response.
        # The mock will look like: identify_response offset=0 data=[]
        async def _injector():
            await asyncio.sleep(0.005)
            resp_payload = mp.messages_by_name["identify_response"].encode_by_name(
                offset=0, data=[]
            )
            transport.inject(encode_frame(resp_payload, send_seq=0))

        asyncio.create_task(_injector())
        params = await asyncio.wait_for(
            q.send_with_response("identify offset=0 count=40", "identify_response"),
            timeout=1.0,
        )
        assert params["offset"] == 0
        assert params["data"] == b""
    finally:
        await q.stop()


@pytest.mark.asyncio
async def test_register_response_persistent_handler():
    transport = _MemTransport()
    mp = msgproto.MessageParser()
    q = Queue(transport, mp)
    q.start()
    received = []
    q.register_response("identify_response", lambda p: received.append(p))
    try:
        resp_payload = mp.messages_by_name["identify_response"].encode_by_name(
            offset=99, data=b"hi"
        )
        transport.inject(encode_frame(resp_payload, send_seq=0))
        for _ in range(20):
            await asyncio.sleep(0.005)
            if received:
                break
        assert len(received) == 1
        assert received[0]["offset"] == 99
        assert received[0]["data"] == b"hi"
    finally:
        await q.stop()


@pytest.mark.asyncio
async def test_bad_crc_triggers_resync_and_recovers():
    transport = _MemTransport()
    mp = msgproto.MessageParser()
    q = Queue(transport, mp)
    q.start()
    received = []
    q.register_response("identify_response", lambda p: received.append(p))
    try:
        # Garbage bytes, then a valid frame after a sync byte
        transport.inject(bytes([0xFF, 0xFF, 0xFF, 0xFF, msgproto.MESSAGE_SYNC]))
        resp_payload = mp.messages_by_name["identify_response"].encode_by_name(
            offset=0, data=b"x"
        )
        transport.inject(encode_frame(resp_payload, send_seq=0))
        for _ in range(20):
            await asyncio.sleep(0.005)
            if received:
                break
        assert len(received) == 1
        assert q.stats["crc_errors"] >= 1
    finally:
        await q.stop()

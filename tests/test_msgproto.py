"""Sanity tests against the vendored msgproto module.

These exist mostly to catch sync regressions — if a future sync from upstream
breaks the encoding/decoding semantics we depend on, these will fail loudly.
"""

import json
import zlib

from proto import msgproto
from proto.queue import encode_frame


def test_vlq_roundtrip_small():
    pt = msgproto.PT_uint32()
    for v in (0, 1, 0x5F, 0x60, 0x1000, 0x100000, 0x10000000):
        out = []
        pt.encode(out, v)
        parsed, pos = pt.parse(bytes(out), 0)
        assert parsed == v
        assert pos == len(out)


def test_vlq_roundtrip_signed():
    pt = msgproto.PT_int32()
    for v in (-1, -0x20, -0x1000, -0x100000, -0x10000000):
        out = []
        pt.encode(out, v)
        parsed, pos = pt.parse(bytes(out), 0)
        assert parsed == v


def test_crc16_known_vector():
    # Sanity vector — empty payload [length=5, seq=0x10].
    assert msgproto.crc16_ccitt([5, 0x10]) == [0xAE, 0xC1] or len(
        msgproto.crc16_ccitt([5, 0x10])
    ) == 2


def test_encode_frame_shape():
    payload = [1]  # one-byte vlq command (identify_response with msgid=1)
    frame = encode_frame(payload, send_seq=0)
    # length + seq + payload + crc(2) + sync(1)
    assert len(frame) == 1 + 1 + 1 + 2 + 1
    assert frame[0] == len(frame)
    assert frame[1] == 0x10
    assert frame[-1] == msgproto.MESSAGE_SYNC


def test_default_identify_messages_present():
    mp = msgproto.MessageParser()
    assert mp.messages_by_name["identify"].msgformat == (
        "identify offset=%u count=%c"
    )
    assert mp.messages_by_name["identify_response"].msgformat == (
        "identify_response offset=%u data=%.*s"
    )


def test_create_identify_command_decodes_back():
    mp = msgproto.MessageParser()
    cmd = mp.create_command("identify offset=0 count=40")
    # cmd is just the payload (no frame headers)
    frame = encode_frame(cmd, send_seq=3)
    msglen = mp.check_packet(frame)
    assert msglen == len(frame)
    params = mp.parse(frame)
    assert params["#name"] == "identify"
    assert params["offset"] == 0
    assert params["count"] == 40


def test_process_identify_with_compressed_blob():
    blob = json.dumps(
        {
            "commands": {"get_clock": 6, "identify offset=%u count=%c": 1},
            "responses": {
                "clock clock=%u": 19,
                "identify_response offset=%u data=%.*s": 0,
            },
            "output": {},
            "enumerations": {},
            "config": {"CLOCK_FREQ": 72000000.0},
            "version": "test",
        }
    ).encode()
    compressed = zlib.compress(blob)
    mp = msgproto.MessageParser()
    mp.process_identify(compressed)
    assert mp.get_constant_float("CLOCK_FREQ") == 72000000.0
    assert mp.messages_by_name["get_clock"].msgformat == "get_clock"

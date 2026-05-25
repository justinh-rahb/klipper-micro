"""Mock Klipper MCU for host-side testing.

Implements just enough of the Klipper firmware protocol to let our host code
complete a full handshake (identify + clock sync) and exercise PWM/analog
commands. Serves over TCP so tests can connect from any process.

Run standalone:
    python tests/mock_mcu.py --port 5555

In tests, instantiate :class:`MockMcu` and start it as an asyncio task.

The identify dictionary is fixed; message IDs are stable across runs so test
fixtures can be deterministic.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
import zlib

# Make src/ importable when running from the repo root or tests/.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(REPO_ROOT, "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from proto import msgproto  # noqa: E402
from proto.queue import encode_frame  # noqa: E402

logger = logging.getLogger("mock_mcu")


# Canonical identify dictionary used by the mock. Format strings and IDs are
# stable; tests can rely on them.
IDENTIFY_DICT = {
    "commands": {
        "identify offset=%u count=%c": 1,
        "get_uptime": 5,
        "get_clock": 6,
        "get_config": 7,
        "allocate_oids count=%c": 8,
        "finalize_config crc=%u": 9,
        "config_pwm_out oid=%c pin=%u cycle_ticks=%u value=%hu"
        " default_value=%hu max_duration=%u": 10,
        "queue_pwm_out oid=%c clock=%u value=%hu": 11,
        "set_pwm_out pin=%u cycle_ticks=%u value=%hu": 12,
        "config_analog_in oid=%c pin=%u": 13,
        "query_analog_in oid=%c clock=%u sample_ticks=%u sample_count=%c"
        " rest_ticks=%u min_value=%hu max_value=%hu range_check_count=%c": 14,
        "emergency_stop": 15,
        "clear_shutdown": 16,
    },
    "responses": {
        "identify_response offset=%u data=%.*s": 0,
        "uptime high=%u clock=%u": 18,
        "clock clock=%u": 19,
        "config is_config=%c crc=%u is_shutdown=%c move_count=%hu": 20,
        "analog_in_state oid=%c next_clock=%u value=%hu": 21,
    },
    "output": {},
    "enumerations": {
        "pin": {"PA0": 0, "PA1": 1, "PA2": 2, "PA3": 3, "PA4": 4},
    },
    "config": {
        "CLOCK_FREQ": 72000000,
        "MCU": "stm32f103",
        "SERIAL_BAUD": 250000,
        "STATS_SUMSQ_BASE": 256,
    },
    "version": "v0.13.0-mock",
    "build_versions": "mock-build",
}


def _build_identify_blob():
    raw = json.dumps(IDENTIFY_DICT).encode("utf-8")
    return zlib.compress(raw)


IDENTIFY_BLOB = _build_identify_blob()


class MockMcu:
    """One MCU instance bound to a single client connection."""

    def __init__(self):
        self.start_time = time.monotonic()
        self.send_seq = 0
        self.mcu_freq = float(IDENTIFY_DICT["config"]["CLOCK_FREQ"])
        # Parser for *incoming* host commands. We seed it with the same dict
        # we hand out, so we can decode whatever the host sends us.
        self.parser = msgproto.MessageParser()
        self.parser.process_identify(IDENTIFY_BLOB)
        # State
        self.oids_allocated = 0
        self.is_config = False
        self.is_shutdown = False
        self.config_crc = 0
        # Dispatch table: command name -> handler(params) -> Optional[(name, kwargs)]
        # Each handler returns either None (no response) or a (response_name,
        # kwargs) tuple to send back.
        self._handlers = {
            "identify": self._h_identify,
            "get_uptime": self._h_get_uptime,
            "get_clock": self._h_get_clock,
            "get_config": self._h_get_config,
            "allocate_oids": self._h_allocate_oids,
            "finalize_config": self._h_finalize_config,
            "config_pwm_out": self._h_noop,
            "queue_pwm_out": self._h_noop,
            "set_pwm_out": self._h_noop,
            "config_analog_in": self._h_noop,
            "query_analog_in": self._h_noop,
            "emergency_stop": self._h_emergency_stop,
            "clear_shutdown": self._h_clear_shutdown,
        }

    # ------------------------------------------------------------------
    # Clock model
    # ------------------------------------------------------------------

    def current_clock(self):
        elapsed = time.monotonic() - self.start_time
        return int(elapsed * self.mcu_freq) & 0xFFFFFFFFFFFFFFFF

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _h_identify(self, params):
        offset = params["offset"]
        count = params["count"]
        chunk = IDENTIFY_BLOB[offset : offset + count]
        return ("identify_response", {"offset": offset, "data": list(chunk)})

    def _h_get_uptime(self, params):
        c = self.current_clock()
        return (
            "uptime",
            {"high": (c >> 32) & 0xFFFFFFFF, "clock": c & 0xFFFFFFFF},
        )

    def _h_get_clock(self, params):
        return ("clock", {"clock": self.current_clock() & 0xFFFFFFFF})

    def _h_get_config(self, params):
        return (
            "config",
            {
                "is_config": 1 if self.is_config else 0,
                "crc": self.config_crc,
                "is_shutdown": 1 if self.is_shutdown else 0,
                "move_count": 1024,
            },
        )

    def _h_allocate_oids(self, params):
        self.oids_allocated = params["count"]
        return None

    def _h_finalize_config(self, params):
        self.is_config = True
        self.config_crc = params["crc"]
        return None

    def _h_noop(self, params):
        return None

    def _h_emergency_stop(self, params):
        self.is_shutdown = True
        return None

    def _h_clear_shutdown(self, params):
        self.is_shutdown = False
        return None

    # ------------------------------------------------------------------
    # Frame dispatch
    # ------------------------------------------------------------------

    def encode_response(self, name, fields):
        mp = self.parser.messages_by_name[name]
        payload = mp.encode_by_name(**fields)
        frame = encode_frame(payload, self.send_seq)
        self.send_seq = (self.send_seq + 1) & msgproto.MESSAGE_SEQ_MASK
        return frame

    def process_frame(self, frame):
        """Decode one incoming frame and yield outbound frames in response.

        A single host frame can carry multiple commands; each may or may not
        produce a response.
        """
        pos = msgproto.MESSAGE_HEADER_SIZE
        end = len(frame) - msgproto.MESSAGE_TRAILER_SIZE
        out = []
        while pos < end:
            msgid, _ = self.parser.msgid_parser.parse(frame, pos)
            mid = self.parser.messages_by_id.get(msgid)
            if mid is None:
                logger.warning("mock: unknown msgid %d", msgid)
                return out
            params, new_pos = mid.parse(frame, pos)
            handler = self._handlers.get(mid.name)
            if handler is None:
                logger.debug("mock: no handler for %s", mid.name)
            else:
                result = handler(params)
                if result is not None:
                    resp_name, resp_fields = result
                    out.append(self.encode_response(resp_name, resp_fields))
            pos = new_pos
        return out


# ----------------------------------------------------------------------
# TCP server
# ----------------------------------------------------------------------


async def _serve_client(reader, writer):
    addr = writer.get_extra_info("peername")
    logger.info("client connected: %s", addr)
    mcu = MockMcu()
    buf = bytearray()
    pos = 0
    need_sync = False
    try:
        while True:
            chunk = await reader.read(64)
            if not chunk:
                break
            buf.extend(chunk)
            while pos < len(buf):
                if need_sync:
                    idx = buf.find(msgproto.MESSAGE_SYNC, pos)
                    if idx < 0:
                        pos = len(buf)
                        break
                    pos = idx + 1
                    need_sync = False
                    continue
                view = bytes(buf[pos:])
                res = mcu.parser.check_packet(view)
                if res == 0:
                    break
                if res < 0:
                    logger.warning("mock: bad frame, resyncing")
                    need_sync = True
                    continue
                frame = bytes(buf[pos : pos + res])
                pos += res
                for resp in mcu.process_frame(frame):
                    writer.write(resp)
                await writer.drain()
            if pos >= 64 or (pos and pos >= len(buf)):
                buf = bytearray(buf[pos:])
                pos = 0
    except (ConnectionResetError, asyncio.CancelledError):
        pass
    finally:
        logger.info("client disconnected: %s", addr)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def serve(host="127.0.0.1", port=5555):
    server = await asyncio.start_server(_serve_client, host, port)
    sockets = ", ".join(str(s.getsockname()) for s in server.sockets)
    logger.info("mock MCU listening on %s", sockets)
    return server


async def _main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    server = await serve(args.host, args.port)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        pass

"""MCU bring-up handshake.

Runs the identify dialogue, loads the data dictionary, primes clock sync, and
returns a connected (queue, clocksync) pair ready for device configuration.

Mirrors the sequence in klippy/serialhdl.py:_get_identify_data plus
clocksync.ClockSync.connect.
"""

import logging

from . import msgproto
from .clocksync import ClockSync
from .queue import Queue

logger = logging.getLogger(__name__)


IDENTIFY_CHUNK = 40


async def fetch_identify(queue):
    """Loop identify offset=N count=40 until the MCU returns an empty chunk."""
    blob = b""
    while True:
        msg = "identify offset=%d count=%d" % (len(blob), IDENTIFY_CHUNK)
        params = await queue.send_with_response(msg, "identify_response")
        if params["offset"] != len(blob):
            # MCU returned a stale chunk — keep asking
            continue
        data = params["data"]
        if not data:
            return blob
        blob += data


async def connect(transport):
    """Open a handshake with the MCU and return a live (queue, clocksync)."""
    msgparser = msgproto.MessageParser()
    queue = Queue(transport, msgparser)
    queue.start()
    try:
        # The default DefaultMessages dictionary in msgproto.py already knows
        # the identify command/response IDs, so we can query immediately.
        identify_blob = await fetch_identify(queue)
        logger.info("identify blob: %d bytes compressed", len(identify_blob))
        msgparser.process_identify(identify_blob)
        logger.info(
            "loaded data dictionary: %d commands, %d responses, version=%s",
            sum(1 for _, t, _ in msgparser.get_messages() if t == "command"),
            sum(1 for _, t, _ in msgparser.get_messages() if t == "response"),
            msgparser.get_version_info()[0],
        )
        # Prime clock sync
        clocksync = ClockSync(queue)
        await clocksync.connect()
        logger.info(
            "clocksync online: mcu_freq=%d est_freq=%.1f",
            int(clocksync.mcu_freq),
            clocksync.clock_est[2],
        )
        return queue, clocksync
    except Exception:
        await queue.stop()
        raise

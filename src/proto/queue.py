"""Command queue and frame dispatcher for one Klipper MCU connection.

Replaces Klipper's C serialqueue.c with a pure-Python asyncio implementation.
The MCU protocol is the same; only the host-side plumbing is reimplemented so
it runs on MicroPython.

Two background tasks:
  - rx_loop: pulls bytes from the transport, finds frames, decodes, dispatches
  - tx_loop: pulls outbound commands and writes framed bytes to the transport

Synchronous request/reply uses send_with_response: it registers a one-shot
future, retries the send on timeout, and resolves on the matching response.
This matches Klipper's SerialRetryCommand pattern.
"""

import asyncio
import logging
import time

from . import msgproto

logger = logging.getLogger(__name__)


# Portable monotonic-seconds clock.
# CPython has time.monotonic; MicroPython doesn't. ticks_ms/ticks_us are 30-bit
# wrapping counters intended for ticks_diff(), so we anchor against a base on
# first call and add up ms deltas. Good for our use (RTT/regression timing
# only cares about ~seconds-scale relative deltas).
try:
    monotonic = time.monotonic  # CPython
except AttributeError:
    _mono_base_ms = time.ticks_ms()
    _mono_accum = 0.0
    _mono_last_ms = _mono_base_ms

    def monotonic():
        global _mono_accum, _mono_last_ms
        now_ms = time.ticks_ms()
        delta = time.ticks_diff(now_ms, _mono_last_ms)
        _mono_last_ms = now_ms
        _mono_accum += delta / 1000.0
        return _mono_accum


def encode_frame(payload, send_seq):
    """Wrap a VLQ-encoded payload (iterable of bytes) in a Klipper frame."""
    payload = list(payload)
    msg_len = msgproto.MESSAGE_MIN + len(payload)
    if msg_len > msgproto.MESSAGE_MAX:
        raise ValueError("frame too long: %d > %d" % (msg_len, msgproto.MESSAGE_MAX))
    seq_byte = (send_seq & msgproto.MESSAGE_SEQ_MASK) | msgproto.MESSAGE_DEST
    out = [msg_len, seq_byte] + payload
    out.extend(msgproto.crc16_ccitt(out))
    out.append(msgproto.MESSAGE_SYNC)
    return bytes(out)


class _AsyncFifo:
    """Minimal asyncio FIFO. MicroPython's asyncio doesn't ship a Queue.

    Only the small subset used by Queue is implemented: put_nowait, async put,
    async get. FIFO order preserved.
    """

    __slots__ = ("_items", "_event")

    def __init__(self):
        self._items = []
        self._event = asyncio.Event()

    def put_nowait(self, item):
        self._items.append(item)
        self._event.set()

    async def put(self, item):
        self._items.append(item)
        self._event.set()

    async def get(self):
        while not self._items:
            await self._event.wait()
            # Clear only after we've consumed; another producer may have set it
            if not self._items:
                self._event.clear()
        item = self._items.pop(0)
        if not self._items:
            self._event.clear()
        return item


class _Waiter:
    """Event-backed one-shot result holder.

    asyncio.Future is not available on MicroPython, so we roll a minimal
    equivalent on top of asyncio.Event which IS available everywhere.
    """

    __slots__ = ("_event", "_result", "_exception")

    def __init__(self):
        self._event = asyncio.Event()
        self._result = None
        self._exception = None

    def set_result(self, value):
        if self._event.is_set():
            return
        self._result = value
        self._event.set()

    def set_exception(self, exc):
        if self._event.is_set():
            return
        self._exception = exc
        self._event.set()

    def done(self):
        return self._event.is_set()

    def result(self):
        if not self._event.is_set():
            raise RuntimeError("Waiter not done")
        if self._exception is not None:
            raise self._exception
        return self._result

    async def wait(self):
        await self._event.wait()
        if self._exception is not None:
            raise self._exception
        return self._result


class _PendingResponse:
    """A waiter registered for a (name, oid) response."""

    __slots__ = ("oid", "waiter")

    def __init__(self, oid, waiter):
        self.oid = oid
        self.waiter = waiter


class Queue:
    """Asyncio-based command queue for a single MCU.

    Lifecycle:
      q = Queue(transport, msgparser)
      q.start()                      # spawn rx_loop, tx_loop
      params = await q.send_with_response('get_uptime', 'uptime')
      ...
      await q.stop()
    """

    # Retry timing, matching SerialRetryCommand defaults
    INITIAL_RETRY_DELAY = 0.010
    MAX_RETRIES = 5

    def __init__(self, transport, msgparser):
        self.transport = transport
        self.msgparser = msgparser
        # Outbound sequence — incremented per frame we send
        self.send_seq = 0
        # Inbound sequence tracking — for duplicate detection
        self.last_recv_seq = -1
        # Response handlers registered via register_response: (name, oid) -> cb
        self.handlers = {}
        # send_with_response futures: (name, oid) -> list[_PendingResponse]
        self.response_waiters = {}
        # Outgoing queue. Items are (payload_bytes, future_or_None).
        # The future, if present, is resolved once the frame is transmitted.
        self._tx_queue = _AsyncFifo()
        # Clock estimate, updated by clocksync; used to convert system time
        # to MCU clock for scheduled commands.
        self.clock_est = (0.0, 0, 1.0)  # (sys_time, mcu_clock, mcu_freq)
        self.last_clock = 0  # 64-bit extended last seen MCU clock
        # Background task handles
        self._rx_task = None
        self._tx_task = None
        # Stats
        self.stats = {
            "bytes_sent": 0,
            "bytes_received": 0,
            "frames_sent": 0,
            "frames_received": 0,
            "retransmits": 0,
            "crc_errors": 0,
            "unknown_responses": 0,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self):
        # Must be called from within a running event loop (async context).
        self._rx_task = asyncio.create_task(self._rx_loop())
        self._tx_task = asyncio.create_task(self._tx_loop())

    async def stop(self):
        for t in (self._rx_task, self._tx_task):
            if t is not None:
                t.cancel()
        for t in (self._rx_task, self._tx_task):
            if t is not None:
                try:
                    await t
                except (asyncio.CancelledError, Exception):
                    pass
        self._rx_task = self._tx_task = None
        # Fail any outstanding waiters
        for waiters in self.response_waiters.values():
            for w in waiters:
                if not w.waiter.done():
                    w.waiter.set_exception(OSError("queue stopped"))
        self.response_waiters.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_response(self, name, callback, oid=None):
        """Register a persistent handler for a named response.

        Pass callback=None to remove a previously registered handler.
        Callback receives a single dict of parsed parameters.
        """
        key = (name, oid)
        if callback is None:
            self.handlers.pop(key, None)
        else:
            self.handlers[key] = callback

    def send(self, msg):
        """Encode a textual command and enqueue it for transmission.

        Fire-and-forget. The frame is sent as soon as the tx loop drains.
        """
        cmd = self.msgparser.create_command(msg)
        self._tx_queue.put_nowait((cmd, None))

    async def send_with_response(self, msg, response_name, oid=None):
        """Send a command and await a named response.

        Retries up to MAX_RETRIES with exponential backoff, mirroring
        Klipper's SerialRetryCommand. Raises OSError on exhaustion.
        """
        cmd = self.msgparser.create_command(msg)
        waiter = _Waiter()
        pending = _PendingResponse(oid, waiter)
        key = (response_name, oid)
        self.response_waiters.setdefault(key, []).append(pending)
        delay = self.INITIAL_RETRY_DELAY
        try:
            for attempt in range(self.MAX_RETRIES + 1):
                await self._enqueue_and_wait_send(cmd)
                if attempt > 0:
                    self.stats["retransmits"] += 1
                try:
                    await asyncio.wait_for(waiter.wait(), delay)
                    return waiter.result()
                except asyncio.TimeoutError:
                    if waiter.done():
                        return waiter.result()
                    delay *= 2.0
            raise OSError(
                "no '%s' response after %d retries"
                % (response_name, self.MAX_RETRIES)
            )
        finally:
            waiters = self.response_waiters.get(key)
            if waiters and pending in waiters:
                waiters.remove(pending)
                if not waiters:
                    del self.response_waiters[key]

    def update_clock_est(self, sys_time, mcu_clock, mcu_freq):
        """Called by clocksync to update the system-time → MCU-clock map."""
        self.clock_est = (sys_time, mcu_clock, mcu_freq)

    def estimate_mcu_clock(self, sys_time=None):
        """Return an estimated 64-bit MCU clock for the given system time."""
        if sys_time is None:
            sys_time = monotonic()
        sample_time, sample_clock, freq = self.clock_est
        return int(sample_clock + (sys_time - sample_time) * freq)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _enqueue_and_wait_send(self, cmd):
        """Push a payload onto the tx queue and wait for it to be written."""
        sent = _Waiter()
        await self._tx_queue.put((cmd, sent))
        await sent.wait()

    async def _tx_loop(self):
        try:
            while True:
                payload, sent = await self._tx_queue.get()
                frame = encode_frame(payload, self.send_seq)
                self.send_seq = (self.send_seq + 1) & msgproto.MESSAGE_SEQ_MASK
                try:
                    await self.transport.write(frame)
                except Exception as exc:
                    if sent is not None and not sent.done():
                        sent.set_exception(exc)
                    raise
                self.stats["frames_sent"] += 1
                self.stats["bytes_sent"] += len(frame)
                if sent is not None and not sent.done():
                    sent.set_result(None)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("tx loop failed")
            raise

    async def _rx_loop(self):
        # MicroPython's bytearray doesn't support `del buf[:n]` in every
        # build, so we keep a read-pointer and periodically compact instead.
        buf = bytearray()
        pos = 0
        need_sync = False
        try:
            while True:
                chunk = await self.transport.read(64)
                if not chunk:
                    await asyncio.sleep(0.01)
                    continue
                buf.extend(chunk)
                self.stats["bytes_received"] += len(chunk)
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
                    res = self.msgparser.check_packet(view)
                    if res == 0:
                        break
                    if res < 0:
                        self.stats["crc_errors"] += 1
                        need_sync = True
                        continue
                    frame = bytes(buf[pos : pos + res])
                    pos += res
                    self._handle_frame(frame)
                # Compact the buffer once we've consumed enough
                if pos >= 64 or (pos and pos >= len(buf)):
                    buf = bytearray(buf[pos:])
                    pos = 0
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("rx loop failed")
            raise

    def _handle_frame(self, frame):
        self.stats["frames_received"] += 1
        # Walk the payload — a frame can carry multiple back-to-back messages
        pos = msgproto.MESSAGE_HEADER_SIZE
        end = len(frame) - msgproto.MESSAGE_TRAILER_SIZE
        sent_time = monotonic()
        while pos < end:
            try:
                msgid, _ = self.msgparser.msgid_parser.parse(frame, pos)
                mid = self.msgparser.messages_by_id.get(msgid, self.msgparser.unknown)
                params, new_pos = mid.parse(frame, pos)
            except Exception:
                logger.exception("failed to parse message in frame")
                return
            params["#name"] = mid.name
            params["#sent_time"] = sent_time
            params["#receive_time"] = sent_time
            self._dispatch(mid.name, params)
            if new_pos <= pos:
                # parser didn't advance — guard against infinite loop
                logger.error("parser stalled at pos=%d", pos)
                return
            pos = new_pos

    def _dispatch(self, name, params):
        # Track MCU clock for 32→64-bit extension if present
        if "clock" in params and isinstance(params["clock"], int):
            last = self.last_clock
            delta = (params["clock"] - last) & 0xFFFFFFFF
            self.last_clock = last + delta
        # Wake one-shot waiters first (send_with_response)
        oid = params.get("oid")
        waiters = self.response_waiters.get((name, oid))
        if not waiters:
            waiters = self.response_waiters.get((name, None))
        if waiters:
            pending = waiters[0]
            if not pending.waiter.done():
                pending.waiter.set_result(params)
        # Then call any persistent handler (register_response)
        cb = self.handlers.get((name, oid)) or self.handlers.get((name, None))
        if cb is not None:
            try:
                cb(params)
            except Exception:
                logger.exception("response handler for %s raised", name)
        elif not waiters:
            self.stats["unknown_responses"] += 1

"""MCU clock synchronisation.

Asyncio adapter around Klipper's clocksync.ClockSync regression. The math is
copied verbatim from vendor/klipper/klippy/clocksync.py (synced to
_vendor_clocksync.py for reference and diff-tracking); only the framework
plumbing — Klipper's reactor + chelper's set_clock_est — is replaced with
asyncio + our Queue.update_clock_est.

We deliberately do not subclass or import the vendor module: it pulls in
serial.set_clock_est (a chelper FFI call) and a Reactor object. Copying the
algorithm keeps the runtime free of those dependencies while preserving the
constants that make the regression converge nicely.
"""

import asyncio
import logging
import math

from .queue import monotonic

logger = logging.getLogger(__name__)


# Constants — copied from klippy/clocksync.py
RTT_AGE = 0.000010 / (60.0 * 60.0)
DECAY = 1.0 / 30.0
TRANSMIT_EXTRA = 0.001


class ClockSync:
    """Estimate MCU clock as a function of host monotonic time.

    Usage:
        cs = ClockSync(queue)
        await cs.connect()       # primes regression, starts background poll
        ...
        mcu_clock = cs.get_clock(monotonic())
        await cs.stop()
    """

    POLL_INTERVAL = 0.9839  # offset from round numbers so messages don't beat

    def __init__(self, queue):
        self.queue = queue
        self.mcu_freq = 1.0
        self.last_clock = 0
        self.clock_est = (0.0, 0.0, 0.0)  # (sample_time, clock_avg, freq)
        # Minimum round-trip-time tracking
        self.min_half_rtt = 999999999.9
        self.min_rtt_time = 0.0
        # Linear regression of MCU clock against host sent_time
        self.time_avg = self.time_variance = 0.0
        self.clock_avg = self.clock_covariance = 0.0
        self.prediction_variance = 0.0
        self.last_prediction_time = 0.0
        self.queries_pending = 0
        self._poll_task = None

    async def connect(self):
        """Prime the regression and start periodic polling."""
        self.mcu_freq = self.queue.msgparser.get_constant_float("CLOCK_FREQ")
        # Seed 64-bit clock from get_uptime
        params = await self.queue.send_with_response("get_uptime", "uptime")
        self.last_clock = (params["high"] << 32) | params["clock"]
        self.queue.last_clock = self.last_clock
        self.clock_avg = float(self.last_clock)
        self.time_avg = params["#sent_time"]
        self.clock_est = (self.time_avg, self.clock_avg, self.mcu_freq)
        self.prediction_variance = (0.001 * self.mcu_freq) ** 2
        # Push an initial estimate into the queue
        self.queue.update_clock_est(self.time_avg, int(self.clock_avg), self.mcu_freq)
        # Take eight tight samples to anchor the regression
        for _ in range(8):
            await asyncio.sleep(0.050)
            self.last_prediction_time = -9999.0
            params = await self.queue.send_with_response("get_clock", "clock")
            self._handle_clock(params)
        # Register the persistent handler and start the background poll
        self.queue.register_response("clock", self._handle_clock)
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None
        self.queue.register_response("clock", None)

    async def _poll_loop(self):
        try:
            while True:
                await asyncio.sleep(self.POLL_INTERVAL)
                self.queue.send("get_clock")
                self.queries_pending += 1
        except asyncio.CancelledError:
            raise

    def _handle_clock(self, params):
        """Run one regression update. Math is verbatim from upstream."""
        self.queries_pending = 0
        # Extend 32-bit clock to 64-bit
        last_clock = self.last_clock
        clock_delta = (params["clock"] - last_clock) & 0xFFFFFFFF
        self.last_clock = clock = last_clock + clock_delta
        self.queue.last_clock = self.last_clock
        sent_time = params.get("#sent_time", 0.0)
        if not sent_time:
            return
        receive_time = params.get("#receive_time", sent_time)
        half_rtt = 0.5 * (receive_time - sent_time)
        aged_rtt = (sent_time - self.min_rtt_time) * RTT_AGE
        if half_rtt < self.min_half_rtt + aged_rtt:
            self.min_half_rtt = half_rtt
            self.min_rtt_time = sent_time
        # Outlier filter
        exp_clock = (
            (sent_time - self.time_avg) * self.clock_est[2] + self.clock_avg
        )
        clock_diff2 = (clock - exp_clock) ** 2
        if clock_diff2 > 25.0 * self.prediction_variance and clock_diff2 > (
            0.000500 * self.mcu_freq
        ) ** 2:
            if (
                clock > exp_clock
                and sent_time < self.last_prediction_time + 10.0
            ):
                return
            logger.info(
                "resetting prediction variance: freq=%d diff=%d stddev=%.3f",
                int(self.clock_est[2]),
                clock - exp_clock,
                math.sqrt(self.prediction_variance),
            )
            self.prediction_variance = (0.001 * self.mcu_freq) ** 2
        else:
            self.last_prediction_time = sent_time
            self.prediction_variance = (1.0 - DECAY) * (
                self.prediction_variance + clock_diff2 * DECAY
            )
        # Linear regression
        diff_sent_time = sent_time - self.time_avg
        self.time_avg += DECAY * diff_sent_time
        self.time_variance = (1.0 - DECAY) * (
            self.time_variance + diff_sent_time ** 2 * DECAY
        )
        diff_clock = clock - self.clock_avg
        self.clock_avg += DECAY * diff_clock
        self.clock_covariance = (1.0 - DECAY) * (
            self.clock_covariance + diff_sent_time * diff_clock * DECAY
        )
        # Update prediction
        if self.time_variance:
            new_freq = self.clock_covariance / self.time_variance
        else:
            new_freq = self.mcu_freq
        self.clock_est = (
            self.time_avg + self.min_half_rtt,
            self.clock_avg,
            new_freq,
        )
        self.queue.update_clock_est(
            self.time_avg + TRANSMIT_EXTRA, int(self.clock_avg), new_freq
        )

    # ------------------------------------------------------------------
    # Public conversions
    # ------------------------------------------------------------------

    def get_clock(self, sys_time):
        sample_time, clock, freq = self.clock_est
        return int(clock + (sys_time - sample_time) * freq)

    def estimate_clock_systime(self, mcu_clock):
        sample_time, clock, freq = self.clock_est
        return float(mcu_clock - clock) / freq + sample_time

    def is_active(self):
        return self.queries_pending <= 4

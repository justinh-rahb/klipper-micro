// SPDX-License-Identifier: GPL-3.0-or-later
#include "klipper_clocksync.h"

#include <math.h>
#include <string.h>

#define KM_RTT_AGE (0.000010 / (60.0 * 60.0))
#define KM_DECAY (1.0 / 30.0)
#define KM_TRANSMIT_EXTRA 0.001

static double seconds(int64_t microseconds)
{
    return (double)microseconds / 1000000.0;
}

void km_clocksync_init(km_clocksync_t *sync, uint32_t frequency,
                       uint32_t uptime_high, uint32_t uptime_clock,
                       int64_t sent_us, int64_t received_us)
{
    (void)received_us;
    memset(sync, 0, sizeof(*sync));
    sync->nominal_frequency = frequency;
    sync->last_clock = ((uint64_t)uptime_high << 32) | uptime_clock;
    sync->clock_average = (double)sync->last_clock;
    sync->time_average = seconds(sent_us);
    sync->estimate_time = sync->time_average;
    sync->estimate_clock = sync->clock_average;
    sync->estimate_frequency = frequency;
    sync->prediction_variance = pow(0.001 * frequency, 2.0);
    sync->min_half_rtt = 999999999.9;
    sync->initialized = true;
}

bool km_clocksync_update(km_clocksync_t *sync, uint32_t clock32,
                         int64_t sent_us, int64_t received_us)
{
    if (!sync || !sync->initialized) return false;
    const uint32_t delta = clock32 - (uint32_t)sync->last_clock;
    const uint64_t clock = sync->last_clock + delta;
    sync->last_clock = clock;
    const double sent_time = seconds(sent_us);
    const double receive_time = seconds(received_us);
    const double half_rtt = 0.5 * (receive_time - sent_time);
    const double aged_rtt = (sent_time - sync->min_rtt_time) * KM_RTT_AGE;
    if (half_rtt < sync->min_half_rtt + aged_rtt) {
        sync->min_half_rtt = half_rtt;
        sync->min_rtt_time = sent_time;
    }

    const double expected = (sent_time - sync->time_average)
        * sync->estimate_frequency + sync->clock_average;
    const double difference = (double)clock - expected;
    const double difference_squared = difference * difference;
    const double outlier_floor = 0.000500 * sync->nominal_frequency;
    if (difference_squared > 25.0 * sync->prediction_variance
        && difference_squared > outlier_floor * outlier_floor) {
        if (clock > expected
            && sent_time < sync->last_prediction_time + 10.0) return false;
        sync->prediction_variance =
            pow(0.001 * sync->nominal_frequency, 2.0);
    } else {
        sync->last_prediction_time = sent_time;
        sync->prediction_variance = (1.0 - KM_DECAY)
            * (sync->prediction_variance + difference_squared * KM_DECAY);
    }

    const double time_difference = sent_time - sync->time_average;
    sync->time_average += KM_DECAY * time_difference;
    sync->time_variance = (1.0 - KM_DECAY)
        * (sync->time_variance + time_difference * time_difference * KM_DECAY);
    const double clock_difference = (double)clock - sync->clock_average;
    sync->clock_average += KM_DECAY * clock_difference;
    sync->clock_covariance = (1.0 - KM_DECAY)
        * (sync->clock_covariance
           + time_difference * clock_difference * KM_DECAY);
    const double frequency = sync->time_variance != 0.0
        ? sync->clock_covariance / sync->time_variance
        : sync->nominal_frequency;
    sync->estimate_time = sync->time_average + KM_TRANSMIT_EXTRA;
    sync->estimate_clock = sync->clock_average;
    sync->estimate_frequency = frequency;
    return true;
}

uint64_t km_clocksync_clock_at(const km_clocksync_t *sync, int64_t system_us)
{
    if (!sync || !sync->initialized) return 0;
    const double clock = sync->estimate_clock
        + (seconds(system_us) - sync->estimate_time) * sync->estimate_frequency;
    return clock > 0.0 ? (uint64_t)clock : 0;
}

double km_clocksync_system_time(const km_clocksync_t *sync,
                                uint64_t mcu_clock)
{
    if (!sync || !sync->initialized || sync->estimate_frequency == 0.0)
        return 0.0;
    return ((double)mcu_clock - sync->estimate_clock)
        / sync->estimate_frequency + sync->estimate_time;
}

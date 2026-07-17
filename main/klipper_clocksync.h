// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef struct {
    double nominal_frequency;
    uint64_t last_clock;
    double min_half_rtt;
    double min_rtt_time;
    double time_average;
    double time_variance;
    double clock_average;
    double clock_covariance;
    double prediction_variance;
    double last_prediction_time;
    double estimate_time;
    double estimate_clock;
    double estimate_frequency;
    bool initialized;
} km_clocksync_t;

void km_clocksync_init(km_clocksync_t *sync, uint32_t frequency,
                       uint32_t uptime_high, uint32_t uptime_clock,
                       int64_t sent_us, int64_t received_us);
bool km_clocksync_update(km_clocksync_t *sync, uint32_t clock,
                         int64_t sent_us, int64_t received_us);
uint64_t km_clocksync_clock_at(const km_clocksync_t *sync, int64_t system_us);
double km_clocksync_system_time(const km_clocksync_t *sync,
                                uint64_t mcu_clock);

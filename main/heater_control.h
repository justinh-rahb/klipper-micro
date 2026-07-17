// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <stdbool.h>
#include <stdint.h>

typedef enum {
    KM_CONTROL_FAULT_NONE,
    KM_CONTROL_FAULT_SENSOR_RANGE,
    KM_CONTROL_FAULT_SENSOR_STALE,
    KM_CONTROL_FAULT_HEATING_RATE,
} km_control_fault_t;

typedef struct {
    double filtered_temperature;
    double raw_temperature;
    double power;
    double integral;
    double previous_temperature;
    double previous_derivative;
    double previous_target;
    double heating_goal;
    int64_t started_us;
    int64_t last_sample_us;
    int64_t heating_deadline_us;
    unsigned rail_samples;
    bool has_sample;
    bool heating_watch_active;
    km_control_fault_t fault;
} km_heater_control_t;

void km_heater_control_init(km_heater_control_t *control, int64_t now_us);
void km_heater_control_sample(km_heater_control_t *control,
                              double adc_fraction, int64_t sample_us,
                              double target);
void km_heater_control_check(km_heater_control_t *control, int64_t now_us,
                             double target);
double km_thermistor_temperature(double adc_fraction);
double km_thermistor_adc_for_temperature(double temperature);
const char *km_control_fault_name(km_control_fault_t fault);

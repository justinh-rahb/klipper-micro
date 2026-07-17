// SPDX-License-Identifier: GPL-3.0-or-later
#include "heater_control.h"

#include <math.h>
#include <string.h>

#define KM_PULLUP_OHMS 4700.0
#define KM_THERMISTOR_R0 100000.0
#define KM_THERMISTOR_T0_KELVIN 298.15
#define KM_THERMISTOR_BETA 3950.0
#define KM_MIN_TEMPERATURE 0.0
#define KM_MAX_TEMPERATURE 85.0
#define KM_MAX_POWER 1.0
#define KM_PID_KP (22.2 / 255.0)
#define KM_PID_KI (1.08 / 255.0)
#define KM_PID_KD (114.0 / 255.0)
#define KM_DERIVATIVE_SMOOTH_SECONDS 1.0
#define KM_SENSOR_STARTUP_TIMEOUT_US 2000000LL
#define KM_SENSOR_STALE_TIMEOUT_US 1000000LL
#define KM_HEATING_HYSTERESIS 5.0
#define KM_HEATING_GAIN 2.0
#define KM_HEATING_GAIN_TIME_US 60000000LL

static double clamp(double value, double minimum, double maximum)
{
    if (value < minimum) return minimum;
    if (value > maximum) return maximum;
    return value;
}

double km_thermistor_temperature(double adc_fraction)
{
    const double adc = clamp(adc_fraction, 0.00001, 0.99999);
    const double resistance = KM_PULLUP_OHMS * adc / (1.0 - adc);
    const double inverse_temperature = 1.0 / KM_THERMISTOR_T0_KELVIN
        + log(resistance / KM_THERMISTOR_R0) / KM_THERMISTOR_BETA;
    return 1.0 / inverse_temperature - 273.15;
}

double km_thermistor_adc_for_temperature(double temperature)
{
    const double kelvin = temperature + 273.15;
    const double resistance = KM_THERMISTOR_R0 * exp(KM_THERMISTOR_BETA
        * (1.0 / kelvin - 1.0 / KM_THERMISTOR_T0_KELVIN));
    return resistance / (KM_PULLUP_OHMS + resistance);
}

void km_heater_control_init(km_heater_control_t *control, int64_t now_us)
{
    memset(control, 0, sizeof(*control));
    control->started_us = now_us;
}

static void trip(km_heater_control_t *control, km_control_fault_t fault)
{
    if (control->fault == KM_CONTROL_FAULT_NONE) control->fault = fault;
    control->power = 0.0;
    control->integral = 0.0;
    control->heating_watch_active = false;
}

static void update_heating_watch(km_heater_control_t *control, int64_t now_us,
                                 double temperature, double target)
{
    if (target <= 0.0 || temperature >= target - KM_HEATING_HYSTERESIS) {
        control->heating_watch_active = false;
        return;
    }
    if (!control->heating_watch_active || target != control->previous_target) {
        control->heating_watch_active = true;
        control->heating_goal = temperature + KM_HEATING_GAIN;
        control->heating_deadline_us = now_us + KM_HEATING_GAIN_TIME_US;
        return;
    }
    if (temperature >= control->heating_goal) {
        control->heating_goal = temperature + KM_HEATING_GAIN;
        control->heating_deadline_us = now_us + KM_HEATING_GAIN_TIME_US;
    } else if (now_us >= control->heating_deadline_us) {
        trip(control, KM_CONTROL_FAULT_HEATING_RATE);
    }
}

void km_heater_control_sample(km_heater_control_t *control,
                              double adc_fraction, int64_t sample_us,
                              double target)
{
    if (!control || control->fault != KM_CONTROL_FAULT_NONE) return;
    if (adc_fraction <= 0.0005 || adc_fraction >= 0.9995) {
        if (++control->rail_samples >= 3)
            trip(control, KM_CONTROL_FAULT_SENSOR_RANGE);
        return;
    }
    control->rail_samples = 0;
    const double temperature = km_thermistor_temperature(adc_fraction);
    if (!isfinite(temperature) || temperature < KM_MIN_TEMPERATURE
        || temperature > KM_MAX_TEMPERATURE) {
        trip(control, KM_CONTROL_FAULT_SENSOR_RANGE);
        return;
    }

    double elapsed = 0.1;
    if (control->has_sample && sample_us > control->last_sample_us)
        elapsed = (double)(sample_us - control->last_sample_us) / 1000000.0;
    elapsed = clamp(elapsed, 0.001, 1.0);
    control->raw_temperature = temperature;
    if (!control->has_sample) {
        control->filtered_temperature = temperature;
        control->previous_temperature = temperature;
    } else {
        const double alpha = clamp(elapsed, 0.0, 1.0);
        control->filtered_temperature +=
            (temperature - control->filtered_temperature) * alpha;
    }
    control->has_sample = true;
    control->last_sample_us = sample_us;

    if (target <= 0.0) {
        control->power = 0.0;
        control->integral = 0.0;
        control->previous_derivative = 0.0;
        control->heating_watch_active = false;
    } else {
        const double difference = temperature - control->previous_temperature;
        double derivative;
        if (elapsed >= KM_DERIVATIVE_SMOOTH_SECONDS) {
            derivative = difference / elapsed;
        } else {
            derivative = (control->previous_derivative
                * (KM_DERIVATIVE_SMOOTH_SECONDS - elapsed) + difference)
                / KM_DERIVATIVE_SMOOTH_SECONDS;
        }
        const double error = target - temperature;
        const double integral_max = KM_PID_KI > 0.0
            ? KM_MAX_POWER / KM_PID_KI : 0.0;
        const double candidate_integral = clamp(
            control->integral + error * elapsed, 0.0, integral_max);
        const double unbounded = KM_PID_KP * error
            + KM_PID_KI * candidate_integral - KM_PID_KD * derivative;
        control->power = clamp(unbounded, 0.0, KM_MAX_POWER);
        if (unbounded == control->power) control->integral = candidate_integral;
        control->previous_derivative = derivative;
        update_heating_watch(control, sample_us, temperature, target);
    }
    control->previous_temperature = temperature;
    control->previous_target = target;
}

void km_heater_control_check(km_heater_control_t *control, int64_t now_us,
                             double target)
{
    if (!control || control->fault != KM_CONTROL_FAULT_NONE) return;
    if ((!control->has_sample
         && now_us - control->started_us > KM_SENSOR_STARTUP_TIMEOUT_US)
        || (control->has_sample
            && now_us - control->last_sample_us > KM_SENSOR_STALE_TIMEOUT_US)) {
        trip(control, KM_CONTROL_FAULT_SENSOR_STALE);
        return;
    }
    update_heating_watch(control, now_us, control->raw_temperature, target);
}

const char *km_control_fault_name(km_control_fault_t fault)
{
    switch (fault) {
    case KM_CONTROL_FAULT_SENSOR_RANGE: return "sensor range";
    case KM_CONTROL_FAULT_SENSOR_STALE: return "sensor stale";
    case KM_CONTROL_FAULT_HEATING_RATE: return "heating rate";
    default: return "none";
    }
}

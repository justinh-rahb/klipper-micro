// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#include "zlib.h"

typedef enum {
    KM_MSG_GET_UPTIME,
    KM_MSG_GET_CLOCK,
    KM_MSG_GET_CONFIG,
    KM_MSG_ALLOCATE_OIDS,
    KM_MSG_FINALIZE_CONFIG,
    KM_MSG_CONFIG_PWM_OUT,
    KM_MSG_QUEUE_PWM_OUT,
    KM_MSG_SET_PWM_OUT,
    KM_MSG_CONFIG_ANALOG_IN,
    KM_MSG_QUERY_ANALOG_IN,
    KM_MSG_EMERGENCY_STOP,
    KM_MSG_CLEAR_SHUTDOWN,
    KM_MSG_UPTIME,
    KM_MSG_CLOCK,
    KM_MSG_CONFIG,
    KM_MSG_ANALOG_IN_STATE,
    KM_MSG_COUNT,
} km_message_key_t;

#define KM_DICTIONARY_AUX_COUNT 6
#define KM_DICTIONARY_SCAN_COUNT (KM_MSG_COUNT + KM_DICTIONARY_AUX_COUNT)

typedef struct {
    uint16_t ids[KM_MSG_COUNT];
    bool found[KM_MSG_COUNT];
    uint32_t clock_frequency;
    bool found_clock_frequency;
    uint32_t adc_max;
    uint32_t pwm_max;
    uint32_t heater_pin;
    uint32_t sensor_pin;
    uint32_t fan_pin;
    bool found_adc_max;
    bool found_pwm_max;
    bool found_heater_pin;
    bool found_sensor_pin;
    bool found_fan_pin;
    z_stream inflater;
    struct {
        uint16_t matched;
        uint32_t value;
        uint8_t state;
        bool has_digit;
    } scans[KM_DICTIONARY_SCAN_COUNT];
    bool inflater_started;
    bool inflater_finished;
} km_dictionary_t;

bool km_dictionary_begin(km_dictionary_t *dictionary);
bool km_dictionary_feed(km_dictionary_t *dictionary, const uint8_t *compressed,
                        size_t length);
bool km_dictionary_end(km_dictionary_t *dictionary);
bool km_dictionary_ready(const km_dictionary_t *dictionary);
bool km_dictionary_control_ready(const km_dictionary_t *dictionary);
uint16_t km_dictionary_id(const km_dictionary_t *dictionary,
                          km_message_key_t key);

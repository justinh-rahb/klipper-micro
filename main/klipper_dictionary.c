// SPDX-License-Identifier: GPL-3.0-or-later
#include "klipper_dictionary.h"

#include <ctype.h>
#include <string.h>

static const char *const s_patterns[KM_MSG_COUNT + 1] = {
    [KM_MSG_GET_UPTIME] = "\"get_uptime\"",
    [KM_MSG_GET_CLOCK] = "\"get_clock\"",
    [KM_MSG_GET_CONFIG] = "\"get_config\"",
    [KM_MSG_ALLOCATE_OIDS] = "\"allocate_oids count=%c\"",
    [KM_MSG_FINALIZE_CONFIG] = "\"finalize_config crc=%u\"",
    [KM_MSG_CONFIG_PWM_OUT] = "\"config_pwm_out oid=%c pin=%u cycle_ticks=%u value=%hu default_value=%hu max_duration=%u\"",
    [KM_MSG_QUEUE_PWM_OUT] = "\"queue_pwm_out oid=%c clock=%u value=%hu\"",
    [KM_MSG_SET_PWM_OUT] = "\"set_pwm_out pin=%u cycle_ticks=%u value=%hu\"",
    [KM_MSG_CONFIG_ANALOG_IN] = "\"config_analog_in oid=%c pin=%u\"",
    [KM_MSG_QUERY_ANALOG_IN] = "\"query_analog_in oid=%c clock=%u sample_ticks=%u sample_count=%c rest_ticks=%u min_value=%hu max_value=%hu range_check_count=%c\"",
    [KM_MSG_EMERGENCY_STOP] = "\"emergency_stop\"",
    [KM_MSG_CLEAR_SHUTDOWN] = "\"clear_shutdown\"",
    [KM_MSG_UPTIME] = "\"uptime high=%u clock=%u\"",
    [KM_MSG_CLOCK] = "\"clock clock=%u\"",
    [KM_MSG_CONFIG] = "\"config is_config=%c crc=%u is_shutdown=%c move_count=%hu\"",
    [KM_MSG_ANALOG_IN_STATE] = "\"analog_in_state oid=%c next_clock=%u value=%hu\"",
    [KM_MSG_COUNT] = "\"CLOCK_FREQ\"",
};

static void finish_value(km_dictionary_t *dictionary, size_t index)
{
    if (!dictionary->scans[index].has_digit) return;
    if (index == KM_MSG_COUNT) {
        dictionary->clock_frequency = dictionary->scans[index].value;
        dictionary->found_clock_frequency = true;
    } else if (dictionary->scans[index].value <= UINT16_MAX) {
        dictionary->ids[index] = (uint16_t)dictionary->scans[index].value;
        dictionary->found[index] = true;
    }
    dictionary->scans[index].state = 3;
}

static void scan_byte(km_dictionary_t *dictionary, uint8_t byte)
{
    for (size_t i = 0; i <= KM_MSG_COUNT; ++i) {
        if ((i < KM_MSG_COUNT && dictionary->found[i])
            || (i == KM_MSG_COUNT && dictionary->found_clock_frequency))
            continue;
        const char *pattern = s_patterns[i];
        switch (dictionary->scans[i].state) {
        case 0: {
            uint16_t matched = dictionary->scans[i].matched;
            if (byte == (uint8_t)pattern[matched]) {
                matched++;
                if (pattern[matched] == '\0') {
                    dictionary->scans[i].state = 1;
                    matched = 0;
                }
            } else {
                matched = byte == (uint8_t)pattern[0] ? 1 : 0;
            }
            dictionary->scans[i].matched = matched;
            break;
        }
        case 1:
            if (byte == ':') dictionary->scans[i].state = 2;
            break;
        case 2:
            if (isdigit((unsigned char)byte)) {
                dictionary->scans[i].value =
                    dictionary->scans[i].value * 10U + (uint32_t)(byte - '0');
                dictionary->scans[i].has_digit = true;
            } else if (dictionary->scans[i].has_digit) {
                finish_value(dictionary, i);
            }
            break;
        default:
            break;
        }
    }
}

static void scan_output(km_dictionary_t *dictionary, const uint8_t *data,
                        size_t length)
{
    for (size_t i = 0; i < length; ++i) scan_byte(dictionary, data[i]);
}

bool km_dictionary_begin(km_dictionary_t *dictionary)
{
    if (!dictionary) return false;
    memset(dictionary, 0, sizeof(*dictionary));
    if (inflateInit(&dictionary->inflater) != Z_OK) return false;
    dictionary->inflater_started = true;
    return true;
}

bool km_dictionary_feed(km_dictionary_t *dictionary, const uint8_t *compressed,
                        size_t length)
{
    if (!dictionary || !dictionary->inflater_started
        || dictionary->inflater_finished || (!compressed && length)) return false;
    uint8_t output[512];
    dictionary->inflater.next_in = (Bytef *)compressed;
    dictionary->inflater.avail_in = (uInt)length;
    do {
        dictionary->inflater.next_out = output;
        dictionary->inflater.avail_out = sizeof(output);
        const int result = inflate(&dictionary->inflater, Z_NO_FLUSH);
        if (result != Z_OK && result != Z_STREAM_END) return false;
        scan_output(dictionary, output,
                    sizeof(output) - dictionary->inflater.avail_out);
        if (result == Z_STREAM_END) {
            dictionary->inflater_finished = true;
            break;
        }
    } while (dictionary->inflater.avail_in || !dictionary->inflater.avail_out);
    return true;
}

bool km_dictionary_end(km_dictionary_t *dictionary)
{
    if (!dictionary || !dictionary->inflater_started) return false;
    for (size_t i = 0; i <= KM_MSG_COUNT; ++i) finish_value(dictionary, i);
    const bool stream_complete = dictionary->inflater_finished;
    inflateEnd(&dictionary->inflater);
    dictionary->inflater_started = false;
    return stream_complete && km_dictionary_ready(dictionary);
}

bool km_dictionary_ready(const km_dictionary_t *dictionary)
{
    if (!dictionary || !dictionary->found_clock_frequency) return false;
    return dictionary->found[KM_MSG_GET_UPTIME]
        && dictionary->found[KM_MSG_GET_CLOCK]
        && dictionary->found[KM_MSG_UPTIME]
        && dictionary->found[KM_MSG_CLOCK];
}

uint16_t km_dictionary_id(const km_dictionary_t *dictionary,
                          km_message_key_t key)
{
    if (!dictionary || key >= KM_MSG_COUNT || !dictionary->found[key])
        return UINT16_MAX;
    return dictionary->ids[key];
}

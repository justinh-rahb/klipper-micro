// SPDX-License-Identifier: GPL-3.0-or-later
#include "klipper_client.h"

#include <inttypes.h>
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "app_state.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "heater_control.h"
#include "klipper_clocksync.h"
#include "klipper_dictionary.h"
#include "klipper_protocol.h"

#define KM_UART UART_NUM_2
#define KM_UART_TX 22
#define KM_UART_RX 27
#define KM_UART_BAUD 250000
#define KM_IDENTIFY_CHUNK 40
#define KM_HEATER_OID 0
#define KM_SENSOR_OID 1
#define KM_FAN_OID 2
#define KM_OID_COUNT 3
#define KM_ADC_SAMPLE_COUNT 4
#define KM_ADC_SAMPLE_US 1000
#define KM_ADC_REPORT_US 100000
#define KM_PWM_CYCLE_US 100000
#define KM_PWM_MAX_DURATION_US 3000000
#define KM_OUTPUT_INTERVAL_US 250000
#define KM_SCHEDULE_AHEAD_US 100000
#define KM_CLOCK_POLL_US 983900
#define KM_CLOCK_TIMEOUT_US 5000000

static const char *TAG = "klipper";
static TaskHandle_t s_task;
static volatile bool s_emergency_requested;

typedef struct {
    uint16_t expected_id;
    bool received;
    uint32_t values[4];
    size_t value_count;
    uint8_t buffer[KM_IDENTIFY_CHUNK];
    size_t buffer_length;
} response_t;

typedef struct {
    uint8_t sequence;
    km_frame_parser_t parser;
    response_t response;
    km_dictionary_t dictionary;
    km_clocksync_t clocksync;
    km_heater_control_t heater;
    uint32_t report_ticks;
    uint32_t last_heater_clock;
    uint32_t last_fan_clock;
    int64_t clock_query_sent_us;
    int64_t last_clock_response_us;
    bool background_mode;
    bool clock_query_pending;
    bool fault_sent;
} client_t;

static void send_emergency_stop(client_t *client);

static bool append_vlq(uint8_t *payload, size_t *length, uint32_t value)
{
    const size_t encoded = km_vlq_encode((int32_t)value, payload + *length,
                                         KM_PAYLOAD_MAX - *length);
    if (!encoded) return false;
    *length += encoded;
    return true;
}

static bool send_payload(client_t *client, const uint8_t *payload, size_t length)
{
    uint8_t frame[KM_MESSAGE_MAX];
    const size_t frame_length = km_frame_encode(client->sequence++, payload,
                                                 length, frame, sizeof(frame));
    if (!frame_length) return false;
    return uart_write_bytes(KM_UART, frame, frame_length) == (int)frame_length;
}

static void publish_control(client_t *client)
{
    km_state_set_control(client->heater.has_sample,
        (float)client->heater.filtered_temperature,
        (float)client->heater.power, client->heater.fault);
    if (client->heater.fault != KM_CONTROL_FAULT_NONE && !client->fault_sent) {
        client->fault_sent = true;
        ESP_LOGE(TAG, "heater safety fault: %s",
                 km_control_fault_name(client->heater.fault));
        send_emergency_stop(client);
    }
}

static void handle_analog_state(client_t *client, const uint8_t *frame,
                                size_t length, size_t position)
{
    int32_t decoded;
    if (!km_vlq_decode(frame, length - 3, &position, &decoded)
        || (uint32_t)decoded != KM_SENSOR_OID) return;
    if (!km_vlq_decode(frame, length - 3, &position, &decoded)) return;
    const uint32_t next_clock32 = (uint32_t)decoded;
    if (position >= length - 3) return;
    const size_t bytes = frame[position++];
    if (!bytes || (bytes & 1U) || position + bytes > length - 3) return;

    const size_t sample_count = bytes / 2;
    const uint64_t next_clock = km_clocksync_clock32_to_clock64(
        &client->clocksync, next_clock32);
    const double adc_scale = (double)KM_ADC_SAMPLE_COUNT
        * client->dictionary.adc_max;
    const double target = km_state_snapshot().target;
    for (size_t i = 0; i < sample_count; ++i) {
        const uint16_t value = (uint16_t)frame[position + i * 2]
            | (uint16_t)((uint16_t)frame[position + i * 2 + 1] << 8);
        const uint64_t sample_clock = next_clock
            - (uint64_t)(sample_count - i) * client->report_ticks;
        const int64_t sample_us = (int64_t)llround(
            km_clocksync_system_time(&client->clocksync, sample_clock)
            * 1000000.0);
        km_heater_control_sample(&client->heater, value / adc_scale,
                                 sample_us, target);
    }
    publish_control(client);
}

static void handle_background_clock(client_t *client, const uint8_t *frame,
                                    size_t length, size_t position)
{
    int32_t decoded;
    if (!client->clock_query_pending
        || !km_vlq_decode(frame, length - 3, &position, &decoded)) return;
    const int64_t received_us = esp_timer_get_time();
    km_clocksync_update(&client->clocksync, (uint32_t)decoded,
                        client->clock_query_sent_us, received_us);
    client->clock_query_pending = false;
    client->last_clock_response_us = received_us;
}

static void receive_frame(const uint8_t *frame, size_t length, void *context)
{
    client_t *client = context;
    size_t position = 2;
    int32_t decoded;
    if (!km_vlq_decode(frame, length - 3, &position, &decoded)) return;
    const uint16_t message_id = (uint16_t)decoded;
    if (client->background_mode) {
        if (message_id == km_dictionary_id(&client->dictionary,
                                           KM_MSG_ANALOG_IN_STATE)) {
            handle_analog_state(client, frame, length, position);
            return;
        }
        if (message_id == km_dictionary_id(&client->dictionary, KM_MSG_CLOCK)) {
            handle_background_clock(client, frame, length, position);
            return;
        }
    }
    if (message_id != client->response.expected_id) return;

    response_t *response = &client->response;
    response->value_count = 0;
    response->buffer_length = 0;
    if (response->expected_id == 0) {
        if (!km_vlq_decode(frame, length - 3, &position, &decoded)) return;
        response->values[0] = (uint32_t)decoded;
        response->value_count = 1;
        if (position >= length - 3) return;
        const size_t buffer_length = frame[position++];
        if (buffer_length > sizeof(response->buffer)
            || position + buffer_length > length - 3) return;
        memcpy(response->buffer, frame + position, buffer_length);
        response->buffer_length = buffer_length;
    } else {
        while (position < length - 3
               && response->value_count < 4) {
            if (!km_vlq_decode(frame, length - 3, &position, &decoded)) return;
            response->values[response->value_count++] = (uint32_t)decoded;
        }
    }
    response->received = true;
}

static bool request(client_t *client, const uint8_t *payload,
                    size_t payload_length, uint16_t expected_id,
                    int64_t *sent_us, int64_t *received_us)
{
    static const TickType_t timeouts[] = {
        pdMS_TO_TICKS(20), pdMS_TO_TICKS(40), pdMS_TO_TICKS(80),
        pdMS_TO_TICKS(160), pdMS_TO_TICKS(320),
    };
    uint8_t incoming[64];
    client->response = (response_t) {.expected_id = expected_id};
    for (size_t attempt = 0; attempt < sizeof(timeouts) / sizeof(timeouts[0]);
         ++attempt) {
        if (sent_us) *sent_us = esp_timer_get_time();
        if (!send_payload(client, payload, payload_length)) return false;
        const TickType_t started = xTaskGetTickCount();
        while (xTaskGetTickCount() - started < timeouts[attempt]) {
            const int count = uart_read_bytes(KM_UART, incoming, sizeof(incoming),
                                              pdMS_TO_TICKS(5));
            if (count > 0) {
                km_frame_parser_feed(&client->parser, incoming, count,
                                     receive_frame, client);
                if (client->response.received) {
                    if (received_us) *received_us = esp_timer_get_time();
                    return true;
                }
            }
        }
    }
    return false;
}

static bool fetch_dictionary(client_t *client)
{
    if (!km_dictionary_begin(&client->dictionary)) return false;
    uint32_t offset = 0;
    for (;;) {
        uint8_t payload[16];
        size_t length = 0;
        if (!append_vlq(payload, &length, 1)
            || !append_vlq(payload, &length, offset)
            || !append_vlq(payload, &length, KM_IDENTIFY_CHUNK)) goto fail;
        if (!request(client, payload, length, 0, NULL, NULL)) goto fail;
        if (client->response.values[0] != offset) continue;
        if (!client->response.buffer_length) break;
        if (!km_dictionary_feed(&client->dictionary, client->response.buffer,
                                client->response.buffer_length)) goto fail;
        offset += client->response.buffer_length;
    }
    if (!km_dictionary_end(&client->dictionary)) return false;
    ESP_LOGI(TAG, "identify: compressed=%" PRIu32 " bytes clock=%" PRIu32,
             offset, client->dictionary.clock_frequency);
    return true;
fail:
    if (client->dictionary.inflater_started) {
        inflateEnd(&client->dictionary.inflater);
        client->dictionary.inflater_started = false;
    }
    return false;
}

static bool request_no_args(client_t *client, km_message_key_t command,
                            km_message_key_t response, int64_t *sent_us,
                            int64_t *received_us)
{
    uint8_t payload[5];
    size_t length = 0;
    const uint16_t command_id = km_dictionary_id(&client->dictionary, command);
    const uint16_t response_id = km_dictionary_id(&client->dictionary, response);
    if (command_id == UINT16_MAX || response_id == UINT16_MAX
        || !append_vlq(payload, &length, command_id)) return false;
    return request(client, payload, length, response_id, sent_us, received_us);
}

static bool synchronize(client_t *client)
{
    int64_t sent_us, received_us;
    if (!request_no_args(client, KM_MSG_GET_UPTIME, KM_MSG_UPTIME,
                         &sent_us, &received_us)
        || client->response.value_count != 2) return false;
    km_clocksync_init(&client->clocksync, client->dictionary.clock_frequency,
                      client->response.values[0], client->response.values[1],
                      sent_us, received_us);
    for (unsigned i = 0; i < 8; ++i) {
        vTaskDelay(pdMS_TO_TICKS(50));
        if (!request_no_args(client, KM_MSG_GET_CLOCK, KM_MSG_CLOCK,
                             &sent_us, &received_us)
            || client->response.value_count != 1) return false;
        km_clocksync_update(&client->clocksync, client->response.values[0],
                            sent_us, received_us);
    }
    return true;
}

static bool send_values(client_t *client, km_message_key_t command,
                        const uint32_t *values, size_t count)
{
    uint8_t payload[KM_PAYLOAD_MAX];
    size_t length = 0;
    const uint16_t id = km_dictionary_id(&client->dictionary, command);
    if (id == UINT16_MAX || !append_vlq(payload, &length, id)) return false;
    for (size_t i = 0; i < count; ++i) {
        if (!append_vlq(payload, &length, values[i])) return false;
    }
    return send_payload(client, payload, length);
}

static uint32_t ticks_for(const client_t *client, uint32_t microseconds)
{
    return (uint32_t)(((uint64_t)client->dictionary.clock_frequency
                       * microseconds + 500000U) / 1000000U);
}

static uint32_t control_config_crc(const client_t *client)
{
    const uint32_t cycle_ticks = ticks_for(client, KM_PWM_CYCLE_US);
    const uint32_t duration_ticks = ticks_for(client, KM_PWM_MAX_DURATION_US);
    char lines[4][180];
    snprintf(lines[0], sizeof(lines[0]), "allocate_oids count=%u", KM_OID_COUNT);
    snprintf(lines[1], sizeof(lines[1]),
             "config_pwm_out oid=%u pin=PA1 cycle_ticks=%" PRIu32
             " value=0 default_value=0 max_duration=%" PRIu32,
             KM_HEATER_OID, cycle_ticks, duration_ticks);
    snprintf(lines[2], sizeof(lines[2]), "config_analog_in oid=%u pin=PA2",
             KM_SENSOR_OID);
    snprintf(lines[3], sizeof(lines[3]),
             "config_pwm_out oid=%u pin=PA3 cycle_ticks=%" PRIu32
             " value=0 default_value=0 max_duration=%" PRIu32,
             KM_FAN_OID, cycle_ticks, duration_ticks);
    uLong crc = crc32(0L, Z_NULL, 0);
    for (size_t i = 0; i < 4; ++i) {
        if (i) crc = crc32(crc, (const Bytef *)"\n", 1);
        crc = crc32(crc, (const Bytef *)lines[i], strlen(lines[i]));
    }
    return (uint32_t)crc;
}

static bool get_config(client_t *client, uint32_t values[4])
{
    if (!request_no_args(client, KM_MSG_GET_CONFIG, KM_MSG_CONFIG, NULL, NULL)
        || client->response.value_count != 4) return false;
    memcpy(values, client->response.values, sizeof(client->response.values));
    return true;
}

static bool send_control_configuration(client_t *client, uint32_t crc)
{
    const uint32_t cycle_ticks = ticks_for(client, KM_PWM_CYCLE_US);
    const uint32_t duration_ticks = ticks_for(client, KM_PWM_MAX_DURATION_US);
    const uint32_t allocate[] = {KM_OID_COUNT};
    const uint32_t heater[] = {
        KM_HEATER_OID, client->dictionary.heater_pin, cycle_ticks,
        0, 0, duration_ticks,
    };
    const uint32_t sensor[] = {KM_SENSOR_OID, client->dictionary.sensor_pin};
    const uint32_t fan[] = {
        KM_FAN_OID, client->dictionary.fan_pin, cycle_ticks,
        0, 0, duration_ticks,
    };
    const uint32_t finalize[] = {crc};
    return send_values(client, KM_MSG_ALLOCATE_OIDS, allocate, 1)
        && send_values(client, KM_MSG_CONFIG_PWM_OUT, heater, 6)
        && send_values(client, KM_MSG_CONFIG_ANALOG_IN, sensor, 2)
        && send_values(client, KM_MSG_CONFIG_PWM_OUT, fan, 6)
        && send_values(client, KM_MSG_FINALIZE_CONFIG, finalize, 1)
        && uart_wait_tx_done(KM_UART, pdMS_TO_TICKS(500)) == ESP_OK;
}

static bool start_analog_query(client_t *client)
{
    client->report_ticks = ticks_for(client, KM_ADC_REPORT_US);
    const double adc_scale = (double)KM_ADC_SAMPLE_COUNT
        * client->dictionary.adc_max;
    uint32_t minimum = (uint32_t)floor(
        km_thermistor_adc_for_temperature(85.0) * adc_scale);
    uint32_t maximum = (uint32_t)ceil(
        km_thermistor_adc_for_temperature(0.0) * adc_scale);
    if (minimum > UINT16_MAX) minimum = UINT16_MAX;
    if (maximum > UINT16_MAX) maximum = UINT16_MAX;
    const uint32_t query[] = {
        KM_SENSOR_OID,
        (uint32_t)km_clocksync_clock_at(&client->clocksync,
                                        esp_timer_get_time() + 200000),
        ticks_for(client, KM_ADC_SAMPLE_US),
        KM_ADC_SAMPLE_COUNT,
        client->report_ticks,
        2,
        minimum,
        maximum,
        3,
    };
    return send_values(client, KM_MSG_QUERY_ANALOG_IN, query, 9);
}

static bool configure_control(client_t *client)
{
    if (!km_dictionary_control_ready(&client->dictionary)) {
        ESP_LOGE(TAG, "MCU dictionary lacks required PWM/ADC commands or pins");
        return false;
    }
    const uint32_t wanted_crc = control_config_crc(client);
    uint32_t config[4];
    if (!get_config(client, config) || config[2]) {
        ESP_LOGE(TAG, "MCU configuration unavailable or shutdown");
        return false;
    }
    if (!config[0]) {
        ESP_LOGI(TAG, "sending heater/sensor/fan configuration crc=%08" PRIx32,
                 wanted_crc);
        if (!send_control_configuration(client, wanted_crc)
            || !get_config(client, config) || !config[0]
            || config[1] != wanted_crc || config[2]) return false;
    } else if (config[1] != wanted_crc) {
        ESP_LOGE(TAG, "MCU config CRC mismatch: have=%08" PRIx32
                 " want=%08" PRIx32 " (MCU reset required)",
                 config[1], wanted_crc);
        return false;
    }
    km_heater_control_init(&client->heater, esp_timer_get_time());
    if (!start_analog_query(client)) return false;
    ESP_LOGI(TAG, "control configured: ADC_MAX=%" PRIu32
             " PWM_MAX=%" PRIu32 " report=%" PRIu32 " ticks",
             client->dictionary.adc_max, client->dictionary.pwm_max,
             client->report_ticks);
    return true;
}

static void send_emergency_stop(client_t *client)
{
    const uint16_t id = km_dictionary_id(&client->dictionary,
                                         KM_MSG_EMERGENCY_STOP);
    if (id == UINT16_MAX) return;
    uint8_t payload[5];
    size_t length = 0;
    if (append_vlq(payload, &length, id)) send_payload(client, payload, length);
}

static bool queue_pwm(client_t *client, uint32_t oid, double duty,
                      uint32_t *last_clock, uint32_t clock)
{
    if (*last_clock && (int32_t)(clock - *last_clock) <= 0)
        clock = *last_clock + ticks_for(client, KM_OUTPUT_INTERVAL_US);
    const uint32_t value = (uint32_t)llround(
        fmax(0.0, fmin(1.0, duty)) * client->dictionary.pwm_max);
    const uint32_t fields[] = {oid, clock, value};
    if (!send_values(client, KM_MSG_QUEUE_PWM_OUT, fields, 3)) return false;
    *last_clock = clock;
    return true;
}

static bool send_outputs(client_t *client, const km_state_snapshot_t *state,
                         int64_t now_us)
{
    const uint32_t clock = (uint32_t)km_clocksync_clock_at(
        &client->clocksync, now_us + KM_SCHEDULE_AHEAD_US);
    const double heater_power = client->heater.has_sample
        && client->heater.fault == KM_CONTROL_FAULT_NONE
        ? client->heater.power : 0.0;
    return queue_pwm(client, KM_HEATER_OID, heater_power,
                     &client->last_heater_clock, clock)
        && queue_pwm(client, KM_FAN_OID, state->fan,
                     &client->last_fan_clock, clock);
}

static bool send_clock_query(client_t *client, int64_t now_us)
{
    const uint16_t id = km_dictionary_id(&client->dictionary, KM_MSG_GET_CLOCK);
    uint8_t payload[5];
    size_t length = 0;
    if (id == UINT16_MAX || !append_vlq(payload, &length, id)) return false;
    client->clock_query_sent_us = now_us;
    client->clock_query_pending = true;
    if (!send_payload(client, payload, length)) {
        client->clock_query_pending = false;
        return false;
    }
    return true;
}

static bool connected_loop(client_t *client)
{
    uint8_t incoming[64];
    int64_t now_us = esp_timer_get_time();
    int64_t next_clock_query_us = now_us;
    int64_t next_output_us = now_us;
    client->background_mode = true;
    client->response.expected_id = UINT16_MAX;
    client->last_clock_response_us = now_us;
    for (;;) {
        if (s_emergency_requested) {
            s_emergency_requested = false;
            send_emergency_stop(client);
        }
        const int count = uart_read_bytes(KM_UART, incoming, sizeof(incoming),
                                          pdMS_TO_TICKS(20));
        if (count > 0)
            km_frame_parser_feed(&client->parser, incoming, count,
                                 receive_frame, client);
        now_us = esp_timer_get_time();
        if (now_us >= next_clock_query_us && !client->clock_query_pending) {
            if (!send_clock_query(client, now_us)) return false;
            next_clock_query_us = now_us + KM_CLOCK_POLL_US;
        }
        if (now_us - client->last_clock_response_us > KM_CLOCK_TIMEOUT_US)
            return false;
        if (now_us >= next_output_us) {
            km_state_snapshot_t state = km_state_snapshot();
            km_heater_control_check(&client->heater, now_us, state.target);
            if (client->heater.has_sample
                || client->heater.fault != KM_CONTROL_FAULT_NONE)
                publish_control(client);
            state = km_state_snapshot();
            if (client->heater.fault == KM_CONTROL_FAULT_NONE
                && !send_outputs(client, &state, now_us)) return false;
            next_output_us = now_us + KM_OUTPUT_INTERVAL_US;
        }
    }
}

static bool connect_once(client_t *client)
{
    memset(client, 0, sizeof(*client));
    km_frame_parser_init(&client->parser);
    uart_flush_input(KM_UART);
    return fetch_dictionary(client) && synchronize(client)
        && configure_control(client);
}

static void client_task(void *unused)
{
    (void)unused;
    client_t client;
    for (;;) {
        ESP_LOGI(TAG, "connecting on UART2 GPIO22/27 at 250000 baud");
        if (connect_once(&client)) {
            ESP_LOGI(TAG, "MCU online; free-running clock estimate %.1f Hz",
                     client.clocksync.estimate_frequency);
            km_state_set_mcu_connected(true);
            connected_loop(&client);
        }
        km_state_set_mcu_connected(false);
        ESP_LOGW(TAG, "MCU link down; retrying");
        vTaskDelay(pdMS_TO_TICKS(1000));
    }
}

bool km_client_start(void)
{
    const uart_config_t config = {
        .baud_rate = KM_UART_BAUD,
        .data_bits = UART_DATA_8_BITS,
        .parity = UART_PARITY_DISABLE,
        .stop_bits = UART_STOP_BITS_1,
        .flow_ctrl = UART_HW_FLOWCTRL_DISABLE,
        .source_clk = UART_SCLK_DEFAULT,
    };
    if (uart_driver_install(KM_UART, 2048, 0, 0, NULL, 0) != ESP_OK
        || uart_param_config(KM_UART, &config) != ESP_OK
        || uart_set_pin(KM_UART, KM_UART_TX, KM_UART_RX,
                        UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE) != ESP_OK)
        return false;
    return xTaskCreate(client_task, "klipper", 6144, NULL, 8, &s_task) == pdPASS;
}

void km_client_emergency_stop(void)
{
    s_emergency_requested = true;
}

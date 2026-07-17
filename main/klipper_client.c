// SPDX-License-Identifier: GPL-3.0-or-later
#include "klipper_client.h"

#include <inttypes.h>
#include <string.h>

#include "app_state.h"
#include "driver/uart.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "klipper_clocksync.h"
#include "klipper_dictionary.h"
#include "klipper_protocol.h"

#define KM_UART UART_NUM_2
#define KM_UART_TX 22
#define KM_UART_RX 27
#define KM_UART_BAUD 250000
#define KM_IDENTIFY_CHUNK 40

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
} client_t;

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

static void receive_frame(const uint8_t *frame, size_t length, void *context)
{
    client_t *client = context;
    size_t position = 2;
    int32_t decoded;
    if (!km_vlq_decode(frame, length - 3, &position, &decoded)
        || (uint16_t)decoded != client->response.expected_id) return;

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

static void send_emergency_stop(client_t *client)
{
    const uint16_t id = km_dictionary_id(&client->dictionary,
                                         KM_MSG_EMERGENCY_STOP);
    if (id == UINT16_MAX) return;
    uint8_t payload[5];
    size_t length = 0;
    if (append_vlq(payload, &length, id)) send_payload(client, payload, length);
}

static bool connected_loop(client_t *client)
{
    for (;;) {
        if (s_emergency_requested) {
            s_emergency_requested = false;
            send_emergency_stop(client);
        }
        int64_t sent_us, received_us;
        if (!request_no_args(client, KM_MSG_GET_CLOCK, KM_MSG_CLOCK,
                             &sent_us, &received_us)
            || client->response.value_count != 1) return false;
        km_clocksync_update(&client->clocksync, client->response.values[0],
                            sent_us, received_us);
        vTaskDelay(pdMS_TO_TICKS(984));
    }
}

static bool connect_once(client_t *client)
{
    memset(client, 0, sizeof(*client));
    km_frame_parser_init(&client->parser);
    uart_flush_input(KM_UART);
    return fetch_dictionary(client) && synchronize(client);
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

// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define KM_MESSAGE_MIN 5U
#define KM_MESSAGE_MAX 64U
#define KM_PAYLOAD_MAX (KM_MESSAGE_MAX - KM_MESSAGE_MIN)
#define KM_MESSAGE_DEST 0x10U
#define KM_MESSAGE_SEQ_MASK 0x0fU
#define KM_MESSAGE_SYNC 0x7eU

typedef void (*km_frame_callback_t)(const uint8_t *frame, size_t length,
                                    void *context);

typedef struct {
    uint8_t data[KM_MESSAGE_MAX];
    size_t length;
    bool seeking_sync;
    uint32_t crc_errors;
    uint32_t framing_errors;
} km_frame_parser_t;

uint16_t km_crc16_ccitt(const uint8_t *data, size_t length);
size_t km_vlq_encode(int32_t value, uint8_t *out, size_t capacity);
bool km_vlq_decode(const uint8_t *data, size_t length, size_t *position,
                   int32_t *value);
size_t km_frame_encode(uint8_t sequence, const uint8_t *payload,
                       size_t payload_length, uint8_t *out, size_t capacity);
bool km_frame_valid(const uint8_t *frame, size_t length);
void km_frame_parser_init(km_frame_parser_t *parser);
void km_frame_parser_feed(km_frame_parser_t *parser, const uint8_t *data,
                          size_t length, km_frame_callback_t callback,
                          void *context);

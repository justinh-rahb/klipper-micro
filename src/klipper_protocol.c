// SPDX-License-Identifier: GPL-3.0-or-later
#include "klipper_protocol.h"

#include <string.h>

uint16_t km_crc16_ccitt(const uint8_t *data, size_t length)
{
    uint16_t crc = 0xffff;
    for (size_t i = 0; i < length; ++i) {
        uint8_t value = data[i] ^ (uint8_t)crc;
        value ^= (uint8_t)(value << 4);
        crc = (uint16_t)(((uint16_t)value << 8) | (crc >> 8))
            ^ (uint16_t)(value >> 4) ^ (uint16_t)((uint16_t)value << 3);
    }
    return crc;
}

size_t km_vlq_encode(int32_t value, uint8_t *out, size_t capacity)
{
    uint8_t encoded[5];
    size_t count = 0;
    if (value >= 0x0c000000 || value < -0x04000000)
        encoded[count++] = (uint8_t)((value >> 28) & 0x7f) | 0x80;
    if (value >= 0x00180000 || value < -0x00080000)
        encoded[count++] = (uint8_t)((value >> 21) & 0x7f) | 0x80;
    if (value >= 0x00003000 || value < -0x00001000)
        encoded[count++] = (uint8_t)((value >> 14) & 0x7f) | 0x80;
    if (value >= 0x00000060 || value < -0x00000020)
        encoded[count++] = (uint8_t)((value >> 7) & 0x7f) | 0x80;
    encoded[count++] = (uint8_t)value & 0x7f;
    if (count > capacity) return 0;
    memcpy(out, encoded, count);
    return count;
}

bool km_vlq_decode(const uint8_t *data, size_t length, size_t *position,
                   int32_t *value)
{
    if (!data || !position || !value || *position >= length) return false;
    uint8_t current = data[(*position)++];
    int32_t decoded = current & 0x7f;
    if ((current & 0x60) == 0x60) decoded |= (int32_t)~0x1f;
    unsigned continuation = 0;
    while (current & 0x80) {
        if (*position >= length || ++continuation >= 5) return false;
        current = data[(*position)++];
        decoded = (int32_t)(((uint32_t)decoded << 7) | (current & 0x7f));
    }
    *value = decoded;
    return true;
}

size_t km_frame_encode(uint8_t sequence, const uint8_t *payload,
                       size_t payload_length, uint8_t *out, size_t capacity)
{
    const size_t frame_length = payload_length + KM_MESSAGE_MIN;
    if (!out || !payload || payload_length > KM_PAYLOAD_MAX
        || capacity < frame_length) return 0;
    out[0] = (uint8_t)frame_length;
    out[1] = (sequence & KM_MESSAGE_SEQ_MASK) | KM_MESSAGE_DEST;
    memcpy(out + 2, payload, payload_length);
    const uint16_t crc = km_crc16_ccitt(out, payload_length + 2);
    out[frame_length - 3] = (uint8_t)(crc >> 8);
    out[frame_length - 2] = (uint8_t)crc;
    out[frame_length - 1] = KM_MESSAGE_SYNC;
    return frame_length;
}

bool km_frame_valid(const uint8_t *frame, size_t length)
{
    if (!frame || length < KM_MESSAGE_MIN || length > KM_MESSAGE_MAX
        || frame[0] != length || frame[length - 1] != KM_MESSAGE_SYNC
        || (frame[1] & (uint8_t)~KM_MESSAGE_SEQ_MASK) != KM_MESSAGE_DEST)
        return false;
    const uint16_t actual = ((uint16_t)frame[length - 3] << 8)
        | frame[length - 2];
    return actual == km_crc16_ccitt(frame, length - 3);
}

void km_frame_parser_init(km_frame_parser_t *parser)
{
    memset(parser, 0, sizeof(*parser));
}

void km_frame_parser_feed(km_frame_parser_t *parser, const uint8_t *data,
                          size_t length, km_frame_callback_t callback,
                          void *context)
{
    for (size_t i = 0; i < length; ++i) {
        const uint8_t byte = data[i];
        if (parser->seeking_sync) {
            if (byte == KM_MESSAGE_SYNC) parser->seeking_sync = false;
            continue;
        }
        if (parser->length >= sizeof(parser->data)) {
            parser->framing_errors++;
            parser->length = 0;
            parser->seeking_sync = true;
            continue;
        }
        parser->data[parser->length++] = byte;
        const size_t expected = parser->data[0];
        if (expected < KM_MESSAGE_MIN || expected > KM_MESSAGE_MAX) {
            parser->framing_errors++;
            parser->length = 0;
            parser->seeking_sync = byte != KM_MESSAGE_SYNC;
            continue;
        }
        if (parser->length < expected) continue;
        if (km_frame_valid(parser->data, parser->length)) {
            if (callback) callback(parser->data, parser->length, context);
        } else {
            parser->crc_errors++;
            parser->seeking_sync = byte != KM_MESSAGE_SYNC;
        }
        parser->length = 0;
    }
}

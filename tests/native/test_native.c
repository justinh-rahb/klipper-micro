#include <assert.h>
#include <limits.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "klipper_clocksync.h"
#include "klipper_dictionary.h"
#include "klipper_protocol.h"
#include "zlib.h"

static unsigned callback_count;

static void count_frame(const uint8_t *frame, size_t length, void *context)
{
    (void)context;
    assert(km_frame_valid(frame, length));
    callback_count++;
}

static void test_crc_and_vlq(void)
{
    const uint8_t crc_input[] = {5, 0x10};
    assert(km_crc16_ccitt(crc_input, sizeof(crc_input)) == 0x9e81);
    const int32_t values[] = {
        0, 1, 95, 96, 4095, 4096, 0x7fffffff,
        -1, -32, -33, -4096, -4097, INT32_MIN,
    };
    for (size_t i = 0; i < sizeof(values) / sizeof(values[0]); ++i) {
        uint8_t encoded[5];
        const size_t length = km_vlq_encode(values[i], encoded, sizeof(encoded));
        assert(length > 0 && length <= sizeof(encoded));
        size_t position = 0;
        int32_t decoded = 0;
        assert(km_vlq_decode(encoded, length, &position, &decoded));
        assert(position == length);
        assert(decoded == values[i]);
    }
}

static void test_frames(void)
{
    const uint8_t payload[] = {1, 0, 40};
    uint8_t frame[KM_MESSAGE_MAX];
    const size_t length = km_frame_encode(5, payload, sizeof(payload), frame,
                                          sizeof(frame));
    assert(length == 8);
    assert(frame[1] == 0x15);
    assert(km_frame_valid(frame, length));

    km_frame_parser_t parser;
    km_frame_parser_init(&parser);
    callback_count = 0;
    km_frame_parser_feed(&parser, frame, 2, count_frame, NULL);
    km_frame_parser_feed(&parser, frame + 2, length - 2, count_frame, NULL);
    assert(callback_count == 1);

    uint8_t bad[KM_MESSAGE_MAX];
    memcpy(bad, frame, length);
    bad[2] ^= 0x01;
    km_frame_parser_feed(&parser, bad, length, count_frame, NULL);
    km_frame_parser_feed(&parser, frame, length, count_frame, NULL);
    assert(parser.crc_errors == 1);
    assert(callback_count == 2);
}

static void test_dictionary(void)
{
    const char json[] =
        "{\"commands\":{\"get_uptime\":5,\"get_clock\":6,"
        "\"emergency_stop\":15},\"responses\":{"
        "\"uptime high=%u clock=%u\":18,\"clock clock=%u\":19},"
        "\"config\":{\"CLOCK_FREQ\":72000000}}";
    uLongf compressed_length = compressBound(sizeof(json) - 1);
    uint8_t compressed[512];
    assert(compressed_length <= sizeof(compressed));
    assert(compress(compressed, &compressed_length,
                    (const Bytef *)json, sizeof(json) - 1) == Z_OK);

    km_dictionary_t dictionary;
    assert(km_dictionary_begin(&dictionary));
    for (size_t offset = 0; offset < compressed_length; offset += 7) {
        size_t chunk = compressed_length - offset;
        if (chunk > 7) chunk = 7;
        assert(km_dictionary_feed(&dictionary, compressed + offset, chunk));
    }
    assert(km_dictionary_end(&dictionary));
    assert(km_dictionary_id(&dictionary, KM_MSG_GET_UPTIME) == 5);
    assert(km_dictionary_id(&dictionary, KM_MSG_GET_CLOCK) == 6);
    assert(km_dictionary_id(&dictionary, KM_MSG_UPTIME) == 18);
    assert(km_dictionary_id(&dictionary, KM_MSG_CLOCK) == 19);
    assert(km_dictionary_id(&dictionary, KM_MSG_EMERGENCY_STOP) == 15);
    assert(dictionary.clock_frequency == 72000000);
}

static void test_clocksync(void)
{
    const uint32_t frequency = 72000000;
    km_clocksync_t sync;
    km_clocksync_init(&sync, frequency, 0, 0, 0, 1000);
    for (unsigned i = 1; i <= 40; ++i) {
        const int64_t sent = (int64_t)i * 50000;
        const int64_t received = sent + 1000;
        const uint32_t clock = (uint32_t)((double)frequency * sent / 1000000.0);
        km_clocksync_update(&sync, clock, sent, received);
    }
    assert(fabs(sync.estimate_frequency - frequency) < 1000.0);
    const uint64_t predicted = km_clocksync_clock_at(&sync, 2500000);
    assert(llabs((long long)predicted - 180000000LL) < 200000);
}

int main(void)
{
    test_crc_and_vlq();
    test_frames();
    test_dictionary();
    test_clocksync();
    puts("native protocol tests passed");
    return 0;
}

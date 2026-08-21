#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

struct explicit_event {
    uint8_t source;
    uint8_t target;
    uint8_t discontinuous;
};

_Static_assert(sizeof(struct explicit_event) == 3, "unexpected explicit_event padding");

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t pack_transition(uint8_t source, uint8_t target, uint8_t discontinuous) {
    return (uint8_t)((source << 2u) | (target << 1u) | discontinuous);
}

static uint64_t scan_explicit(const struct explicit_event *events, size_t n) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        allowed += (uint64_t)(events[i].target == 1u && events[i].discontinuous == 0u);
    }
    return allowed;
}

static uint64_t scan_packed(const uint8_t *events, size_t n) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t code = events[i];
        allowed += (uint64_t)((code & 0x2u) != 0u && (code & 0x1u) == 0u);
    }
    return allowed;
}

static uint64_t scan_streaming(size_t n) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t source = (uint8_t)(i & 1u);
        const uint8_t target = (uint8_t)(1u - source);
        const uint8_t discontinuous = (uint8_t)((i & 3u) == 0u);
        allowed += (uint64_t)(target == 1u && discontinuous == 0u);
    }
    return allowed;
}

int main(void) {
    const size_t n = 20000000u;
    const unsigned repeats = 8u;
    const uint64_t expected_per_scan = (uint64_t)(n / 4u);

    struct explicit_event *explicit_events = malloc(n * sizeof(*explicit_events));
    uint8_t *packed_events = malloc(n * sizeof(*packed_events));
    if (explicit_events == NULL || packed_events == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_events);
        free(packed_events);
        return 2;
    }

    double started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t source = (uint8_t)(i & 1u);
        const uint8_t target = (uint8_t)(1u - source);
        const uint8_t discontinuous = (uint8_t)((i & 3u) == 0u);
        explicit_events[i].source = source;
        explicit_events[i].target = target;
        explicit_events[i].discontinuous = discontinuous;
    }
    const double explicit_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t source = (uint8_t)(i & 1u);
        const uint8_t target = (uint8_t)(1u - source);
        const uint8_t discontinuous = (uint8_t)((i & 3u) == 0u);
        packed_events[i] = pack_transition(source, target, discontinuous);
    }
    const double packed_build = now_seconds() - started;

    uint64_t explicit_checksum = 0;
    started = now_seconds();
    for (unsigned r = 0; r < repeats; ++r) {
        explicit_checksum += scan_explicit(explicit_events, n);
    }
    const double explicit_scan_total = now_seconds() - started;

    uint64_t packed_checksum = 0;
    started = now_seconds();
    for (unsigned r = 0; r < repeats; ++r) {
        packed_checksum += scan_packed(packed_events, n);
    }
    const double packed_scan_total = now_seconds() - started;

    uint64_t streaming_checksum = 0;
    started = now_seconds();
    for (unsigned r = 0; r < repeats; ++r) {
        streaming_checksum += scan_streaming(n);
    }
    const double streaming_total = now_seconds() - started;

    const uint64_t expected_checksum = expected_per_scan * repeats;
    if (explicit_checksum != expected_checksum || packed_checksum != expected_checksum ||
        streaming_checksum != expected_checksum) {
        fprintf(stderr, "incorrect checksum\n");
        free(explicit_events);
        free(packed_events);
        return 3;
    }

    const size_t explicit_bytes = n * sizeof(*explicit_events);
    const size_t packed_bytes = n * sizeof(*packed_events);
    const double explicit_scan = explicit_scan_total / repeats;
    const double packed_scan = packed_scan_total / repeats;
    const double streaming_scan = streaming_total / repeats;

    printf("events=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("expected_allowed_per_scan=%" PRIu64 "\n", expected_per_scan);
    printf("correct=true\n\n");

    printf("[explicit equal-information struct]\n");
    printf("bytes_per_event=%zu\n", sizeof(*explicit_events));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[packed 3-bit semantics in uint8_t]\n");
    printf("bytes_per_event=%zu\n", sizeof(*packed_events));
    printf("total_bytes=%zu\n", packed_bytes);
    printf("build_seconds=%.6f\n", packed_build);
    printf("scan_seconds_avg=%.6f\n\n", packed_scan);

    printf("[streaming / no retained transition state]\n");
    printf("scan_seconds_avg=%.6f\n\n", streaming_scan);

    printf("packed_memory_vs_explicit=%.3fx\n", (double)packed_bytes / (double)explicit_bytes);
    printf("packed_build_vs_explicit=%.3fx\n", packed_build / explicit_build);
    printf("packed_scan_vs_explicit=%.3fx\n", packed_scan / explicit_scan);
    printf("packed_scan_vs_streaming=%.3fx\n", packed_scan / streaming_scan);
    printf("representation_note=the packed code is a generic bitfield carrying the Bardo v0.2 semantics\n");

    free(explicit_events);
    free(packed_events);
    return 0;
}

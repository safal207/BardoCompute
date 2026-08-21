#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

typedef struct {
    uint8_t bardo;
    uint8_t missing;
} ExplicitRecord;

static const uint8_t valid_bardo_codes[6] = {
    0x0u, /* stable 0 */
    0x2u, /* 0->1 continuous */
    0x3u, /* 0->1 discontinuous */
    0x4u, /* 1->0 continuous */
    0x5u, /* 1->0 discontinuous */
    0x6u  /* stable 1 */
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t pack_record(uint8_t bardo, uint8_t missing) {
    return (uint8_t)((bardo & 0x7u) | ((missing & 0x7u) << 3u));
}

static uint64_t scan_explicit(const ExplicitRecord *records, size_t n) {
    uint64_t relevant = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t bardo = records[i].bardo;
        const uint8_t missing = records[i].missing;
        const uint8_t continuous = (uint8_t)((bardo & 0x1u) == 0u);
        const uint8_t target_one = (uint8_t)(((bardo >> 1u) & 0x1u) != 0u);
        const uint8_t waits_outcome = (uint8_t)((missing & 0x4u) != 0u);
        relevant += (uint64_t)(continuous && target_one && waits_outcome);
    }
    return relevant;
}

static uint64_t scan_packed(const uint8_t *records, size_t n) {
    uint64_t relevant = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t record = records[i];
        const uint8_t bardo = (uint8_t)(record & 0x7u);
        const uint8_t missing = (uint8_t)((record >> 3u) & 0x7u);
        const uint8_t continuous = (uint8_t)((bardo & 0x1u) == 0u);
        const uint8_t target_one = (uint8_t)(((bardo >> 1u) & 0x1u) != 0u);
        const uint8_t waits_outcome = (uint8_t)((missing & 0x4u) != 0u);
        relevant += (uint64_t)(continuous && target_one && waits_outcome);
    }
    return relevant;
}

int main(void) {
    const size_t n = 20000000u;
    const unsigned repeats = 8u;

    ExplicitRecord *explicit_records = malloc(n * sizeof(*explicit_records));
    uint8_t *packed_records = malloc(n * sizeof(*packed_records));
    if (explicit_records == NULL || packed_records == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_records);
        free(packed_records);
        return 2;
    }

    double started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t bardo = valid_bardo_codes[(i * 5u + i / 7u) % 6u];
        const uint8_t missing = (uint8_t)((i * 3u + i / 11u) & 0x7u);
        explicit_records[i].bardo = bardo;
        explicit_records[i].missing = missing;
    }
    const double explicit_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t bardo = valid_bardo_codes[(i * 5u + i / 7u) % 6u];
        const uint8_t missing = (uint8_t)((i * 3u + i / 11u) & 0x7u);
        packed_records[i] = pack_record(bardo, missing);
    }
    const double packed_build = now_seconds() - started;

    const uint64_t warm_explicit = scan_explicit(explicit_records, n);
    const uint64_t warm_packed = scan_packed(packed_records, n);
    if (warm_explicit != warm_packed) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(explicit_records);
        free(packed_records);
        return 3;
    }

    double explicit_total = 0.0;
    double packed_total = 0.0;
    uint64_t explicit_checksum = 0;
    uint64_t packed_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        if ((r & 1u) == 0u) {
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;

            started = now_seconds();
            packed_checksum += scan_packed(packed_records, n);
            packed_total += now_seconds() - started;
        } else {
            started = now_seconds();
            packed_checksum += scan_packed(packed_records, n);
            packed_total += now_seconds() - started;

            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
        }
    }

    if (explicit_checksum != packed_checksum) {
        fprintf(stderr, "checksum mismatch: explicit=%" PRIu64 " packed=%" PRIu64 "\n",
                explicit_checksum, packed_checksum);
        free(explicit_records);
        free(packed_records);
        return 4;
    }

    const double explicit_scan = explicit_total / repeats;
    const double packed_scan = packed_total / repeats;
    const size_t explicit_bytes = n * sizeof(*explicit_records);
    const size_t packed_bytes = n * sizeof(*packed_records);

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("semantic_bits=6\n");
    printf("reserved_bits_in_packed_byte=2\n");
    printf("correct=true\n\n");

    printf("[explicit equal-information record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*explicit_records));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[packed Bardo+Tao / generic 6-bit record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*packed_records));
    printf("total_bytes=%zu\n", packed_bytes);
    printf("build_seconds=%.6f\n", packed_build);
    printf("scan_seconds_avg=%.6f\n\n", packed_scan);

    printf("packed_memory_vs_explicit=%.3fx\n", (double)packed_bytes / (double)explicit_bytes);
    printf("packed_build_vs_explicit=%.3fx\n", packed_build / explicit_build);
    printf("packed_scan_vs_explicit=%.3fx\n", packed_scan / explicit_scan);
    printf("representation_note=the packed byte is generic bit packing carrying Bardo transition plus Tao orientation semantics\n");

    free(explicit_records);
    free(packed_records);
    return 0;
}

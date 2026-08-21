#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

typedef struct {
    uint8_t current_missing;
    uint8_t current_phase;
    uint8_t age_bucket;
} explicit_age_t;

enum {
    PHASE_CONVERGING = 1,
    AGE_FRESH = 0,
    AGE_WARM = 1,
    AGE_STALE = 2,
    AGE_EXPIRED = 3
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t pack_age(uint8_t current_missing, uint8_t phase, uint8_t age_bucket) {
    return (uint8_t)(
        (current_missing & 0x7u) |
        ((phase & 0x3u) << 3u) |
        ((age_bucket & 0x3u) << 5u) |
        0x80u
    );
}

static uint8_t pack_generic(uint8_t current_missing, uint8_t phase, uint8_t age_bucket) {
    return (uint8_t)(
        (current_missing & 0x7u) |
        ((phase & 0x3u) << 3u) |
        ((age_bucket & 0x3u) << 5u) |
        0x80u
    );
}

static uint64_t scan_explicit(const explicit_age_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += (uint64_t)(records[i].age_bucket >= AGE_STALE);
    }
    return alerts;
}

static uint64_t scan_packed(const uint8_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t code = records[i];
        const uint8_t age = (uint8_t)((code >> 5u) & 0x3u);
        alerts += (uint64_t)((code & 0x80u) != 0u && age >= AGE_STALE);
    }
    return alerts;
}

int main(void) {
    const size_t n = 16000000u;
    const unsigned repeats = 10u;

    explicit_age_t *explicit_records = malloc(n * sizeof(*explicit_records));
    uint8_t *age_records = malloc(n * sizeof(*age_records));
    uint8_t *generic_records = malloc(n * sizeof(*generic_records));
    if (explicit_records == NULL || age_records == NULL || generic_records == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_records);
        free(age_records);
        free(generic_records);
        return 2;
    }

    double started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t age = (uint8_t)(i & 3u);
        explicit_records[i] = (explicit_age_t){0x4u, PHASE_CONVERGING, age};
    }
    const double explicit_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        age_records[i] = pack_age(0x4u, PHASE_CONVERGING, (uint8_t)(i & 3u));
    }
    const double age_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        generic_records[i] = pack_generic(0x4u, PHASE_CONVERGING, (uint8_t)(i & 3u));
    }
    const double generic_build = now_seconds() - started;

    for (size_t i = 0; i < n; ++i) {
        if (age_records[i] != generic_records[i]) {
            fprintf(stderr, "representation mismatch at %zu\n", i);
            free(explicit_records);
            free(age_records);
            free(generic_records);
            return 3;
        }
    }

    const uint64_t expected = n / 2u;
    const uint64_t explicit_warm = scan_explicit(explicit_records, n);
    const uint64_t age_warm = scan_packed(age_records, n);
    const uint64_t generic_warm = scan_packed(generic_records, n);
    if (explicit_warm != expected || age_warm != expected || generic_warm != expected) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(explicit_records);
        free(age_records);
        free(generic_records);
        return 4;
    }

    double explicit_total = 0.0;
    double age_total = 0.0;
    double generic_total = 0.0;
    uint64_t explicit_checksum = 0;
    uint64_t age_checksum = 0;
    uint64_t generic_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        if ((r % 3u) == 0u) {
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
            started = now_seconds();
            age_checksum += scan_packed(age_records, n);
            age_total += now_seconds() - started;
            started = now_seconds();
            generic_checksum += scan_packed(generic_records, n);
            generic_total += now_seconds() - started;
        } else if ((r % 3u) == 1u) {
            started = now_seconds();
            generic_checksum += scan_packed(generic_records, n);
            generic_total += now_seconds() - started;
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
            started = now_seconds();
            age_checksum += scan_packed(age_records, n);
            age_total += now_seconds() - started;
        } else {
            started = now_seconds();
            age_checksum += scan_packed(age_records, n);
            age_total += now_seconds() - started;
            started = now_seconds();
            generic_checksum += scan_packed(generic_records, n);
            generic_total += now_seconds() - started;
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
        }
    }

    if (explicit_checksum != age_checksum || age_checksum != generic_checksum) {
        fprintf(stderr, "checksum mismatch\n");
        free(explicit_records);
        free(age_records);
        free(generic_records);
        return 5;
    }

    const double explicit_scan = explicit_total / repeats;
    const double age_scan = age_total / repeats;
    const double generic_scan = generic_total / repeats;
    const size_t explicit_bytes = n * sizeof(*explicit_records);
    const size_t age_bytes = n * sizeof(*age_records);
    const size_t generic_bytes = n * sizeof(*generic_records);

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("age_buckets=4\n");
    printf("same_current_center=true\n");
    printf("same_current_phase=true\n");
    printf("representation_identity=true\n");
    printf("correct=true\n\n");

    printf("[explicit phase-age record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*explicit_records));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[one-byte phase-age signature]\n");
    printf("bytes_per_record=1\n");
    printf("total_bytes=%zu\n", age_bytes);
    printf("build_seconds=%.6f\n", age_build);
    printf("scan_seconds_avg=%.6f\n\n", age_scan);

    printf("[generic one-byte equal-information control]\n");
    printf("bytes_per_record=1\n");
    printf("total_bytes=%zu\n", generic_bytes);
    printf("build_seconds=%.6f\n", generic_build);
    printf("scan_seconds_avg=%.6f\n\n", generic_scan);

    printf("age_memory_vs_explicit=%.3fx\n", (double)age_bytes / (double)explicit_bytes);
    printf("age_build_vs_explicit=%.3fx\n", age_build / explicit_build);
    printf("age_scan_vs_explicit=%.3fx\n", age_scan / explicit_scan);
    printf("age_build_vs_generic=%.3fx\n", age_build / generic_build);
    printf("age_scan_vs_generic=%.3fx\n", age_scan / generic_scan);
    printf("stale_or_expired_alerts_per_scan=%" PRIu64 "\n", age_warm);
    printf("control_note=generic packed control is intentionally byte-identical; any packed advantage belongs to explicit hot dwell-time representation, not the Tao name\n");

    free(explicit_records);
    free(age_records);
    free(generic_records);
    return 0;
}

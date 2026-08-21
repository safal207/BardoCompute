#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

typedef struct {
    uint8_t current_missing;
    uint8_t previous_phase;
    uint8_t current_phase;
    uint8_t age_bucket;
    uint8_t had_regression;
    uint8_t had_discontinuity;
    uint8_t decision;
    uint8_t capability_mode;
} explicit_capability_t;

enum {
    PHASE_STALLED = 0,
    PHASE_CONVERGING = 1,
    PHASE_REGRESSING = 2,
    PHASE_REORIENTING = 3,
    AGE_FRESH = 0,
    AGE_WARM = 1,
    AGE_STALE = 2,
    DECISION_ALLOW = 0,
    DECISION_DEFER = 1,
    MODE_MANIFEST = 0,
    MODE_ACQUIRE = 1,
    MODE_ADAPT = 2,
    CAPABILITY_POLICY_ENTRIES = 1 << 16
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t expected_mode(
    uint8_t current_missing,
    uint8_t current_phase,
    uint8_t age_bucket,
    uint8_t had_discontinuity
) {
    if (
        had_discontinuity != 0u ||
        current_phase == PHASE_REGRESSING ||
        current_phase == PHASE_REORIENTING
    ) {
        return MODE_ADAPT;
    }
    if (
        current_missing != 0u ||
        (current_phase == PHASE_STALLED && age_bucket >= AGE_STALE)
    ) {
        return MODE_ACQUIRE;
    }
    return MODE_MANIFEST;
}

static uint16_t pack_state(explicit_capability_t record) {
    return (uint16_t)(
        (uint16_t)(record.current_missing & 0x7u) |
        ((uint16_t)(record.previous_phase & 0x3u) << 3u) |
        ((uint16_t)(record.current_phase & 0x3u) << 5u) |
        ((uint16_t)(record.age_bucket & 0x3u) << 7u) |
        ((uint16_t)(record.had_regression & 0x1u) << 9u) |
        ((uint16_t)(record.had_discontinuity & 0x1u) << 10u) |
        ((uint16_t)1u << 11u) |
        ((uint16_t)(record.decision & 0x3u) << 12u) |
        ((uint16_t)(record.capability_mode & 0x3u) << 14u)
    );
}

static uint8_t explicit_alert(explicit_capability_t record) {
    const uint8_t current_regression =
        (uint8_t)(record.current_phase == PHASE_REGRESSING);
    const uint8_t recent_regression = (uint8_t)(
        record.previous_phase == PHASE_REGRESSING &&
        record.current_phase == PHASE_CONVERGING
    );
    const uint8_t stale_stall = (uint8_t)(
        record.current_phase == PHASE_STALLED &&
        record.age_bucket >= AGE_STALE
    );
    const uint8_t mode_mismatch = (uint8_t)(
        record.capability_mode != expected_mode(
            record.current_missing,
            record.current_phase,
            record.age_bucket,
            record.had_discontinuity
        )
    );
    return (uint8_t)(
        current_regression ||
        recent_regression ||
        stale_stall ||
        record.had_discontinuity != 0u ||
        record.decision == 2u ||
        mode_mismatch
    );
}

static uint8_t packed_alert(uint16_t code) {
    const uint8_t current_missing = (uint8_t)(code & 0x7u);
    const uint8_t previous = (uint8_t)((code >> 3u) & 0x3u);
    const uint8_t current = (uint8_t)((code >> 5u) & 0x3u);
    const uint8_t age = (uint8_t)((code >> 7u) & 0x3u);
    const uint8_t discontinuity = (uint8_t)((code >> 10u) & 0x1u);
    const uint8_t edge_valid = (uint8_t)((code >> 11u) & 0x1u);
    const uint8_t decision = (uint8_t)((code >> 12u) & 0x3u);
    const uint8_t mode = (uint8_t)((code >> 14u) & 0x3u);
    const uint8_t current_regression = (uint8_t)(current == PHASE_REGRESSING);
    const uint8_t recent_regression = (uint8_t)(
        edge_valid != 0u &&
        previous == PHASE_REGRESSING &&
        current == PHASE_CONVERGING
    );
    const uint8_t stale_stall = (uint8_t)(
        current == PHASE_STALLED && age >= AGE_STALE
    );
    const uint8_t mode_mismatch = (uint8_t)(
        mode == 3u ||
        mode != expected_mode(current_missing, current, age, discontinuity)
    );
    return (uint8_t)(
        current_regression ||
        recent_regression ||
        stale_stall ||
        discontinuity != 0u ||
        decision == 2u ||
        mode_mismatch
    );
}

static uint64_t scan_explicit(const explicit_capability_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += explicit_alert(records[i]);
    }
    return alerts;
}

static uint64_t scan_direct(const uint16_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += packed_alert(records[i]);
    }
    return alerts;
}

static uint64_t scan_lut(
    const uint16_t *records,
    size_t n,
    const uint8_t policy[CAPABILITY_POLICY_ENTRIES]
) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += policy[records[i]];
    }
    return alerts;
}

static explicit_capability_t make_record(size_t i) {
    const uint8_t kind = (uint8_t)(i % 6u);
    explicit_capability_t record = {
        0u,
        PHASE_CONVERGING,
        PHASE_CONVERGING,
        AGE_FRESH,
        0u,
        0u,
        DECISION_ALLOW,
        MODE_MANIFEST
    };

    if (kind == 1u) {
        record.current_missing = 4u;
        record.previous_phase = PHASE_STALLED;
        record.current_phase = PHASE_STALLED;
        record.age_bucket = AGE_WARM;
        record.decision = DECISION_DEFER;
        record.capability_mode = MODE_ACQUIRE;
    } else if (kind == 2u) {
        record.current_phase = PHASE_REGRESSING;
        record.had_regression = 1u;
        record.capability_mode = MODE_ADAPT;
    } else if (kind == 3u) {
        record.current_phase = PHASE_REORIENTING;
        record.capability_mode = MODE_ADAPT;
    } else if (kind == 4u) {
        record.capability_mode = MODE_ACQUIRE;
    } else if (kind == 5u) {
        record.current_missing = 4u;
        record.decision = DECISION_DEFER;
        record.capability_mode = MODE_MANIFEST;
    }
    return record;
}

int main(void) {
    const size_t n = 12000000u;
    const unsigned repeats = 12u;
    explicit_capability_t *explicit_records = malloc(n * sizeof(*explicit_records));
    uint16_t *packed_records = malloc(n * sizeof(*packed_records));
    uint16_t *generic_records = malloc(n * sizeof(*generic_records));
    uint8_t *policy = malloc(CAPABILITY_POLICY_ENTRIES * sizeof(*policy));
    if (
        explicit_records == NULL || packed_records == NULL ||
        generic_records == NULL || policy == NULL
    ) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_records);
        free(packed_records);
        free(generic_records);
        free(policy);
        return 2;
    }

    double started = now_seconds();
    for (unsigned code = 0; code < CAPABILITY_POLICY_ENTRIES; ++code) {
        policy[code] = packed_alert((uint16_t)code);
    }
    const double policy_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        explicit_records[i] = make_record(i);
    }
    const double explicit_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        packed_records[i] = pack_state(make_record(i));
    }
    const double packed_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        generic_records[i] = pack_state(make_record(i));
    }
    const double generic_build = now_seconds() - started;

    for (size_t i = 0; i < n; ++i) {
        if (packed_records[i] != generic_records[i]) {
            fprintf(stderr, "representation mismatch at %zu\n", i);
            free(explicit_records);
            free(packed_records);
            free(generic_records);
            free(policy);
            return 3;
        }
    }

    const uint64_t explicit_warm = scan_explicit(explicit_records, n);
    const uint64_t direct_warm = scan_direct(packed_records, n);
    const uint64_t lut_warm = scan_lut(packed_records, n, policy);
    const uint64_t generic_warm = scan_lut(generic_records, n, policy);
    if (
        explicit_warm != direct_warm || direct_warm != lut_warm ||
        lut_warm != generic_warm
    ) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(explicit_records);
        free(packed_records);
        free(generic_records);
        free(policy);
        return 4;
    }

    double explicit_total = 0.0;
    double direct_total = 0.0;
    double lut_total = 0.0;
    double generic_total = 0.0;
    uint64_t explicit_checksum = 0;
    uint64_t direct_checksum = 0;
    uint64_t lut_checksum = 0;
    uint64_t generic_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        started = now_seconds();
        explicit_checksum += scan_explicit(explicit_records, n);
        explicit_total += now_seconds() - started;

        started = now_seconds();
        direct_checksum += scan_direct(packed_records, n);
        direct_total += now_seconds() - started;

        started = now_seconds();
        lut_checksum += scan_lut(packed_records, n, policy);
        lut_total += now_seconds() - started;

        started = now_seconds();
        generic_checksum += scan_lut(generic_records, n, policy);
        generic_total += now_seconds() - started;
    }

    if (
        explicit_checksum != direct_checksum || direct_checksum != lut_checksum ||
        lut_checksum != generic_checksum
    ) {
        fprintf(stderr, "checksum mismatch\n");
        free(explicit_records);
        free(packed_records);
        free(generic_records);
        free(policy);
        return 5;
    }

    const double explicit_scan = explicit_total / repeats;
    const double direct_scan = direct_total / repeats;
    const double lut_scan = lut_total / repeats;
    const double generic_scan = generic_total / repeats;
    const size_t explicit_bytes = n * sizeof(*explicit_records);
    const size_t packed_bytes = n * sizeof(*packed_records);
    const size_t policy_bytes = CAPABILITY_POLICY_ENTRIES * sizeof(*policy);

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("state_bits=16\n");
    printf("capability_bits=2\n");
    printf("capability_modes=3\n");
    printf("policy_entries=%d\n", CAPABILITY_POLICY_ENTRIES);
    printf("policy_bytes=%zu\n", policy_bytes);
    printf("policy_build_seconds=%.9f\n", policy_build);
    printf("alerts_per_scan=%" PRIu64 "\n", explicit_warm);
    printf("representation_identity=true\n");
    printf("correct=true\n\n");

    printf("[explicit temporal + capability record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*explicit_records));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[CapabilityTemporalState16 direct decode]\n");
    printf("bytes_per_record=%zu\n", sizeof(*packed_records));
    printf("total_bytes=%zu\n", packed_bytes);
    printf("build_seconds=%.6f\n", packed_build);
    printf("scan_seconds_avg=%.6f\n\n", direct_scan);

    printf("[CapabilityTemporalState16 + 64KB policy LUT]\n");
    printf("total_bytes=%zu\n", packed_bytes);
    printf("scan_seconds_avg=%.6f\n\n", lut_scan);

    printf("[generic equal-information uint16_t + same LUT]\n");
    printf("total_bytes=%zu\n", packed_bytes);
    printf("build_seconds=%.6f\n", generic_build);
    printf("scan_seconds_avg=%.6f\n\n", generic_scan);

    printf("packed_memory_vs_explicit=%.3fx\n", (double)packed_bytes / (double)explicit_bytes);
    printf("packed_build_vs_explicit=%.3fx\n", packed_build / explicit_build);
    printf("direct_scan_vs_explicit=%.3fx\n", direct_scan / explicit_scan);
    printf("lut_scan_vs_explicit=%.3fx\n", lut_scan / explicit_scan);
    printf("lut_scan_vs_direct=%.3fx\n", lut_scan / direct_scan);
    printf("lut_scan_vs_generic=%.3fx\n", lut_scan / generic_scan);
    printf("control_note=the two capability bits fill the previous TemporalState16 reserve; generic uint16_t uses identical bits and the same 64KB lookup table\n");

    free(explicit_records);
    free(packed_records);
    free(generic_records);
    free(policy);
    return 0;
}

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
} explicit_temporal_t;

enum {
    PHASE_STALLED = 0,
    PHASE_CONVERGING = 1,
    PHASE_REGRESSING = 2,
    PHASE_REORIENTING = 3,
    AGE_FRESH = 0,
    AGE_WARM = 1,
    AGE_STALE = 2,
    AGE_EXPIRED = 3,
    DECISION_ALLOW = 0,
    DECISION_DEFER = 1,
    DECISION_DENY = 2,
    TEMPORAL_USED_BITS = 14,
    TEMPORAL_POLICY_ENTRIES = 1 << TEMPORAL_USED_BITS,
    TEMPORAL_POLICY_MASK = TEMPORAL_POLICY_ENTRIES - 1
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint16_t pack_temporal(
    uint8_t current_missing,
    uint8_t previous_phase,
    uint8_t current_phase,
    uint8_t age_bucket,
    uint8_t had_regression,
    uint8_t had_discontinuity,
    uint8_t decision
) {
    return (uint16_t)(
        (uint16_t)(current_missing & 0x7u) |
        ((uint16_t)(previous_phase & 0x3u) << 3u) |
        ((uint16_t)(current_phase & 0x3u) << 5u) |
        ((uint16_t)(age_bucket & 0x3u) << 7u) |
        ((uint16_t)(had_regression & 0x1u) << 9u) |
        ((uint16_t)(had_discontinuity & 0x1u) << 10u) |
        ((uint16_t)1u << 11u) |
        ((uint16_t)(decision & 0x3u) << 12u)
    );
}

static uint16_t pack_generic(
    uint8_t current_missing,
    uint8_t previous_phase,
    uint8_t current_phase,
    uint8_t age_bucket,
    uint8_t had_regression,
    uint8_t had_discontinuity,
    uint8_t decision
) {
    return pack_temporal(
        current_missing,
        previous_phase,
        current_phase,
        age_bucket,
        had_regression,
        had_discontinuity,
        decision
    );
}

static uint8_t explicit_alert(explicit_temporal_t record) {
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
    return (uint8_t)(
        current_regression ||
        recent_regression ||
        stale_stall ||
        record.had_discontinuity != 0u ||
        record.decision == DECISION_DENY
    );
}

static uint8_t packed_alert(uint16_t code) {
    const uint8_t previous = (uint8_t)((code >> 3u) & 0x3u);
    const uint8_t current = (uint8_t)((code >> 5u) & 0x3u);
    const uint8_t age = (uint8_t)((code >> 7u) & 0x3u);
    const uint8_t discontinuity = (uint8_t)((code >> 10u) & 0x1u);
    const uint8_t edge_valid = (uint8_t)((code >> 11u) & 0x1u);
    const uint8_t decision = (uint8_t)((code >> 12u) & 0x3u);

    const uint8_t current_regression = (uint8_t)(current == PHASE_REGRESSING);
    const uint8_t recent_regression = (uint8_t)(
        edge_valid != 0u &&
        previous == PHASE_REGRESSING &&
        current == PHASE_CONVERGING
    );
    const uint8_t stale_stall = (uint8_t)(
        current == PHASE_STALLED && age >= AGE_STALE
    );
    return (uint8_t)(
        current_regression ||
        recent_regression ||
        stale_stall ||
        discontinuity != 0u ||
        decision == DECISION_DENY
    );
}

static uint64_t scan_explicit(const explicit_temporal_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += explicit_alert(records[i]);
    }
    return alerts;
}

static uint64_t scan_packed_direct(const uint16_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += packed_alert(records[i]);
    }
    return alerts;
}

static uint64_t scan_packed_lut(
    const uint16_t *records,
    size_t n,
    const uint8_t policy[TEMPORAL_POLICY_ENTRIES]
) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        alerts += policy[records[i] & TEMPORAL_POLICY_MASK];
    }
    return alerts;
}

static explicit_temporal_t make_record(size_t i) {
    const uint8_t kind = (uint8_t)(i % 5u);
    explicit_temporal_t record = {
        0x4u,
        PHASE_CONVERGING,
        PHASE_CONVERGING,
        AGE_FRESH,
        0u,
        0u,
        DECISION_DEFER
    };

    if (kind == 1u) {
        record.current_phase = PHASE_REGRESSING;
        record.had_regression = 1u;
    } else if (kind == 2u) {
        record.previous_phase = PHASE_REGRESSING;
        record.had_regression = 1u;
    } else if (kind == 3u) {
        record.previous_phase = PHASE_STALLED;
        record.current_phase = PHASE_STALLED;
        record.age_bucket = AGE_STALE;
    } else if (kind == 4u) {
        record.had_discontinuity = 1u;
    }
    return record;
}

int main(void) {
    const size_t n = 12000000u;
    const unsigned repeats = 12u;
    const uint64_t expected_alerts = (uint64_t)(n / 5u * 4u);

    explicit_temporal_t *explicit_records = malloc(n * sizeof(*explicit_records));
    uint16_t *temporal_records = malloc(n * sizeof(*temporal_records));
    uint16_t *generic_records = malloc(n * sizeof(*generic_records));
    uint8_t *policy = malloc(TEMPORAL_POLICY_ENTRIES * sizeof(*policy));
    if (
        explicit_records == NULL ||
        temporal_records == NULL ||
        generic_records == NULL ||
        policy == NULL
    ) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_records);
        free(temporal_records);
        free(generic_records);
        free(policy);
        return 2;
    }

    double started = now_seconds();
    for (unsigned code = 0; code < TEMPORAL_POLICY_ENTRIES; ++code) {
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
        const explicit_temporal_t record = make_record(i);
        temporal_records[i] = pack_temporal(
            record.current_missing,
            record.previous_phase,
            record.current_phase,
            record.age_bucket,
            record.had_regression,
            record.had_discontinuity,
            record.decision
        );
    }
    const double temporal_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const explicit_temporal_t record = make_record(i);
        generic_records[i] = pack_generic(
            record.current_missing,
            record.previous_phase,
            record.current_phase,
            record.age_bucket,
            record.had_regression,
            record.had_discontinuity,
            record.decision
        );
    }
    const double generic_build = now_seconds() - started;

    for (size_t i = 0; i < n; ++i) {
        if (temporal_records[i] != generic_records[i]) {
            fprintf(stderr, "representation mismatch at %zu\n", i);
            free(explicit_records);
            free(temporal_records);
            free(generic_records);
            free(policy);
            return 3;
        }
        if ((temporal_records[i] & 0xC000u) != 0u) {
            fprintf(stderr, "reserved bits unexpectedly set at %zu\n", i);
            free(explicit_records);
            free(temporal_records);
            free(generic_records);
            free(policy);
            return 4;
        }
    }

    const uint64_t explicit_warm = scan_explicit(explicit_records, n);
    const uint64_t direct_warm = scan_packed_direct(temporal_records, n);
    const uint64_t lut_warm = scan_packed_lut(temporal_records, n, policy);
    const uint64_t generic_lut_warm = scan_packed_lut(generic_records, n, policy);
    if (
        explicit_warm != expected_alerts ||
        direct_warm != expected_alerts ||
        lut_warm != expected_alerts ||
        generic_lut_warm != expected_alerts
    ) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(explicit_records);
        free(temporal_records);
        free(generic_records);
        free(policy);
        return 5;
    }

    double explicit_total = 0.0;
    double direct_total = 0.0;
    double lut_total = 0.0;
    double generic_lut_total = 0.0;
    uint64_t explicit_checksum = 0;
    uint64_t direct_checksum = 0;
    uint64_t lut_checksum = 0;
    uint64_t generic_lut_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        const unsigned order = r & 3u;
        if (order == 0u) {
            started = now_seconds(); explicit_checksum += scan_explicit(explicit_records, n); explicit_total += now_seconds() - started;
            started = now_seconds(); direct_checksum += scan_packed_direct(temporal_records, n); direct_total += now_seconds() - started;
            started = now_seconds(); lut_checksum += scan_packed_lut(temporal_records, n, policy); lut_total += now_seconds() - started;
            started = now_seconds(); generic_lut_checksum += scan_packed_lut(generic_records, n, policy); generic_lut_total += now_seconds() - started;
        } else if (order == 1u) {
            started = now_seconds(); direct_checksum += scan_packed_direct(temporal_records, n); direct_total += now_seconds() - started;
            started = now_seconds(); lut_checksum += scan_packed_lut(temporal_records, n, policy); lut_total += now_seconds() - started;
            started = now_seconds(); generic_lut_checksum += scan_packed_lut(generic_records, n, policy); generic_lut_total += now_seconds() - started;
            started = now_seconds(); explicit_checksum += scan_explicit(explicit_records, n); explicit_total += now_seconds() - started;
        } else if (order == 2u) {
            started = now_seconds(); lut_checksum += scan_packed_lut(temporal_records, n, policy); lut_total += now_seconds() - started;
            started = now_seconds(); generic_lut_checksum += scan_packed_lut(generic_records, n, policy); generic_lut_total += now_seconds() - started;
            started = now_seconds(); explicit_checksum += scan_explicit(explicit_records, n); explicit_total += now_seconds() - started;
            started = now_seconds(); direct_checksum += scan_packed_direct(temporal_records, n); direct_total += now_seconds() - started;
        } else {
            started = now_seconds(); generic_lut_checksum += scan_packed_lut(generic_records, n, policy); generic_lut_total += now_seconds() - started;
            started = now_seconds(); explicit_checksum += scan_explicit(explicit_records, n); explicit_total += now_seconds() - started;
            started = now_seconds(); direct_checksum += scan_packed_direct(temporal_records, n); direct_total += now_seconds() - started;
            started = now_seconds(); lut_checksum += scan_packed_lut(temporal_records, n, policy); lut_total += now_seconds() - started;
        }
    }

    if (
        explicit_checksum != direct_checksum ||
        direct_checksum != lut_checksum ||
        lut_checksum != generic_lut_checksum
    ) {
        fprintf(stderr, "checksum mismatch\n");
        free(explicit_records);
        free(temporal_records);
        free(generic_records);
        free(policy);
        return 6;
    }

    const double explicit_scan = explicit_total / repeats;
    const double direct_scan = direct_total / repeats;
    const double lut_scan = lut_total / repeats;
    const double generic_lut_scan = generic_lut_total / repeats;
    const size_t explicit_bytes = n * sizeof(*explicit_records);
    const size_t temporal_bytes = n * sizeof(*temporal_records);
    const size_t generic_bytes = n * sizeof(*generic_records);
    const size_t policy_bytes = TEMPORAL_POLICY_ENTRIES * sizeof(*policy);

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("used_bits=%d\n", TEMPORAL_USED_BITS);
    printf("reserved_bits=2\n");
    printf("policy_entries=%d\n", TEMPORAL_POLICY_ENTRIES);
    printf("policy_bytes=%zu\n", policy_bytes);
    printf("policy_build_seconds=%.9f\n", policy_build);
    printf("expected_alerts=%" PRIu64 "\n", expected_alerts);
    printf("representation_identity=true\n");
    printf("correct=true\n\n");

    printf("[explicit equal-information temporal record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*explicit_records));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[TemporalState16 direct decode]\n");
    printf("bytes_per_record=%zu\n", sizeof(*temporal_records));
    printf("total_bytes=%zu\n", temporal_bytes);
    printf("build_seconds=%.6f\n", temporal_build);
    printf("scan_seconds_avg=%.6f\n\n", direct_scan);

    printf("[TemporalState16 + 16KB policy LUT]\n");
    printf("total_bytes=%zu\n", temporal_bytes);
    printf("scan_seconds_avg=%.6f\n\n", lut_scan);

    printf("[generic equal-information uint16_t + same LUT]\n");
    printf("total_bytes=%zu\n", generic_bytes);
    printf("build_seconds=%.6f\n", generic_build);
    printf("scan_seconds_avg=%.6f\n\n", generic_lut_scan);

    printf("temporal_memory_vs_explicit=%.3fx\n", (double)temporal_bytes / (double)explicit_bytes);
    printf("temporal_build_vs_explicit=%.3fx\n", temporal_build / explicit_build);
    printf("direct_scan_vs_explicit=%.3fx\n", direct_scan / explicit_scan);
    printf("lut_scan_vs_explicit=%.3fx\n", lut_scan / explicit_scan);
    printf("lut_scan_vs_direct=%.3fx\n", lut_scan / direct_scan);
    printf("lut_scan_vs_generic_lut=%.3fx\n", lut_scan / generic_lut_scan);
    printf("alerts_per_scan=%" PRIu64 "\n", lut_warm);
    printf("control_note=the 16KB lookup execution path is generic to the 14-bit state space; generic uint16_t uses the identical table and bits\n");

    free(explicit_records);
    free(temporal_records);
    free(generic_records);
    free(policy);
    return 0;
}

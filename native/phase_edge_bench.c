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
} explicit_edge_t;

enum {
    PHASE_STALLED = 0,
    PHASE_CONVERGING = 1,
    PHASE_REGRESSING = 2,
    PHASE_REORIENTING = 3
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t pack_edge(uint8_t current_missing, uint8_t previous, uint8_t current) {
    return (uint8_t)(
        (current_missing & 0x7u) |
        ((previous & 0x3u) << 3u) |
        ((current & 0x3u) << 5u) |
        0x80u
    );
}

/* Deliberately identical conventional one-byte control. */
static uint8_t pack_generic(uint8_t current_missing, uint8_t previous, uint8_t current) {
    return (uint8_t)(
        (current_missing & 0x7u) |
        ((previous & 0x3u) << 3u) |
        ((current & 0x3u) << 5u) |
        0x80u
    );
}

static uint64_t scan_explicit(const explicit_edge_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        const explicit_edge_t record = records[i];
        alerts += (uint64_t)(
            record.current_phase == PHASE_CONVERGING &&
            record.previous_phase == PHASE_REGRESSING
        );
    }
    return alerts;
}

static uint64_t scan_packed(const uint8_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t code = records[i];
        const uint8_t previous = (uint8_t)((code >> 3u) & 0x3u);
        const uint8_t current = (uint8_t)((code >> 5u) & 0x3u);
        alerts += (uint64_t)(
            (code & 0x80u) != 0u &&
            current == PHASE_CONVERGING &&
            previous == PHASE_REGRESSING
        );
    }
    return alerts;
}

int main(void) {
    const size_t n = 16000000u;
    const unsigned repeats = 10u;

    explicit_edge_t *explicit_records = malloc(n * sizeof(*explicit_records));
    uint8_t *edge_records = malloc(n * sizeof(*edge_records));
    uint8_t *generic_records = malloc(n * sizeof(*generic_records));
    if (explicit_records == NULL || edge_records == NULL || generic_records == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_records);
        free(edge_records);
        free(generic_records);
        return 2;
    }

    double started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t previous = (uint8_t)(i & 3u);
        const uint8_t current = PHASE_CONVERGING;
        const uint8_t center = 0x4u; /* OUTCOME missing for every record. */
        explicit_records[i] = (explicit_edge_t){center, previous, current};
    }
    const double explicit_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t previous = (uint8_t)(i & 3u);
        edge_records[i] = pack_edge(0x4u, previous, PHASE_CONVERGING);
    }
    const double edge_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t previous = (uint8_t)(i & 3u);
        generic_records[i] = pack_generic(0x4u, previous, PHASE_CONVERGING);
    }
    const double generic_build = now_seconds() - started;

    for (size_t i = 0; i < n; ++i) {
        if (edge_records[i] != generic_records[i]) {
            fprintf(stderr, "representation mismatch at %zu\n", i);
            free(explicit_records);
            free(edge_records);
            free(generic_records);
            return 3;
        }
    }

    const uint64_t explicit_warm = scan_explicit(explicit_records, n);
    const uint64_t edge_warm = scan_packed(edge_records, n);
    const uint64_t generic_warm = scan_packed(generic_records, n);
    const uint64_t expected_alerts = n / 4u;
    if (explicit_warm != expected_alerts || edge_warm != expected_alerts || generic_warm != expected_alerts) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(explicit_records);
        free(edge_records);
        free(generic_records);
        return 4;
    }

    double explicit_total = 0.0;
    double edge_total = 0.0;
    double generic_total = 0.0;
    uint64_t explicit_checksum = 0;
    uint64_t edge_checksum = 0;
    uint64_t generic_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        if ((r % 3u) == 0u) {
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
            started = now_seconds();
            edge_checksum += scan_packed(edge_records, n);
            edge_total += now_seconds() - started;
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
            edge_checksum += scan_packed(edge_records, n);
            edge_total += now_seconds() - started;
        } else {
            started = now_seconds();
            edge_checksum += scan_packed(edge_records, n);
            edge_total += now_seconds() - started;
            started = now_seconds();
            generic_checksum += scan_packed(generic_records, n);
            generic_total += now_seconds() - started;
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
        }
    }

    if (explicit_checksum != edge_checksum || edge_checksum != generic_checksum) {
        fprintf(stderr, "checksum mismatch\n");
        free(explicit_records);
        free(edge_records);
        free(generic_records);
        return 5;
    }

    const double explicit_scan = explicit_total / repeats;
    const double edge_scan = edge_total / repeats;
    const double generic_scan = generic_total / repeats;
    const size_t explicit_bytes = n * sizeof(*explicit_records);
    const size_t edge_bytes = n * sizeof(*edge_records);
    const size_t generic_bytes = n * sizeof(*generic_records);

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("phase_edge_states=16\n");
    printf("all_current_centers_equal=true\n");
    printf("all_current_phases_equal=true\n");
    printf("representation_identity=true\n");
    printf("correct=true\n\n");

    printf("[explicit previous/current phase record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*explicit_records));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[one-byte phase edge signature]\n");
    printf("bytes_per_record=1\n");
    printf("total_bytes=%zu\n", edge_bytes);
    printf("build_seconds=%.6f\n", edge_build);
    printf("scan_seconds_avg=%.6f\n\n", edge_scan);

    printf("[generic one-byte equal-information control]\n");
    printf("bytes_per_record=1\n");
    printf("total_bytes=%zu\n", generic_bytes);
    printf("build_seconds=%.6f\n", generic_build);
    printf("scan_seconds_avg=%.6f\n\n", generic_scan);

    printf("edge_memory_vs_explicit=%.3fx\n", (double)edge_bytes / (double)explicit_bytes);
    printf("edge_build_vs_explicit=%.3fx\n", edge_build / explicit_build);
    printf("edge_scan_vs_explicit=%.3fx\n", edge_scan / explicit_scan);
    printf("edge_build_vs_generic=%.3fx\n", edge_build / generic_build);
    printf("edge_scan_vs_generic=%.3fx\n", edge_scan / generic_scan);
    printf("recent_regression_alerts_per_scan=%" PRIu64 "\n", edge_warm);
    printf("control_note=generic packed control is intentionally byte-identical; any packed advantage belongs to ordered online phase representation, not the Bardo/Tao name\n");

    free(explicit_records);
    free(edge_records);
    free(generic_records);
    return 0;
}

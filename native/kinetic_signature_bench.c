#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

typedef struct {
    uint8_t current_missing;
    uint8_t had_regression;
    uint8_t had_discontinuity;
    uint8_t phase;
    uint8_t phase_valid;
} explicit_kinetic_t;

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

static uint8_t classify_phase(uint8_t previous, uint8_t current) {
    const uint8_t cleared = (uint8_t)((previous & (uint8_t)~current) & 0x7u);
    const uint8_t added = (uint8_t)(((uint8_t)~previous & current) & 0x7u);
    if (cleared != 0u && added != 0u) {
        return PHASE_REORIENTING;
    }
    if (cleared != 0u) {
        return PHASE_CONVERGING;
    }
    if (added != 0u) {
        return PHASE_REGRESSING;
    }
    return PHASE_STALLED;
}

static uint8_t pack_kinetic(
    uint8_t current_missing,
    uint8_t had_regression,
    uint8_t had_discontinuity,
    uint8_t phase
) {
    return (uint8_t)(
        (current_missing & 0x7u) |
        ((had_regression & 1u) << 3u) |
        ((had_discontinuity & 1u) << 4u) |
        ((phase & 0x3u) << 5u) |
        0x80u
    );
}

/* Fair conventional control: deliberately the same one-byte information. */
static uint8_t pack_generic_control(
    uint8_t current_missing,
    uint8_t had_regression,
    uint8_t had_discontinuity,
    uint8_t phase
) {
    return (uint8_t)(
        (current_missing & 0x7u) |
        ((had_regression & 1u) << 3u) |
        ((had_discontinuity & 1u) << 4u) |
        ((phase & 0x3u) << 5u) |
        0x80u
    );
}

static uint64_t scan_explicit(const explicit_kinetic_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        const explicit_kinetic_t record = records[i];
        alerts += (uint64_t)(
            record.phase_valid != 0u &&
            (record.phase == PHASE_REGRESSING || record.had_discontinuity != 0u)
        );
    }
    return alerts;
}

static uint64_t scan_packed(const uint8_t *records, size_t n) {
    uint64_t alerts = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t code = records[i];
        const uint8_t phase = (uint8_t)((code >> 5u) & 0x3u);
        alerts += (uint64_t)(
            (code & 0x80u) != 0u &&
            (phase == PHASE_REGRESSING || (code & 0x10u) != 0u)
        );
    }
    return alerts;
}

int main(void) {
    const size_t n = 12000000u;
    const unsigned repeats = 10u;

    explicit_kinetic_t *explicit_records = malloc(n * sizeof(*explicit_records));
    uint8_t *kinetic_records = malloc(n * sizeof(*kinetic_records));
    uint8_t *generic_records = malloc(n * sizeof(*generic_records));
    if (explicit_records == NULL || kinetic_records == NULL || generic_records == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(explicit_records);
        free(kinetic_records);
        free(generic_records);
        return 2;
    }

    double started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t kind = (uint8_t)(i & 3u);
        const uint8_t current = 0x4u; /* OUTCOME missing for every record. */
        uint8_t previous;
        if (kind == 0u) {
            previous = 0x5u; /* AUTHORITY + OUTCOME -> OUTCOME: converging */
        } else if (kind == 1u) {
            previous = 0x4u; /* OUTCOME -> OUTCOME: stalled */
        } else if (kind == 2u) {
            previous = 0x0u; /* settled -> OUTCOME: regressing */
        } else {
            previous = 0x1u; /* AUTHORITY -> OUTCOME: reorienting */
        }
        const uint8_t phase = classify_phase(previous, current);
        const uint8_t regression = (uint8_t)(
            phase == PHASE_REGRESSING || phase == PHASE_REORIENTING
        );
        const uint8_t discontinuity = (uint8_t)((i % 17u) == 0u);
        explicit_records[i] = (explicit_kinetic_t){
            current,
            regression,
            discontinuity,
            phase,
            1u
        };
    }
    const double explicit_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t kind = (uint8_t)(i & 3u);
        const uint8_t current = 0x4u;
        const uint8_t previous =
            kind == 0u ? 0x5u :
            kind == 1u ? 0x4u :
            kind == 2u ? 0x0u : 0x1u;
        const uint8_t phase = classify_phase(previous, current);
        const uint8_t regression = (uint8_t)(
            phase == PHASE_REGRESSING || phase == PHASE_REORIENTING
        );
        const uint8_t discontinuity = (uint8_t)((i % 17u) == 0u);
        kinetic_records[i] = pack_kinetic(current, regression, discontinuity, phase);
    }
    const double kinetic_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t kind = (uint8_t)(i & 3u);
        const uint8_t current = 0x4u;
        const uint8_t previous =
            kind == 0u ? 0x5u :
            kind == 1u ? 0x4u :
            kind == 2u ? 0x0u : 0x1u;
        const uint8_t phase = classify_phase(previous, current);
        const uint8_t regression = (uint8_t)(
            phase == PHASE_REGRESSING || phase == PHASE_REORIENTING
        );
        const uint8_t discontinuity = (uint8_t)((i % 17u) == 0u);
        generic_records[i] = pack_generic_control(
            current,
            regression,
            discontinuity,
            phase
        );
    }
    const double generic_build = now_seconds() - started;

    for (size_t i = 0; i < n; ++i) {
        if (kinetic_records[i] != generic_records[i]) {
            fprintf(stderr, "representation mismatch at %zu\n", i);
            free(explicit_records);
            free(kinetic_records);
            free(generic_records);
            return 3;
        }
    }

    const uint64_t explicit_warm = scan_explicit(explicit_records, n);
    const uint64_t kinetic_warm = scan_packed(kinetic_records, n);
    const uint64_t generic_warm = scan_packed(generic_records, n);
    if (explicit_warm != kinetic_warm || kinetic_warm != generic_warm) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(explicit_records);
        free(kinetic_records);
        free(generic_records);
        return 4;
    }

    double explicit_total = 0.0;
    double kinetic_total = 0.0;
    double generic_total = 0.0;
    uint64_t explicit_checksum = 0;
    uint64_t kinetic_checksum = 0;
    uint64_t generic_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        if ((r % 3u) == 0u) {
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
            started = now_seconds();
            kinetic_checksum += scan_packed(kinetic_records, n);
            kinetic_total += now_seconds() - started;
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
            kinetic_checksum += scan_packed(kinetic_records, n);
            kinetic_total += now_seconds() - started;
        } else {
            started = now_seconds();
            kinetic_checksum += scan_packed(kinetic_records, n);
            kinetic_total += now_seconds() - started;
            started = now_seconds();
            generic_checksum += scan_packed(generic_records, n);
            generic_total += now_seconds() - started;
            started = now_seconds();
            explicit_checksum += scan_explicit(explicit_records, n);
            explicit_total += now_seconds() - started;
        }
    }

    if (explicit_checksum != kinetic_checksum || kinetic_checksum != generic_checksum) {
        fprintf(stderr, "checksum mismatch\n");
        free(explicit_records);
        free(kinetic_records);
        free(generic_records);
        return 5;
    }

    const double explicit_scan = explicit_total / repeats;
    const double kinetic_scan = kinetic_total / repeats;
    const double generic_scan = generic_total / repeats;
    const size_t explicit_bytes = n * sizeof(*explicit_records);
    const size_t kinetic_bytes = n * sizeof(*kinetic_records);
    const size_t generic_bytes = n * sizeof(*generic_records);

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("phase_classes=4\n");
    printf("all_current_orientation_masks_equal=true\n");
    printf("representation_identity=true\n");
    printf("correct=true\n\n");

    printf("[explicit equal-information kinetic record]\n");
    printf("bytes_per_record=%zu\n", sizeof(*explicit_records));
    printf("total_bytes=%zu\n", explicit_bytes);
    printf("build_seconds=%.6f\n", explicit_build);
    printf("scan_seconds_avg=%.6f\n\n", explicit_scan);

    printf("[Bardo/Tao one-byte kinetic signature]\n");
    printf("bytes_per_record=1\n");
    printf("total_bytes=%zu\n", kinetic_bytes);
    printf("build_seconds=%.6f\n", kinetic_build);
    printf("scan_seconds_avg=%.6f\n\n", kinetic_scan);

    printf("[generic one-byte equal-information control]\n");
    printf("bytes_per_record=1\n");
    printf("total_bytes=%zu\n", generic_bytes);
    printf("build_seconds=%.6f\n", generic_build);
    printf("scan_seconds_avg=%.6f\n\n", generic_scan);

    printf("kinetic_memory_vs_explicit=%.3fx\n",
           (double)kinetic_bytes / (double)explicit_bytes);
    printf("kinetic_build_vs_explicit=%.3fx\n", kinetic_build / explicit_build);
    printf("kinetic_scan_vs_explicit=%.3fx\n", kinetic_scan / explicit_scan);
    printf("kinetic_build_vs_generic=%.3fx\n", kinetic_build / generic_build);
    printf("kinetic_scan_vs_generic=%.3fx\n", kinetic_scan / generic_scan);
    printf("alerts_per_scan=%" PRIu64 "\n", kinetic_warm);
    printf("control_note=generic packed control is intentionally byte-identical; any packed advantage belongs to online representation, not the Bardo/Tao name\n");

    free(explicit_records);
    free(kinetic_records);
    free(generic_records);
    return 0;
}

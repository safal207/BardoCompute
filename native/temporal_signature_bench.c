#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

/* phase byte: bits 0..2 missing-evidence mask, bit 3 discontinuity */
#define PHASE_MISSING(x) ((uint8_t)((x) & 0x7u))
#define PHASE_DISC(x) ((uint8_t)(((x) >> 3u) & 0x1u))

/* signature byte: bits 0..2 current missing, bit 3 regression, bit 4 discontinuity */
#define SIG_REGRESSION (1u << 3u)
#define SIG_DISCONTINUITY (1u << 4u)

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t advance_signature(uint8_t signature, uint8_t phase) {
    const uint8_t previous_missing = (uint8_t)(signature & 0x7u);
    const uint8_t next_missing = PHASE_MISSING(phase);
    const uint8_t added = (uint8_t)((~previous_missing) & next_missing & 0x7u);
    signature = (uint8_t)((signature & ~0x7u) | next_missing);
    if (added != 0u) {
        signature |= SIG_REGRESSION;
    }
    if (PHASE_DISC(phase)) {
        signature |= SIG_DISCONTINUITY;
    }
    return signature;
}

static uint64_t scan_snapshot(const uint8_t *final_masks, size_t n) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        allowed += (uint64_t)(final_masks[i] == 0u);
    }
    return allowed;
}

static uint64_t scan_full_history(const uint8_t *history, size_t n, size_t phases) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t *row = history + i * phases;
        uint8_t previous_missing = PHASE_MISSING(row[0]);
        uint8_t unsafe = PHASE_DISC(row[0]);
        for (size_t p = 1; p < phases; ++p) {
            const uint8_t next_missing = PHASE_MISSING(row[p]);
            const uint8_t added = (uint8_t)((~previous_missing) & next_missing & 0x7u);
            unsafe |= (uint8_t)(added != 0u);
            unsafe |= PHASE_DISC(row[p]);
            previous_missing = next_missing;
        }
        allowed += (uint64_t)(!unsafe && previous_missing == 0u);
    }
    return allowed;
}

static uint64_t scan_signature(const uint8_t *signatures, size_t n) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        const uint8_t signature = signatures[i];
        const uint8_t unsafe = (uint8_t)(signature & (SIG_REGRESSION | SIG_DISCONTINUITY));
        allowed += (uint64_t)(!unsafe && (signature & 0x7u) == 0u);
    }
    return allowed;
}

int main(void) {
    const size_t n = 12000000u;
    const size_t phases = 4u;
    const unsigned repeats = 8u;

    uint8_t *history = malloc(n * phases);
    uint8_t *snapshot = malloc(n);
    uint8_t *signature = malloc(n);
    if (history == NULL || snapshot == NULL || signature == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(history);
        free(snapshot);
        free(signature);
        return 2;
    }

    double started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        uint8_t *row = history + i * phases;
        if ((i & 1u) == 0u) {
            /* monotone: AUTHORITY+OUTCOME -> OUTCOME -> NONE -> NONE */
            row[0] = 0x5u;
            row[1] = 0x4u;
            row[2] = 0x0u;
            row[3] = 0x0u;
        } else {
            /* regressive/discontinuous: pending -> settled -> pending again -> settled */
            row[0] = 0x5u;
            row[1] = 0x0u;
            row[2] = (uint8_t)(0x5u | (1u << 3u));
            row[3] = 0x0u;
        }
        snapshot[i] = PHASE_MISSING(row[3]);
    }
    const double history_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n; ++i) {
        const uint8_t *row = history + i * phases;
        uint8_t sig = PHASE_MISSING(row[0]);
        if (PHASE_DISC(row[0])) {
            sig |= SIG_DISCONTINUITY;
        }
        for (size_t p = 1; p < phases; ++p) {
            sig = advance_signature(sig, row[p]);
        }
        signature[i] = sig;
    }
    const double signature_build = now_seconds() - started;

    const uint64_t expected_safe = n / 2u;
    const uint64_t warm_history = scan_full_history(history, n, phases);
    const uint64_t warm_signature = scan_signature(signature, n);
    if (warm_history != expected_safe || warm_signature != expected_safe) {
        fprintf(stderr, "warmup mismatch\n");
        return 3;
    }

    double snapshot_total = 0.0;
    double history_total = 0.0;
    double signature_total = 0.0;
    uint64_t snapshot_checksum = 0;
    uint64_t history_checksum = 0;
    uint64_t signature_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        started = now_seconds();
        snapshot_checksum += scan_snapshot(snapshot, n);
        snapshot_total += now_seconds() - started;

        started = now_seconds();
        history_checksum += scan_full_history(history, n, phases);
        history_total += now_seconds() - started;

        started = now_seconds();
        signature_checksum += scan_signature(signature, n);
        signature_total += now_seconds() - started;
    }

    if (history_checksum != signature_checksum) {
        fprintf(stderr, "history/signature checksum mismatch\n");
        return 4;
    }

    const double snapshot_scan = snapshot_total / repeats;
    const double history_scan = history_total / repeats;
    const double signature_scan = signature_total / repeats;

    printf("records=%zu\n", n);
    printf("phases_per_record=%zu\n", phases);
    printf("expected_safe=%" PRIu64 "\n", expected_safe);
    printf("correct=true\n\n");

    printf("[final snapshot only]\n");
    printf("retained_bytes=%zu\n", n);
    printf("allowed_per_scan=%" PRIu64 "\n", snapshot_checksum / repeats);
    printf("false_allows_per_scan=%" PRIu64 "\n", snapshot_checksum / repeats - expected_safe);
    printf("scan_seconds_avg=%.6f\n\n", snapshot_scan);

    printf("[full temporal history]\n");
    printf("retained_bytes=%zu\n", n * phases);
    printf("build_seconds=%.6f\n", history_build);
    printf("allowed_per_scan=%" PRIu64 "\n", history_checksum / repeats);
    printf("false_allows_per_scan=0\n");
    printf("scan_seconds_avg=%.6f\n\n", history_scan);

    printf("[online one-byte temporal signature]\n");
    printf("retained_bytes=%zu\n", n);
    printf("build_from_phases_seconds=%.6f\n", signature_build);
    printf("allowed_per_scan=%" PRIu64 "\n", signature_checksum / repeats);
    printf("false_allows_per_scan=0\n");
    printf("scan_seconds_avg=%.6f\n\n", signature_scan);

    printf("signature_memory_vs_history=%.3fx\n", (double)n / (double)(n * phases));
    printf("signature_scan_vs_history=%.3fx\n", signature_scan / history_scan);
    printf("snapshot_semantically_sufficient=false\n");
    printf("representation_note=temporal signature is generic online state compression carrying Bardo/Tao trajectory semantics\n");

    free(history);
    free(snapshot);
    free(signature);
    return 0;
}

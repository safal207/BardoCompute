#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

enum {
    MODE_MANIFEST = 0,
    MODE_ACQUIRE = 1,
    MODE_ADAPT = 2,
    SIGNAL_HOLD = 0,
    SIGNAL_CHANGE = 1,
    SIGNAL_GAP = 2,
    SIGNAL_READY = 3,
    MODE_COUNT = 3,
    SIGNAL_COUNT = 4,
    TRANSITION_ENTRIES = MODE_COUNT * SIGNAL_COUNT
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t branch_step(uint8_t current, uint8_t signal) {
    if (signal == SIGNAL_HOLD) {
        return current;
    }
    if (signal == SIGNAL_CHANGE) {
        return MODE_ADAPT;
    }
    if (signal == SIGNAL_GAP) {
        if (current == MODE_ADAPT || current == MODE_ACQUIRE) {
            return MODE_ACQUIRE;
        }
        return MODE_ADAPT;
    }
    if (signal == SIGNAL_READY) {
        if (current == MODE_ADAPT || current == MODE_ACQUIRE) {
            return MODE_MANIFEST;
        }
        return current;
    }
    return current;
}

static void build_transition_lut(uint8_t lut[TRANSITION_ENTRIES]) {
    for (uint8_t mode = 0; mode < MODE_COUNT; ++mode) {
        for (uint8_t signal = 0; signal < SIGNAL_COUNT; ++signal) {
            lut[(uint8_t)(mode * SIGNAL_COUNT + signal)] = branch_step(mode, signal);
        }
    }
}

static uint64_t run_branch(
    const uint8_t *signals,
    const uint8_t *expected,
    size_t n,
    uint8_t *final_mode
) {
    uint8_t mode = MODE_MANIFEST;
    uint64_t wrong = 0;
    for (size_t i = 0; i < n; ++i) {
        mode = branch_step(mode, signals[i]);
        wrong += (uint64_t)(mode != expected[i]);
    }
    *final_mode = mode;
    return wrong;
}

static uint64_t run_lut(
    const uint8_t *signals,
    const uint8_t *expected,
    size_t n,
    const uint8_t lut[TRANSITION_ENTRIES],
    uint8_t *final_mode
) {
    uint8_t mode = MODE_MANIFEST;
    uint64_t wrong = 0;
    for (size_t i = 0; i < n; ++i) {
        mode = lut[(uint8_t)(mode * SIGNAL_COUNT + signals[i])];
        wrong += (uint64_t)(mode != expected[i]);
    }
    *final_mode = mode;
    return wrong;
}

static uint64_t run_fixed_manifest(const uint8_t *expected, size_t n) {
    uint64_t wrong = 0;
    for (size_t i = 0; i < n; ++i) {
        wrong += (uint64_t)(expected[i] != MODE_MANIFEST);
    }
    return wrong;
}

int main(void) {
    const size_t episodes = 3000000u;
    const size_t steps_per_episode = 4u;
    const size_t n = episodes * steps_per_episode;
    const unsigned repeats = 12u;
    const uint8_t episode_signals[4] = {
        SIGNAL_HOLD,
        SIGNAL_CHANGE,
        SIGNAL_GAP,
        SIGNAL_READY
    };
    const uint8_t episode_expected[4] = {
        MODE_MANIFEST,
        MODE_ADAPT,
        MODE_ACQUIRE,
        MODE_MANIFEST
    };

    uint8_t *signals = malloc(n * sizeof(*signals));
    uint8_t *expected = malloc(n * sizeof(*expected));
    if (signals == NULL || expected == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(signals);
        free(expected);
        return 2;
    }

    for (size_t episode = 0; episode < episodes; ++episode) {
        for (size_t step = 0; step < steps_per_episode; ++step) {
            const size_t i = episode * steps_per_episode + step;
            signals[i] = episode_signals[step];
            expected[i] = episode_expected[step];
        }
    }

    uint8_t lut[TRANSITION_ENTRIES];
    build_transition_lut(lut);

    uint8_t branch_final = 0;
    uint8_t lut_final = 0;
    const uint64_t branch_warm = run_branch(signals, expected, n, &branch_final);
    const uint64_t lut_warm = run_lut(signals, expected, n, lut, &lut_final);
    const uint64_t fixed_wrong = run_fixed_manifest(expected, n);
    if (branch_warm != 0 || lut_warm != 0 || branch_final != lut_final) {
        fprintf(stderr, "semantic mismatch\n");
        free(signals);
        free(expected);
        return 3;
    }

    double branch_total = 0.0;
    double lut_total = 0.0;
    uint64_t branch_checksum = 0;
    uint64_t lut_checksum = 0;

    for (unsigned r = 0; r < repeats; ++r) {
        double started;
        if ((r & 1u) == 0u) {
            started = now_seconds();
            branch_checksum += run_branch(signals, expected, n, &branch_final);
            branch_total += now_seconds() - started;

            started = now_seconds();
            lut_checksum += run_lut(signals, expected, n, lut, &lut_final);
            lut_total += now_seconds() - started;
        } else {
            started = now_seconds();
            lut_checksum += run_lut(signals, expected, n, lut, &lut_final);
            lut_total += now_seconds() - started;

            started = now_seconds();
            branch_checksum += run_branch(signals, expected, n, &branch_final);
            branch_total += now_seconds() - started;
        }
    }

    if (branch_checksum != 0 || lut_checksum != 0 || branch_final != lut_final) {
        fprintf(stderr, "checksum mismatch\n");
        free(signals);
        free(expected);
        return 4;
    }

    const double branch_avg = branch_total / (double)repeats;
    const double lut_avg = lut_total / (double)repeats;

    printf("episodes=%zu\n", episodes);
    printf("steps_per_episode=%zu\n", steps_per_episode);
    printf("transitions=%zu\n", n);
    printf("expected_path=MANIFEST->ADAPT->ACQUIRE->MANIFEST\n");
    printf("mean_recovery_ticks=2\n");
    printf("fixed_manifest_wrong_ticks=%" PRIu64 "\n", fixed_wrong);
    printf("branch_fsm_wrong_ticks=%" PRIu64 "\n", branch_warm);
    printf("lut_fsm_wrong_ticks=%" PRIu64 "\n", lut_warm);
    printf("transition_lut_entries=%d\n", TRANSITION_ENTRIES);
    printf("transition_lut_bytes=%zu\n", sizeof(lut));
    printf("correct=true\n\n");

    printf("[conventional branch FSM]\n");
    printf("seconds_avg=%.6f\n", branch_avg);
    printf("mtransitions_s=%.3f\n\n", ((double)n / branch_avg) / 1000000.0);

    printf("[12-entry capability transition LUT]\n");
    printf("seconds_avg=%.6f\n", lut_avg);
    printf("mtransitions_s=%.3f\n\n", ((double)n / lut_avg) / 1000000.0);

    printf("lut_vs_branch_time=%.3fx\n", lut_avg / branch_avg);
    printf("semantic_equivalence=true\n");
    printf("interpretation=The recovery trajectory is an ordinary three-state finite-state machine under equal information. The 12-byte transition LUT tests whether a tiny second-stage indexed path is a practical execution form for Manifest/Acquire/Adapt flow without widening the 16-bit hot state or its 64KB first-stage policy.\n");

    free(signals);
    free(expected);
    return 0;
}

#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define SIGNALS 12000000u
#define REPEATS 8
#define PROFILES 4

static volatile uint64_t sink = 0;

static double now_seconds(void) {
    struct timespec ts;
    timespec_get(&ts, TIME_UTC);
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1e9;
}

static uint32_t xorshift32(uint32_t *state) {
    uint32_t x = *state;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    *state = x;
    return x;
}

/* modes: 0 Manifest, 1 Acquire, 2 Adapt
 * signals: 0 Hold, 1 EnvironmentChange, 2 GapDetected, 3 EvidenceReady
 */
static inline uint8_t branch_step(uint8_t mode, uint8_t signal) {
    if (signal == 0) return mode;
    if (signal == 1) return 2;
    if (signal == 2) return (mode == 1 || mode == 2) ? 1 : 2;
    if (signal == 3) return (mode == 1 || mode == 2) ? 0 : mode;
    return mode;
}

static void build_lut(uint8_t lut[12]) {
    for (uint8_t mode = 0; mode < 3; ++mode) {
        for (uint8_t signal = 0; signal < 4; ++signal) {
            lut[(unsigned)mode * 4u + signal] = branch_step(mode, signal);
        }
    }
}

static uint8_t sample_signal(uint32_t r, unsigned profile) {
    uint32_t x = r % 1000u;
    switch (profile) {
        case 0: /* 90% HOLD, remaining 10% split */
            if (x < 900u) return 0;
            if (x < 934u) return 1;
            if (x < 967u) return 2;
            return 3;
        case 1: /* 60% HOLD */
            if (x < 600u) return 0;
            if (x < 734u) return 1;
            if (x < 867u) return 2;
            return 3;
        case 2: /* approximately uniform */
            return (uint8_t)(x / 250u);
        default: /* shock-heavy: 10% HOLD, 30% each active signal */
            if (x < 100u) return 0;
            if (x < 400u) return 1;
            if (x < 700u) return 2;
            return 3;
    }
}

static uint64_t scan_branch(const uint8_t *signals) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (size_t i = 0; i < SIGNALS; ++i) {
        mode = branch_step(mode, signals[i]);
        checksum += (uint64_t)mode + 1u;
    }
    return checksum ^ mode;
}

static uint64_t scan_lut(const uint8_t *signals, const uint8_t lut[12]) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (size_t i = 0; i < SIGNALS; ++i) {
        mode = lut[(unsigned)mode * 4u + signals[i]];
        checksum += (uint64_t)mode + 1u;
    }
    return checksum ^ mode;
}

int main(void) {
    static const char *names[PROFILES] = {
        "low_entropy_90pct_hold",
        "medium_entropy_60pct_hold",
        "balanced_uniform",
        "shock_heavy_10pct_hold"
    };
    uint8_t lut[12];
    uint8_t *signals = (uint8_t *)malloc(SIGNALS);
    if (!signals) return 2;
    build_lut(lut);

    printf("signals=%u\n", SIGNALS);
    printf("repeats=%d\n", REPEATS);
    printf("transition_lut_bytes=12\n");
    printf("profile,branch_seconds,lut_seconds,lut_vs_branch,branch_mtransitions_s,lut_mtransitions_s,checksum\n");

    uint32_t rng = 0xC0FFEEu;
    int correct = 1;
    for (unsigned profile = 0; profile < PROFILES; ++profile) {
        for (size_t i = 0; i < SIGNALS; ++i) {
            signals[i] = sample_signal(xorshift32(&rng), profile);
        }

        uint64_t warm_branch = scan_branch(signals);
        uint64_t warm_lut = scan_lut(signals, lut);
        if (warm_branch != warm_lut) correct = 0;
        sink ^= warm_branch ^ warm_lut;

        double branch_total = 0.0;
        double lut_total = 0.0;
        uint64_t checksum = 0;
        for (int repeat = 0; repeat < REPEATS; ++repeat) {
            if ((repeat & 1) == 0) {
                double t0 = now_seconds();
                uint64_t b = scan_branch(signals);
                branch_total += now_seconds() - t0;
                t0 = now_seconds();
                uint64_t l = scan_lut(signals, lut);
                lut_total += now_seconds() - t0;
                if (b != l) correct = 0;
                checksum ^= b ^ l;
            } else {
                double t0 = now_seconds();
                uint64_t l = scan_lut(signals, lut);
                lut_total += now_seconds() - t0;
                t0 = now_seconds();
                uint64_t b = scan_branch(signals);
                branch_total += now_seconds() - t0;
                if (b != l) correct = 0;
                checksum ^= b ^ l;
            }
        }

        double branch_avg = branch_total / REPEATS;
        double lut_avg = lut_total / REPEATS;
        printf(
            "%s,%.6f,%.6f,%.3f,%.3f,%.3f,%llu\n",
            names[profile],
            branch_avg,
            lut_avg,
            lut_avg / branch_avg,
            ((double)SIGNALS / 1e6) / branch_avg,
            ((double)SIGNALS / 1e6) / lut_avg,
            (unsigned long long)checksum
        );
        sink ^= checksum;
    }

    printf("correct=%s\n", correct ? "true" : "false");
    printf("sink=%llu\n", (unsigned long long)sink);
    printf("interpretation=Signal entropy tests when a predictable branch FSM loses enough branch-prediction advantage for indexed execution to become competitive. The transition semantics are identical.\n");

    free(signals);
    return correct ? 0 : 1;
}

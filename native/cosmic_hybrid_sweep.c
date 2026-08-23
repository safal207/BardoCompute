#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define N 12000000u
#define REPEATS 8

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

static void build_transitional(uint8_t *signals, unsigned chunk) {
    uint32_t rng = 0xC05C1Cu;
    for (unsigned i = 0; i < N; ++i) {
        unsigned local = i / chunk;
        if ((local & 1u) == 0u) signals[i] = (uint8_t)(i & 3u);
        else signals[i] = (uint8_t)(xorshift32(&rng) & 3u);
    }
}

static unsigned conditional_misses(const uint8_t *sample, unsigned n) {
    unsigned counts[4][4] = {{0}};
    unsigned totals[4] = {0};
    for (unsigned i = 1; i < n; ++i) {
        counts[sample[i - 1]][sample[i]] += 1u;
        totals[sample[i - 1]] += 1u;
    }
    unsigned misses = 0;
    for (unsigned source = 0; source < 4; ++source) {
        unsigned best = 0;
        for (unsigned next = 0; next < 4; ++next) {
            if (counts[source][next] > best) best = counts[source][next];
        }
        misses += totals[source] - best;
    }
    return misses;
}

static uint64_t run_branch(const uint8_t *signals) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned i = 0; i < N; ++i) {
        mode = branch_step(mode, signals[i]);
        checksum += (uint64_t)mode + 1u;
    }
    return checksum ^ mode;
}

static uint64_t run_lut(const uint8_t *signals, const uint8_t lut[12]) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned i = 0; i < N; ++i) {
        mode = lut[(unsigned)mode * 4u + signals[i]];
        checksum += (uint64_t)mode + 1u;
    }
    return checksum ^ mode;
}

static uint64_t run_oracle(const uint8_t *signals, const uint8_t lut[12], unsigned chunk) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned begin = 0; begin < N; begin += chunk) {
        unsigned end = begin + chunk;
        if (end > N) end = N;
        if (((begin / chunk) & 1u) == 0u) {
            for (unsigned i = begin; i < end; ++i) {
                mode = branch_step(mode, signals[i]);
                checksum += (uint64_t)mode + 1u;
            }
        } else {
            for (unsigned i = begin; i < end; ++i) {
                mode = lut[(unsigned)mode * 4u + signals[i]];
                checksum += (uint64_t)mode + 1u;
            }
        }
    }
    return checksum ^ mode;
}

static uint64_t run_probe_hybrid(
    const uint8_t *signals,
    const uint8_t lut[12],
    unsigned chunk,
    unsigned probe
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned begin = 0; begin < N; begin += chunk) {
        unsigned end = begin + chunk;
        if (end > N) end = N;
        unsigned probe_end = begin + probe;
        if (probe_end > end) probe_end = end;

        for (unsigned i = begin; i < probe_end; ++i) {
            mode = branch_step(mode, signals[i]);
            checksum += (uint64_t)mode + 1u;
        }
        if (probe_end == end) continue;

        unsigned n = probe_end - begin;
        unsigned misses = conditional_misses(signals + begin, n);
        int choose_lut = misses * 5u > (n - 1u);
        if (choose_lut) {
            for (unsigned i = probe_end; i < end; ++i) {
                mode = lut[(unsigned)mode * 4u + signals[i]];
                checksum += (uint64_t)mode + 1u;
            }
        } else {
            for (unsigned i = probe_end; i < end; ++i) {
                mode = branch_step(mode, signals[i]);
                checksum += (uint64_t)mode + 1u;
            }
        }
    }
    return checksum ^ mode;
}

int main(void) {
    const unsigned chunks[] = {32u, 64u, 128u, 256u, 512u, 1024u};
    const unsigned probes[] = {4u, 8u, 16u, 32u, 64u};
    uint8_t *signals = (uint8_t *)malloc(N);
    uint8_t lut[12];
    if (!signals) return 2;
    build_lut(lut);

    printf("signals=%u\n", N);
    printf("repeats=%d\n", REPEATS);
    printf("morphology=alternating structured/amorphous local regions\n");
    printf("chunk,probe,branch_seconds,lut_seconds,oracle_seconds,hybrid_seconds,hybrid_vs_lut,oracle_vs_lut,correct\n");

    int all_correct = 1;
    for (unsigned ci = 0; ci < sizeof(chunks) / sizeof(chunks[0]); ++ci) {
        unsigned chunk = chunks[ci];
        build_transitional(signals, chunk);
        uint64_t branch_checksum = run_branch(signals);
        uint64_t lut_checksum = run_lut(signals, lut);
        uint64_t oracle_checksum = run_oracle(signals, lut, chunk);
        if (!(branch_checksum == lut_checksum && lut_checksum == oracle_checksum)) all_correct = 0;

        double branch_total = 0.0, lut_total = 0.0, oracle_total = 0.0;
        for (int r = 0; r < REPEATS; ++r) {
            double t0 = now_seconds();
            sink ^= run_branch(signals);
            branch_total += now_seconds() - t0;
            t0 = now_seconds();
            sink ^= run_lut(signals, lut);
            lut_total += now_seconds() - t0;
            t0 = now_seconds();
            sink ^= run_oracle(signals, lut, chunk);
            oracle_total += now_seconds() - t0;
        }
        double branch_avg = branch_total / REPEATS;
        double lut_avg = lut_total / REPEATS;
        double oracle_avg = oracle_total / REPEATS;

        for (unsigned pi = 0; pi < sizeof(probes) / sizeof(probes[0]); ++pi) {
            unsigned probe = probes[pi];
            if (probe >= chunk) continue;
            uint64_t hybrid_checksum = run_probe_hybrid(signals, lut, chunk, probe);
            int correct = hybrid_checksum == lut_checksum;
            if (!correct) all_correct = 0;
            double hybrid_total = 0.0;
            for (int r = 0; r < REPEATS; ++r) {
                double t0 = now_seconds();
                sink ^= run_probe_hybrid(signals, lut, chunk, probe);
                hybrid_total += now_seconds() - t0;
            }
            double hybrid_avg = hybrid_total / REPEATS;
            printf(
                "%u,%u,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%s\n",
                chunk, probe, branch_avg, lut_avg, oracle_avg, hybrid_avg,
                hybrid_avg / lut_avg, oracle_avg / lut_avg,
                correct ? "true" : "false"
            );
        }
    }

    printf("all_correct=%s\n", all_correct ? "true" : "false");
    printf("coherence_note=The third Cosmic morphology only has execution value if local structured/amorphous regions persist long enough to amortize observation. This sweep searches that temporal-coherence boundary; it is generic morphology-aware execution, not a claim of ancient or metaphysical computation.\n");
    printf("sink=%llu\n", (unsigned long long)sink);
    free(signals);
    return all_correct ? 0 : 1;
}

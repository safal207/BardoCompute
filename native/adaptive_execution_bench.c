#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BLOCK_SIZE 131072u
#define BLOCKS 96u
#define SIGNALS ((size_t)BLOCK_SIZE * (size_t)BLOCKS)
#define SAMPLE 512u
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

static void build_workload(uint8_t *signals, uint8_t *stochastic_block) {
    uint32_t rng = 0x51A7E5u;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        /* Alternate calm deterministic and stochastic blocks. */
        if ((block & 1u) == 0u) {
            stochastic_block[block] = 0;
            for (unsigned i = 0; i < BLOCK_SIZE; ++i) {
                signals[base + i] = (uint8_t)(i & 3u);
            }
        } else {
            stochastic_block[block] = 1;
            for (unsigned i = 0; i < BLOCK_SIZE; ++i) {
                signals[base + i] = (uint8_t)(xorshift32(&rng) & 3u);
            }
        }
    }
}

static inline void accumulate(uint8_t *mode, uint64_t *checksum, uint8_t next) {
    *mode = next;
    *checksum += (uint64_t)next + 1u;
}

static uint64_t run_branch(const uint8_t *signals) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (size_t i = 0; i < SIGNALS; ++i) {
        accumulate(&mode, &checksum, branch_step(mode, signals[i]));
    }
    return checksum ^ mode;
}

static uint64_t run_lut(const uint8_t *signals, const uint8_t lut[12]) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (size_t i = 0; i < SIGNALS; ++i) {
        accumulate(&mode, &checksum, lut[(unsigned)mode * 4u + signals[i]]);
    }
    return checksum ^ mode;
}

static uint64_t run_oracle(
    const uint8_t *signals,
    const uint8_t *stochastic_block,
    const uint8_t lut[12]
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t end = base + BLOCK_SIZE;
        if (stochastic_block[block]) {
            for (size_t i = base; i < end; ++i) {
                accumulate(&mode, &checksum, lut[(unsigned)mode * 4u + signals[i]]);
            }
        } else {
            for (size_t i = base; i < end; ++i) {
                accumulate(&mode, &checksum, branch_step(mode, signals[i]));
            }
        }
    }
    return checksum ^ mode;
}

static unsigned conditional_miss_proxy(const uint8_t *sample) {
    unsigned counts[4][4];
    unsigned source_totals[4];
    memset(counts, 0, sizeof(counts));
    memset(source_totals, 0, sizeof(source_totals));

    for (unsigned i = 1; i < SAMPLE; ++i) {
        uint8_t prev = sample[i - 1];
        uint8_t next = sample[i];
        counts[prev][next] += 1u;
        source_totals[prev] += 1u;
    }

    unsigned misses = 0;
    for (unsigned source = 0; source < 4; ++source) {
        unsigned best = 0;
        for (unsigned next = 0; next < 4; ++next) {
            if (counts[source][next] > best) best = counts[source][next];
        }
        misses += source_totals[source] - best;
    }
    return misses;
}

static uint64_t run_adaptive(
    const uint8_t *signals,
    const uint8_t lut[12],
    unsigned *branch_blocks,
    unsigned *lut_blocks
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    unsigned branch_selected = 0;
    unsigned lut_selected = 0;

    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t sample_end = base + SAMPLE;
        size_t end = base + BLOCK_SIZE;

        /* The prefix is part of the timed workload and is executed while the
         * selector observes conditional transition predictability. */
        for (size_t i = base; i < sample_end; ++i) {
            accumulate(&mode, &checksum, branch_step(mode, signals[i]));
        }

        unsigned misses = conditional_miss_proxy(signals + base);
        /* 20% conditional next-signal miss rate separates the deterministic
         * cycle (~0%) from the random blocks (~70%+) with wide margin. */
        int choose_lut = misses * 5u > (SAMPLE - 1u);
        if (choose_lut) {
            lut_selected += 1u;
            for (size_t i = sample_end; i < end; ++i) {
                accumulate(&mode, &checksum, lut[(unsigned)mode * 4u + signals[i]]);
            }
        } else {
            branch_selected += 1u;
            for (size_t i = sample_end; i < end; ++i) {
                accumulate(&mode, &checksum, branch_step(mode, signals[i]));
            }
        }
    }

    *branch_blocks = branch_selected;
    *lut_blocks = lut_selected;
    return checksum ^ mode;
}

int main(void) {
    uint8_t lut[12];
    uint8_t *signals = (uint8_t *)malloc(SIGNALS);
    uint8_t *stochastic_block = (uint8_t *)malloc(BLOCKS);
    if (!signals || !stochastic_block) {
        free(signals);
        free(stochastic_block);
        return 2;
    }

    build_lut(lut);
    build_workload(signals, stochastic_block);

    uint64_t warm_branch = run_branch(signals);
    uint64_t warm_lut = run_lut(signals, lut);
    uint64_t warm_oracle = run_oracle(signals, stochastic_block, lut);
    unsigned warm_b = 0, warm_l = 0;
    uint64_t warm_adaptive = run_adaptive(signals, lut, &warm_b, &warm_l);
    int correct = warm_branch == warm_lut && warm_lut == warm_oracle && warm_oracle == warm_adaptive;

    double branch_total = 0.0;
    double lut_total = 0.0;
    double oracle_total = 0.0;
    double adaptive_total = 0.0;
    uint64_t checksum = 0;
    unsigned selected_branch = 0, selected_lut = 0;

    for (int repeat = 0; repeat < REPEATS; ++repeat) {
        double t0 = now_seconds();
        uint64_t b = run_branch(signals);
        branch_total += now_seconds() - t0;

        t0 = now_seconds();
        uint64_t l = run_lut(signals, lut);
        lut_total += now_seconds() - t0;

        t0 = now_seconds();
        uint64_t o = run_oracle(signals, stochastic_block, lut);
        oracle_total += now_seconds() - t0;

        unsigned sb = 0, sl = 0;
        t0 = now_seconds();
        uint64_t a = run_adaptive(signals, lut, &sb, &sl);
        adaptive_total += now_seconds() - t0;

        if (!(b == l && l == o && o == a)) correct = 0;
        checksum ^= b ^ l ^ o ^ a;
        selected_branch = sb;
        selected_lut = sl;
    }

    double branch_avg = branch_total / REPEATS;
    double lut_avg = lut_total / REPEATS;
    double oracle_avg = oracle_total / REPEATS;
    double adaptive_avg = adaptive_total / REPEATS;

    printf("signals=%zu\n", SIGNALS);
    printf("blocks=%u\n", BLOCKS);
    printf("block_size=%u\n", BLOCK_SIZE);
    printf("sample_per_block=%u\n", SAMPLE);
    printf("calm_blocks=%u\n", BLOCKS / 2u);
    printf("stochastic_blocks=%u\n", BLOCKS / 2u);
    printf("adaptive_branch_blocks=%u\n", selected_branch);
    printf("adaptive_lut_blocks=%u\n", selected_lut);
    printf("correct=%s\n", correct ? "true" : "false");
    printf("branch_only_seconds=%.6f\n", branch_avg);
    printf("lut_only_seconds=%.6f\n", lut_avg);
    printf("oracle_hybrid_seconds=%.6f\n", oracle_avg);
    printf("online_adaptive_seconds=%.6f\n", adaptive_avg);
    printf("adaptive_vs_branch=%.3fx\n", adaptive_avg / branch_avg);
    printf("adaptive_vs_lut=%.3fx\n", adaptive_avg / lut_avg);
    printf("adaptive_vs_oracle=%.3fx\n", adaptive_avg / oracle_avg);
    printf("checksum=%llu\n", (unsigned long long)checksum);
    printf("selector_note=The online selector observes a 512-signal prefix in each block, estimates conditional next-signal unpredictability, and includes that observation cost in the timed path.\n");
    printf("interpretation=This tests whether execution mode itself can adapt to trajectory predictability. Any advantage belongs to online selection between generic branch and LUT implementations with identical transition semantics.\n");

    sink ^= checksum ^ warm_branch ^ warm_lut ^ warm_oracle ^ warm_adaptive;
    printf("sink=%llu\n", (unsigned long long)sink);

    free(signals);
    free(stochastic_block);
    return correct ? 0 : 1;
}

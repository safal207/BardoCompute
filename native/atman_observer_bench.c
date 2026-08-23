#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BLOCK_SIZE 65536u
#define BLOCKS 144u
#define SIGNALS ((size_t)BLOCK_SIZE * (size_t)BLOCKS)
#define W_SHORT 32u
#define W_MEDIUM 128u
#define W_LONG 512u
#define REPEATS 6

/* morphology: 0 structured, 1 transitional, 2 amorphous */
/* execution: structured -> branch, transitional/amorphous -> LUT */

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

static inline uint8_t next_signal(uint8_t prev, uint8_t morphology, uint32_t *rng) {
    if (morphology == 0) return (uint8_t)((prev + 1u) & 3u);
    if (morphology == 2) return (uint8_t)(xorshift32(rng) & 3u);
    /* Transitional: 65% follows the structured successor, 35% random. */
    if ((xorshift32(rng) % 100u) < 65u) return (uint8_t)((prev + 1u) & 3u);
    return (uint8_t)(xorshift32(rng) & 3u);
}

static void build_workload(uint8_t *signals, uint8_t *truth, uint8_t *deceptive) {
    uint32_t rng = 0xA7A14E5u;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        uint8_t morphology = (uint8_t)(block % 3u);
        int decoy = (block % 4u) == 1u; /* 25% deceptive prefixes. */
        truth[block] = morphology;
        deceptive[block] = (uint8_t)decoy;
        size_t base = (size_t)block * BLOCK_SIZE;
        uint8_t prev = (uint8_t)(block & 3u);
        signals[base] = prev;
        for (unsigned i = 1; i < BLOCK_SIZE; ++i) {
            uint8_t local = morphology;
            if (decoy && i < W_SHORT) {
                if (morphology == 0) local = 2; /* Structured starts noisy. */
                else local = 0;                /* Others start deceptively structured. */
            }
            uint8_t value = next_signal(prev, local, &rng);
            signals[base + i] = value;
            prev = value;
        }
    }
}

static unsigned miss_bps(const uint8_t *sample, unsigned length) {
    unsigned counts[4][4] = {{0}};
    unsigned totals[4] = {0};
    for (unsigned i = 1; i < length; ++i) {
        uint8_t prev = sample[i - 1];
        uint8_t next = sample[i];
        counts[prev][next] += 1u;
        totals[prev] += 1u;
    }
    unsigned misses = 0;
    for (unsigned source = 0; source < 4; ++source) {
        unsigned best = 0;
        for (unsigned next = 0; next < 4; ++next) {
            if (counts[source][next] > best) best = counts[source][next];
        }
        misses += totals[source] - best;
    }
    return (unsigned)(((uint64_t)misses * 10000u) / (length - 1u));
}

static uint8_t morphology_from_miss(unsigned bps) {
    if (bps <= 1200u) return 0;
    if (bps >= 4500u) return 2;
    return 1;
}

static unsigned threshold_margin_bps(unsigned bps) {
    unsigned d1 = bps > 1200u ? bps - 1200u : 1200u - bps;
    unsigned d2 = bps > 4500u ? bps - 4500u : 4500u - bps;
    return d1 < d2 ? d1 : d2;
}

typedef struct {
    uint8_t morphology;
    unsigned observed;
    unsigned disagreements;
} ObserverDecision;

static ObserverDecision observe_naive32(const uint8_t *sample) {
    ObserverDecision d;
    d.morphology = morphology_from_miss(miss_bps(sample, W_SHORT));
    d.observed = W_SHORT;
    d.disagreements = 0;
    return d;
}

static ObserverDecision observe_baseline512(const uint8_t *sample) {
    ObserverDecision d;
    d.morphology = morphology_from_miss(miss_bps(sample, W_LONG));
    d.observed = W_LONG;
    d.disagreements = 0;
    return d;
}

static ObserverDecision observe_atman(const uint8_t *sample) {
    uint8_t short_class = morphology_from_miss(miss_bps(sample, W_SHORT));
    unsigned medium_bps = miss_bps(sample, W_MEDIUM);
    uint8_t medium_class = morphology_from_miss(medium_bps);

    ObserverDecision d;
    d.disagreements = short_class != medium_class ? 1u : 0u;
    /* ATMAN-inspired lightweight rule: do not promote a short observation by
     * itself. Require cross-window agreement plus calibrated distance from a
     * decision boundary; otherwise escalate to the long window. */
    if (short_class == medium_class && threshold_margin_bps(medium_bps) >= 500u) {
        d.morphology = medium_class;
        d.observed = W_MEDIUM;
        return d;
    }
    d.morphology = morphology_from_miss(miss_bps(sample, W_LONG));
    d.observed = W_LONG;
    return d;
}

static inline void accumulate(uint8_t *mode, uint64_t *checksum, uint8_t next) {
    *mode = next;
    *checksum += (uint64_t)next + 1u;
}

static uint64_t execute_observed(
    const uint8_t *signals,
    const uint8_t lut[12],
    int observer_kind,
    unsigned *morphology_errors,
    unsigned *mode_errors,
    uint64_t *samples_observed,
    unsigned *disagreements,
    const uint8_t *truth
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    unsigned m_errors = 0, e_errors = 0, disag = 0;
    uint64_t observed_total = 0;

    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        ObserverDecision d;
        if (observer_kind == 0) d = observe_naive32(signals + base);
        else if (observer_kind == 1) d = observe_baseline512(signals + base);
        else d = observe_atman(signals + base);

        observed_total += d.observed;
        disag += d.disagreements;
        if (d.morphology != truth[block]) m_errors += 1u;
        int selected_lut = d.morphology != 0;
        int truth_lut = truth[block] != 0;
        if (selected_lut != truth_lut) e_errors += 1u;

        size_t prefix_end = base + d.observed;
        size_t end = base + BLOCK_SIZE;
        /* Observation work is inside the timed path. During observation the
         * conservative default is the branch implementation. */
        for (size_t i = base; i < prefix_end; ++i) {
            accumulate(&mode, &checksum, branch_step(mode, signals[i]));
        }
        if (selected_lut) {
            for (size_t i = prefix_end; i < end; ++i) {
                accumulate(&mode, &checksum, lut[(unsigned)mode * 4u + signals[i]]);
            }
        } else {
            for (size_t i = prefix_end; i < end; ++i) {
                accumulate(&mode, &checksum, branch_step(mode, signals[i]));
            }
        }
    }

    *morphology_errors = m_errors;
    *mode_errors = e_errors;
    *samples_observed = observed_total;
    *disagreements = disag;
    return checksum ^ mode;
}

static uint64_t run_oracle(const uint8_t *signals, const uint8_t lut[12], const uint8_t *truth) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t end = base + BLOCK_SIZE;
        if (truth[block] == 0) {
            for (size_t i = base; i < end; ++i) accumulate(&mode, &checksum, branch_step(mode, signals[i]));
        } else {
            for (size_t i = base; i < end; ++i) accumulate(&mode, &checksum, lut[(unsigned)mode * 4u + signals[i]]);
        }
    }
    return checksum ^ mode;
}

int main(void) {
    uint8_t lut[12];
    uint8_t *signals = (uint8_t *)malloc(SIGNALS);
    uint8_t *truth = (uint8_t *)malloc(BLOCKS);
    uint8_t *deceptive = (uint8_t *)malloc(BLOCKS);
    if (!signals || !truth || !deceptive) {
        free(signals); free(truth); free(deceptive); return 2;
    }
    build_lut(lut);
    build_workload(signals, truth, deceptive);

    unsigned deceptive_count = 0;
    for (unsigned b = 0; b < BLOCKS; ++b) deceptive_count += deceptive[b];

    unsigned warm_me[3], warm_ee[3], warm_d[3];
    uint64_t warm_obs[3];
    uint64_t warm[3];
    for (int k = 0; k < 3; ++k) warm[k] = execute_observed(signals, lut, k, &warm_me[k], &warm_ee[k], &warm_obs[k], &warm_d[k], truth);
    uint64_t warm_oracle = run_oracle(signals, lut, truth);
    int correct = warm[0] == warm[1] && warm[1] == warm[2] && warm[2] == warm_oracle;

    double totals[4] = {0};
    unsigned me[3] = {0}, ee[3] = {0}, disagreements[3] = {0};
    uint64_t obs[3] = {0};
    uint64_t checksum = 0;

    for (int r = 0; r < REPEATS; ++r) {
        for (int k = 0; k < 3; ++k) {
            unsigned xme = 0, xee = 0, xd = 0;
            uint64_t xobs = 0;
            double t0 = now_seconds();
            uint64_t v = execute_observed(signals, lut, k, &xme, &xee, &xobs, &xd, truth);
            totals[k] += now_seconds() - t0;
            checksum ^= v;
            me[k] = xme;
            ee[k] = xee;
            obs[k] = xobs;
            disagreements[k] = xd;
            if (v != warm_oracle) correct = 0;
        }
        double t0 = now_seconds();
        uint64_t ov = run_oracle(signals, lut, truth);
        totals[3] += now_seconds() - t0;
        checksum ^= ov;
        if (ov != warm_oracle) correct = 0;
    }

    for (int k = 0; k < 4; ++k) totals[k] /= REPEATS;

    printf("signals=%zu\n", SIGNALS);
    printf("blocks=%u\n", BLOCKS);
    printf("block_size=%u\n", BLOCK_SIZE);
    printf("deceptive_prefix_blocks=%u\n", deceptive_count);
    printf("morphology_classes=structured,transitional,amorphous\n");
    printf("correct=%s\n", correct ? "true" : "false");
    printf("\n[naive 32-signal observer]\n");
    printf("morphology_errors=%u\nmode_errors=%u\nmean_observed=%.1f\nseconds=%.6f\n", me[0], ee[0], (double)obs[0] / BLOCKS, totals[0]);
    printf("\n[baseline 512-signal observer]\n");
    printf("morphology_errors=%u\nmode_errors=%u\nmean_observed=%.1f\nseconds=%.6f\n", me[1], ee[1], (double)obs[1] / BLOCKS, totals[1]);
    printf("\n[ATMAN-inspired calibrated multi-window observer]\n");
    printf("morphology_errors=%u\nmode_errors=%u\nwindow_disagreements=%u\nmean_observed=%.1f\nseconds=%.6f\n", me[2], ee[2], disagreements[2], (double)obs[2] / BLOCKS, totals[2]);
    printf("\n[oracle morphology]\nseconds=%.6f\n", totals[3]);
    printf("atman_observation_vs_baseline=%.3fx\n", ((double)obs[2] / BLOCKS) / W_LONG);
    printf("atman_runtime_vs_baseline=%.3fx\n", totals[2] / totals[1]);
    printf("atman_runtime_vs_oracle=%.3fx\n", totals[2] / totals[3]);
    printf("checksum=%llu\n", (unsigned long long)checksum);
    printf("interpretation=The multi-window observer borrows ATMAN-LATTICE's calibration/escalation discipline: short evidence is not sovereign, cross-window agreement can promote early, and disagreement escalates to a longer observation. Cosmic morphology labels describe the observed regime; they are not imported executable code from COSMIC-ORGANICS.\n");

    sink ^= checksum ^ warm[0] ^ warm[1] ^ warm[2] ^ warm_oracle;
    printf("sink=%llu\n", (unsigned long long)sink);
    free(signals); free(truth); free(deceptive);
    return correct ? 0 : 1;
}

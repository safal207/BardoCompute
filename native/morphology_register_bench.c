#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

#define N 12000000u
#define REPEATS 8
#define SENTINEL_SAMPLES 8u

/* Local morphology register states inside a top-level TRANSITIONAL regime. */
typedef enum {
    LOCAL_STRUCTURED = 0,
    LOCAL_AMORPHOUS = 1
} LocalMorphology;

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

static void build_transitional(uint8_t *signals, unsigned coherence) {
    uint32_t rng = 0xBADA71u;
    for (unsigned i = 0; i < N; ++i) {
        unsigned local = i / coherence;
        if ((local & 1u) == 0u) signals[i] = (uint8_t)(i & 3u);
        else signals[i] = (uint8_t)(xorshift32(&rng) & 3u);
    }
}

static inline void run_branch_range(
    const uint8_t *signals, unsigned begin, unsigned end,
    uint8_t *mode, uint64_t *checksum
) {
    for (unsigned i = begin; i < end; ++i) {
        *mode = branch_step(*mode, signals[i]);
        *checksum += (uint64_t)(*mode) + 1u;
    }
}

static inline void run_lut_range(
    const uint8_t *signals, unsigned begin, unsigned end, const uint8_t lut[12],
    uint8_t *mode, uint64_t *checksum
) {
    for (unsigned i = begin; i < end; ++i) {
        *mode = lut[(unsigned)(*mode) * 4u + signals[i]];
        *checksum += (uint64_t)(*mode) + 1u;
    }
}

static uint64_t run_lut_only(const uint8_t *signals, const uint8_t lut[12]) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    run_lut_range(signals, 0u, N, lut, &mode, &checksum);
    return checksum ^ mode;
}

static uint64_t run_oracle(
    const uint8_t *signals, const uint8_t lut[12], unsigned coherence
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned begin = 0; begin < N; begin += coherence) {
        unsigned end = begin + coherence;
        if (end > N) end = N;
        if (((begin / coherence) & 1u) == 0u) {
            run_branch_range(signals, begin, end, &mode, &checksum);
        } else {
            run_lut_range(signals, begin, end, lut, &mode, &checksum);
        }
    }
    return checksum ^ mode;
}

/* Boundary-aware control from v0.1: it is told region boundaries but still
 * pays a 16-signal conditional-predictability probe at every region. */
static unsigned conditional_misses_16(const uint8_t *sample) {
    unsigned counts[4][4] = {{0}};
    unsigned totals[4] = {0};
    for (unsigned i = 1; i < 16u; ++i) {
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

static uint64_t run_fixed_probe(
    const uint8_t *signals, const uint8_t lut[12], unsigned coherence
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned begin = 0; begin < N; begin += coherence) {
        unsigned end = begin + coherence;
        if (end > N) end = N;
        unsigned probe_end = begin + 16u;
        if (probe_end > end) probe_end = end;
        run_branch_range(signals, begin, probe_end, &mode, &checksum);
        if (probe_end == end) continue;
        unsigned probe_n = probe_end - begin;
        int choose_lut = 0;
        if (probe_n == 16u) {
            unsigned misses = conditional_misses_16(signals + begin);
            choose_lut = misses * 5u > 15u;
        }
        if (choose_lut) run_lut_range(signals, probe_end, end, lut, &mode, &checksum);
        else run_branch_range(signals, probe_end, end, &mode, &checksum);
    }
    return checksum ^ mode;
}

/* Cheap drift sentinel: inspect only the last eight adjacent transitions in
 * the just-executed interval. The structured generator has successor hits=8;
 * uniform amorphous traffic has expected hits=2. One ambiguous observation
 * is HOLD: it does not mutate the morphology register. */
static int sentinel_vote(const uint8_t *signals, unsigned end) {
    if (end < SENTINEL_SAMPLES + 1u) return -1;
    unsigned hits = 0;
    unsigned begin = end - SENTINEL_SAMPLES;
    for (unsigned i = begin; i < end; ++i) {
        uint8_t expected = (uint8_t)((signals[i - 1u] + 1u) & 3u);
        if (signals[i] == expected) hits += 1u;
    }
    if (hits >= 7u) return LOCAL_STRUCTURED;
    if (hits <= 4u) return LOCAL_AMORPHOUS;
    return -1; /* HOLD */
}

typedef struct {
    unsigned switches;
    unsigned hold_votes;
    unsigned wrong_intervals;
    uint64_t detection_lag_signals;
    uint64_t sentinel_signal_reads;
} RegisterStats;

static uint64_t run_register(
    const uint8_t *signals,
    const uint8_t lut[12],
    unsigned coherence,
    unsigned interval,
    RegisterStats *stats
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    LocalMorphology reg = LOCAL_STRUCTURED;
    RegisterStats s = {0, 0, 0, 0, 0};

    unsigned last_truth_change = 0u;
    LocalMorphology previous_truth = LOCAL_STRUCTURED;
    int waiting_for_detection = 0;

    for (unsigned begin = 0; begin < N; begin += interval) {
        unsigned end = begin + interval;
        if (end > N) end = N;
        LocalMorphology truth = ((begin / coherence) & 1u)
            ? LOCAL_AMORPHOUS : LOCAL_STRUCTURED;

        if (truth != previous_truth) {
            last_truth_change = begin;
            previous_truth = truth;
            waiting_for_detection = reg != truth;
        }

        if (reg != truth) s.wrong_intervals += 1u;
        if (reg == LOCAL_STRUCTURED) {
            run_branch_range(signals, begin, end, &mode, &checksum);
        } else {
            run_lut_range(signals, begin, end, lut, &mode, &checksum);
        }

        int vote = sentinel_vote(signals, end);
        s.sentinel_signal_reads += SENTINEL_SAMPLES + 1u;
        if (vote < 0) {
            s.hold_votes += 1u;
            continue;
        }
        LocalMorphology voted = (LocalMorphology)vote;
        if (voted != reg) {
            reg = voted;
            s.switches += 1u;
            if (waiting_for_detection && reg == truth) {
                s.detection_lag_signals += (uint64_t)(end - last_truth_change);
                waiting_for_detection = 0;
            }
        }
    }

    *stats = s;
    return checksum ^ mode;
}

int main(void) {
    const unsigned coherences[] = {32u, 64u, 128u, 256u, 512u, 1024u};
    const unsigned intervals[] = {16u, 32u, 64u, 128u};
    uint8_t *signals = (uint8_t *)malloc(N);
    uint8_t lut[12];
    if (!signals) return 2;
    build_lut(lut);

    printf("signals=%u\n", N);
    printf("repeats=%d\n", REPEATS);
    printf("sentinel_samples=%u\n", SENTINEL_SAMPLES);
    printf("coherence,interval,lut_seconds,fixed_probe_seconds,register_seconds,oracle_seconds,register_vs_lut,register_vs_fixed,oracle_vs_lut,switches,hold_votes,wrong_intervals,mean_detection_lag,sentinel_reads,correct\n");

    int all_correct = 1;
    for (unsigned ci = 0; ci < sizeof(coherences) / sizeof(coherences[0]); ++ci) {
        unsigned coherence = coherences[ci];
        build_transitional(signals, coherence);
        uint64_t expected = run_lut_only(signals, lut);
        uint64_t fixed = run_fixed_probe(signals, lut, coherence);
        uint64_t oracle = run_oracle(signals, lut, coherence);
        if (!(expected == fixed && fixed == oracle)) all_correct = 0;

        double lut_total = 0.0, fixed_total = 0.0, oracle_total = 0.0;
        for (int r = 0; r < REPEATS; ++r) {
            double t0 = now_seconds(); sink ^= run_lut_only(signals, lut); lut_total += now_seconds() - t0;
            t0 = now_seconds(); sink ^= run_fixed_probe(signals, lut, coherence); fixed_total += now_seconds() - t0;
            t0 = now_seconds(); sink ^= run_oracle(signals, lut, coherence); oracle_total += now_seconds() - t0;
        }
        double lut_avg = lut_total / REPEATS;
        double fixed_avg = fixed_total / REPEATS;
        double oracle_avg = oracle_total / REPEATS;

        for (unsigned ii = 0; ii < sizeof(intervals) / sizeof(intervals[0]); ++ii) {
            unsigned interval = intervals[ii];
            if (interval > coherence) continue;
            RegisterStats warm_stats;
            uint64_t reg_checksum = run_register(signals, lut, coherence, interval, &warm_stats);
            int correct = reg_checksum == expected;
            if (!correct) all_correct = 0;

            double reg_total = 0.0;
            RegisterStats stats = warm_stats;
            for (int r = 0; r < REPEATS; ++r) {
                RegisterStats rs;
                double t0 = now_seconds();
                sink ^= run_register(signals, lut, coherence, interval, &rs);
                reg_total += now_seconds() - t0;
                stats = rs;
            }
            double reg_avg = reg_total / REPEATS;
            double mean_lag = stats.switches
                ? (double)stats.detection_lag_signals / (double)stats.switches
                : 0.0;
            printf(
                "%u,%u,%.6f,%.6f,%.6f,%.6f,%.3f,%.3f,%.3f,%u,%u,%u,%.2f,%llu,%s\n",
                coherence, interval, lut_avg, fixed_avg, reg_avg, oracle_avg,
                reg_avg / lut_avg, reg_avg / fixed_avg, oracle_avg / lut_avg,
                stats.switches, stats.hold_votes, stats.wrong_intervals, mean_lag,
                (unsigned long long)stats.sentinel_signal_reads,
                correct ? "true" : "false"
            );
        }
    }

    printf("all_correct=%s\n", all_correct ? "true" : "false");
    printf("register_note=The morphology register is not given local region boundaries. It persists the last accepted local morphology and mutates only after a cheap sentinel produces a non-ambiguous vote; ambiguous evidence is HOLD. This tests whether retaining observer state is cheaper than re-probing every region.\n");
    printf("control_note=All execution paths implement identical Manifest/Acquire/Adapt transition semantics; performance differences belong to observation/routing strategy.\n");
    printf("sink=%llu\n", (unsigned long long)sink);
    free(signals);
    return all_correct ? 0 : 1;
}

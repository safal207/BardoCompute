#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define BLOCK_SIZE 131072u
#define BLOCKS 90u
#define SIGNALS ((size_t)BLOCK_SIZE * (size_t)BLOCKS)
#define SAMPLE_SHORT 32u
#define SAMPLE_MID 128u
#define SAMPLE_LONG 512u
#define HYBRID_CHUNK 64u
#define HYBRID_PROBE 16u
#define REPEATS 6

typedef enum {
    MORPH_STRUCTURED = 0,
    MORPH_TRANSITIONAL = 1,
    MORPH_AMORPHOUS = 2
} Morphology;

typedef struct {
    unsigned total;
    unsigned correct;
} ObserverAudit;

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

static inline void accumulate(uint8_t *mode, uint64_t *checksum, uint8_t next) {
    *mode = next;
    *checksum += (uint64_t)next + 1u;
}

static void build_workload(uint8_t *signals, uint8_t *truth) {
    uint32_t rng = 0xA71A4C05u;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        /* Six-block regimes make change persistent long enough to distinguish
         * real regime structure from one noisy local sample. */
        Morphology morph = (Morphology)((block / 6u) % 3u);
        truth[block] = (uint8_t)morph;

        for (unsigned i = 0; i < BLOCK_SIZE; ++i) {
            if (morph == MORPH_STRUCTURED) {
                signals[base + i] = (uint8_t)(i & 3u);
            } else if (morph == MORPH_AMORPHOUS) {
                signals[base + i] = (uint8_t)(xorshift32(&rng) & 3u);
            } else {
                /* Semi-amorphous control: locally structured and amorphous
                 * 64-signal regions coexist inside the same global regime. */
                unsigned chunk = i / HYBRID_CHUNK;
                if ((chunk & 1u) == 0u) {
                    signals[base + i] = (uint8_t)(i & 3u);
                } else {
                    signals[base + i] = (uint8_t)(xorshift32(&rng) & 3u);
                }
            }
        }
    }
}

static unsigned conditional_misses(const uint8_t *sample, unsigned n) {
    unsigned counts[4][4];
    unsigned source_totals[4];
    memset(counts, 0, sizeof(counts));
    memset(source_totals, 0, sizeof(source_totals));

    for (unsigned i = 1; i < n; ++i) {
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

static Morphology classify_window(const uint8_t *sample, unsigned n) {
    unsigned misses = conditional_misses(sample, n);
    unsigned denom = n - 1u;
    if (misses * 100u <= denom * 12u) return MORPH_STRUCTURED;
    if (misses * 100u >= denom * 45u) return MORPH_AMORPHOUS;
    return MORPH_TRANSITIONAL;
}

static void audit_observer(ObserverAudit *audit, Morphology predicted, Morphology truth) {
    audit->total += 1u;
    if (predicted == truth) audit->correct += 1u;
}

/* Existing Bardo selector: fixed 512-signal observation and binary branch/LUT choice. */
static int current_choose_lut(const uint8_t *block) {
    unsigned misses = conditional_misses(block, SAMPLE_LONG);
    return misses * 5u > (SAMPLE_LONG - 1u);
}

/* ATMAN-inspired observer plane: multiple frozen windows. It can commit early
 * only when short and mid observers agree on a strong extreme. Disagreement
 * is HOLD, not failure, and forces a longer observation before binary choice. */
static int atman_choose_lut(
    const uint8_t *block,
    unsigned *observed,
    ObserverAudit *short_audit,
    ObserverAudit *mid_audit,
    ObserverAudit *long_audit,
    Morphology truth
) {
    Morphology s = classify_window(block, SAMPLE_SHORT);
    Morphology m = classify_window(block, SAMPLE_MID);
    audit_observer(short_audit, s, truth);
    audit_observer(mid_audit, m, truth);

    if (s == m && s != MORPH_TRANSITIONAL) {
        *observed = SAMPLE_MID;
        return s == MORPH_AMORPHOUS;
    }

    Morphology l = classify_window(block, SAMPLE_LONG);
    audit_observer(long_audit, l, truth);
    *observed = SAMPLE_LONG;
    return l != MORPH_STRUCTURED;
}

static Morphology cosmic_classify(
    const uint8_t *block,
    unsigned *observed,
    ObserverAudit *short_audit,
    ObserverAudit *mid_audit,
    ObserverAudit *long_audit,
    Morphology truth
) {
    Morphology s = classify_window(block, SAMPLE_SHORT);
    Morphology m = classify_window(block, SAMPLE_MID);
    audit_observer(short_audit, s, truth);
    audit_observer(mid_audit, m, truth);

    if (s == m && s != MORPH_TRANSITIONAL) {
        *observed = SAMPLE_MID;
        return s;
    }

    Morphology l = classify_window(block, SAMPLE_LONG);
    audit_observer(long_audit, l, truth);
    *observed = SAMPLE_LONG;

    /* Cosmic Organic v0.1 morphology: if the long window contains both
     * strongly structured and strongly amorphous local regions, preserve the
     * middle class instead of collapsing it to one binary execution regime. */
    unsigned low = 0, high = 0;
    for (unsigned off = 0; off < SAMPLE_LONG; off += HYBRID_CHUNK) {
        Morphology local = classify_window(block + off, HYBRID_CHUNK);
        if (local == MORPH_STRUCTURED) low += 1u;
        if (local == MORPH_AMORPHOUS) high += 1u;
    }
    if (low >= 2u && high >= 2u) return MORPH_TRANSITIONAL;
    return l;
}

static void run_branch_range(
    const uint8_t *signals, size_t begin, size_t end,
    uint8_t *mode, uint64_t *checksum
) {
    for (size_t i = begin; i < end; ++i) {
        accumulate(mode, checksum, branch_step(*mode, signals[i]));
    }
}

static void run_lut_range(
    const uint8_t *signals, size_t begin, size_t end, const uint8_t lut[12],
    uint8_t *mode, uint64_t *checksum
) {
    for (size_t i = begin; i < end; ++i) {
        accumulate(mode, checksum, lut[(unsigned)(*mode) * 4u + signals[i]]);
    }
}

/* Semi-amorphous execution: observe a tiny local prefix, then choose the
 * equal-semantic execution path for the remainder of the 64-signal region. */
static void run_hybrid_range(
    const uint8_t *signals, size_t begin, size_t end, const uint8_t lut[12],
    uint8_t *mode, uint64_t *checksum
) {
    for (size_t chunk = begin; chunk < end; chunk += HYBRID_CHUNK) {
        size_t chunk_end = chunk + HYBRID_CHUNK;
        if (chunk_end > end) chunk_end = end;
        size_t probe_end = chunk + HYBRID_PROBE;
        if (probe_end > chunk_end) probe_end = chunk_end;

        run_branch_range(signals, chunk, probe_end, mode, checksum);
        if (probe_end == chunk_end) continue;

        unsigned probe_n = (unsigned)(probe_end - chunk);
        unsigned misses = conditional_misses(signals + chunk, probe_n);
        int choose_lut = misses * 5u > (probe_n - 1u);
        if (choose_lut) {
            run_lut_range(signals, probe_end, chunk_end, lut, mode, checksum);
        } else {
            run_branch_range(signals, probe_end, chunk_end, mode, checksum);
        }
    }
}

static uint64_t run_current(
    const uint8_t *signals, const uint8_t lut[12],
    unsigned *branch_blocks, unsigned *lut_blocks
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    unsigned b = 0, l = 0;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t sample_end = base + SAMPLE_LONG;
        size_t end = base + BLOCK_SIZE;
        run_branch_range(signals, base, sample_end, &mode, &checksum);
        if (current_choose_lut(signals + base)) {
            l += 1u;
            run_lut_range(signals, sample_end, end, lut, &mode, &checksum);
        } else {
            b += 1u;
            run_branch_range(signals, sample_end, end, &mode, &checksum);
        }
    }
    *branch_blocks = b;
    *lut_blocks = l;
    return checksum ^ mode;
}

static uint64_t run_atman(
    const uint8_t *signals, const uint8_t *truth, const uint8_t lut[12],
    unsigned *branch_blocks, unsigned *lut_blocks, uint64_t *observation_signals,
    ObserverAudit *short_audit, ObserverAudit *mid_audit, ObserverAudit *long_audit
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    unsigned b = 0, l = 0;
    uint64_t obs = 0;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t end = base + BLOCK_SIZE;
        unsigned observed = 0;
        int choose_lut = atman_choose_lut(
            signals + base, &observed,
            short_audit, mid_audit, long_audit,
            (Morphology)truth[block]
        );
        size_t observed_end = base + observed;
        run_branch_range(signals, base, observed_end, &mode, &checksum);
        obs += observed;
        if (choose_lut) {
            l += 1u;
            run_lut_range(signals, observed_end, end, lut, &mode, &checksum);
        } else {
            b += 1u;
            run_branch_range(signals, observed_end, end, &mode, &checksum);
        }
    }
    *branch_blocks = b;
    *lut_blocks = l;
    *observation_signals = obs;
    return checksum ^ mode;
}

static uint64_t run_atman_cosmic(
    const uint8_t *signals, const uint8_t *truth, const uint8_t lut[12],
    unsigned selected[3], uint64_t *observation_signals, unsigned *morph_errors,
    ObserverAudit *short_audit, ObserverAudit *mid_audit, ObserverAudit *long_audit
) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    unsigned errors = 0;
    uint64_t obs = 0;
    selected[0] = selected[1] = selected[2] = 0;

    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t end = base + BLOCK_SIZE;
        unsigned observed = 0;
        Morphology morph = cosmic_classify(
            signals + base, &observed,
            short_audit, mid_audit, long_audit,
            (Morphology)truth[block]
        );
        if (morph != (Morphology)truth[block]) errors += 1u;
        selected[(unsigned)morph] += 1u;
        obs += observed;

        size_t observed_end = base + observed;
        run_branch_range(signals, base, observed_end, &mode, &checksum);
        if (morph == MORPH_STRUCTURED) {
            run_branch_range(signals, observed_end, end, &mode, &checksum);
        } else if (morph == MORPH_AMORPHOUS) {
            run_lut_range(signals, observed_end, end, lut, &mode, &checksum);
        } else {
            run_hybrid_range(signals, observed_end, end, lut, &mode, &checksum);
        }
    }
    *observation_signals = obs;
    *morph_errors = errors;
    return checksum ^ mode;
}

static uint64_t run_oracle(const uint8_t *signals, const uint8_t *truth, const uint8_t lut[12]) {
    uint8_t mode = 0;
    uint64_t checksum = 0;
    for (unsigned block = 0; block < BLOCKS; ++block) {
        size_t base = (size_t)block * BLOCK_SIZE;
        size_t end = base + BLOCK_SIZE;
        Morphology morph = (Morphology)truth[block];
        if (morph == MORPH_STRUCTURED) {
            run_branch_range(signals, base, end, &mode, &checksum);
        } else if (morph == MORPH_AMORPHOUS) {
            run_lut_range(signals, base, end, lut, &mode, &checksum);
        } else {
            for (size_t chunk = base; chunk < end; chunk += HYBRID_CHUNK) {
                size_t chunk_end = chunk + HYBRID_CHUNK;
                unsigned local = (unsigned)((chunk - base) / HYBRID_CHUNK);
                if ((local & 1u) == 0u) {
                    run_branch_range(signals, chunk, chunk_end, &mode, &checksum);
                } else {
                    run_lut_range(signals, chunk, chunk_end, lut, &mode, &checksum);
                }
            }
        }
    }
    return checksum ^ mode;
}

static double audit_accuracy(const ObserverAudit *a) {
    return a->total ? (double)a->correct / (double)a->total : 0.0;
}

int main(void) {
    uint8_t lut[12];
    uint8_t *signals = (uint8_t *)malloc(SIGNALS);
    uint8_t *truth = (uint8_t *)malloc(BLOCKS);
    if (!signals || !truth) {
        free(signals);
        free(truth);
        return 2;
    }
    build_lut(lut);
    build_workload(signals, truth);

    unsigned current_b = 0, current_l = 0;
    uint64_t warm_current = run_current(signals, lut, &current_b, &current_l);

    unsigned atman_b = 0, atman_l = 0;
    uint64_t atman_obs = 0;
    ObserverAudit as = {0, 0}, am = {0, 0}, al = {0, 0};
    uint64_t warm_atman = run_atman(
        signals, truth, lut, &atman_b, &atman_l, &atman_obs, &as, &am, &al
    );

    unsigned cosmic_selected[3];
    uint64_t cosmic_obs = 0;
    unsigned morph_errors = 0;
    ObserverAudit cs = {0, 0}, cm = {0, 0}, cl = {0, 0};
    uint64_t warm_cosmic = run_atman_cosmic(
        signals, truth, lut, cosmic_selected, &cosmic_obs, &morph_errors,
        &cs, &cm, &cl
    );
    uint64_t warm_oracle = run_oracle(signals, truth, lut);
    int correct = warm_current == warm_atman && warm_atman == warm_cosmic && warm_cosmic == warm_oracle;

    double current_total = 0.0, atman_total = 0.0, cosmic_total = 0.0, oracle_total = 0.0;
    uint64_t checksum = 0;

    for (int repeat = 0; repeat < REPEATS; ++repeat) {
        double t0 = now_seconds();
        uint64_t c = run_current(signals, lut, &current_b, &current_l);
        current_total += now_seconds() - t0;

        ObserverAudit ras = {0, 0}, ram = {0, 0}, ral = {0, 0};
        t0 = now_seconds();
        uint64_t a = run_atman(
            signals, truth, lut, &atman_b, &atman_l, &atman_obs,
            &ras, &ram, &ral
        );
        atman_total += now_seconds() - t0;

        ObserverAudit rcs = {0, 0}, rcm = {0, 0}, rcl = {0, 0};
        t0 = now_seconds();
        uint64_t co = run_atman_cosmic(
            signals, truth, lut, cosmic_selected, &cosmic_obs, &morph_errors,
            &rcs, &rcm, &rcl
        );
        cosmic_total += now_seconds() - t0;

        t0 = now_seconds();
        uint64_t o = run_oracle(signals, truth, lut);
        oracle_total += now_seconds() - t0;

        if (!(c == a && a == co && co == o)) correct = 0;
        checksum ^= c ^ a ^ co ^ o;
        as = ras; am = ram; al = ral;
        cs = rcs; cm = rcm; cl = rcl;
    }

    double current_avg = current_total / REPEATS;
    double atman_avg = atman_total / REPEATS;
    double cosmic_avg = cosmic_total / REPEATS;
    double oracle_avg = oracle_total / REPEATS;

    printf("signals=%zu\n", SIGNALS);
    printf("blocks=%u\n", BLOCKS);
    printf("truth_structured=%u\n", BLOCKS / 3u);
    printf("truth_transitional=%u\n", BLOCKS / 3u);
    printf("truth_amorphous=%u\n", BLOCKS / 3u);
    printf("correct=%s\n", correct ? "true" : "false");
    printf("\n[current fixed-512 binary selector]\n");
    printf("branch_blocks=%u\n", current_b);
    printf("lut_blocks=%u\n", current_l);
    printf("observation_signals=%u\n", BLOCKS * SAMPLE_LONG);
    printf("seconds_avg=%.6f\n", current_avg);

    printf("\n[ATMAN-inspired multi-window binary observer]\n");
    printf("branch_blocks=%u\n", atman_b);
    printf("lut_blocks=%u\n", atman_l);
    printf("observation_signals=%llu\n", (unsigned long long)atman_obs);
    printf("observation_vs_current=%.3fx\n", (double)atman_obs / (double)(BLOCKS * SAMPLE_LONG));
    printf("observer32_accuracy=%.3f\n", audit_accuracy(&as));
    printf("observer128_accuracy=%.3f\n", audit_accuracy(&am));
    printf("observer512_accuracy=%.3f\n", audit_accuracy(&al));
    printf("seconds_avg=%.6f\n", atman_avg);

    printf("\n[ATMAN observers + Cosmic three-way morphology]\n");
    printf("structured_blocks=%u\n", cosmic_selected[MORPH_STRUCTURED]);
    printf("transitional_blocks=%u\n", cosmic_selected[MORPH_TRANSITIONAL]);
    printf("amorphous_blocks=%u\n", cosmic_selected[MORPH_AMORPHOUS]);
    printf("morphology_errors=%u\n", morph_errors);
    printf("observation_signals=%llu\n", (unsigned long long)cosmic_obs);
    printf("observation_vs_current=%.3fx\n", (double)cosmic_obs / (double)(BLOCKS * SAMPLE_LONG));
    printf("observer32_accuracy=%.3f\n", audit_accuracy(&cs));
    printf("observer128_accuracy=%.3f\n", audit_accuracy(&cm));
    printf("observer512_accuracy=%.3f\n", audit_accuracy(&cl));
    printf("seconds_avg=%.6f\n", cosmic_avg);

    printf("\n[oracle morphology + oracle local execution]\n");
    printf("seconds_avg=%.6f\n", oracle_avg);

    printf("\n[ratios]\n");
    printf("atman_vs_current=%.3fx\n", atman_avg / current_avg);
    printf("atman_cosmic_vs_current=%.3fx\n", cosmic_avg / current_avg);
    printf("atman_cosmic_vs_atman=%.3fx\n", cosmic_avg / atman_avg);
    printf("atman_cosmic_vs_oracle=%.3fx\n", cosmic_avg / oracle_avg);
    printf("checksum=%llu\n", (unsigned long long)checksum);
    printf("observer_note=ATMAN principles used here are frozen multi-window observations, HOLD-on-disagreement, and post-outcome observer audit; this is a minimal benchmark kernel, not the full ATMAN runtime.\n");
    printf("cosmic_note=Structured/transitional/amorphous is a new engineering morphology abstraction for this benchmark; COSMIC-ORGANICS main currently does not provide an executable implementation to import.\n");
    printf("interpretation=The test asks whether calibrated multi-scale observation reduces decision lag and whether preserving a transitional morphology enables a useful third execution regime. Equal transition semantics are maintained across all paths.\n");

    sink ^= checksum ^ warm_current ^ warm_atman ^ warm_cosmic ^ warm_oracle;
    printf("sink=%llu\n", (unsigned long long)sink);

    free(signals);
    free(truth);
    return correct ? 0 : 1;
}

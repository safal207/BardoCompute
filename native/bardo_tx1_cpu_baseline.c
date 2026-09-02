#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#include "bardo_tx1_oracle.h"

#if defined(__GNUC__) || defined(__clang__)
#define NOINLINE __attribute__((noinline))
#else
#define NOINLINE
#endif

#define REDUCTION_LANES 71u
#define SIGNATURE_SEED UINT64_C(0x424152444f545831)

static const uint8_t valid_code[8] = {1u, 0u, 1u, 1u, 1u, 1u, 1u, 0u};
static const uint8_t radix_digit[8] = {0u, 0u, 1u, 2u, 3u, 4u, 5u, 0u};
static volatile uint64_t observable_sink;

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static inline uint32_t evaluate_bundle(uint16_t bundle) {
    const uint8_t lower = (uint8_t)(bundle & 0x7u);
    const uint8_t middle = (uint8_t)((bundle >> 3u) & 0x7u);
    const uint8_t upper = (uint8_t)((bundle >> 6u) & 0x7u);
    const uint8_t valid = (uint8_t)(
        valid_code[lower] & valid_code[middle] & valid_code[upper]
    );

    if (!valid) {
        return 0u;
    }

    const uint8_t index = (uint8_t)(
        radix_digit[lower]
        + 6u * radix_digit[middle]
        + 36u * radix_digit[upper]
    );
    const uint8_t any_discontinuous = (uint8_t)(
        (lower | middle | upper) & 1u
    );
    const uint8_t any_transition = (uint8_t)(
        (((lower >> 2u) ^ (lower >> 1u))
        | ((middle >> 2u) ^ (middle >> 1u))
        | ((upper >> 2u) ^ (upper >> 1u))) & 1u
    );
    const uint8_t target_count = (uint8_t)(
        ((lower >> 1u) & 1u)
        + ((middle >> 1u) & 1u)
        + ((upper >> 1u) & 1u)
    );
    const uint8_t policy_allow = (uint8_t)(
        !any_discontinuous && target_count >= 2u && any_transition
    );
    const uint16_t settled = (uint16_t)(
        (((lower >> 1u) & 1u) ? 0x6u : 0u)
        | ((((middle >> 1u) & 1u) ? 0x6u : 0u) << 3u)
        | ((((upper >> 1u) & 1u) ? 0x6u : 0u) << 6u)
    );

    return (uint32_t)index
        | ((uint32_t)policy_allow << 8u)
        | ((uint32_t)settled << 9u)
        | ((uint32_t)any_discontinuous << 18u)
        | ((uint32_t)any_transition << 19u)
        | ((uint32_t)target_count << 20u)
        | ((uint32_t)valid << 22u);
}

static NOINLINE void materialize_direct(
    const uint16_t *restrict bundles,
    uint32_t *restrict outputs,
    size_t count
) {
    for (size_t i = 0; i < count; ++i) {
        outputs[i] = evaluate_bundle(bundles[i]);
    }
}

static NOINLINE void materialize_lut(
    const uint16_t *restrict bundles,
    uint32_t *restrict outputs,
    size_t count,
    const uint32_t *restrict result_lut
) {
    size_t i = 0;
    for (; i + 8u <= count; i += 8u) {
        outputs[i + 0u] = result_lut[bundles[i + 0u]];
        outputs[i + 1u] = result_lut[bundles[i + 1u]];
        outputs[i + 2u] = result_lut[bundles[i + 2u]];
        outputs[i + 3u] = result_lut[bundles[i + 3u]];
        outputs[i + 4u] = result_lut[bundles[i + 4u]];
        outputs[i + 5u] = result_lut[bundles[i + 5u]];
        outputs[i + 6u] = result_lut[bundles[i + 6u]];
        outputs[i + 7u] = result_lut[bundles[i + 7u]];
    }
    for (; i < count; ++i) {
        outputs[i] = result_lut[bundles[i]];
    }
}

static inline uint64_t rotate_left_one_64(uint64_t value) {
    return (value << 1u) | (value >> 63u);
}

static NOINLINE uint64_t reduce_direct(
    const uint16_t *restrict bundles,
    size_t count
) {
    uint64_t signature = SIGNATURE_SEED;
    size_t index = 0;
    uint64_t frame = 0;

    while (index < count) {
        const size_t remaining = count - index;
        const size_t frame_items = remaining < REDUCTION_LANES
            ? remaining
            : REDUCTION_LANES;
        const size_t frame_end = index + frame_items;
        uint32_t xor0 = 0u;
        uint32_t xor1 = 0u;
        uint32_t xor2 = 0u;
        uint32_t xor3 = 0u;
        uint32_t xor4 = 0u;
        uint32_t xor5 = 0u;
        uint32_t xor6 = 0u;
        uint32_t xor7 = 0u;

        for (; index + 8u <= frame_end; index += 8u) {
            xor0 ^= evaluate_bundle(bundles[index + 0u]);
            xor1 ^= evaluate_bundle(bundles[index + 1u]);
            xor2 ^= evaluate_bundle(bundles[index + 2u]);
            xor3 ^= evaluate_bundle(bundles[index + 3u]);
            xor4 ^= evaluate_bundle(bundles[index + 4u]);
            xor5 ^= evaluate_bundle(bundles[index + 5u]);
            xor6 ^= evaluate_bundle(bundles[index + 6u]);
            xor7 ^= evaluate_bundle(bundles[index + 7u]);
        }

        uint32_t cycle_xor = xor0 ^ xor1 ^ xor2 ^ xor3
            ^ xor4 ^ xor5 ^ xor6 ^ xor7;
        for (; index < frame_end; ++index) {
            cycle_xor ^= evaluate_bundle(bundles[index]);
        }

        signature = rotate_left_one_64(signature)
            ^ (uint64_t)cycle_xor
            ^ (frame & UINT64_C(0x1ff));
        ++frame;
    }

    return signature;
}

static NOINLINE uint64_t reduce_lut(
    const uint16_t *restrict bundles,
    size_t count,
    const uint32_t *restrict result_lut
) {
    uint64_t signature = SIGNATURE_SEED;
    size_t index = 0;
    uint64_t frame = 0;

    while (index < count) {
        const size_t remaining = count - index;
        const size_t frame_items = remaining < REDUCTION_LANES
            ? remaining
            : REDUCTION_LANES;
        const size_t frame_end = index + frame_items;
        uint32_t xor0 = 0u;
        uint32_t xor1 = 0u;
        uint32_t xor2 = 0u;
        uint32_t xor3 = 0u;
        uint32_t xor4 = 0u;
        uint32_t xor5 = 0u;
        uint32_t xor6 = 0u;
        uint32_t xor7 = 0u;

        for (; index + 8u <= frame_end; index += 8u) {
            xor0 ^= result_lut[bundles[index + 0u]];
            xor1 ^= result_lut[bundles[index + 1u]];
            xor2 ^= result_lut[bundles[index + 2u]];
            xor3 ^= result_lut[bundles[index + 3u]];
            xor4 ^= result_lut[bundles[index + 4u]];
            xor5 ^= result_lut[bundles[index + 5u]];
            xor6 ^= result_lut[bundles[index + 6u]];
            xor7 ^= result_lut[bundles[index + 7u]];
        }

        uint32_t cycle_xor = xor0 ^ xor1 ^ xor2 ^ xor3
            ^ xor4 ^ xor5 ^ xor6 ^ xor7;
        for (; index < frame_end; ++index) {
            cycle_xor ^= result_lut[bundles[index]];
        }

        signature = rotate_left_one_64(signature)
            ^ (uint64_t)cycle_xor
            ^ (frame & UINT64_C(0x1ff));
        ++frame;
    }

    return signature;
}

static uint64_t checksum_outputs(const uint32_t *outputs, size_t count) {
    uint64_t checksum = UINT64_C(0xcbf29ce484222325);
    for (size_t i = 0; i < count; ++i) {
        checksum ^= (uint64_t)outputs[i] + (uint64_t)i;
        checksum *= UINT64_C(0x100000001b3);
    }
    return checksum;
}

static size_t parse_count(int argc, char **argv) {
    if (argc < 2) {
        return 16000000u;
    }
    errno = 0;
    char *end = NULL;
    const uintmax_t parsed = strtoumax(argv[1], &end, 10);
    if (errno != 0 || end == argv[1] || *end != '\0' || parsed == 0u || parsed > SIZE_MAX) {
        fprintf(stderr, "invalid item count: %s\n", argv[1]);
        exit(2);
    }
    return (size_t)parsed;
}

static unsigned parse_repeats(int argc, char **argv) {
    if (argc < 3) {
        return 6u;
    }
    errno = 0;
    char *end = NULL;
    const uintmax_t parsed = strtoumax(argv[2], &end, 10);
    if (errno != 0 || end == argv[2] || *end != '\0' || parsed == 0u || parsed > 1000u) {
        fprintf(stderr, "invalid repeat count: %s\n", argv[2]);
        exit(2);
    }
    return (unsigned)parsed;
}

static void *checked_malloc(size_t count, size_t item_size, const char *name) {
    if (count > SIZE_MAX / item_size) {
        fprintf(stderr, "allocation size overflow for %s\n", name);
        exit(2);
    }
    void *memory = malloc(count * item_size);
    if (memory == NULL) {
        fprintf(stderr, "allocation failed for %s (%zu bytes)\n", name, count * item_size);
        exit(2);
    }
    return memory;
}

static double mtrigrams_per_second(size_t count, double seconds) {
    return (double)count / seconds / 1000000.0;
}

int main(int argc, char **argv) {
    const size_t count = parse_count(argc, argv);
    const unsigned repeats = parse_repeats(argc, argv);
    uint16_t *bundles = checked_malloc(count, sizeof(*bundles), "input bundles");
    uint32_t *direct_outputs = checked_malloc(
        count, sizeof(*direct_outputs), "direct outputs"
    );
    uint32_t *lut_outputs = checked_malloc(count, sizeof(*lut_outputs), "LUT outputs");

    uint32_t result_lut[512];
    for (unsigned bundle = 0; bundle < BARDO_TX1_ORACLE_SIZE; ++bundle) {
        const uint32_t expected = BARDO_TX1_ORACLE[bundle];
        const uint32_t actual = evaluate_bundle((uint16_t)bundle);
        if (actual != expected) {
            fprintf(
                stderr,
                "oracle mismatch bundle=%u actual=0x%06" PRIx32
                " expected=0x%06" PRIx32 "\n",
                bundle,
                actual,
                expected
            );
            return 3;
        }
        result_lut[bundle] = expected;
    }

    for (size_t i = 0; i < count; ++i) {
        // Full 9-bit state space, including reserved codes, in a deterministic
        // non-sequential order so invalid fail-closed handling stays in scope.
        bundles[i] = (uint16_t)((i * 40503u + (i >> 3u) * 97u + 17u) & 0x1ffu);
    }

    materialize_direct(bundles, direct_outputs, count);
    materialize_lut(bundles, lut_outputs, count, result_lut);
    if (memcmp(direct_outputs, lut_outputs, count * sizeof(*direct_outputs)) != 0) {
        fprintf(stderr, "warm materialized output mismatch\n");
        return 4;
    }

    const uint64_t warm_direct_signature = reduce_direct(bundles, count);
    const uint64_t warm_lut_signature = reduce_lut(bundles, count, result_lut);
    if (warm_direct_signature != warm_lut_signature) {
        fprintf(stderr, "warm reduced signature mismatch\n");
        return 5;
    }

    double materialize_direct_total = 0.0;
    double materialize_lut_total = 0.0;
    double reduce_direct_total = 0.0;
    double reduce_lut_total = 0.0;

    observable_sink = warm_direct_signature;
    for (unsigned repeat = 0; repeat < repeats; ++repeat) {
        const size_t sample = ((size_t)repeat * 4099u + 17u) % count;
        double started;
        uint64_t signature;

        if ((repeat & 1u) == 0u) {
            started = now_seconds();
            materialize_direct(bundles, direct_outputs, count);
            materialize_direct_total += now_seconds() - started;
            observable_sink ^= direct_outputs[sample];

            started = now_seconds();
            materialize_lut(bundles, lut_outputs, count, result_lut);
            materialize_lut_total += now_seconds() - started;
            observable_sink ^= lut_outputs[sample];

            started = now_seconds();
            signature = reduce_direct(bundles, count);
            reduce_direct_total += now_seconds() - started;
            observable_sink ^= signature;

            started = now_seconds();
            signature = reduce_lut(bundles, count, result_lut);
            reduce_lut_total += now_seconds() - started;
            observable_sink ^= signature;
        } else {
            started = now_seconds();
            materialize_lut(bundles, lut_outputs, count, result_lut);
            materialize_lut_total += now_seconds() - started;
            observable_sink ^= lut_outputs[sample];

            started = now_seconds();
            materialize_direct(bundles, direct_outputs, count);
            materialize_direct_total += now_seconds() - started;
            observable_sink ^= direct_outputs[sample];

            started = now_seconds();
            signature = reduce_lut(bundles, count, result_lut);
            reduce_lut_total += now_seconds() - started;
            observable_sink ^= signature;

            started = now_seconds();
            signature = reduce_direct(bundles, count);
            reduce_direct_total += now_seconds() - started;
            observable_sink ^= signature;
        }
    }

    if (memcmp(direct_outputs, lut_outputs, count * sizeof(*direct_outputs)) != 0) {
        fprintf(stderr, "timed materialized output mismatch\n");
        return 6;
    }

    const uint64_t final_direct_signature = reduce_direct(bundles, count);
    const uint64_t final_lut_signature = reduce_lut(bundles, count, result_lut);
    if (final_direct_signature != final_lut_signature) {
        fprintf(stderr, "timed reduced signature mismatch\n");
        return 7;
    }

    const uint64_t direct_checksum = checksum_outputs(direct_outputs, count);
    const uint64_t lut_checksum = checksum_outputs(lut_outputs, count);
    if (direct_checksum != lut_checksum) {
        fprintf(stderr, "post-timing output checksum mismatch\n");
        return 8;
    }

    const double materialize_direct_seconds = materialize_direct_total / (double)repeats;
    const double materialize_lut_seconds = materialize_lut_total / (double)repeats;
    const double reduce_direct_seconds = reduce_direct_total / (double)repeats;
    const double reduce_lut_seconds = reduce_lut_total / (double)repeats;

    printf("items=%zu\n", count);
    printf("repeats=%u\n", repeats);
    printf("cpu_baseline_model=materialize_and_reduction\n");
    printf("threads=1\n");
    printf("compiler=%s\n", __VERSION__);
    printf("input_bytes=%zu\n", count * sizeof(*bundles));
    printf("materialized_output_bytes=%zu\n", count * sizeof(*direct_outputs));
    printf("valid_sparse_states=216\n");
    printf("full_sparse_address_space=512\n");
    printf("reduction_lanes=%u\n", REDUCTION_LANES);
    printf("oracle_verified=true\n");
    printf("correct=true\n");
    printf("output_checksum=%" PRIu64 "\n", direct_checksum);
    printf("reduced_signature=%" PRIu64 "\n", final_direct_signature);
    printf("observable_sink=%" PRIu64 "\n", observable_sink);
    printf("materialize_direct_seconds_avg=%.9f\n", materialize_direct_seconds);
    printf("materialize_lut_seconds_avg=%.9f\n", materialize_lut_seconds);
    printf("reduce_direct_seconds_avg=%.9f\n", reduce_direct_seconds);
    printf("reduce_lut_seconds_avg=%.9f\n", reduce_lut_seconds);
    printf(
        "materialize_direct_mtrigrams_s=%.3f\n",
        mtrigrams_per_second(count, materialize_direct_seconds)
    );
    printf(
        "materialize_lut_mtrigrams_s=%.3f\n",
        mtrigrams_per_second(count, materialize_lut_seconds)
    );
    printf(
        "reduce_direct_mtrigrams_s=%.3f\n",
        mtrigrams_per_second(count, reduce_direct_seconds)
    );
    printf(
        "reduce_lut_mtrigrams_s=%.3f\n",
        mtrigrams_per_second(count, reduce_lut_seconds)
    );
    const double best_materialized = mtrigrams_per_second(
        count,
        materialize_direct_seconds < materialize_lut_seconds
            ? materialize_direct_seconds
            : materialize_lut_seconds
    );
    const double best_reduced = mtrigrams_per_second(
        count,
        reduce_direct_seconds < reduce_lut_seconds
            ? reduce_direct_seconds
            : reduce_lut_seconds
    );
    const double strongest_cpu = best_materialized > best_reduced
        ? best_materialized
        : best_reduced;
    printf("best_materialized_cpu_mtrigrams_s=%.3f\n", best_materialized);
    printf("best_reduced_cpu_mtrigrams_s=%.3f\n", best_reduced);
    // Compatibility field for the physical claim gate. Choosing the strongest
    // fair path is conservative: the FPGA roofline is never compared to a
    // deliberately weaker CPU boundary.
    printf("best_cpu_mtrigrams_s=%.3f\n", strongest_cpu);
    printf(
        "comparison_boundary=single-thread same 9-bit inputs and 23-bit semantic outputs; "
        "materialization writes one 32-bit word per trigram; reduction uses 71-item frames\n"
    );

    free(lut_outputs);
    free(direct_outputs);
    free(bundles);
    return 0;
}

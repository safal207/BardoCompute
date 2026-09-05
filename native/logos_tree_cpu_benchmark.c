#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#if defined(__GNUC__) || defined(__clang__)
#define NOINLINE __attribute__((noinline))
#else
#define NOINLINE
#endif

#define MAX_LANES 71u
#define MASK23 UINT32_C(0x7fffff)
#define LEAF_DOMAIN UINT64_C(0x4c4f474f534c4541)
#define NODE_DOMAIN UINT64_C(0x4c4f474f534e4f44)

typedef struct {
    uint8_t span_start;
    uint8_t span_length;
    uint8_t valid_count;
    uint8_t invalid_count;
    uint8_t transition_count;
    uint8_t discontinuity_count;
    uint8_t target_count;
    uint8_t policy_allow_count;
    uint8_t consequential_count;
    uint64_t ordered_root;
} logos_word_t;

typedef struct {
    uint16_t input_bundle;
    uint32_t payload;
    logos_word_t word;
} logos_leaf_t;

static volatile uint64_t observable_sink;

static const uint8_t valid_code[8] = {1u, 0u, 1u, 1u, 1u, 1u, 1u, 0u};
static const uint8_t radix_digit[8] = {0u, 0u, 1u, 2u, 3u, 4u, 5u, 0u};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static inline uint64_t rotl64(uint64_t value, unsigned shift) {
    shift &= 63u;
    if (shift == 0u) {
        return value;
    }
    return (value << shift) | (value >> (64u - shift));
}

static inline uint64_t mix64(uint64_t value) {
    value ^= value >> 30u;
    value *= UINT64_C(0xbf58476d1ce4e5b9);
    value ^= value >> 27u;
    value *= UINT64_C(0x94d049bb133111eb);
    value ^= value >> 31u;
    return value;
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

    return ((uint32_t)index
        | ((uint32_t)policy_allow << 8u)
        | ((uint32_t)settled << 9u)
        | ((uint32_t)any_discontinuous << 18u)
        | ((uint32_t)any_transition << 19u)
        | ((uint32_t)target_count << 20u)
        | ((uint32_t)valid << 22u)) & MASK23;
}

static inline uint64_t leaf_root(
    uint8_t lane_index,
    uint16_t input_bundle,
    uint32_t payload
) {
    return mix64(
        LEAF_DOMAIN
        ^ mix64((uint64_t)lane_index + 1u)
        ^ rotl64(mix64(input_bundle), 17u)
        ^ rotl64(mix64(payload), 41u)
    );
}

static inline logos_leaf_t make_leaf(uint8_t lane_index, uint16_t bundle) {
    const uint32_t payload = evaluate_bundle(bundle);
    const uint8_t valid = (uint8_t)((payload >> 22u) & 1u);
    const uint8_t policy_allow = (uint8_t)((payload >> 8u) & 1u);
    const uint8_t discontinuous = (uint8_t)((payload >> 18u) & 1u);
    const uint8_t transition = (uint8_t)((payload >> 19u) & 1u);
    const uint8_t target_count = (uint8_t)((payload >> 20u) & 0x3u);
    const uint8_t consequential = (uint8_t)(
        !valid || transition || discontinuous || policy_allow
    );

    logos_leaf_t leaf;
    leaf.input_bundle = bundle;
    leaf.payload = payload;
    leaf.word.span_start = lane_index;
    leaf.word.span_length = 1u;
    leaf.word.valid_count = valid;
    leaf.word.invalid_count = (uint8_t)!valid;
    leaf.word.transition_count = transition;
    leaf.word.discontinuity_count = discontinuous;
    leaf.word.target_count = target_count;
    leaf.word.policy_allow_count = policy_allow;
    leaf.word.consequential_count = consequential;
    leaf.word.ordered_root = leaf_root(lane_index, bundle, payload);
    return leaf;
}

static inline logos_word_t merge_words(logos_word_t left, logos_word_t right) {
    if ((unsigned)right.span_start
        != (unsigned)left.span_start + (unsigned)left.span_length) {
        fprintf(stderr, "noncontiguous LOGOS spans\n");
        exit(3);
    }

    logos_word_t merged;
    merged.span_start = left.span_start;
    merged.span_length = (uint8_t)(left.span_length + right.span_length);
    merged.valid_count = (uint8_t)(left.valid_count + right.valid_count);
    merged.invalid_count = (uint8_t)(left.invalid_count + right.invalid_count);
    merged.transition_count = (uint8_t)(
        left.transition_count + right.transition_count
    );
    merged.discontinuity_count = (uint8_t)(
        left.discontinuity_count + right.discontinuity_count
    );
    merged.target_count = (uint8_t)(left.target_count + right.target_count);
    merged.policy_allow_count = (uint8_t)(
        left.policy_allow_count + right.policy_allow_count
    );
    merged.consequential_count = (uint8_t)(
        left.consequential_count + right.consequential_count
    );
    merged.ordered_root = mix64(
        NODE_DOMAIN
        ^ rotl64(left.ordered_root, 7u)
        ^ rotl64(right.ordered_root, 37u)
        ^ mix64(left.span_start)
        ^ rotl64(mix64(left.span_length), 13u)
        ^ rotl64(mix64(right.span_length), 29u)
    );
    return merged;
}

static NOINLINE logos_word_t linear_logos(
    const logos_leaf_t *leaves,
    size_t lanes
) {
    logos_word_t root = leaves[0].word;
    for (size_t lane = 1; lane < lanes; ++lane) {
        root = merge_words(root, leaves[lane].word);
    }
    return root;
}

static NOINLINE logos_word_t balanced_logos(
    const logos_leaf_t *leaves,
    size_t lanes
) {
    logos_word_t level_a[MAX_LANES];
    logos_word_t level_b[MAX_LANES];
    logos_word_t *current = level_a;
    logos_word_t *next = level_b;

    for (size_t lane = 0; lane < lanes; ++lane) {
        current[lane] = leaves[lane].word;
    }

    size_t count = lanes;
    while (count > 1u) {
        size_t next_count = 0u;
        size_t index = 0u;
        for (; index + 1u < count; index += 2u) {
            next[next_count++] = merge_words(current[index], current[index + 1u]);
        }
        if (index < count) {
            next[next_count++] = current[index];
        }
        logos_word_t *temporary = current;
        current = next;
        next = temporary;
        count = next_count;
    }

    return current[0];
}

static NOINLINE uint32_t flat_xor(
    const logos_leaf_t *leaves,
    size_t lanes
) {
    uint32_t value = 0u;
    for (size_t lane = 0; lane < lanes; ++lane) {
        value ^= leaves[lane].payload;
    }
    return value;
}

static NOINLINE void materialize(
    const logos_leaf_t *leaves,
    uint32_t *outputs,
    size_t lanes
) {
    for (size_t lane = 0; lane < lanes; ++lane) {
        outputs[lane] = leaves[lane].payload;
    }
}

static uint16_t deterministic_bundle(size_t frame, size_t lane) {
    return (uint16_t)(
        (
            frame * 131u
            + lane * 197u
            + (frame >> 2u) * 29u
            + lane * lane * 3u
            + 17u
        ) & 0x1ffu
    );
}

static size_t parse_size(
    int argc,
    char **argv,
    int position,
    size_t default_value,
    const char *name
) {
    if (argc <= position) {
        return default_value;
    }
    errno = 0;
    char *end = NULL;
    const uintmax_t parsed = strtoumax(argv[position], &end, 10);
    if (errno != 0 || end == argv[position] || *end != '\0' || parsed == 0u) {
        fprintf(stderr, "invalid %s: %s\n", name, argv[position]);
        exit(2);
    }
    return (size_t)parsed;
}

static double mlanes_per_second(size_t frames, size_t lanes, double seconds) {
    return (double)(frames * lanes) / seconds / 1000000.0;
}

int main(int argc, char **argv) {
    const size_t frames = parse_size(argc, argv, 1, 65536u, "frame count");
    const size_t repeats = parse_size(argc, argv, 2, 6u, "repeat count");
    const size_t lanes = parse_size(argc, argv, 3, MAX_LANES, "lane count");

    if (lanes > MAX_LANES) {
        fprintf(stderr, "lane count exceeds %u\n", MAX_LANES);
        return 2;
    }
    if (frames > SIZE_MAX / lanes) {
        fprintf(stderr, "frame allocation overflow\n");
        return 2;
    }

    logos_leaf_t *prepared = calloc(frames * lanes, sizeof(*prepared));
    uint32_t *outputs = calloc(lanes, sizeof(*outputs));
    if (prepared == NULL || outputs == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(outputs);
        free(prepared);
        return 2;
    }

    for (size_t frame = 0; frame < frames; ++frame) {
        for (size_t lane = 0; lane < lanes; ++lane) {
            prepared[frame * lanes + lane] = make_leaf(
                (uint8_t)lane,
                deterministic_bundle(frame, lane)
            );
        }
    }

    const logos_leaf_t *first = prepared;
    const uint32_t baseline_xor = flat_xor(first, lanes);
    logos_leaf_t swapped[MAX_LANES];
    memcpy(swapped, first, lanes * sizeof(*swapped));
    if (lanes > 1u) {
        const uint16_t first_bundle = swapped[0].input_bundle;
        const uint16_t second_bundle = swapped[1].input_bundle;
        swapped[0] = make_leaf(0u, second_bundle);
        swapped[1] = make_leaf(1u, first_bundle);
    }
    const uint32_t swapped_xor = flat_xor(swapped, lanes);
    const logos_word_t baseline_root = balanced_logos(first, lanes);
    const logos_word_t swapped_root = balanced_logos(swapped, lanes);

    const int xor_collision = lanes == 1u || baseline_xor == swapped_xor;
    const int ordered_swap_detected = lanes == 1u
        || baseline_root.ordered_root != swapped_root.ordered_root;
    if (!xor_collision || !ordered_swap_detected) {
        fprintf(stderr, "permutation contract failed\n");
        free(outputs);
        free(prepared);
        return 4;
    }

    double materialize_total = 0.0;
    double xor_total = 0.0;
    double linear_total = 0.0;
    double balanced_total = 0.0;

    for (size_t repeat = 0; repeat < repeats; ++repeat) {
        double started = now_seconds();
        uint64_t local_sink = 0u;
        for (size_t frame = 0; frame < frames; ++frame) {
            const logos_leaf_t *leaves = prepared + frame * lanes;
            materialize(leaves, outputs, lanes);
            local_sink ^= outputs[0];
            local_sink ^= outputs[lanes - 1u];
        }
        materialize_total += now_seconds() - started;
        observable_sink ^= local_sink;

        started = now_seconds();
        local_sink = 0u;
        for (size_t frame = 0; frame < frames; ++frame) {
            local_sink ^= flat_xor(prepared + frame * lanes, lanes);
        }
        xor_total += now_seconds() - started;
        observable_sink ^= local_sink;

        started = now_seconds();
        local_sink = 0u;
        for (size_t frame = 0; frame < frames; ++frame) {
            const logos_word_t word = linear_logos(
                prepared + frame * lanes,
                lanes
            );
            local_sink ^= word.ordered_root;
            local_sink ^= word.target_count;
        }
        linear_total += now_seconds() - started;
        observable_sink ^= local_sink;

        started = now_seconds();
        local_sink = 0u;
        for (size_t frame = 0; frame < frames; ++frame) {
            const logos_word_t word = balanced_logos(
                prepared + frame * lanes,
                lanes
            );
            local_sink ^= word.ordered_root;
            local_sink ^= word.target_count;
        }
        balanced_total += now_seconds() - started;
        observable_sink ^= local_sink;
    }

    const double materialize_seconds = materialize_total / (double)repeats;
    const double xor_seconds = xor_total / (double)repeats;
    const double linear_seconds = linear_total / (double)repeats;
    const double balanced_seconds = balanced_total / (double)repeats;

    printf("correct=true\n");
    printf("boundary=native reduction-only over pre-evaluated TX1 leaves; not FPGA evidence\n");
    printf("frames=%zu\n", frames);
    printf("repeats=%zu\n", repeats);
    printf("lanes=%zu\n", lanes);
    printf("full_result_bits_per_frame=%zu\n", lanes * 23u);
    printf("logos_result_bits_per_frame=128\n");
    printf("flat_dependency_depth=%zu\n", lanes);
    unsigned depth = 0u;
    for (size_t remaining = lanes; remaining > 1u; remaining = (remaining + 1u) / 2u) {
        ++depth;
    }
    printf("balanced_tree_depth=%u\n", depth);
    printf("flat_xor_permutation_collision=%s\n", xor_collision ? "true" : "false");
    printf("ordered_tree_swap_detected=%s\n", ordered_swap_detected ? "true" : "false");
    printf("baseline_ordered_root=%016" PRIx64 "\n", baseline_root.ordered_root);
    printf("swapped_ordered_root=%016" PRIx64 "\n", swapped_root.ordered_root);
    printf("materialize_mlanes_s=%.6f\n",
        mlanes_per_second(frames, lanes, materialize_seconds));
    printf("flat_xor_mlanes_s=%.6f\n",
        mlanes_per_second(frames, lanes, xor_seconds));
    printf("linear_ordered_logos_mlanes_s=%.6f\n",
        mlanes_per_second(frames, lanes, linear_seconds));
    printf("balanced_ordered_logos_mlanes_s=%.6f\n",
        mlanes_per_second(frames, lanes, balanced_seconds));
    printf("observable_sink=%" PRIu64 "\n", observable_sink);

    free(outputs);
    free(prepared);
    return 0;
}

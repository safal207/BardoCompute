#define _POSIX_C_SOURCE 200809L

#include <errno.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

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

static uint32_t evaluate_bundle(uint16_t bundle) {
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

static uint64_t mix_checksum(uint64_t checksum, uint32_t value, size_t index) {
    checksum ^= (uint64_t)value + 0x9e3779b97f4a7c15ULL + (uint64_t)index;
    checksum *= 0x100000001b3ULL;
    return checksum;
}

static uint64_t scan_direct(const uint16_t *bundles, size_t count) {
    uint64_t checksum = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < count; ++i) {
        checksum = mix_checksum(checksum, evaluate_bundle(bundles[i]), i);
    }
    return checksum;
}

static uint64_t scan_lut(
    const uint16_t *bundles,
    size_t count,
    const uint32_t result_lut[512]
) {
    uint64_t checksum = 0xcbf29ce484222325ULL;
    for (size_t i = 0; i < count; ++i) {
        checksum = mix_checksum(checksum, result_lut[bundles[i]], i);
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

int main(int argc, char **argv) {
    const size_t count = parse_count(argc, argv);
    const unsigned repeats = 8u;
    uint16_t *bundles = malloc(count * sizeof(*bundles));
    if (bundles == NULL) {
        fprintf(stderr, "allocation failed for %zu bundles\n", count);
        return 2;
    }

    uint32_t result_lut[512];
    for (unsigned bundle = 0; bundle < 512u; ++bundle) {
        result_lut[bundle] = evaluate_bundle((uint16_t)bundle);
    }

    for (size_t i = 0; i < count; ++i) {
        // Full 9-bit state space, including reserved codes, in a deterministic
        // non-sequential order so invalid fail-closed handling stays in scope.
        bundles[i] = (uint16_t)((i * 40503u + (i >> 3u) * 97u + 17u) & 0x1ffu);
    }

    const uint64_t direct_warm = scan_direct(bundles, count);
    const uint64_t lut_warm = scan_lut(bundles, count, result_lut);
    if (direct_warm != lut_warm) {
        fprintf(stderr, "warm checksum mismatch\n");
        free(bundles);
        return 3;
    }

    double direct_total = 0.0;
    double lut_total = 0.0;
    uint64_t direct_checksum = 0u;
    uint64_t lut_checksum = 0u;

    for (unsigned repeat = 0; repeat < repeats; ++repeat) {
        if ((repeat & 1u) == 0u) {
            double started = now_seconds();
            direct_checksum += scan_direct(bundles, count);
            direct_total += now_seconds() - started;

            started = now_seconds();
            lut_checksum += scan_lut(bundles, count, result_lut);
            lut_total += now_seconds() - started;
        } else {
            double started = now_seconds();
            lut_checksum += scan_lut(bundles, count, result_lut);
            lut_total += now_seconds() - started;

            started = now_seconds();
            direct_checksum += scan_direct(bundles, count);
            direct_total += now_seconds() - started;
        }
    }

    // The non-zero accumulated checksums keep both timed paths observable and
    // provide a second semantic-equivalence guard after the warm run.
    if (direct_checksum != lut_checksum) {
        fprintf(stderr, "timed checksum mismatch\n");
        free(bundles);
        return 4;
    }

    const double direct_seconds = direct_total / (double)repeats;
    const double lut_seconds = lut_total / (double)repeats;

    printf("items=%zu\n", count);
    printf("repeats=%u\n", repeats);
    printf("input_bytes=%zu\n", count * sizeof(*bundles));
    printf("valid_sparse_states=216\n");
    printf("full_sparse_address_space=512\n");
    printf("correct=true\n");
    printf("warm_checksum=%" PRIu64 "\n", direct_warm);
    printf("direct_seconds_avg=%.9f\n", direct_seconds);
    printf("lut_seconds_avg=%.9f\n", lut_seconds);
    printf("direct_mtrigrams_s=%.3f\n", (double)count / direct_seconds / 1000000.0);
    printf("lut_mtrigrams_s=%.3f\n", (double)count / lut_seconds / 1000000.0);
    printf("best_cpu_mtrigrams_s=%.3f\n",
           (double)count / (direct_seconds < lut_seconds ? direct_seconds : lut_seconds) / 1000000.0);
    printf("comparison_boundary=same 9-bit sparse input, same fail-closed outputs, direct and 512-entry LUT CPU paths\n");

    free(bundles);
    return 0;
}

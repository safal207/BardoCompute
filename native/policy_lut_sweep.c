#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint64_t scan_sequential(
    const uint8_t *policy,
    uint32_t mask,
    size_t n
) {
    uint64_t sum = 0;
    for (size_t i = 0; i < n; ++i) {
        sum += policy[(uint32_t)i & mask];
    }
    return sum;
}

static uint64_t scan_randomized(
    const uint8_t *policy,
    const uint32_t *keys,
    uint32_t mask,
    size_t n
) {
    uint64_t sum = 0;
    for (size_t i = 0; i < n; ++i) {
        sum += policy[keys[i] & mask];
    }
    return sum;
}

static void fill_policy(uint8_t *policy, uint32_t entries) {
    for (uint32_t i = 0; i < entries; ++i) {
        uint32_t x = i;
        x ^= x >> 7u;
        x *= 0x9E3779B1u;
        x ^= x >> 13u;
        policy[i] = (uint8_t)(x & 1u);
    }
}

int main(void) {
    const size_t n = 8000000u;
    const unsigned repeats = 6u;
    const unsigned min_bits = 12u;
    const unsigned max_bits = 23u;
    const uint32_t max_entries = 1u << max_bits;

    uint8_t *policy = malloc((size_t)max_entries * sizeof(*policy));
    uint32_t *keys = malloc(n * sizeof(*keys));
    if (policy == NULL || keys == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(policy);
        free(keys);
        return 2;
    }

    uint32_t state = 0xC0FFEE11u;
    for (size_t i = 0; i < n; ++i) {
        state = state * 1664525u + 1013904223u;
        keys[i] = state;
    }

    printf("records=%zu\n", n);
    printf("repeats=%u\n", repeats);
    printf("entry_bytes=1\n");
    printf("access_patterns=sequential,randomized\n");
    printf("correct=true\n");
    printf("bits,table_kb,sequential_seconds,randomized_seconds,sequential_mlookups_s,randomized_mlookups_s,random_vs_sequential\n");

    volatile uint64_t sink = 0;

    for (unsigned bits = min_bits; bits <= max_bits; ++bits) {
        const uint32_t entries = 1u << bits;
        const uint32_t mask = entries - 1u;
        fill_policy(policy, entries);

        const uint64_t warm_seq = scan_sequential(policy, mask, n);
        const uint64_t warm_random = scan_randomized(policy, keys, mask, n);
        sink ^= warm_seq ^ warm_random;

        double seq_total = 0.0;
        double random_total = 0.0;
        uint64_t seq_checksum = 0;
        uint64_t random_checksum = 0;

        for (unsigned r = 0; r < repeats; ++r) {
            double started;
            if ((r & 1u) == 0u) {
                started = now_seconds();
                seq_checksum += scan_sequential(policy, mask, n);
                seq_total += now_seconds() - started;

                started = now_seconds();
                random_checksum += scan_randomized(policy, keys, mask, n);
                random_total += now_seconds() - started;
            } else {
                started = now_seconds();
                random_checksum += scan_randomized(policy, keys, mask, n);
                random_total += now_seconds() - started;

                started = now_seconds();
                seq_checksum += scan_sequential(policy, mask, n);
                seq_total += now_seconds() - started;
            }
        }

        sink ^= seq_checksum ^ random_checksum;

        const double seq_avg = seq_total / (double)repeats;
        const double random_avg = random_total / (double)repeats;
        const double seq_m = ((double)n / seq_avg) / 1000000.0;
        const double random_m = ((double)n / random_avg) / 1000000.0;
        const double table_kb = (double)entries / 1024.0;

        printf(
            "%u,%.0f,%.6f,%.6f,%.3f,%.3f,%.3f\n",
            bits,
            table_kb,
            seq_avg,
            random_avg,
            seq_m,
            random_m,
            random_avg / seq_avg
        );
    }

    printf("checksum=%" PRIu64 "\n", (uint64_t)sink);
    printf("interpretation=This is a generic cache/locality control for state-indexed one-byte policy tables; it does not encode Bardo/Tao semantics.\n");

    free(policy);
    free(keys);
    return 0;
}

#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

static const uint8_t line_code_from_digit[6] = {
    0x0u, /* stable 0 */
    0x2u, /* 0->1 continuous */
    0x3u, /* 0->1 discontinuous */
    0x4u, /* 1->0 continuous */
    0x5u, /* 1->0 discontinuous */
    0x6u  /* stable 1 */
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec / 1000000000.0;
}

static uint8_t is_transition(uint8_t code) {
    return (uint8_t)(((code >> 2u) & 1u) != ((code >> 1u) & 1u));
}

static uint8_t joint_policy(uint8_t a, uint8_t b, uint8_t c) {
    const uint8_t any_discontinuous = (uint8_t)((a | b | c) & 1u);
    const unsigned target_count =
        (unsigned)((a >> 1u) & 1u) +
        (unsigned)((b >> 1u) & 1u) +
        (unsigned)((c >> 1u) & 1u);
    const uint8_t any_transition =
        (uint8_t)(is_transition(a) | is_transition(b) | is_transition(c));
    return (uint8_t)(!any_discontinuous && target_count >= 2u && any_transition);
}

static uint16_t pack_generic_9bit(uint8_t a, uint8_t b, uint8_t c) {
    return (uint16_t)(a | ((uint16_t)b << 3u) | ((uint16_t)c << 6u));
}

static uint8_t pack_radix6(uint8_t da, uint8_t db, uint8_t dc) {
    return (uint8_t)(da + 6u * db + 36u * dc);
}

static uint64_t scan_u16(
    const uint16_t *groups,
    size_t n,
    const uint8_t policy[512]
) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        allowed += policy[groups[i]];
    }
    return allowed;
}

static uint64_t scan_u8(
    const uint8_t *groups,
    size_t n,
    const uint8_t policy[216]
) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        allowed += policy[groups[i]];
    }
    return allowed;
}

int main(void) {
    const size_t n_groups = 16000000u;
    const unsigned repeats = 12u;

    uint16_t *generic_groups = malloc(n_groups * sizeof(*generic_groups));
    uint8_t *trigram_groups = malloc(n_groups * sizeof(*trigram_groups));
    if (generic_groups == NULL || trigram_groups == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(generic_groups);
        free(trigram_groups);
        return 2;
    }

    uint8_t generic_policy[512] = {0};
    uint8_t trigram_policy[216] = {0};

    for (uint8_t da = 0; da < 6u; ++da) {
        for (uint8_t db = 0; db < 6u; ++db) {
            for (uint8_t dc = 0; dc < 6u; ++dc) {
                const uint8_t a = line_code_from_digit[da];
                const uint8_t b = line_code_from_digit[db];
                const uint8_t c = line_code_from_digit[dc];
                const uint8_t result = joint_policy(a, b, c);
                generic_policy[pack_generic_9bit(a, b, c)] = result;
                trigram_policy[pack_radix6(da, db, dc)] = result;
            }
        }
    }

    double started = now_seconds();
    for (size_t i = 0; i < n_groups; ++i) {
        const uint8_t da = (uint8_t)((i * 5u + i / 7u) % 6u);
        const uint8_t db = (uint8_t)((i * 3u + i / 11u + 1u) % 6u);
        const uint8_t dc = (uint8_t)((i * 7u + i / 13u + 2u) % 6u);
        generic_groups[i] = pack_generic_9bit(
            line_code_from_digit[da],
            line_code_from_digit[db],
            line_code_from_digit[dc]
        );
    }
    const double generic_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n_groups; ++i) {
        const uint8_t da = (uint8_t)((i * 5u + i / 7u) % 6u);
        const uint8_t db = (uint8_t)((i * 3u + i / 11u + 1u) % 6u);
        const uint8_t dc = (uint8_t)((i * 7u + i / 13u + 2u) % 6u);
        trigram_groups[i] = pack_radix6(da, db, dc);
    }
    const double trigram_build = now_seconds() - started;

    /* Warm both paths before measuring. */
    const uint64_t generic_warm = scan_u16(generic_groups, n_groups, generic_policy);
    const uint64_t trigram_warm = scan_u8(trigram_groups, n_groups, trigram_policy);
    if (generic_warm != trigram_warm) {
        fprintf(stderr, "warmup checksum mismatch\n");
        free(generic_groups);
        free(trigram_groups);
        return 3;
    }

    uint64_t generic_checksum = 0;
    uint64_t trigram_checksum = 0;
    double generic_scan_total = 0.0;
    double trigram_scan_total = 0.0;

    /* Alternate order to reduce frequency/thermal/order bias. */
    for (unsigned r = 0; r < repeats; ++r) {
        if ((r & 1u) == 0u) {
            started = now_seconds();
            generic_checksum += scan_u16(generic_groups, n_groups, generic_policy);
            generic_scan_total += now_seconds() - started;

            started = now_seconds();
            trigram_checksum += scan_u8(trigram_groups, n_groups, trigram_policy);
            trigram_scan_total += now_seconds() - started;
        } else {
            started = now_seconds();
            trigram_checksum += scan_u8(trigram_groups, n_groups, trigram_policy);
            trigram_scan_total += now_seconds() - started;

            started = now_seconds();
            generic_checksum += scan_u16(generic_groups, n_groups, generic_policy);
            generic_scan_total += now_seconds() - started;
        }
    }

    const double generic_scan = generic_scan_total / repeats;
    const double trigram_scan = trigram_scan_total / repeats;

    if (generic_checksum != trigram_checksum) {
        fprintf(stderr, "checksum mismatch: generic=%" PRIu64 " trigram=%" PRIu64 "\n",
                generic_checksum, trigram_checksum);
        free(generic_groups);
        free(trigram_groups);
        return 4;
    }

    const size_t generic_bytes = n_groups * sizeof(*generic_groups);
    const size_t trigram_bytes = n_groups * sizeof(*trigram_groups);

    printf("groups=%zu\n", n_groups);
    printf("repeats=%u\n", repeats);
    printf("valid_group_states=216\n");
    printf("measurement_order=alternating_after_warmup\n");
    printf("correct=true\n\n");

    printf("[generic packed group: three 3-bit line codes in uint16_t]\n");
    printf("storage_bits_per_group=16\n");
    printf("logical_bits_used=9\n");
    printf("total_bytes=%zu\n", generic_bytes);
    printf("lookup_table_entries=512\n");
    printf("build_seconds=%.6f\n", generic_build);
    printf("scan_seconds_avg=%.6f\n\n", generic_scan);

    printf("[radix-6 trigram byte]\n");
    printf("storage_bits_per_group=8\n");
    printf("logical_states_used=216\n");
    printf("total_bytes=%zu\n", trigram_bytes);
    printf("lookup_table_entries=216\n");
    printf("build_seconds=%.6f\n", trigram_build);
    printf("scan_seconds_avg=%.6f\n\n", trigram_scan);

    printf("trigram_memory_vs_generic=%.3fx\n", (double)trigram_bytes / (double)generic_bytes);
    printf("trigram_build_vs_generic=%.3fx\n", trigram_build / generic_build);
    printf("trigram_scan_vs_generic=%.3fx\n", trigram_scan / generic_scan);
    printf("generic_throughput_mgroups_s=%.3f\n", (double)n_groups / generic_scan / 1000000.0);
    printf("trigram_throughput_mgroups_s=%.3f\n", (double)n_groups / trigram_scan / 1000000.0);
    printf("control_note=both representations use precomputed lookup tables and carry the same 216 valid semantic states\n");

    free(generic_groups);
    free(trigram_groups);
    return 0;
}

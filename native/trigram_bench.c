#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>

/*
 * Six v0.2 line states are mapped to dense radix-6 digits:
 *
 * 0 = stable 0
 * 1 = 0->1 continuous
 * 2 = 0->1 discontinuous
 * 3 = 1->0 continuous
 * 4 = 1->0 discontinuous
 * 5 = stable 1
 *
 * Three such digits yield 6^3 = 216 trigram states, so a complete
 * transition-aware trigram fits in one uint8_t.
 */

static const uint8_t line_code_from_digit[6] = {
    0x0u, /* stable 0 */
    0x2u, /* rising continuous */
    0x3u, /* rising discontinuous */
    0x4u, /* falling continuous */
    0x5u, /* falling discontinuous */
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

static uint8_t is_allowed_line(uint8_t code) {
    return (uint8_t)(((code & 0x2u) != 0u) && ((code & 0x1u) == 0u));
}

static uint8_t pack_trigram_digits(uint8_t a, uint8_t b, uint8_t c) {
    return (uint8_t)(a + 6u * b + 36u * c);
}

static uint64_t scan_lines(const uint8_t *lines, size_t n) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n; ++i) {
        allowed += is_allowed_line(lines[i]);
    }
    return allowed;
}

static uint64_t scan_trigrams(
    const uint8_t *trigrams,
    size_t n_trigrams,
    const uint8_t allowed_count[216]
) {
    uint64_t allowed = 0;
    for (size_t i = 0; i < n_trigrams; ++i) {
        allowed += allowed_count[trigrams[i]];
    }
    return allowed;
}

int main(void) {
    const size_t n_lines = 24000000u;
    const size_t n_trigrams = n_lines / 3u;
    const unsigned repeats = 8u;

    uint8_t *lines = malloc(n_lines * sizeof(*lines));
    uint8_t *trigrams = malloc(n_trigrams * sizeof(*trigrams));
    if (lines == NULL || trigrams == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(lines);
        free(trigrams);
        return 2;
    }

    /* Deterministic mixed six-state workload. */
    double started = now_seconds();
    for (size_t i = 0; i < n_lines; ++i) {
        const uint8_t digit = (uint8_t)((i * 5u + i / 7u) % 6u);
        lines[i] = line_code_from_digit[digit];
    }
    const double line_build = now_seconds() - started;

    started = now_seconds();
    for (size_t i = 0; i < n_trigrams; ++i) {
        const size_t base = i * 3u;

        uint8_t digits[3];
        for (size_t j = 0; j < 3u; ++j) {
            const uint8_t code = lines[base + j];
            /* Dense mapping for the six legal v0.2 packed line codes. */
            switch (code) {
                case 0x0u: digits[j] = 0u; break;
                case 0x2u: digits[j] = 1u; break;
                case 0x3u: digits[j] = 2u; break;
                case 0x4u: digits[j] = 3u; break;
                case 0x5u: digits[j] = 4u; break;
                case 0x6u: digits[j] = 5u; break;
                default:
                    fprintf(stderr, "invalid line code\n");
                    free(lines);
                    free(trigrams);
                    return 3;
            }
        }

        trigrams[i] = pack_trigram_digits(digits[0], digits[1], digits[2]);
    }
    const double trigram_build = now_seconds() - started;

    uint8_t allowed_count[216];
    for (unsigned value = 0; value < 216u; ++value) {
        unsigned x = value;
        uint8_t count = 0;
        for (unsigned position = 0; position < 3u; ++position) {
            const uint8_t digit = (uint8_t)(x % 6u);
            x /= 6u;
            count = (uint8_t)(count + is_allowed_line(line_code_from_digit[digit]));
        }
        allowed_count[value] = count;
    }

    uint64_t line_checksum = 0;
    started = now_seconds();
    for (unsigned r = 0; r < repeats; ++r) {
        line_checksum += scan_lines(lines, n_lines);
    }
    const double line_scan_total = now_seconds() - started;

    uint64_t trigram_checksum = 0;
    started = now_seconds();
    for (unsigned r = 0; r < repeats; ++r) {
        trigram_checksum += scan_trigrams(trigrams, n_trigrams, allowed_count);
    }
    const double trigram_scan_total = now_seconds() - started;

    if (line_checksum != trigram_checksum) {
        fprintf(stderr, "checksum mismatch: lines=%" PRIu64 " trigrams=%" PRIu64 "\n",
                line_checksum, trigram_checksum);
        free(lines);
        free(trigrams);
        return 4;
    }

    const size_t line_bytes = n_lines * sizeof(*lines);
    const size_t trigram_bytes = n_trigrams * sizeof(*trigrams);
    const double line_scan = line_scan_total / repeats;
    const double trigram_scan = trigram_scan_total / repeats;

    printf("lines=%zu\n", n_lines);
    printf("trigrams=%zu\n", n_trigrams);
    printf("semantic_states_per_line=6\n");
    printf("semantic_states_per_trigram=216\n");
    printf("correct=true\n\n");

    printf("[independent packed lines]\n");
    printf("total_bytes=%zu\n", line_bytes);
    printf("build_seconds=%.6f\n", line_build);
    printf("scan_seconds_avg=%.6f\n\n", line_scan);

    printf("[radix-6 trigram byte + 216-entry lookup]\n");
    printf("total_bytes=%zu\n", trigram_bytes);
    printf("pack_from_lines_seconds=%.6f\n", trigram_build);
    printf("scan_seconds_avg=%.6f\n\n", trigram_scan);

    printf("trigram_memory_vs_lines=%.3fx\n", (double)trigram_bytes / (double)line_bytes);
    printf("trigram_scan_vs_lines=%.3fx\n", trigram_scan / line_scan);
    printf("line_scan_throughput_mlines_s=%.3f\n", (double)n_lines / line_scan / 1000000.0);
    printf("trigram_scan_equivalent_mlines_s=%.3f\n", (double)n_lines / trigram_scan / 1000000.0);
    printf("encoding_note=6^3=216 is generic radix packing; the trigram supplies a natural three-line grouping\n");

    free(lines);
    free(trigrams);
    return 0;
}

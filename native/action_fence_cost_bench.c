#define _POSIX_C_SOURCE 200809L

#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

#define ACTIONS (8u * 1024u * 1024u)
#define REPEATS 7
#define AUTHORITY_EPOCH 7u

typedef enum {
    PATTERN_NONE = 0,
    PATTERN_PERIODIC = 1,
    PATTERN_RANDOM = 2,
} PatternKind;

typedef struct {
    const char *name;
    PatternKind kind;
    uint32_t stale_per_million;
} Profile;

typedef struct {
    double seconds;
    uint64_t accepted;
    uint64_t rejected;
    uint64_t checksum;
    uint64_t auxiliary;
} Result;

static volatile uint64_t g_sink = 0;

static const Profile PROFILES[] = {
    {"none", PATTERN_NONE, 0},
    {"periodic_0.1pct", PATTERN_PERIODIC, 1000},
    {"random_0.1pct", PATTERN_RANDOM, 1000},
    {"periodic_10pct", PATTERN_PERIODIC, 100000},
    {"random_10pct", PATTERN_RANDOM, 100000},
    {"random_50pct", PATTERN_RANDOM, 500000},
};

static double now_seconds(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts) != 0) {
        perror("clock_gettime");
        exit(2);
    }
    return (double)ts.tv_sec + (double)ts.tv_nsec * 1e-9;
}

static uint32_t lcg32(uint32_t *state) {
    *state = (*state * 1664525u) + 1013904223u;
    return *state;
}

static void build_payload(uint32_t *payload, size_t n) {
    uint32_t state = 0xC0FFEE11u;
    for (size_t i = 0; i < n; ++i) {
        payload[i] = (lcg32(&state) & 0xFFFFu) + 1u;
    }
}

static void build_tokens(uint32_t *tokens, size_t n, Profile profile) {
    if (profile.kind == PATTERN_NONE || profile.stale_per_million == 0) {
        for (size_t i = 0; i < n; ++i) {
            tokens[i] = AUTHORITY_EPOCH;
        }
        return;
    }

    if (profile.kind == PATTERN_PERIODIC) {
        uint32_t every = 1000000u / profile.stale_per_million;
        if (every == 0) {
            every = 1;
        }
        for (size_t i = 0; i < n; ++i) {
            tokens[i] = ((i % every) == 0) ? (AUTHORITY_EPOCH - 1u) : AUTHORITY_EPOCH;
        }
        return;
    }

    uint32_t state = 0xBADC0DE5u ^ profile.stale_per_million;
    for (size_t i = 0; i < n; ++i) {
        uint32_t draw = lcg32(&state) % 1000000u;
        tokens[i] = (draw < profile.stale_per_million)
            ? (AUTHORITY_EPOCH - 1u)
            : AUTHORITY_EPOCH;
    }
}

static Result run_unguarded(const uint32_t *payload, size_t n) {
    Result out = {0};
    double start = now_seconds();
    uint64_t checksum = 0;
    for (size_t i = 0; i < n; ++i) {
        checksum += payload[i];
    }
    out.seconds = now_seconds() - start;
    out.accepted = n;
    out.checksum = checksum;
    g_sink ^= checksum;
    return out;
}

static Result run_equal_load(
    const uint32_t *payload,
    const uint32_t *tokens,
    size_t n
) {
    Result out = {0};
    double start = now_seconds();
    uint64_t checksum = 0;
    uint64_t token_checksum = 0;
    for (size_t i = 0; i < n; ++i) {
        checksum += payload[i];
        token_checksum += tokens[i];
    }
    out.seconds = now_seconds() - start;
    out.accepted = n;
    out.checksum = checksum;
    out.auxiliary = token_checksum;
    g_sink ^= checksum ^ token_checksum;
    return out;
}

static Result run_fenced_branch(
    const uint32_t *payload,
    const uint32_t *tokens,
    size_t n
) {
    Result out = {0};
    double start = now_seconds();
    uint64_t accepted = 0;
    uint64_t rejected = 0;
    uint64_t checksum = 0;

    for (size_t i = 0; i < n; ++i) {
        if (tokens[i] == AUTHORITY_EPOCH) {
            checksum += payload[i];
            accepted += 1;
        } else {
            rejected += 1;
        }
    }

    out.seconds = now_seconds() - start;
    out.accepted = accepted;
    out.rejected = rejected;
    out.checksum = checksum;
    g_sink ^= checksum ^ accepted ^ rejected;
    return out;
}

static Result run_fenced_branchless(
    const uint32_t *payload,
    const uint32_t *tokens,
    size_t n
) {
    Result out = {0};
    double start = now_seconds();
    uint64_t accepted = 0;
    uint64_t rejected = 0;
    uint64_t checksum = 0;

    for (size_t i = 0; i < n; ++i) {
        uint64_t valid = (uint64_t)(tokens[i] == AUTHORITY_EPOCH);
        accepted += valid;
        rejected += 1u - valid;
        checksum += (uint64_t)payload[i] * valid;
    }

    out.seconds = now_seconds() - start;
    out.accepted = accepted;
    out.rejected = rejected;
    out.checksum = checksum;
    g_sink ^= checksum ^ accepted ^ rejected;
    return out;
}

static int compare_double(const void *a, const void *b) {
    double x = *(const double *)a;
    double y = *(const double *)b;
    return (x > y) - (x < y);
}

static double median_seconds(double values[REPEATS]) {
    qsort(values, REPEATS, sizeof(double), compare_double);
    return values[REPEATS / 2];
}

static void report_profile(
    const uint32_t *payload,
    const uint32_t *tokens,
    size_t n,
    Profile profile
) {
    double unguarded_times[REPEATS];
    double equal_load_times[REPEATS];
    double branch_times[REPEATS];
    double branchless_times[REPEATS];

    Result reference_branch = {0};
    Result reference_branchless = {0};
    Result reference_equal_load = {0};

    for (int repeat = 0; repeat < REPEATS; ++repeat) {
        Result unguarded = run_unguarded(payload, n);
        Result equal_load = run_equal_load(payload, tokens, n);
        Result branch = run_fenced_branch(payload, tokens, n);
        Result branchless = run_fenced_branchless(payload, tokens, n);

        unguarded_times[repeat] = unguarded.seconds;
        equal_load_times[repeat] = equal_load.seconds;
        branch_times[repeat] = branch.seconds;
        branchless_times[repeat] = branchless.seconds;

        if (repeat == 0) {
            reference_branch = branch;
            reference_branchless = branchless;
            reference_equal_load = equal_load;
        }

        if (
            branch.accepted != branchless.accepted ||
            branch.rejected != branchless.rejected ||
            branch.checksum != branchless.checksum
        ) {
            fprintf(stderr, "semantic mismatch for profile %s\n", profile.name);
            exit(3);
        }
    }

    double unguarded = median_seconds(unguarded_times);
    double equal_load = median_seconds(equal_load_times);
    double branch = median_seconds(branch_times);
    double branchless = median_seconds(branchless_times);

    double ns_per_action_unguarded = unguarded * 1e9 / (double)n;
    double ns_per_action_equal_load = equal_load * 1e9 / (double)n;
    double ns_per_action_branch = branch * 1e9 / (double)n;
    double ns_per_action_branchless = branchless * 1e9 / (double)n;

    printf("\n[%s]\n", profile.name);
    printf("actions=%zu\n", n);
    printf("accepted=%" PRIu64 "\n", reference_branch.accepted);
    printf("rejected=%" PRIu64 "\n", reference_branch.rejected);
    printf("fenced_semantic_equivalence=true\n");
    printf("equal_load_token_checksum=%" PRIu64 "\n", reference_equal_load.auxiliary);
    printf("unguarded_ns_per_action=%.3f\n", ns_per_action_unguarded);
    printf("equal_load_ns_per_action=%.3f\n", ns_per_action_equal_load);
    printf("branch_fence_ns_per_action=%.3f\n", ns_per_action_branch);
    printf("branchless_fence_ns_per_action=%.3f\n", ns_per_action_branchless);
    printf("equal_load_vs_unguarded=%.3fx\n", equal_load / unguarded);
    printf("branch_fence_vs_equal_load=%.3fx\n", branch / equal_load);
    printf("branchless_fence_vs_equal_load=%.3fx\n", branchless / equal_load);
    printf("branch_vs_branchless=%.3fx\n", branch / branchless);
    printf("accepted_checksum=%" PRIu64 "\n", reference_branch.checksum);
}

int main(void) {
    const size_t n = ACTIONS;
    uint32_t *payload = malloc(n * sizeof(*payload));
    uint32_t *tokens = malloc(n * sizeof(*tokens));
    if (payload == NULL || tokens == NULL) {
        fprintf(stderr, "allocation failed\n");
        free(payload);
        free(tokens);
        return 2;
    }

    build_payload(payload, n);

    printf("benchmark=local_action_fence_cost_v0.10\n");
    printf("actions=%zu\n", n);
    printf("repeats=%d\n", REPEATS);
    printf("authority_epoch=%u\n", AUTHORITY_EPOCH);
    printf("scope=local_in_memory_epoch_token_enforcement_only\n");
    printf("not_modeled=network,consensus,replication,lease_acquisition,remote_storage\n");
    printf("primary_runtime_comparator=equal_load_control\n");

    for (size_t p = 0; p < sizeof(PROFILES) / sizeof(PROFILES[0]); ++p) {
        build_tokens(tokens, n, PROFILES[p]);
        report_profile(payload, tokens, n, PROFILES[p]);
    }

    printf("\nvolatile_sink=%" PRIu64 "\n", g_sink);
    printf(
        "interpretation=Unguarded is the absolute local floor but does not read "
        "authority tokens. Equal-load reads the same payload and token streams "
        "without enforcing authority, so fence/equal-load ratios better isolate "
        "comparison, rejection accounting, branch predictability, and compiler "
        "effects. Branch and branchless fenced paths must produce identical "
        "accepted/rejected counts and accepted checksums. This microbenchmark "
        "does not estimate distributed-system validation latency.\n"
    );

    free(payload);
    free(tokens);
    return 0;
}

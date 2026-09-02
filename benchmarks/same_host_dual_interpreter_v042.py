from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections import Counter, defaultdict
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter
from typing import Any

import event_aligned_trajectory_v041 as v041
from computational_interoception_v019 import HEALTHY_PAIN
from continuous_miss_burden_v026 import SEVERE_MISS_THRESHOLD
from cost_mediation_v039 import safe_ratio
from incremental_rate_weaning_v037 import IncrementalRateWeaningMembrane
from rate_first_recovery_v028 import RateFirstRecoveryMembrane
from real_work_queue_transfer import _work, build_epochs

# Frozen in issue #38 before implementation/results.
SEEDS = (
    25_101_003,
    25_201_009,
    25_301_017,
    25_401_031,
    25_501_039,
    25_601_047,
    25_701_059,
    25_801_067,
)
WORK_ROUNDS = 32
PAIRED_REPETITIONS = 4
MIN_SEED_AGREEMENT = 6
CALIBRATION_SAMPLES = 7
ORDER_PREVALENCE_GAP = 0.50
POLICIES = ("binary", "incremental")
VERSIONS = ("3.11", "3.12")
CAUSES = (
    "CONTROLLER_STATE_ALREADY_DIVERGED",
    "RELEASE_COUNT_DIVERGENCE",
    "DELIVERED_COUNT_DIVERGENCE",
    "SEVERE_THRESHOLD_CROSSING",
    "HEALTHY_PAIN_THRESHOLD_CROSSING",
    "OTHER_EVIDENCE_DIVERGENCE",
)


class RecordingController:
    """Transparent wrapper used only to retain per-epoch post-observe values."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner
        self.after_weaning_limits: list[int] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def command(self):
        return self.inner.command()

    def observe(self, result) -> None:
        self.inner.observe(result)
        self.after_weaning_limits.append(int(getattr(self.inner, "weaning_limit", 0)))


def make_controller(policy: str) -> RecordingController:
    if policy == "binary":
        return RecordingController(RateFirstRecoveryMembrane())
    if policy == "incremental":
        return RecordingController(IncrementalRateWeaningMembrane())
    raise ValueError(f"unknown policy: {policy}")


def calibration_payload() -> dict[str, Any]:
    _work(WORK_ROUNDS)
    samples: list[float] = []
    for _ in range(CALIBRATION_SAMPLES):
        started = perf_counter()
        _work(WORK_ROUNDS)
        samples.append(perf_counter() - started)
    return {
        "rounds": WORK_ROUNDS,
        "samples": samples,
        "median_task_seconds": float(median(samples)),
    }


def run_worker(*, seed: int, repetition: int, policy: str, rounds: int, deadline: float) -> dict[str, Any]:
    controller = make_controller(policy)
    elapsed_by_epoch: list[float] = []
    original_execute = v041._execute_batch

    def recording_execute(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        elapsed_by_epoch.append(float(result[0]))
        return result

    v041._execute_batch = recording_execute
    try:
        run = v041.run_policy(
            build_epochs(seed),
            policy=policy,
            controller=controller,
            rounds=rounds,
            deadline_seconds=deadline,
        )
    finally:
        v041._execute_batch = original_execute

    if len(elapsed_by_epoch) != len(run.trace):
        raise AssertionError(
            f"elapsed/trace mismatch: {len(elapsed_by_epoch)} != {len(run.trace)}"
        )
    if len(controller.after_weaning_limits) != len(run.trace):
        raise AssertionError(
            "post-observe weaning/trace mismatch: "
            f"{len(controller.after_weaning_limits)} != {len(run.trace)}"
        )

    trace: list[dict[str, Any]] = []
    for index, row in enumerate(run.trace):
        item = asdict(row)
        item["elapsed_seconds"] = elapsed_by_epoch[index]
        item["deadline_seconds"] = deadline
        item["missed"] = max(0, int(item["released"]) - int(item["delivered"]))
        item["severe_margin"] = float(item["miss_fraction"]) - SEVERE_MISS_THRESHOLD
        item["healthy_margin"] = float(item["after_pain"]) - HEALTHY_PAIN
        item["after_weaning_limit"] = controller.after_weaning_limits[index]
        trace.append(item)

    stats = run.stats
    return {
        "seed": seed,
        "repetition": repetition,
        "policy": policy,
        "rounds": rounds,
        "deadline_seconds": deadline,
        "stats": {
            "completed": stats.completed,
            "lost": stats.lost,
            "terminal_backlog": stats.terminal_backlog,
            "wall_seconds": stats.wall_seconds,
            "seconds_per_completion": stats.seconds_per_completion(),
            "digest_mismatches": stats.digest_mismatches,
            "missed_work_fraction": stats.missed_work_fraction(),
            "severe_excess_fraction": stats.severe_excess_fraction(),
            "executed_epochs": stats.executed_epochs,
            "drain_epochs": stats.drain_epochs,
        },
        "stage_counts": dict(run.stage_counts),
        "reason_counts": dict(run.reason_counts),
        "elastic_epochs": run.elastic_epochs(),
        "support_epochs": run.support_epochs(),
        "backlog_elastic_epochs": run.backlog_elastic_epochs(),
        "failure_count": run.failure_count,
        "trace": trace,
    }


def invoke_json(executable: Path, arguments: list[str]) -> dict[str, Any]:
    env = dict(os.environ)
    env["PYTHONHASHSEED"] = "0"
    result = subprocess.run(
        [str(executable), str(Path(__file__).resolve()), *arguments],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError(f"no JSON from {executable}; stderr={result.stderr[-2000:]}")
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"invalid JSON from {executable}: {lines[-1]!r}; stderr={result.stderr[-2000:]}"
        ) from exc


def before_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["before_protective"],
        row["before_stage"],
        row["before_resolution"],
        row["before_step_resolution"],
        row["before_weaning_limit"],
        row["before_buffered"],
    )


def command_state(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["command_stage"],
        row["release_limit"],
        row["buffer_limit"],
        row["elastic_storage_active"],
    )


def first_epoch(common, by311, by312, predicate) -> int:
    for epoch in common:
        if predicate(by311[epoch], by312[epoch]):
            return epoch
    return -1


def boundary_cause(left: dict[str, Any], right: dict[str, Any]) -> str:
    if before_state(left) != before_state(right):
        return "CONTROLLER_STATE_ALREADY_DIVERGED"
    if left["released"] != right["released"]:
        return "RELEASE_COUNT_DIVERGENCE"
    if left["delivered"] != right["delivered"]:
        return "DELIVERED_COUNT_DIVERGENCE"

    severe_left = left["released"] > 0 and left["severe_margin"] >= 0.0
    severe_right = right["released"] > 0 and right["severe_margin"] >= 0.0
    if severe_left != severe_right:
        return "SEVERE_THRESHOLD_CROSSING"

    healthy_left = not severe_left and left["healthy_margin"] < 0.0
    healthy_right = not severe_right and right["healthy_margin"] < 0.0
    if healthy_left != healthy_right:
        return "HEALTHY_PAIN_THRESHOLD_CROSSING"
    return "OTHER_EVIDENCE_DIVERGENCE"


def compare_runs(
    run311: dict[str, Any],
    run312: dict[str, Any],
    *,
    seed: int,
    repetition: int,
    policy: str,
    interpreter_order: str,
    policy_order: str,
) -> dict[str, Any]:
    by311 = {int(row["epoch_index"]): row for row in run311["trace"]}
    by312 = {int(row["epoch_index"]): row for row in run312["trace"]}
    common = sorted(set(by311) & set(by312))

    structure_mismatches = sum(
        by311[epoch]["phase"] != by312[epoch]["phase"]
        or by311[epoch]["incoming"] != by312[epoch]["incoming"]
        for epoch in common
    )
    unmatched = sorted(set(by311) ^ set(by312))
    structure_mismatches += sum(
        (by311.get(epoch) or by312[epoch])["phase"] != "drain" for epoch in unmatched
    )

    first_controller = first_epoch(
        common, by311, by312, lambda a, b: before_state(a) != before_state(b)
    )
    first_command = first_epoch(
        common, by311, by312, lambda a, b: command_state(a) != command_state(b)
    )
    first_release = first_epoch(
        common, by311, by312, lambda a, b: a["released"] != b["released"]
    )
    first_delivered = first_epoch(
        common, by311, by312, lambda a, b: a["delivered"] != b["delivered"]
    )
    first_evidence = first_epoch(
        common,
        by311,
        by312,
        lambda a, b: a["evidence_class"] != b["evidence_class"],
    )
    first_storage = first_epoch(
        common,
        by311,
        by312,
        lambda a, b: a["elastic_storage_active"] != b["elastic_storage_active"],
    )

    cause = "NONE"
    boundary: dict[str, Any] = {
        "boundary_epoch": -1,
        "py311_released": -1,
        "py312_released": -1,
        "py311_delivered": -1,
        "py312_delivered": -1,
        "py311_miss_fraction": 0.0,
        "py312_miss_fraction": 0.0,
        "py311_severe_margin": 0.0,
        "py312_severe_margin": 0.0,
        "py311_pain": 0.0,
        "py312_pain": 0.0,
        "py311_healthy_margin": 0.0,
        "py312_healthy_margin": 0.0,
        "py311_elapsed_ratio": 0.0,
        "py312_elapsed_ratio": 0.0,
        "py311_stage": "NONE",
        "py312_stage": "NONE",
        "py311_backlog": -1,
        "py312_backlog": -1,
    }
    if first_evidence >= 0:
        left, right = by311[first_evidence], by312[first_evidence]
        cause = boundary_cause(left, right)
        boundary = {
            "boundary_epoch": first_evidence,
            "py311_released": left["released"],
            "py312_released": right["released"],
            "py311_delivered": left["delivered"],
            "py312_delivered": right["delivered"],
            "py311_miss_fraction": left["miss_fraction"],
            "py312_miss_fraction": right["miss_fraction"],
            "py311_severe_margin": left["severe_margin"],
            "py312_severe_margin": right["severe_margin"],
            "py311_pain": left["after_pain"],
            "py312_pain": right["after_pain"],
            "py311_healthy_margin": left["healthy_margin"],
            "py312_healthy_margin": right["healthy_margin"],
            "py311_elapsed_ratio": safe_ratio(
                left["elapsed_seconds"], left["deadline_seconds"]
            ),
            "py312_elapsed_ratio": safe_ratio(
                right["elapsed_seconds"], right["deadline_seconds"]
            ),
            "py311_stage": left["before_stage"],
            "py312_stage": right["before_stage"],
            "py311_backlog": left["before_buffered"],
            "py312_backlog": right["before_buffered"],
        }

    stats311, stats312 = run311["stats"], run312["stats"]
    return {
        "seed": seed,
        "repetition": repetition,
        "policy": policy,
        "interpreter_order": interpreter_order,
        "policy_order": policy_order,
        "completed_ratio": safe_ratio(stats312["completed"], stats311["completed"]),
        "lost_delta": stats312["lost"] - stats311["lost"],
        "seconds_ratio": safe_ratio(
            stats312["seconds_per_completion"], stats311["seconds_per_completion"]
        ),
        "continuous_missed_delta": (
            stats312["missed_work_fraction"] - stats311["missed_work_fraction"]
        ),
        "continuous_severe_delta": (
            stats312["severe_excess_fraction"] - stats311["severe_excess_fraction"]
        ),
        "elastic_epoch_delta": run312["elastic_epochs"] - run311["elastic_epochs"],
        "support_epoch_delta": run312["support_epochs"] - run311["support_epochs"],
        "backlog_elastic_delta": (
            run312["backlog_elastic_epochs"] - run311["backlog_elastic_epochs"]
        ),
        "failure_delta": run312["failure_count"] - run311["failure_count"],
        "evidence_mismatch": int(first_evidence >= 0),
        "boundary_cause": cause,
        "first_controller_mismatch": first_controller,
        "first_command_mismatch": first_command,
        "first_release_mismatch": first_release,
        "first_delivered_mismatch": first_delivered,
        "first_evidence_mismatch": first_evidence,
        "first_storage_mismatch": first_storage,
        "unpaired_tail_epochs": len(unmatched),
        "non_drain_structure_mismatches": structure_mismatches,
        "terminal_backlog_violations": int(stats311["terminal_backlog"] != 0)
        + int(stats312["terminal_backlog"] != 0),
        "digest_mismatches": stats311["digest_mismatches"]
        + stats312["digest_mismatches"],
        **boundary,
    }


NUMERIC_KEYS = (
    "completed_ratio",
    "lost_delta",
    "seconds_ratio",
    "continuous_missed_delta",
    "continuous_severe_delta",
    "elastic_epoch_delta",
    "support_epoch_delta",
    "backlog_elastic_delta",
    "failure_delta",
    "unpaired_tail_epochs",
)


def aggregate_seed(rows: list[dict[str, Any]]) -> dict[str, Any]:
    result = {key: float(median(float(row[key]) for row in rows)) for key in NUMERIC_KEYS}
    mismatch_repetitions = sum(int(row["evidence_mismatch"]) for row in rows)
    result["mismatch_repetitions"] = mismatch_repetitions
    result["stable_evidence_mismatch"] = int(mismatch_repetitions >= 3)
    return result


def med(rows: list[dict[str, Any]], key: str) -> float:
    return float(median(float(row[key]) for row in rows))


def sign(value: float) -> int:
    return int(value > 0.0) - int(value < 0.0)


def prevalence(rows: list[dict[str, Any]]) -> float:
    return sum(int(row["evidence_mismatch"]) for row in rows) / max(1, len(rows))


def dominant_cause(rows: list[dict[str, Any]]) -> tuple[str, int, int]:
    counts = Counter(
        str(row["boundary_cause"])
        for row in rows
        if int(row["evidence_mismatch"]) == 1
    )
    total = sum(counts.values())
    if total == 0:
        return "NONE", 0, 0
    cause, count = counts.most_common(1)[0]
    return (cause if count * 3 >= total * 2 else "MIXED", count, total)


def summarize_policy(
    policy: str,
    rows: list[dict[str, Any]],
    seed_rows: list[dict[str, Any]],
    integrity_ok: bool,
) -> dict[str, Any]:
    stable_seeds = sum(int(row["stable_evidence_mismatch"]) for row in seed_rows)
    cause, cause_count, cause_total = dominant_cause(rows)
    groups = {
        order: [row for row in rows if row["interpreter_order"] == order]
        for order in ("PY311_FIRST", "PY312_FIRST")
    }
    sign_flip = any(
        sign(med(groups["PY311_FIRST"], key))
        * sign(med(groups["PY312_FIRST"], key))
        < 0
        for key in (
            "lost_delta",
            "continuous_missed_delta",
            "elastic_epoch_delta",
            "failure_delta",
        )
    )
    prevalence_gap = abs(
        prevalence(groups["PY311_FIRST"]) - prevalence(groups["PY312_FIRST"])
    )
    order_sensitive = sign_flip or prevalence_gap >= ORDER_PREVALENCE_GAP

    if stable_seeds >= MIN_SEED_AGREEMENT and integrity_ok and not order_sensitive:
        classification = "same_host_boundary_reproduced"
    elif stable_seeds <= 2 and integrity_ok:
        classification = "same_host_boundary_not_reproduced"
    else:
        classification = "same_host_boundary_mixed"

    mismatch_rows = [row for row in rows if int(row["evidence_mismatch"]) == 1]
    median_first = (
        float(median(int(row["first_evidence_mismatch"]) for row in mismatch_rows))
        if mismatch_rows
        else -1.0
    )
    state_before_or_at = sum(
        int(row["first_controller_mismatch"]) >= 0
        and int(row["first_controller_mismatch"])
        <= int(row["first_evidence_mismatch"])
        for row in mismatch_rows
    )
    return {
        "policy": policy,
        "stable_mismatch_seeds": stable_seeds,
        "mismatching_pairs": len(mismatch_rows),
        "dominant_boundary_cause": cause,
        "dominant_cause_count": cause_count,
        "cause_total": cause_total,
        "interpreter_order_sensitive": order_sensitive,
        "interpreter_order_prevalence_gap": prevalence_gap,
        "classification": classification,
        "median_first_evidence_epoch": median_first,
        "controller_state_before_or_at_evidence_pairs": state_before_or_at,
        **{f"median_seed_{key}": med(seed_rows, key) for key in NUMERIC_KEYS},
    }


def cross_policy(summaries: dict[str, dict[str, Any]]) -> str:
    binary, incremental = summaries["binary"], summaries["incremental"]
    b_class, i_class = binary["classification"], incremental["classification"]
    if b_class == "same_host_boundary_reproduced" and i_class == "same_host_boundary_not_reproduced":
        return "binary_challenge_path_interpreter_sensitive"
    if (
        b_class == i_class == "same_host_boundary_reproduced"
        and binary["dominant_boundary_cause"] == incremental["dominant_boundary_cause"]
        and binary["dominant_boundary_cause"] not in ("NONE", "MIXED")
    ):
        return "shared_executor_boundary_interpreter_sensitive"
    if b_class == i_class == "same_host_boundary_not_reproduced":
        return "separate_host_placement_remains_likely_contributor"
    return "same_host_mixed_or_policy_specific"


def coordinator(args: argparse.Namespace) -> None:
    py311, py312 = Path(args.py311).resolve(), Path(args.py312).resolve()
    for executable in (py311, py312):
        if not executable.exists():
            raise FileNotFoundError(executable)

    cal311 = invoke_json(py311, ["--calibrate"])
    cal312 = invoke_json(py312, ["--calibrate"])
    shared_deadline = max(
        0.025,
        48.0 * float(median((cal311["median_task_seconds"], cal312["median_task_seconds"]))),
    )

    print("diagnostic=same_host_dual_interpreter_evidence_boundary_v0.42")
    print("same_host=true")
    print("controller_changes=false")
    print("policy_promotion=false")
    print("controllers_phase_blind=true")
    print(f"WORK_ROUNDS={WORK_ROUNDS}")
    print(f"PAIRED_REPETITIONS={PAIRED_REPETITIONS}")
    print(f"MIN_SEED_AGREEMENT={MIN_SEED_AGREEMENT}")
    print(f"CALIBRATION_SAMPLES={CALIBRATION_SAMPLES}")
    print(f"py311_task_seconds={cal311['median_task_seconds']:.9f}")
    print(f"py312_task_seconds={cal312['median_task_seconds']:.9f}")
    print(f"shared_deadline_seconds={shared_deadline:.9f}")

    executables = {"3.11": py311, "3.12": py312}
    pairs: list[dict[str, Any]] = []
    by_policy: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_seed_policy: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
    runs: list[dict[str, Any]] = []
    run_cells = 0
    config_mismatches = 0
    backlog_violations = 0
    digest_mismatches = 0

    for seed in SEEDS:
        for repetition in range(PAIRED_REPETITIONS):
            versions = ("3.11", "3.12") if (seed + repetition) % 2 == 0 else ("3.12", "3.11")
            policies = (
                ("binary", "incremental")
                if ((seed // 1000) + repetition) % 2 == 0
                else ("incremental", "binary")
            )
            interpreter_order = "PY311_FIRST" if versions[0] == "3.11" else "PY312_FIRST"
            policy_order = "BINARY_FIRST" if policies[0] == "binary" else "INCREMENTAL_FIRST"
            current: dict[tuple[str, str], dict[str, Any]] = {}

            for version in versions:
                for policy in policies:
                    payload = invoke_json(
                        executables[version],
                        [
                            "--worker",
                            "--seed",
                            str(seed),
                            "--repetition",
                            str(repetition),
                            "--policy",
                            policy,
                            "--rounds",
                            str(WORK_ROUNDS),
                            "--deadline",
                            repr(shared_deadline),
                        ],
                    )
                    payload["python_version"] = version
                    current[(version, policy)] = payload
                    runs.append(payload)
                    run_cells += 1
                    config_mismatches += int(payload["rounds"] != WORK_ROUNDS)
                    config_mismatches += int(float(payload["deadline_seconds"]) != shared_deadline)
                    backlog_violations += int(payload["stats"]["terminal_backlog"] != 0)
                    digest_mismatches += int(payload["stats"]["digest_mismatches"])

            for policy in POLICIES:
                row = compare_runs(
                    current[("3.11", policy)],
                    current[("3.12", policy)],
                    seed=seed,
                    repetition=repetition,
                    policy=policy,
                    interpreter_order=interpreter_order,
                    policy_order=policy_order,
                )
                pairs.append(row)
                by_policy[policy].append(row)
                by_seed_policy[(seed, policy)].append(row)
                print(
                    f"pair seed={seed} repetition={repetition} policy={policy} "
                    f"interpreter_order={interpreter_order} policy_order={policy_order} "
                    f"evidence_mismatch={row['evidence_mismatch']} cause={row['boundary_cause']} "
                    f"first_controller={row['first_controller_mismatch']} "
                    f"first_command={row['first_command_mismatch']} "
                    f"first_release={row['first_release_mismatch']} "
                    f"first_delivered={row['first_delivered_mismatch']} "
                    f"first_evidence={row['first_evidence_mismatch']} "
                    f"first_storage={row['first_storage_mismatch']} "
                    f"released={row['py311_released']}/{row['py312_released']} "
                    f"delivered={row['py311_delivered']}/{row['py312_delivered']} "
                    f"miss={row['py311_miss_fraction']:.6f}/{row['py312_miss_fraction']:.6f} "
                    f"pain={row['py311_pain']:.6f}/{row['py312_pain']:.6f} "
                    f"elapsed_ratio={row['py311_elapsed_ratio']:.6f}/{row['py312_elapsed_ratio']:.6f} "
                    f"lost_delta={row['lost_delta']} missed_delta={row['continuous_missed_delta']:.6f}"
                )

    expected_runs = len(SEEDS) * PAIRED_REPETITIONS * len(POLICIES) * len(VERSIONS)
    expected_pairs = len(SEEDS) * PAIRED_REPETITIONS * len(POLICIES)
    structure_mismatches = sum(int(row["non_drain_structure_mismatches"]) for row in pairs)
    complete_cells = run_cells == expected_runs and len(pairs) == expected_pairs
    integrity_ok = (
        backlog_violations == 0
        and digest_mismatches == 0
        and structure_mismatches == 0
        and config_mismatches == 0
        and complete_cells
    )

    seed_summaries = {
        policy: [aggregate_seed(by_seed_policy[(seed, policy)]) for seed in SEEDS]
        for policy in POLICIES
    }
    summaries = {
        policy: summarize_policy(policy, by_policy[policy], seed_summaries[policy], integrity_ok)
        for policy in POLICIES
    }
    final_interpretation = cross_policy(summaries)

    print("\n[same_host_dual_interpreter]")
    print(f"run_cells={run_cells}/{expected_runs}")
    print(f"same_policy_comparisons={len(pairs)}/{expected_pairs}")
    print(f"py311_task_seconds={cal311['median_task_seconds']:.9f}")
    print(f"py312_task_seconds={cal312['median_task_seconds']:.9f}")
    print(f"shared_deadline_seconds={shared_deadline:.9f}")
    for policy in POLICIES:
        summary = summaries[policy]
        print(
            f"policy={policy} stable_mismatch_seeds={summary['stable_mismatch_seeds']}/8 "
            f"mismatching_pairs={summary['mismatching_pairs']}/32 "
            f"dominant_boundary_cause={summary['dominant_boundary_cause']} "
            f"dominant_cause_count={summary['dominant_cause_count']}/{summary['cause_total']} "
            f"median_first_evidence_epoch={summary['median_first_evidence_epoch']:.3f} "
            f"controller_state_before_or_at_evidence_pairs="
            f"{summary['controller_state_before_or_at_evidence_pairs']} "
            f"interpreter_order_sensitive={str(summary['interpreter_order_sensitive']).lower()} "
            f"classification={summary['classification']}"
        )
        print(
            f"policy={policy} outcomes "
            f"median_seed_completed_ratio={summary['median_seed_completed_ratio']:.6f} "
            f"median_seed_lost_delta={summary['median_seed_lost_delta']:.6f} "
            f"median_seed_seconds_ratio={summary['median_seed_seconds_ratio']:.6f} "
            f"median_seed_continuous_missed_delta="
            f"{summary['median_seed_continuous_missed_delta']:.6f} "
            f"median_seed_continuous_severe_delta="
            f"{summary['median_seed_continuous_severe_delta']:.6f} "
            f"median_seed_elastic_epoch_delta={summary['median_seed_elastic_epoch_delta']:.6f} "
            f"median_seed_support_epoch_delta={summary['median_seed_support_epoch_delta']:.6f} "
            f"median_seed_backlog_elastic_delta="
            f"{summary['median_seed_backlog_elastic_delta']:.6f} "
            f"median_seed_failure_delta={summary['median_seed_failure_delta']:.6f}"
        )
        counts = Counter(
            str(row["boundary_cause"])
            for row in by_policy[policy]
            if int(row["evidence_mismatch"]) == 1
        )
        for cause in CAUSES:
            print(f"policy={policy} cause={cause} count={counts[cause]}")

    print(f"cross_policy_interpretation={final_interpretation}")
    print(f"terminal_backlog_violations={backlog_violations}")
    print(f"digest_mismatches={digest_mismatches}")
    print(f"non_drain_structure_mismatches={structure_mismatches}")
    print(f"shared_config_mismatches={config_mismatches}")
    print(f"complete_cells={str(complete_cells).lower()}")
    print(f"integrity_ok={str(integrity_ok).lower()}")
    print(f"diagnostic_complete={str(integrity_ok).lower()}")
    print(
        "passes_preregistered_acceptance=diagnostic_complete"
        if integrity_ok
        else "passes_preregistered_acceptance=blocked_by_integrity"
    )
    print(
        "interpretation=v0.42 compares unchanged controllers under CPython 3.11 and "
        "3.12 on one VM with fixed work rounds and one shared deadline, then classifies "
        "the first exact same-policy evidence boundary."
    )

    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(
                {
                    "diagnostic": "same_host_dual_interpreter_evidence_boundary_v0.42",
                    "calibration": {
                        "py311": cal311,
                        "py312": cal312,
                        "shared_deadline_seconds": shared_deadline,
                    },
                    "runs": runs,
                    "comparisons": pairs,
                    "seed_summaries": seed_summaries,
                    "policy_summaries": summaries,
                    "cross_policy_interpretation": final_interpretation,
                    "integrity": {
                        "run_cells": run_cells,
                        "expected_runs": expected_runs,
                        "comparisons": len(pairs),
                        "expected_pairs": expected_pairs,
                        "terminal_backlog_violations": backlog_violations,
                        "digest_mismatches": digest_mismatches,
                        "non_drain_structure_mismatches": structure_mismatches,
                        "shared_config_mismatches": config_mismatches,
                        "complete_cells": complete_cells,
                        "integrity_ok": integrity_ok,
                    },
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--calibrate", action="store_true")
    mode.add_argument("--worker", action="store_true")
    mode.add_argument("--coordinator", action="store_true")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--repetition", type=int, default=0)
    parser.add_argument("--policy", choices=POLICIES)
    parser.add_argument("--rounds", type=int, default=WORK_ROUNDS)
    parser.add_argument("--deadline", type=float)
    parser.add_argument("--py311")
    parser.add_argument("--py312")
    parser.add_argument("--json-output")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.calibrate:
        print(json.dumps(calibration_payload(), sort_keys=True))
        return
    if args.worker:
        if args.seed is None or args.policy is None or args.deadline is None:
            raise SystemExit("--worker requires --seed --policy --deadline")
        print(
            json.dumps(
                run_worker(
                    seed=args.seed,
                    repetition=args.repetition,
                    policy=args.policy,
                    rounds=args.rounds,
                    deadline=args.deadline,
                ),
                sort_keys=True,
            )
        )
        return
    if not args.py311 or not args.py312:
        raise SystemExit("--coordinator requires --py311 and --py312")
    coordinator(args)


if __name__ == "__main__":
    main()

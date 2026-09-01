from __future__ import annotations

import json
import math
import os
import subprocess
import sys
from pathlib import Path

from bardocompute.hardware_contract import (
    evaluate_trigram,
    pack_tx1_result,
    unpack_trigram_lines,
)

LANES = 71
BOARD_CLOCK_MHZ = 25
PLL_PROFILE_CLOCK_MHZ = 75
PLL_INPUT_DIV = 1
PLL_FEEDBACK_DIV = 3
PLL_OUTPUT_DIV = 8
SIGNATURE_SEED = 0x424152444F545831
EXPECTED_SIGNATURE = 0xF8CC45C1E3244A5A
MASK64 = 0xFFFFFFFFFFFFFFFF
REPO_ROOT = Path(__file__).resolve().parents[1]
CHECK_REPORT = REPO_ROOT / "fpga/ulx3s-85f/check_report.py"


def _payload_word(bundle: int) -> int:
    result = evaluate_trigram(unpack_trigram_lines(bundle))
    return (pack_tx1_result(result) << 9) | bundle


def _position_shifts(lane: int) -> tuple[int, int]:
    if not 0 <= lane < LANES:
        raise ValueError("lane is outside the ULX3S harness")
    if lane < 32:
        return 0, lane + 1
    if lane < 63:
        return 1, lane - 30
    return 2, lane - 60


def _position_term(payload: int, lane: int) -> int:
    shift_a, shift_b = _position_shifts(lane)
    return ((payload << shift_a) ^ (payload << shift_b)) & MASK64


def _cycle_fold(payloads: list[int]) -> int:
    value = 0
    for lane, payload in enumerate(payloads):
        value ^= _position_term(payload, lane)
    return value


def _rotate_left_one_64(value: int) -> int:
    return ((value << 1) & MASK64) | (value >> 63)


def _epoch_frame(epoch_position: int) -> tuple[int, int]:
    payloads = [
        _payload_word((epoch_position + lane) & 0x1FF)
        for lane in range(LANES)
    ]
    return epoch_position, _cycle_fold(payloads)


def test_ulx3s_epoch_signature_matches_rtl_constant() -> None:
    signature = SIGNATURE_SEED
    valid_outputs = 0
    policy_allows = 0

    for epoch_position in range(512):
        payloads = []
        for lane in range(LANES):
            bundle = (epoch_position + lane) & 0x1FF
            result = evaluate_trigram(unpack_trigram_lines(bundle))
            payloads.append(_payload_word(bundle))
            valid_outputs += int(result.valid)
            policy_allows += int(result.policy_allow)

        signature = (
            _rotate_left_one_64(signature)
            ^ _cycle_fold(payloads)
            ^ epoch_position
        )

    assert valid_outputs == 216 * LANES == 15_336
    assert policy_allows == 28 * LANES == 1_988
    assert signature == EXPECTED_SIGNATURE


def test_two_stage_ordered_fold_preserves_frame_order_and_signature() -> None:
    frames = [_epoch_frame(epoch_position) for epoch_position in range(512)]
    stage1: tuple[int, int] | None = None
    stage2: tuple[int, int] | None = None
    outputs: list[tuple[int, int]] = []

    for incoming in [*frames, None, None]:
        if stage2 is not None:
            outputs.append(stage2)
        stage2 = stage1
        stage1 = incoming

    assert [position for position, _ in outputs] == list(range(512))

    signature = SIGNATURE_SEED
    for epoch_position, fold in outputs:
        signature = _rotate_left_one_64(signature) ^ fold ^ epoch_position

    assert signature == EXPECTED_SIGNATURE


def test_position_coefficients_are_unique_and_detect_every_pair_swap() -> None:
    assert len({_position_shifts(lane) for lane in range(LANES)}) == LANES

    for epoch_position in (0, 137, 511):
        payloads = [
            _payload_word((epoch_position + lane) & 0x1FF)
            for lane in range(LANES)
        ]
        baseline = _cycle_fold(payloads)
        for left in range(LANES):
            for right in range(left + 1, LANES):
                swapped = payloads.copy()
                swapped[left], swapped[right] = swapped[right], swapped[left]
                assert _cycle_fold(swapped) != baseline


def test_each_lane_record_bit_changes_the_position_fold() -> None:
    payloads = [_payload_word(lane) for lane in range(LANES)]
    baseline = _cycle_fold(payloads)

    for lane in range(LANES):
        for bit in range(32):
            changed = payloads.copy()
            changed[lane] ^= 1 << bit
            assert _cycle_fold(changed) != baseline


def test_native_board_core_capacity_is_explicit_without_a_cpu_win_claim() -> None:
    fpga_core_mtrigrams_s = LANES * BOARD_CLOCK_MHZ
    raw_input_gbytes_s = fpga_core_mtrigrams_s * 9 / 8 / 1_000
    full_output_gbytes_s = fpga_core_mtrigrams_s * 23 / 8 / 1_000

    assert fpga_core_mtrigrams_s == 1_775
    assert raw_input_gbytes_s == 1.996875
    assert full_output_gbytes_s == 5.103125


def test_75mhz_pll_profile_has_a_frozen_clock_contract() -> None:
    pfd_mhz = BOARD_CLOCK_MHZ / PLL_INPUT_DIV
    vco_mhz = pfd_mhz * PLL_FEEDBACK_DIV * PLL_OUTPUT_DIV
    output_mhz = vco_mhz / PLL_OUTPUT_DIV

    assert pfd_mhz == 25
    assert vco_mhz == 600
    assert output_mhz == PLL_PROFILE_CLOCK_MHZ == 75
    assert PLL_PROFILE_CLOCK_MHZ == 3 * BOARD_CLOCK_MHZ


def test_75mhz_profile_remains_a_core_only_bandwidth_boundary() -> None:
    fpga_core_mtrigrams_s = LANES * PLL_PROFILE_CLOCK_MHZ
    raw_input_gbytes_s = fpga_core_mtrigrams_s * 9 / 8 / 1_000
    full_output_gbytes_s = fpga_core_mtrigrams_s * 23 / 8 / 1_000

    assert fpga_core_mtrigrams_s == 5_325
    assert raw_input_gbytes_s == 5.990625
    assert full_output_gbytes_s == 15.309375
    assert math.isclose(raw_input_gbytes_s + full_output_gbytes_s, 21.3)


def test_75mhz_build_lock_and_position_fold_boundaries_are_declared() -> None:
    makefile = (REPO_ROOT / "fpga/ulx3s-85f/Makefile").read_text(encoding="utf-8")
    harness = (
        REPO_ROOT / "fpga/ulx3s-85f/bardo_tx1_ulx3s_bench_75.sv"
    ).read_text(encoding="utf-8")
    ordered_fold = (
        REPO_ROOT / "fpga/ulx3s-85f/bardo_tx1_ordered_fold.sv"
    ).read_text(encoding="utf-8")

    for required in (
        "ecppll -i 25 -o 75",
        ".CLKI_DIV(1)",
        ".CLKFB_DIV(3)",
        ".CLKOP_DIV(8)",
        "bardo_tx1_ordered_fold.sv",
        "synth_ecp5 -top $(TOP_75)",
        "--freq 75",
        "core_mtrigrams_s=5325",
    ):
        assert required in makefile

    assert "hierarchy -check -top $(TOP_75)" not in makefile
    assert "if (!pll_locked)" in harness
    assert "reset_shift <= 8'h00" in harness
    assert ".clk(clk_75mhz)" in harness
    assert "EXPECTED_SIGNATURE = 64'hf8cc45c1e3244a5a" in harness
    assert "payload_epoch_position" in harness
    assert "bardo_tx1_ordered_fold ordered_fold" in harness
    assert ".in_epoch_position(payload_epoch_position)" in harness
    assert ".out_epoch_position(fold_epoch_position)" in harness
    assert "cycle_fold" not in harness
    assert "lane_position_term" in ordered_fold
    assert "group_fold_stage1_0" in ordered_fold
    assert "combined_fold_stage2" in ordered_fold
    assert "expected_lane_value[8:0]" in harness
    assert "cycle_xor" not in harness


def test_75mhz_dynamic_and_full_harness_simulations_are_evidence_bound() -> None:
    makefile = (REPO_ROOT / "fpga/ulx3s-85f/Makefile").read_text(encoding="utf-8")
    native_harness = (
        REPO_ROOT / "fpga/ulx3s-85f/bardo_tx1_ulx3s_bench.sv"
    ).read_text(encoding="utf-8")
    fold_tb = (
        REPO_ROOT / "fpga/ulx3s-85f/tb_bardo_tx1_ordered_fold.sv"
    ).read_text(encoding="utf-8")
    harness_tb = (
        REPO_ROOT / "fpga/ulx3s-85f/tb_bardo_tx1_ulx3s_bench_75.sv"
    ).read_text(encoding="utf-8")

    for required in (
        ".DELETE_ON_ERROR:",
        "sim-75:",
        "ordered-fold-sim.log",
        "harness-sim.log",
        "tb_bardo_tx1_ordered_fold.sv",
        "tb_bardo_tx1_ulx3s_bench_75.sv",
        "$(ORDERED_FOLD_SIM_LOG_75) $(HARNESS_SIM_LOG_75)",
        "nextpnr_report_sha256=",
        "$(REPORT_CHECK) $(REPORT) 25",
        "$(REPORT_CHECK) $(REPORT_75) 75",
    ):
        assert required in makefile

    assert "grep -E 'Max frequency|Device utilisation" not in makefile
    assert "vvp $(ORDERED_FOLD_SIM_75) > $(ORDERED_FOLD_SIM_LOG_75) 2>&1" in makefile
    assert "vvp $(HARNESS_SIM_75) > $(HARNESS_SIM_LOG_75) 2>&1" in makefile
    assert "vvp $(ORDERED_FOLD_SIM_75) 2>&1 | tee" not in makefile
    assert "vvp $(HARNESS_SIM_75) 2>&1 | tee" not in makefile
    assert "RTL := ../../rtl/bardo_tx1.sv $(TOP).sv" in makefile
    assert "bardo_tx1_ordered_fold" not in native_harness
    assert "changed frame epoch identity or order" in fold_tb
    assert "output differs from dynamic lane fold" in fold_tb
    assert "EXPECTED_SIGNATURE = 64'hf8cc45c1e3244a5a" in harness_tb
    assert "full harness changed ordered-fold epoch identity" in harness_tb
    assert "full harness did not produce the frozen self-test signature" in harness_tb


def test_failed_simulation_log_cannot_be_reused_by_make(tmp_path: Path) -> None:
    fpga_dir = REPO_ROOT / "fpga/ulx3s-85f"
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_vvp = fake_bin / "vvp"
    fake_vvp.write_text(
        "#!/bin/sh\nprintf '%s\\n' 'partial failed simulation'\nexit 1\n",
        encoding="utf-8",
    )
    fake_vvp.chmod(0o755)

    ordered_fold = tmp_path / "ordered_fold.sv"
    ordered_fold_tb = tmp_path / "ordered_fold_tb.sv"
    simulation = tmp_path / "simulation"
    simulation_log = tmp_path / "ordered-fold-sim.log"
    ordered_fold.write_text("// dependency\n", encoding="utf-8")
    ordered_fold_tb.write_text("// dependency\n", encoding="utf-8")
    simulation.write_text("placeholder\n", encoding="utf-8")

    command = [
        "make",
        "-f",
        str(fpga_dir / "Makefile"),
        str(simulation_log),
        f"ORDERED_FOLD_75={ordered_fold}",
        f"ORDERED_FOLD_TB_75={ordered_fold_tb}",
        f"ORDERED_FOLD_SIM_75={simulation}",
        f"ORDERED_FOLD_SIM_LOG_75={simulation_log}",
    ]
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    for _ in range(2):
        result = subprocess.run(
            command,
            cwd=fpga_dir,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert not simulation_log.exists()


def _nextpnr_report() -> dict[str, object]:
    return {
        "utilization": {
            "MULT18X18D": {"used": 0},
            "TRELLIS_COMB": {"used": 5927},
            "TRELLIS_FF": {"used": 1863},
        },
        "fmax": {
            "$glbnet$clk_75mhz": {
                "achieved": 90.09,
                "constraint": 75.002,
            }
        },
    }


def _run_report_check(
    tmp_path: Path,
    report: dict[str, object],
    expected_clock_mhz: float = 75.0,
) -> subprocess.CompletedProcess[str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    report_path = tmp_path / "nextpnr-report.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(CHECK_REPORT),
            str(report_path),
            str(expected_clock_mhz),
        ],
        check=False,
        capture_output=True,
        text=True,
    )


def test_report_check_accepts_finite_timing_and_integral_resources(
    tmp_path: Path,
) -> None:
    result = _run_report_check(tmp_path, _nextpnr_report())

    assert result.returncode == 0, result.stderr
    assert "resource_check=pass" in result.stdout


def test_report_check_rejects_boolean_and_non_integral_resources(
    tmp_path: Path,
) -> None:
    for index, bad_value in enumerate((True, 0.0, 1.5, "0")):
        report = _nextpnr_report()
        utilization = report["utilization"]
        assert isinstance(utilization, dict)
        utilization["MULT18X18D"] = {"used": bad_value}

        case_path = tmp_path / str(index)
        case_path.mkdir()
        result = _run_report_check(case_path, report)

        assert result.returncode == 1
        assert "must be an integer" in result.stderr
        assert "resource_check=fail" in result.stderr


def test_report_check_rejects_non_finite_timing(tmp_path: Path) -> None:
    for index, (field, bad_value) in enumerate(
        (("achieved", math.nan), ("constraint", math.inf))
    ):
        report = _nextpnr_report()
        fmax = report["fmax"]
        assert isinstance(fmax, dict)
        timing = fmax["$glbnet$clk_75mhz"]
        assert isinstance(timing, dict)
        timing[field] = bad_value

        case_path = tmp_path / str(index)
        case_path.mkdir()
        result = _run_report_check(case_path, report)

        assert result.returncode == 1
        assert f"{field!r} must be finite" in result.stderr
        assert "resource_check=fail" in result.stderr


def test_report_check_requires_exactly_one_expected_clock_constraint(
    tmp_path: Path,
) -> None:
    unrelated = _nextpnr_report()
    fmax = unrelated["fmax"]
    assert isinstance(fmax, dict)
    timing = fmax["$glbnet$clk_75mhz"]
    assert isinstance(timing, dict)
    timing["constraint"] = 25.0

    unrelated_result = _run_report_check(tmp_path / "unrelated", unrelated)
    assert unrelated_result.returncode == 1
    assert "expected exactly one fmax constraint matching 75 MHz, found 0" in (
        unrelated_result.stderr
    )

    duplicate = _nextpnr_report()
    duplicate_fmax = duplicate["fmax"]
    assert isinstance(duplicate_fmax, dict)
    duplicate_fmax["duplicate_clock"] = {
        "achieved": 80.0,
        "constraint": 75.0,
    }

    duplicate_result = _run_report_check(tmp_path / "duplicate", duplicate)
    assert duplicate_result.returncode == 1
    assert "expected exactly one fmax constraint matching 75 MHz, found 2" in (
        duplicate_result.stderr
    )

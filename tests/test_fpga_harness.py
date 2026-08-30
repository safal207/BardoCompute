from __future__ import annotations

import math
from pathlib import Path

from bardocompute.hardware_contract import evaluate_trigram, unpack_trigram_lines

LANES = 71
BOARD_CLOCK_MHZ = 25
PLL_PROFILE_CLOCK_MHZ = 75
PLL_INPUT_DIV = 1
PLL_FEEDBACK_DIV = 3
PLL_OUTPUT_DIV = 8
SIGNATURE_SEED = 0x424152444F545831
EXPECTED_SIGNATURE = 0xB0058CD5263C1FC3
REPO_ROOT = Path(__file__).resolve().parents[1]


def _payload_word(bundle: int) -> int:
    result = evaluate_trigram(unpack_trigram_lines(bundle))
    return (
        (int(result.valid) << 31)
        | (result.target_count << 29)
        | (int(result.any_transition) << 28)
        | (int(result.any_discontinuous) << 27)
        | (pack_settled(result.settled_lines) << 18)
        | (int(result.policy_allow) << 17)
        | (result.trigram_index << 9)
    )


def pack_settled(lines: tuple[int, int, int]) -> int:
    lower, middle, upper = lines
    return lower | (middle << 3) | (upper << 6)


def _rotate_left_one_64(value: int) -> int:
    return ((value << 1) & 0xFFFFFFFFFFFFFFFF) | (value >> 63)


def test_ulx3s_epoch_signature_matches_rtl_constant() -> None:
    signature = SIGNATURE_SEED
    valid_outputs = 0
    policy_allows = 0

    for epoch_position in range(512):
        cycle_xor = 0
        for lane in range(LANES):
            bundle = (epoch_position + lane) & 0x1FF
            result = evaluate_trigram(unpack_trigram_lines(bundle))
            cycle_xor ^= _payload_word(bundle)
            valid_outputs += int(result.valid)
            policy_allows += int(result.policy_allow)

        signature = _rotate_left_one_64(signature) ^ cycle_xor ^ epoch_position

    assert valid_outputs == 216 * LANES == 15_336
    assert policy_allows == 28 * LANES == 1_988
    assert signature == EXPECTED_SIGNATURE


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


def test_75mhz_build_and_lock_boundaries_are_declared() -> None:
    makefile = (REPO_ROOT / "fpga/ulx3s-85f/Makefile").read_text(encoding="utf-8")
    harness = (
        REPO_ROOT / "fpga/ulx3s-85f/bardo_tx1_ulx3s_bench_75.sv"
    ).read_text(encoding="utf-8")

    for required in (
        "ecppll -i 25 -o 75",
        ".CLKI_DIV(1)",
        ".CLKFB_DIV(3)",
        ".CLKOP_DIV(8)",
        "--freq 75",
        "core_mtrigrams_s=5325",
    ):
        assert required in makefile

    assert "if (!pll_locked)" in harness
    assert "reset_shift <= 8'h00" in harness
    assert ".clk(clk_75mhz)" in harness

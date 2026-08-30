from __future__ import annotations

from bardocompute.hardware_contract import evaluate_trigram, unpack_trigram_lines

LANES = 71
BOARD_CLOCK_MHZ = 25
SIGNATURE_SEED = 0x424152444F545831
EXPECTED_SIGNATURE = 0xB0058CD5263C1FC3


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


def test_board_core_capacity_is_explicit_without_a_cpu_win_claim() -> None:
    fpga_core_mtrigrams_s = LANES * BOARD_CLOCK_MHZ
    raw_input_gbytes_s = fpga_core_mtrigrams_s * 9 / 8 / 1_000
    full_output_gbytes_s = fpga_core_mtrigrams_s * 23 / 8 / 1_000

    assert fpga_core_mtrigrams_s == 1_775
    assert raw_input_gbytes_s == 1.996875
    assert full_output_gbytes_s == 5.103125

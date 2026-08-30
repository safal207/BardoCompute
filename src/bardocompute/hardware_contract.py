from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

from .packed import (
    PACKED_FALLING_CONTINUOUS,
    PACKED_FALLING_DISCONTINUOUS,
    PACKED_ONE,
    PACKED_RISING_CONTINUOUS,
    PACKED_RISING_DISCONTINUOUS,
    PACKED_ZERO,
    VALID_PACKED_CODES,
    packed_is_discontinuous,
    packed_is_transition,
    packed_settle,
    packed_target,
)

LINE_CODE_FROM_DIGIT: tuple[int, ...] = (
    PACKED_ZERO,
    PACKED_RISING_CONTINUOUS,
    PACKED_RISING_DISCONTINUOUS,
    PACKED_FALLING_CONTINUOUS,
    PACKED_FALLING_DISCONTINUOUS,
    PACKED_ONE,
)
LINE_DIGIT_FROM_CODE = {code: digit for digit, code in enumerate(LINE_CODE_FROM_DIGIT)}


@dataclass(frozen=True, slots=True)
class Tx1Result:
    """Bit-exact software contract for one BARDO-TX1 trigram lane.

    Lines are ordered lower, middle, upper. Invalid or reserved line codes are
    fail-closed: every derived field is zero and ``valid`` is false.
    """

    valid: bool
    trigram_index: int
    policy_allow: bool
    settled_lines: tuple[int, int, int]
    any_discontinuous: bool
    any_transition: bool
    target_count: int


def _require_three_bit(code: int) -> None:
    if not isinstance(code, int) or not 0 <= code <= 0b111:
        raise ValueError(f"line code must be a three-bit integer, got {code!r}")


def pack_trigram_lines(lower: int, middle: int, upper: int) -> int:
    """Pack three sparse 3-bit line codes into the RTL input ordering."""
    for code in (lower, middle, upper):
        _require_three_bit(code)
    return lower | (middle << 3) | (upper << 6)


def unpack_trigram_lines(bundle: int) -> tuple[int, int, int]:
    if not isinstance(bundle, int) or not 0 <= bundle <= 0x1FF:
        raise ValueError(f"trigram bundle must be a nine-bit integer, got {bundle!r}")
    return bundle & 0x7, (bundle >> 3) & 0x7, (bundle >> 6) & 0x7


def decode_trigram_index(index: int) -> tuple[int, int, int]:
    """Decode a dense radix-6 ordinal into lower/middle/upper line codes."""
    if not isinstance(index, int) or not 0 <= index < 216:
        raise ValueError(f"trigram index must be in [0, 215], got {index!r}")
    lower_digit = index % 6
    middle_digit = (index // 6) % 6
    upper_digit = index // 36
    return (
        LINE_CODE_FROM_DIGIT[lower_digit],
        LINE_CODE_FROM_DIGIT[middle_digit],
        LINE_CODE_FROM_DIGIT[upper_digit],
    )


def evaluate_trigram(lines: Sequence[int]) -> Tx1Result:
    """Evaluate the exact BARDO-TX1 v0.1 lane contract.

    The reference policy is the already-benchmarked joint predicate:

    * every line is valid;
    * no line is discontinuous;
    * at least two target bits are one;
    * at least one line is an actual transition.
    """
    if len(lines) != 3:
        raise ValueError(f"exactly three ordered line codes are required, got {len(lines)}")

    lower, middle, upper = lines
    for code in (lower, middle, upper):
        _require_three_bit(code)

    if any(code not in VALID_PACKED_CODES for code in (lower, middle, upper)):
        return Tx1Result(
            valid=False,
            trigram_index=0,
            policy_allow=False,
            settled_lines=(0, 0, 0),
            any_discontinuous=False,
            any_transition=False,
            target_count=0,
        )

    digits = tuple(LINE_DIGIT_FROM_CODE[code] for code in (lower, middle, upper))
    trigram_index = digits[0] + 6 * digits[1] + 36 * digits[2]
    any_discontinuous = any(
        packed_is_discontinuous(code) for code in (lower, middle, upper)
    )
    any_transition = any(packed_is_transition(code) for code in (lower, middle, upper))
    target_count = sum(packed_target(code) for code in (lower, middle, upper))
    policy_allow = not any_discontinuous and target_count >= 2 and any_transition

    return Tx1Result(
        valid=True,
        trigram_index=trigram_index,
        policy_allow=policy_allow,
        settled_lines=tuple(  # type: ignore[arg-type]
            packed_settle(code) for code in (lower, middle, upper)
        ),
        any_discontinuous=any_discontinuous,
        any_transition=any_transition,
        target_count=target_count,
    )


def evaluate_lanes(bundles: Iterable[Sequence[int]]) -> tuple[Tx1Result, ...]:
    """Reference behavior for the parameterized parallel RTL lanes."""
    return tuple(evaluate_trigram(bundle) for bundle in bundles)

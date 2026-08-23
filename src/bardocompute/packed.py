from __future__ import annotations

# Three-bit layout:
#
#   bit 2: source value
#   bit 1: target value
#   bit 0: discontinuity flag
#
# v0.2 uses six of the eight possible codes. The two reserved codes represent
# same-value discontinuous events, which are intentionally deferred.

PACKED_ZERO = 0b000
PACKED_RISING_CONTINUOUS = 0b010
PACKED_RISING_DISCONTINUOUS = 0b011
PACKED_FALLING_CONTINUOUS = 0b100
PACKED_FALLING_DISCONTINUOUS = 0b101
PACKED_ONE = 0b110

VALID_PACKED_CODES = frozenset(
    {
        PACKED_ZERO,
        PACKED_RISING_CONTINUOUS,
        PACKED_RISING_DISCONTINUOUS,
        PACKED_FALLING_CONTINUOUS,
        PACKED_FALLING_DISCONTINUOUS,
        PACKED_ONE,
    }
)

RESERVED_PACKED_CODES = frozenset({0b001, 0b111})


def pack_line(source: int, target: int, discontinuous: bool = False) -> int:
    """Pack v0.2 line semantics into three bits."""
    if source not in (0, 1) or target not in (0, 1):
        raise ValueError("source and target must be 0 or 1")
    if source == target and discontinuous:
        raise ValueError("same-value discontinuous events are reserved in v0.2")

    return (source << 2) | (target << 1) | int(discontinuous)


def validate_packed_line(code: int) -> int:
    if code not in VALID_PACKED_CODES:
        raise ValueError(f"invalid or reserved packed Bardo line code: {code:#05b}")
    return code


def packed_source(code: int) -> int:
    validate_packed_line(code)
    return (code >> 2) & 1


def packed_target(code: int) -> int:
    validate_packed_line(code)
    return (code >> 1) & 1


def packed_is_discontinuous(code: int) -> bool:
    validate_packed_line(code)
    return bool(code & 1)


def packed_is_transition(code: int) -> bool:
    return packed_source(code) != packed_target(code)


def packed_settle(code: int) -> int:
    """Resolve a packed transition to its target stable packed state."""
    target = packed_target(code)
    return PACKED_ONE if target else PACKED_ZERO

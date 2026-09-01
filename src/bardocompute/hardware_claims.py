"""Evidence gate for BARDO-TX1 CPU-competition claims.

The module deliberately separates three different statements:

* the RTL is correct and place-and-route succeeds;
* the on-chip datapath has a theoretical throughput roofline;
* a physical, host-fed implementation beats a CPU end to end.

Only the last statement is a CPU-competition claim. The gate fails closed when
required evidence is missing, inconsistent, or not bound to the measured
bitstream.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence

SCHEMA_VERSION = 1
SEMANTIC_CONTRACT = "bardo-tx1-v0.1"
INPUT_BITS_PER_TRIGRAM = 9
OUTPUT_BITS_PER_TRIGRAM = 23
COMPETITION_THRESHOLD = 2.0
EQUAL_THROUGHPUT_REL_TOLERANCE = 0.05
EXPECTED_SELF_TEST_SIGNATURE = "0xf8cc45c1e3244a5a"
FPGA_PROFILE_CONTRACTS: Mapping[str, Mapping[str, Any]] = {
    "native_25mhz": {
        "top": "bardo_tx1_ulx3s_bench",
        "bitstream": "bardo_tx1_ulx3s_bench.bit",
        "clock_mhz": 25.0,
        "expected_self_test_signature": EXPECTED_SELF_TEST_SIGNATURE,
    },
    "pll_25_to_75mhz": {
        "top": "bardo_tx1_ulx3s_bench_75",
        "bitstream": "bardo_tx1_ulx3s_bench_75.bit",
        "clock_mhz": 75.0,
        "expected_self_test_signature": EXPECTED_SELF_TEST_SIGNATURE,
    },
}

_KEY_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SIGNATURE_RE = re.compile(r"^0x[0-9a-fA-F]{16}$")


class EvidenceError(ValueError):
    """Raised when evidence is malformed or internally inconsistent."""


def parse_key_value_text(text: str, *, source: str = "evidence") -> dict[str, str]:
    """Parse one ``key=value`` record per line, rejecting duplicates."""

    result: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise EvidenceError(
                f"{source}:{line_number}: expected key=value, got {raw_line!r}"
            )
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not _KEY_RE.fullmatch(key):
            raise EvidenceError(f"{source}:{line_number}: invalid key {key!r}")
        if not value:
            raise EvidenceError(f"{source}:{line_number}: empty value for {key}")
        if key in result:
            raise EvidenceError(f"{source}:{line_number}: duplicate key {key}")
        result[key] = value
    if not result:
        raise EvidenceError(f"{source}: no evidence records found")
    return result


def parse_sha256_manifest(
    text: str, *, source: str = "SHA256SUMS"
) -> dict[str, str]:
    """Parse a sha256sum manifest, rejecting unsafe or duplicate paths."""

    manifest: dict[str, str] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            raise EvidenceError(f"{source}:{line_number}: malformed checksum line")
        digest, filename = parts
        digest = digest.lower()
        filename = filename.lstrip("*").strip()
        if not _SHA256_RE.fullmatch(digest):
            raise EvidenceError(f"{source}:{line_number}: invalid SHA-256 digest")
        if not filename:
            raise EvidenceError(f"{source}:{line_number}: empty filename")
        pure_path = PurePosixPath(filename)
        if (
            "\x00" in filename
            or "\\" in filename
            or not pure_path.parts
            or pure_path.is_absolute()
            or re.match(r"^[A-Za-z]:", filename)
            or any(part in {".", ".."} for part in pure_path.parts)
            or pure_path.as_posix() != filename
        ):
            raise EvidenceError(
                f"{source}:{line_number}: unsafe manifest path {filename!r}"
            )
        if filename in manifest:
            raise EvidenceError(f"{source}:{line_number}: duplicate filename {filename!r}")
        manifest[filename] = digest
    if not manifest:
        raise EvidenceError(f"{source}: no checksum records found")
    return manifest


def _manifest_digest_for_basename(
    manifest: Mapping[str, str], basename: str, *, source: str
) -> tuple[str, str]:
    if PurePosixPath(basename).name != basename or not basename:
        raise EvidenceError(f"{source}: expected manifest basename is invalid")
    candidates = [
        (filename, digest)
        for filename, digest in manifest.items()
        if PurePosixPath(filename).name == basename
    ]
    if len(candidates) != 1:
        raise EvidenceError(
            f"{source}: expected exactly one manifest entry for {basename!r}, "
            f"found {len(candidates)}"
        )
    return candidates[0]


def parse_sha256s_text(
    text: str,
    *,
    source: str = "SHA256SUMS",
    expected_filename: str | None = None,
) -> str:
    """Return the profile-selected bitstream digest from a checksum manifest."""

    manifest = parse_sha256_manifest(text, source=source)
    if expected_filename is not None:
        if not expected_filename.endswith(".bit"):
            raise EvidenceError(f"{source}: expected bitstream filename is invalid")
        _, digest = _manifest_digest_for_basename(
            manifest, expected_filename, source=source
        )
        return digest

    bitstream_digests = [
        digest for filename, digest in manifest.items() if filename.endswith(".bit")
    ]
    if len(bitstream_digests) != 1:
        raise EvidenceError(
            f"{source}: expected exactly one .bit digest, found {len(bitstream_digests)}"
        )
    return bitstream_digests[0]


def _read_input_bytes(path: Path, *, source: str) -> bytes:
    """Read one direct regular-file input without following a leaf symlink."""

    try:
        if path.is_symlink():
            raise EvidenceError(f"{source}: direct symlink input is not allowed: {path}")
        if not path.is_file():
            raise EvidenceError(f"{source}: input is not a regular file: {path}")
        return path.read_bytes()
    except EvidenceError:
        raise
    except OSError as exc:
        raise EvidenceError(f"{source}: cannot read {path}: {exc}") from exc


def _decode_utf8(data: bytes, *, path: Path, source: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EvidenceError(f"{source}: {path} is not valid UTF-8: {exc}") from exc


def _verify_manifest_bytes(
    manifest: Mapping[str, str],
    path: Path,
    data: bytes,
    *,
    source: str,
    expected_filename: str | None = None,
) -> str:
    basename = expected_filename if expected_filename is not None else path.name
    if expected_filename is not None and path.name != expected_filename:
        raise EvidenceError(
            f"{source}: input basename {path.name!r} does not match selected profile "
            f"bitstream {expected_filename!r}"
        )
    filename, expected = _manifest_digest_for_basename(
        manifest, basename, source=source
    )
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise EvidenceError(
            f"{source}: SHA-256 mismatch for {filename!r}: "
            f"expected {expected}, got {actual}"
        )
    return actual


def verify_manifest_path(
    manifest: Mapping[str, str],
    path: Path,
    *,
    source: str,
    expected_filename: str | None = None,
) -> str:
    """Verify a required claim input against exactly one manifest entry."""

    data = _read_input_bytes(path, source=source)
    return _verify_manifest_bytes(
        manifest,
        path,
        data,
        source=source,
        expected_filename=expected_filename,
    )


def _required(mapping: Mapping[str, Any], key: str, *, source: str) -> Any:
    if key not in mapping:
        raise EvidenceError(f"{source}: missing required field {key!r}")
    return mapping[key]


def _positive_float(value: Any, *, field: str, source: str) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"{source}: {field} must be a number") from exc
    if not math.isfinite(parsed) or parsed <= 0.0:
        raise EvidenceError(f"{source}: {field} must be finite and > 0")
    return parsed


def _nonnegative_int(value: Any, *, field: str, source: str) -> int:
    if isinstance(value, bool):
        raise EvidenceError(f"{source}: {field} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EvidenceError(f"{source}: {field} must be an integer") from exc
    if str(parsed) != str(value).strip() and not isinstance(value, int):
        raise EvidenceError(f"{source}: {field} must be an integer")
    if parsed < 0:
        raise EvidenceError(f"{source}: {field} must be >= 0")
    return parsed


def _positive_int(value: Any, *, field: str, source: str) -> int:
    parsed = _nonnegative_int(value, field=field, source=source)
    if parsed == 0:
        raise EvidenceError(f"{source}: {field} must be > 0")
    return parsed


def _strict_bool(value: Any, *, field: str, source: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
    raise EvidenceError(f"{source}: {field} must be true or false")


def _optional_positive_float(
    mapping: Mapping[str, Any], key: str, *, source: str
) -> float | None:
    if key not in mapping or mapping[key] is None:
        return None
    return _positive_float(mapping[key], field=key, source=source)


def _validate_fpga_profile(fpga_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Bind declared FPGA evidence to one immutable build-profile contract."""

    source = "FPGA evidence"
    profile = str(_required(fpga_evidence, "profile", source=source)).strip()
    contract = FPGA_PROFILE_CONTRACTS.get(profile)
    if contract is None:
        raise EvidenceError(f"{source}: unsupported profile {profile!r}")

    top = str(_required(fpga_evidence, "top", source=source)).strip()
    bitstream = str(_required(fpga_evidence, "bitstream", source=source)).strip()
    clock_mhz = _positive_float(
        _required(fpga_evidence, "clock_mhz", source=source),
        field="clock_mhz",
        source=source,
    )
    expected_signature = str(
        _required(fpga_evidence, "expected_self_test_signature", source=source)
    ).strip().lower()

    if top != contract["top"]:
        raise EvidenceError(f"{source}: top {top!r} does not match profile {profile!r}")
    if bitstream != contract["bitstream"]:
        raise EvidenceError(
            f"{source}: bitstream {bitstream!r} does not match profile {profile!r}"
        )
    if not math.isclose(
        clock_mhz,
        float(contract["clock_mhz"]),
        rel_tol=0.0,
        abs_tol=1e-9,
    ):
        raise EvidenceError(
            f"{source}: clock_mhz={clock_mhz:.6g} does not match profile {profile!r}"
        )
    if not _SIGNATURE_RE.fullmatch(expected_signature):
        raise EvidenceError(
            f"{source}: expected_self_test_signature must be a 64-bit "
            "0x-prefixed value"
        )
    if expected_signature != contract["expected_self_test_signature"]:
        raise EvidenceError(
            f"{source}: expected_self_test_signature does not match profile {profile!r}"
        )

    return {
        "profile": profile,
        "top": top,
        "bitstream": bitstream,
        "clock_mhz": clock_mhz,
        "expected_self_test_signature": expected_signature,
    }


def _nextpnr_summary(report: Mapping[str, Any], requested_clock_mhz: float) -> dict[str, Any]:
    source = "nextpnr report"
    fmax = _required(report, "fmax", source=source)
    utilization = _required(report, "utilization", source=source)
    if not isinstance(fmax, Mapping) or not fmax:
        raise EvidenceError(f"{source}: fmax must be a non-empty object")
    if not isinstance(utilization, Mapping):
        raise EvidenceError(f"{source}: utilization must be an object")

    clocks: list[dict[str, Any]] = []
    matching_constraint = False
    for name, raw_timing in fmax.items():
        if not isinstance(raw_timing, Mapping):
            raise EvidenceError(f"{source}: malformed timing for clock {name!r}")
        achieved = _positive_float(
            _required(raw_timing, "achieved", source=source),
            field=f"fmax.{name}.achieved",
            source=source,
        )
        constraint = _positive_float(
            _required(raw_timing, "constraint", source=source),
            field=f"fmax.{name}.constraint",
            source=source,
        )
        if achieved + 1e-9 < constraint:
            raise EvidenceError(
                f"{source}: clock {name!r} achieved {achieved:.3f} MHz below "
                f"{constraint:.3f} MHz constraint"
            )
        # nextpnr serializes the requested clock after period/frequency
        # quantization, so the JSON constraint can differ by a few tens of ppm.
        # Keep the tolerance narrow enough that a distinct clock profile fails.
        if math.isclose(
            constraint,
            requested_clock_mhz,
            rel_tol=1e-4,
            abs_tol=1e-6,
        ):
            matching_constraint = True
        clocks.append(
            {
                "name": str(name),
                "achieved_mhz": achieved,
                "constraint_mhz": constraint,
            }
        )
    if not matching_constraint:
        raise EvidenceError(
            f"{source}: no clock constraint matches evidence clock_mhz="
            f"{requested_clock_mhz:.6g}"
        )

    def used(resource: str) -> int:
        raw = utilization.get(resource)
        if not isinstance(raw, Mapping):
            raise EvidenceError(f"{source}: missing utilization.{resource}")
        return _nonnegative_int(
            _required(raw, "used", source=source),
            field=f"utilization.{resource}.used",
            source=source,
        )

    resources = {
        "trellis_comb_used": used("TRELLIS_COMB"),
        "trellis_ff_used": used("TRELLIS_FF"),
        "dp16kd_used": used("DP16KD"),
        "mult18x18d_used": used("MULT18X18D"),
    }
    if resources["mult18x18d_used"] != 0:
        raise EvidenceError(
            "nextpnr report: BARDO-TX1 radix constants unexpectedly consume DSPs"
        )

    return {
        "clocks": clocks,
        "minimum_achieved_mhz": min(clock["achieved_mhz"] for clock in clocks),
        **resources,
    }


def _validate_measurement_identity(
    measurement: Mapping[str, Any],
    *,
    board: str,
    bitstream_sha256: str,
) -> str:
    source = "physical measurement"
    schema_version = _positive_int(
        _required(measurement, "schema_version", source=source),
        field="schema_version",
        source=source,
    )
    if schema_version != SCHEMA_VERSION:
        raise EvidenceError(
            f"{source}: unsupported schema_version={schema_version}; expected {SCHEMA_VERSION}"
        )

    mode = str(_required(measurement, "mode", source=source))
    if mode not in {"on_chip_self_test", "host_stream"}:
        raise EvidenceError(f"{source}: mode must be on_chip_self_test or host_stream")
    measured_board = str(_required(measurement, "board", source=source))
    if measured_board != board:
        raise EvidenceError(
            f"{source}: board {measured_board!r} does not match build board {board!r}"
        )
    semantic_contract = str(
        _required(measurement, "semantic_contract", source=source)
    )
    if semantic_contract != SEMANTIC_CONTRACT:
        raise EvidenceError(
            f"{source}: semantic_contract must be {SEMANTIC_CONTRACT!r}"
        )
    measured_digest = str(
        _required(measurement, "bitstream_sha256", source=source)
    ).lower()
    if not _SHA256_RE.fullmatch(measured_digest):
        raise EvidenceError(f"{source}: bitstream_sha256 is not a SHA-256 digest")
    if measured_digest != bitstream_sha256:
        raise EvidenceError(
            f"{source}: bitstream_sha256 does not match the CI bitstream manifest"
        )
    correct = _strict_bool(
        _required(measurement, "correct", source=source),
        field="correct",
        source=source,
    )
    if not correct:
        raise EvidenceError(f"{source}: correctness failed; no performance claim is admissible")
    return mode


def build_claim_report(
    *,
    fpga_evidence: Mapping[str, Any],
    cpu_evidence: Mapping[str, Any],
    nextpnr_report: Mapping[str, Any],
    bitstream_sha256: str,
    measurement: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate evidence and return a machine-readable claim decision."""

    fpga_source = "FPGA evidence"
    cpu_source = "CPU evidence"
    profile_contract = _validate_fpga_profile(fpga_evidence)

    board = str(_required(fpga_evidence, "board", source=fpga_source))
    lanes = _positive_int(
        _required(fpga_evidence, "lanes", source=fpga_source),
        field="lanes",
        source=fpga_source,
    )
    clock_mhz = float(profile_contract["clock_mhz"])
    reported_core = _positive_float(
        _required(fpga_evidence, "core_mtrigrams_s", source=fpga_source),
        field="core_mtrigrams_s",
        source=fpga_source,
    )
    expected_core = lanes * clock_mhz
    if not math.isclose(reported_core, expected_core, rel_tol=1e-9, abs_tol=1e-6):
        raise EvidenceError(
            f"{fpga_source}: core_mtrigrams_s={reported_core:.6g} does not equal "
            f"lanes*clock_mhz={expected_core:.6g}"
        )

    declared_status = str(
        _required(fpga_evidence, "cpu_competition_status", source=fpga_source)
    ).strip().lower()
    if declared_status != "unresolved":
        raise EvidenceError(
            f"{fpga_source}: generated build evidence must remain "
            "cpu_competition_status=unresolved; only the claim gate may promote it"
        )
    claim_boundary = str(
        _required(fpga_evidence, "claim_boundary", source=fpga_source)
    ).strip()
    if not claim_boundary:
        raise EvidenceError(f"{fpga_source}: claim_boundary must not be empty")

    cpu_correct = _strict_bool(
        _required(cpu_evidence, "correct", source=cpu_source),
        field="correct",
        source=cpu_source,
    )
    if not cpu_correct:
        raise EvidenceError(f"{cpu_source}: CPU semantic baseline is not correct")
    best_cpu = _positive_float(
        _required(cpu_evidence, "best_cpu_mtrigrams_s", source=cpu_source),
        field="best_cpu_mtrigrams_s",
        source=cpu_source,
    )
    cpu_boundary = str(
        _required(cpu_evidence, "comparison_boundary", source=cpu_source)
    ).strip()
    if not cpu_boundary:
        raise EvidenceError(f"{cpu_source}: comparison_boundary must not be empty")

    if not _SHA256_RE.fullmatch(bitstream_sha256):
        raise EvidenceError("bitstream SHA-256 is malformed")

    implementation = _nextpnr_summary(nextpnr_report, clock_mhz)
    core_ratio = reported_core / best_cpu
    input_gb_s = reported_core * INPUT_BITS_PER_TRIGRAM / 8000.0
    output_gb_s = reported_core * OUTPUT_BITS_PER_TRIGRAM / 8000.0

    status = "CORE_ROOFLINE_ONLY"
    claim_allowed = False
    reasons = [
        "The FPGA number is lanes × clock, generated and reduced on chip.",
        "No physical host-fed end-to-end measurement was supplied.",
    ]
    physical: dict[str, Any] | None = None

    if measurement is not None:
        mode = _validate_measurement_identity(
            measurement,
            board=board,
            bitstream_sha256=bitstream_sha256,
        )
        source = "physical measurement"
        if mode == "on_chip_self_test":
            signature = str(
                _required(measurement, "self_test_signature", source=source)
            )
            if not _SIGNATURE_RE.fullmatch(signature):
                raise EvidenceError(
                    f"{source}: self_test_signature must be a 64-bit 0x-prefixed value"
                )
            signature = signature.lower()
            if signature != profile_contract["expected_self_test_signature"]:
                raise EvidenceError(
                    f"{source}: self_test_signature does not match the selected "
                    "FPGA profile"
                )
            epochs = _positive_int(
                _required(measurement, "completed_epochs", source=source),
                field="completed_epochs",
                source=source,
            )
            status = "PHYSICAL_SELF_TEST_ONLY"
            reasons = [
                "The exact CI bitstream passed its on-board self-test.",
                "Inputs and reduction remained on chip, so host/device cost is still unmeasured.",
            ]
            physical = {
                "mode": mode,
                "self_test_signature": signature,
                "completed_epochs": epochs,
            }
        else:
            includes_transfer = _strict_bool(
                _required(measurement, "includes_host_device_transfer", source=source),
                field="includes_host_device_transfer",
                source=source,
            )
            includes_setup = _strict_bool(
                _required(measurement, "includes_setup_overhead", source=source),
                field="includes_setup_overhead",
                source=source,
            )
            same_workload = _strict_bool(
                _required(measurement, "same_workload_as_cpu", source=source),
                field="same_workload_as_cpu",
                source=source,
            )
            same_host = _strict_bool(
                _required(measurement, "same_host_cpu_baseline", source=source),
                field="same_host_cpu_baseline",
                source=source,
            )
            workload_kind = str(
                _required(measurement, "workload_kind", source=source)
            )
            if workload_kind not in {"synthetic", "real"}:
                raise EvidenceError(f"{source}: workload_kind must be synthetic or real")
            workload = str(_required(measurement, "workload", source=source)).strip()
            if not workload:
                raise EvidenceError(f"{source}: workload must not be empty")
            output_mode = str(_required(measurement, "output_mode", source=source))
            if output_mode not in {"full_results", "reduced_verdicts"}:
                raise EvidenceError(
                    f"{source}: output_mode must be full_results or reduced_verdicts"
                )

            items = _positive_int(
                _required(measurement, "items", source=source),
                field="items",
                source=source,
            )
            elapsed_seconds = _positive_float(
                _required(measurement, "elapsed_seconds", source=source),
                field="elapsed_seconds",
                source=source,
            )
            input_bytes = _nonnegative_int(
                _required(measurement, "input_bytes", source=source),
                field="input_bytes",
                source=source,
            )
            output_bytes = _nonnegative_int(
                _required(measurement, "output_bytes", source=source),
                field="output_bytes",
                source=source,
            )
            minimum_input_bytes = math.ceil(items * INPUT_BITS_PER_TRIGRAM / 8)
            if input_bytes < minimum_input_bytes:
                raise EvidenceError(
                    f"{source}: input_bytes={input_bytes} is below the 9-bit information minimum "
                    f"of {minimum_input_bytes}"
                )
            if output_mode == "full_results":
                minimum_output_bytes = math.ceil(items * OUTPUT_BITS_PER_TRIGRAM / 8)
                if output_bytes < minimum_output_bytes:
                    raise EvidenceError(
                        f"{source}: output_bytes={output_bytes} is below the 23-bit full-result "
                        f"minimum of {minimum_output_bytes}"
                    )

            measured_throughput = items / elapsed_seconds / 1_000_000.0
            measured_cpu = _optional_positive_float(
                measurement, "cpu_mtrigrams_s", source=source
            )
            board_power = _optional_positive_float(
                measurement, "board_power_w", source=source
            )
            cpu_power = _optional_positive_float(
                measurement, "cpu_power_w", source=source
            )
            fpga_p99_ns = _optional_positive_float(
                measurement, "fpga_p99_ns", source=source
            )
            cpu_p99_ns = _optional_positive_float(
                measurement, "cpu_p99_ns", source=source
            )
            throughput_relative_gap: float | None = None
            equal_throughput_verified = False
            if measured_cpu is not None:
                throughput_relative_gap = abs(
                    measured_throughput - measured_cpu
                ) / max(measured_throughput, measured_cpu)
                equal_throughput_verified = (
                    throughput_relative_gap
                    <= EQUAL_THROUGHPUT_REL_TOLERANCE + 1e-12
                )

            if "equal_throughput" in measurement:
                declared_equal_throughput = _strict_bool(
                    measurement["equal_throughput"],
                    field="equal_throughput",
                    source=source,
                )
                if declared_equal_throughput != equal_throughput_verified:
                    raise EvidenceError(
                        f"{source}: equal_throughput={declared_equal_throughput} "
                        "contradicts measured FPGA/CPU throughput"
                    )

            energy_ratio: float | None = None
            if measured_cpu is not None and board_power is not None and cpu_power is not None:
                energy_ratio = (
                    measured_throughput / board_power
                ) / (measured_cpu / cpu_power)

            latency_ratio: float | None = None
            if (
                fpga_p99_ns is not None
                and cpu_p99_ns is not None
                and equal_throughput_verified
            ):
                latency_ratio = cpu_p99_ns / fpga_p99_ns

            identity_complete = (
                includes_transfer
                and includes_setup
                and same_workload
                and same_host
                and workload_kind == "real"
                and measured_cpu is not None
                and equal_throughput_verified
            )
            passes_energy = (
                energy_ratio is not None
                and energy_ratio + 1e-12 >= COMPETITION_THRESHOLD
            )
            passes_latency = (
                latency_ratio is not None
                and latency_ratio + 1e-12 >= COMPETITION_THRESHOLD
            )
            claim_allowed = identity_complete and passes_energy and passes_latency
            status = (
                "CPU_COMPETITIVE_PASS" if claim_allowed else "END_TO_END_NOT_PROVEN"
            )

            reasons = []
            if claim_allowed:
                reasons.append(
                    f"End-to-end throughput per watt is {energy_ratio:.3f}× the same-host CPU."
                )
                reasons.append(
                    f"p99 latency is {latency_ratio:.3f}× better at verified equal throughput."
                )
            else:
                if not includes_transfer:
                    reasons.append("Host/device transfer is excluded from elapsed time.")
                if not includes_setup:
                    reasons.append("Setup overhead is excluded from elapsed time.")
                if not same_workload:
                    reasons.append("FPGA and CPU did not run the same workload.")
                if not same_host:
                    reasons.append("The CPU baseline was not measured on the same host.")
                if workload_kind != "real":
                    reasons.append("The supplied workload is synthetic, not a real workload gate.")
                if measured_cpu is None:
                    reasons.append("A same-run CPU throughput measurement is missing.")
                elif not equal_throughput_verified:
                    reasons.append(
                        "FPGA and CPU throughput differ beyond the "
                        f"{EQUAL_THROUGHPUT_REL_TOLERANCE:.0%} equal-throughput tolerance."
                    )
                if energy_ratio is None:
                    reasons.append("A complete throughput-per-watt comparison is missing.")
                elif not passes_energy:
                    reasons.append(
                        f"Throughput per watt ratio {energy_ratio:.3f}× is below {COMPETITION_THRESHOLD:.1f}×."
                    )
                if latency_ratio is None:
                    reasons.append("A p99 latency comparison at equal throughput is missing.")
                elif not passes_latency:
                    reasons.append(
                        f"p99 latency ratio {latency_ratio:.3f}× is below {COMPETITION_THRESHOLD:.1f}×."
                    )

            physical = {
                "mode": mode,
                "workload": workload,
                "workload_kind": workload_kind,
                "output_mode": output_mode,
                "items": items,
                "elapsed_seconds": elapsed_seconds,
                "throughput_mtrigrams_s": measured_throughput,
                "input_bytes": input_bytes,
                "output_bytes": output_bytes,
                "includes_host_device_transfer": includes_transfer,
                "includes_setup_overhead": includes_setup,
                "same_workload_as_cpu": same_workload,
                "same_host_cpu_baseline": same_host,
                "cpu_mtrigrams_s": measured_cpu,
                "board_power_w": board_power,
                "cpu_power_w": cpu_power,
                "throughput_per_watt_ratio": energy_ratio,
                "fpga_p99_ns": fpga_p99_ns,
                "cpu_p99_ns": cpu_p99_ns,
                "throughput_relative_gap": throughput_relative_gap,
                "equal_throughput_tolerance": EQUAL_THROUGHPUT_REL_TOLERANCE,
                "equal_throughput_verified": equal_throughput_verified,
                "p99_latency_improvement_ratio": latency_ratio,
            }

    return {
        "schema_version": SCHEMA_VERSION,
        "semantic_contract": SEMANTIC_CONTRACT,
        "status": status,
        "claim_allowed": claim_allowed,
        "claim_threshold": {
            "throughput_per_watt_ratio": COMPETITION_THRESHOLD,
            "p99_latency_improvement_ratio": COMPETITION_THRESHOLD,
            "equal_throughput_relative_tolerance": EQUAL_THROUGHPUT_REL_TOLERANCE,
            "requires_all_metrics": True,
        },
        "bitstream_sha256": bitstream_sha256,
        "core": {
            "profile": profile_contract["profile"],
            "top": profile_contract["top"],
            "bitstream": profile_contract["bitstream"],
            "expected_self_test_signature": profile_contract[
                "expected_self_test_signature"
            ],
            "board": board,
            "lanes": lanes,
            "clock_mhz": clock_mhz,
            "roofline_mtrigrams_s": reported_core,
            "input_bits_per_trigram": INPUT_BITS_PER_TRIGRAM,
            "output_bits_per_trigram": OUTPUT_BITS_PER_TRIGRAM,
            "required_input_gb_s": input_gb_s,
            "required_full_output_gb_s": output_gb_s,
            "required_full_roundtrip_gb_s": input_gb_s + output_gb_s,
            "claim_boundary": claim_boundary,
        },
        "implementation": implementation,
        "cpu_control": {
            "correct": cpu_correct,
            "best_mtrigrams_s": best_cpu,
            "comparison_boundary": cpu_boundary,
        },
        "core_roofline_vs_cpu_ratio": core_ratio,
        "physical_measurement": physical,
        "reasons": reasons,
    }


def render_markdown(report: Mapping[str, Any]) -> str:
    """Render a compact human-reviewable claim report."""

    core = report["core"]
    implementation = report["implementation"]
    cpu = report["cpu_control"]
    claim_allowed = bool(report["claim_allowed"])
    lines = [
        "# BARDO-TX1 CPU competition gate",
        "",
        f"**Status:** `{report['status']}`  ",
        f"**CPU-competition claim allowed:** `{'yes' if claim_allowed else 'no'}`",
        "",
        "| Evidence | Value |",
        "| --- | ---: |",
        f"| Core roofline | {core['roofline_mtrigrams_s']:.3f} Mtrigrams/s |",
        f"| Fastest CPU control | {cpu['best_mtrigrams_s']:.3f} Mtrigrams/s |",
        f"| Core-only ratio | {report['core_roofline_vs_cpu_ratio']:.3f}× |",
        f"| Required input bandwidth | {core['required_input_gb_s']:.3f} GB/s |",
        f"| Required full-result output bandwidth | {core['required_full_output_gb_s']:.3f} GB/s |",
        f"| Required full round trip | {core['required_full_roundtrip_gb_s']:.3f} GB/s |",
        f"| Post-route minimum achieved clock | {implementation['minimum_achieved_mhz']:.3f} MHz |",
        f"| ECP5 LUT4 cells | {implementation['trellis_comb_used']} |",
        f"| ECP5 flip-flops | {implementation['trellis_ff_used']} |",
        "",
        "## Decision basis",
        "",
    ]
    lines.extend(f"- {reason}" for reason in report["reasons"])
    lines.extend(
        [
            "",
            "The core-only ratio is diagnostic, not an end-to-end speedup claim.",
            "",
        ]
    )
    return "\n".join(lines)


def _parse_json_bytes(
    data: bytes, path: Path, *, source: str
) -> Mapping[str, Any]:
    try:
        value = json.loads(_decode_utf8(data, path=path, source=source))
    except json.JSONDecodeError as exc:
        raise EvidenceError(f"{source}: cannot read valid JSON from {path}: {exc}") from exc
    if not isinstance(value, Mapping):
        raise EvidenceError(f"{source}: top-level JSON value must be an object")
    return value


def _load_json(path: Path, *, source: str) -> Mapping[str, Any]:
    return _parse_json_bytes(
        _read_input_bytes(path, source=source), path, source=source
    )


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate BARDO-TX1 evidence and gate CPU-competition claims."
    )
    parser.add_argument("--fpga-evidence", type=Path, required=True)
    parser.add_argument("--cpu-evidence", type=Path, required=True)
    parser.add_argument("--nextpnr-report", type=Path, required=True)
    parser.add_argument("--sha256s", type=Path, required=True)
    parser.add_argument(
        "--bitstream",
        type=Path,
        required=True,
        help="actual profile-selected .bit file; its bytes are hashed by this gate",
    )
    parser.add_argument("--measurement", type=Path)
    parser.add_argument("--json-output", type=Path, required=True)
    parser.add_argument("--markdown-output", type=Path, required=True)
    parser.add_argument(
        "--require-competitive",
        action="store_true",
        help="return non-zero unless physical evidence earns CPU_COMPETITIVE_PASS",
    )
    args = parser.parse_args(argv)

    try:
        manifest_bytes = _read_input_bytes(args.sha256s, source=str(args.sha256s))
        manifest_text = _decode_utf8(
            manifest_bytes, path=args.sha256s, source=str(args.sha256s)
        )
        manifest = parse_sha256_manifest(manifest_text, source=str(args.sha256s))
        fpga_bytes = _read_input_bytes(
            args.fpga_evidence, source=str(args.fpga_evidence)
        )
        _verify_manifest_bytes(
            manifest,
            args.fpga_evidence,
            fpga_bytes,
            source=str(args.sha256s),
        )
        fpga = parse_key_value_text(
            _decode_utf8(
                fpga_bytes,
                path=args.fpga_evidence,
                source=str(args.fpga_evidence),
            ),
            source=str(args.fpga_evidence),
        )
        profile_contract = _validate_fpga_profile(fpga)

        cpu_bytes = _read_input_bytes(args.cpu_evidence, source=str(args.cpu_evidence))
        cpu = parse_key_value_text(
            _decode_utf8(
                cpu_bytes,
                path=args.cpu_evidence,
                source=str(args.cpu_evidence),
            ),
            source=str(args.cpu_evidence),
        )

        nextpnr_bytes = _read_input_bytes(
            args.nextpnr_report, source=str(args.nextpnr_report)
        )
        _verify_manifest_bytes(
            manifest,
            args.nextpnr_report,
            nextpnr_bytes,
            source=str(args.sha256s),
        )
        nextpnr = _parse_json_bytes(
            nextpnr_bytes, args.nextpnr_report, source="nextpnr report"
        )

        bitstream_bytes = _read_input_bytes(args.bitstream, source=str(args.bitstream))
        bitstream_sha256 = _verify_manifest_bytes(
            manifest,
            args.bitstream,
            bitstream_bytes,
            source=str(args.sha256s),
            expected_filename=str(profile_contract["bitstream"]),
        )

        measurement: Mapping[str, Any] | None = None
        if args.measurement is not None:
            measurement_bytes = _read_input_bytes(
                args.measurement, source=str(args.measurement)
            )
            # Physical results may promote a CPU-competition claim, so all three
            # evidence roles must be byte-bound to the same manifest.
            _verify_manifest_bytes(
                manifest,
                args.cpu_evidence,
                cpu_bytes,
                source=str(args.sha256s),
            )
            _verify_manifest_bytes(
                manifest,
                args.measurement,
                measurement_bytes,
                source=str(args.sha256s),
            )
            measurement = _parse_json_bytes(
                measurement_bytes,
                args.measurement,
                source="physical measurement",
            )
        report = build_claim_report(
            fpga_evidence=fpga,
            cpu_evidence=cpu,
            nextpnr_report=nextpnr,
            bitstream_sha256=bitstream_sha256,
            measurement=measurement,
        )
        _write_text(
            args.json_output,
            json.dumps(report, indent=2, sort_keys=True) + "\n",
        )
        _write_text(args.markdown_output, render_markdown(report))
    except (OSError, EvidenceError) as exc:
        print(f"claim_gate=fail reason={exc}")
        return 1

    print("claim_gate=pass")
    print(f"status={report['status']}")
    print(f"claim_allowed={'true' if report['claim_allowed'] else 'false'}")
    print(f"core_roofline_mtrigrams_s={report['core']['roofline_mtrigrams_s']:.3f}")
    print(f"best_cpu_mtrigrams_s={report['cpu_control']['best_mtrigrams_s']:.3f}")
    print(f"core_roofline_vs_cpu_ratio={report['core_roofline_vs_cpu_ratio']:.3f}")
    print(
        f"required_full_roundtrip_gb_s={report['core']['required_full_roundtrip_gb_s']:.3f}"
    )
    if args.require_competitive and not report["claim_allowed"]:
        print("competition_requirement=fail")
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

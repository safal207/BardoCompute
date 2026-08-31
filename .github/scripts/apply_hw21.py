from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path.cwd()
MASK64 = (1 << 64) - 1


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(path: str, old: str, new: str) -> None:
    text = read(path)
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one exact replacement, found {count}")
    write(path, text.replace(old, new, 1))


def replace_n(path: str, old: str, new: str, expected: int) -> None:
    text = read(path)
    count = text.count(old)
    if count != expected:
        raise RuntimeError(
            f"{path}: expected {expected} replacements, found {count}"
        )
    write(path, text.replace(old, new))


def replace_between(path: str, start_marker: str, end_marker: str, body: str) -> None:
    text = read(path)
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{path}: start marker not found: {start_marker!r}")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{path}: end marker not found: {end_marker!r}")
    write(path, text[:start] + body + text[end:])


# ---------------------------------------------------------------------------
# P1: bind all claim inputs and require complete energy + p99 evidence.
# ---------------------------------------------------------------------------
claims_path = "src/bardocompute/hardware_claims.py"
replace_once(
    claims_path,
    "import argparse\nimport json\nimport math\nimport re\n",
    "import argparse\nimport hashlib\nimport json\nimport math\nimport re\n",
)
replace_once(
    claims_path,
    "COMPETITION_THRESHOLD = 2.0\n",
    "COMPETITION_THRESHOLD = 2.0\n"
    "THROUGHPUT_COMPARABILITY_REL_TOL = 0.05\n",
)

manifest_block = '''def parse_sha256_manifest(
    text: str, *, source: str = "SHA256SUMS"
) -> dict[str, str]:
    """Parse a sha256sum manifest, rejecting ambiguous basenames."""

    result: dict[str, str] = {}
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
        basename = Path(filename).name
        if not basename:
            raise EvidenceError(f"{source}:{line_number}: empty manifest filename")
        if basename in result:
            raise EvidenceError(
                f"{source}:{line_number}: duplicate manifest basename {basename!r}"
            )
        result[basename] = digest
    if not result:
        raise EvidenceError(f"{source}: no checksum records found")
    return result


def parse_sha256s_text(text: str, *, source: str = "SHA256SUMS") -> str:
    """Return the single bitstream digest from a sha256sum manifest."""

    manifest = parse_sha256_manifest(text, source=source)
    bitstream_digests = [
        digest for filename, digest in manifest.items() if filename.endswith(".bit")
    ]
    if len(bitstream_digests) != 1:
        raise EvidenceError(
            f"{source}: expected exactly one .bit digest, found {len(bitstream_digests)}"
        )
    return bitstream_digests[0]


def _sha256_file(path: Path) -> str:
    try:
        payload = path.read_bytes()
    except OSError as exc:
        raise EvidenceError(f"cannot read manifest-bound file {path}: {exc}") from exc
    return hashlib.sha256(payload).hexdigest()


def verify_manifest_binding(
    manifest: Mapping[str, str], path: Path, *, source: str
) -> None:
    """Require a claim input to be present in and match the CI manifest."""

    expected = manifest.get(path.name)
    if expected is None:
        raise EvidenceError(
            f"{source}: {path.name!r} is not bound by the bitstream manifest"
        )
    actual = _sha256_file(path)
    if actual != expected:
        raise EvidenceError(
            f"{source}: SHA-256 mismatch for {path.name!r}; "
            "claim inputs may come from mixed build profiles"
        )


'''
replace_between(claims_path, "def parse_sha256s_text(", "def _required(", manifest_block)

claims = read(claims_path)
old_measurement = '''            equal_throughput = (
                _strict_bool(
                    measurement["equal_throughput"],
                    field="equal_throughput",
                    source=source,
                )
                if "equal_throughput" in measurement
                else False
            )

            energy_ratio: float | None = None
            if measured_cpu is not None and board_power is not None and cpu_power is not None:
                energy_ratio = (
                    measured_throughput / board_power
                ) / (measured_cpu / cpu_power)

            latency_ratio: float | None = None
            if fpga_p99_ns is not None and cpu_p99_ns is not None and equal_throughput:
                latency_ratio = cpu_p99_ns / fpga_p99_ns

'''
new_measurement = '''            declared_equal_throughput = (
                _strict_bool(
                    measurement["equal_throughput"],
                    field="equal_throughput",
                    source=source,
                )
                if "equal_throughput" in measurement
                else None
            )
            throughput_comparable = (
                measured_cpu is not None
                and math.isclose(
                    measured_throughput,
                    measured_cpu,
                    rel_tol=THROUGHPUT_COMPARABILITY_REL_TOL,
                    abs_tol=0.0,
                )
            )
            if (
                declared_equal_throughput is not None
                and declared_equal_throughput != throughput_comparable
            ):
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
                and throughput_comparable
            ):
                latency_ratio = cpu_p99_ns / fpga_p99_ns

'''
if claims.count(old_measurement) != 1:
    raise RuntimeError("hardware_claims.py: measurement block changed unexpectedly")
claims = claims.replace(old_measurement, new_measurement, 1)
claims = claims.replace(
    '''            identity_complete = (
                includes_transfer
                and includes_setup
                and same_workload
                and same_host
                and workload_kind == "real"
                and measured_cpu is not None
            )
''',
    '''            identity_complete = (
                includes_transfer
                and includes_setup
                and same_workload
                and same_host
                and workload_kind == "real"
                and measured_cpu is not None
                and throughput_comparable
            )
''',
    1,
)
claims = claims.replace(
    "            claim_allowed = identity_complete and (passes_energy or passes_latency)\n",
    "            claim_allowed = identity_complete and passes_energy and passes_latency\n",
    1,
)
claims = claims.replace(
    '''                if measured_cpu is None:
                    reasons.append("A same-run CPU throughput measurement is missing.")
                if energy_ratio is None:
''',
    '''                if measured_cpu is None:
                    reasons.append("A same-run CPU throughput measurement is missing.")
                elif not throughput_comparable:
                    reasons.append(
                        "FPGA and CPU throughput differ by more than the "
                        f"{THROUGHPUT_COMPARABILITY_REL_TOL:.0%} equal-throughput tolerance."
                    )
                if energy_ratio is None:
''',
    1,
)
claims = claims.replace(
    '                "equal_throughput": equal_throughput,\n',
    '                "declared_equal_throughput": declared_equal_throughput,\n'
    '                "throughput_comparable": throughput_comparable,\n'
    '                "throughput_comparability_rel_tol": THROUGHPUT_COMPARABILITY_REL_TOL,\n',
    1,
)
claims = claims.replace(
    '''        "claim_threshold": {
            "throughput_per_watt_ratio": COMPETITION_THRESHOLD,
            "p99_latency_improvement_ratio": COMPETITION_THRESHOLD,
        },
''',
    '''        "claim_threshold": {
            "throughput_per_watt_ratio": COMPETITION_THRESHOLD,
            "p99_latency_improvement_ratio": COMPETITION_THRESHOLD,
            "requires_both_gates": True,
            "throughput_comparability_rel_tol": THROUGHPUT_COMPARABILITY_REL_TOL,
        },
''',
    1,
)
old_main = '''        nextpnr = _load_json(args.nextpnr_report, source="nextpnr report")
        bitstream_sha256 = parse_sha256s_text(
            args.sha256s.read_text(encoding="utf-8"), source=str(args.sha256s)
        )
'''
new_main = '''        manifest_text = args.sha256s.read_text(encoding="utf-8")
        manifest = parse_sha256_manifest(manifest_text, source=str(args.sha256s))
        verify_manifest_binding(
            manifest, args.fpga_evidence, source=str(args.sha256s)
        )
        verify_manifest_binding(
            manifest, args.nextpnr_report, source=str(args.sha256s)
        )
        nextpnr = _load_json(args.nextpnr_report, source="nextpnr report")
        bitstream_sha256 = parse_sha256s_text(
            manifest_text, source=str(args.sha256s)
        )
'''
if claims.count(old_main) != 1:
    raise RuntimeError("hardware_claims.py: CLI manifest block changed unexpectedly")
claims = claims.replace(old_main, new_main, 1)
write(claims_path, claims)

# Manifest generation: produce evidence first, then bind evidence and timing to bitstream.
makefile_path = "fpga/ulx3s-85f/Makefile"
makefile = read(makefile_path)
start = makefile.index("evidence: $(BIT) resource-check tool-versions\n")
end = makefile.index("$(BUILD_75):\n", start)
native_evidence = '''evidence: $(BIT) resource-check tool-versions
\tprintf '%s\\n' \\
\t  'board=ULX3S-85F' \\
\t  'device=LFE5U-85F' \\
\t  'package=CABGA381' \\
\t  'profile=native_25mhz' \\
\t  'input_clock_mhz=25' \\
\t  'clock_source=board_oscillator' \\
\t  'clock_mhz=25' \\
\t  'lanes=71' \\
\t  'core_mtrigrams_s=1775' \\
\t  'cpu_competition_status=unresolved' \\
\t  'claim_boundary=on-chip generator and reducer; not physical-board or host end-to-end' \\
\t  > $(BUILD)/evidence.txt
\tcd $(BUILD) && sha256sum \\
\t  $(notdir $(JSON)) \\
\t  $(notdir $(CONFIG)) \\
\t  $(notdir $(BIT)) \\
\t  $(notdir $(REPORT)) \\
\t  evidence.txt \\
\t  > SHA256SUMS
\tgrep -E 'Max frequency|Device utilisation|TRELLIS_SLICE|Timing' $(BUILD)/nextpnr.log > $(BUILD)/timing-summary.txt || true

'''
makefile = makefile[:start] + native_evidence + makefile[end:]
start = makefile.index("evidence-75: $(BIT_75) resource-check-75 tool-versions-75\n")
end = makefile.index("all-75:", start)
pll_evidence = '''evidence-75: $(BIT_75) resource-check-75 tool-versions-75
\tprintf '%s\\n' \\
\t  'board=ULX3S-85F' \\
\t  'device=LFE5U-85F' \\
\t  'package=CABGA381' \\
\t  'profile=pll_25_to_75mhz' \\
\t  'input_clock_mhz=25' \\
\t  'clock_source=ecp5_pll' \\
\t  'clock_mhz=75' \\
\t  'lanes=71' \\
\t  'core_mtrigrams_s=5325' \\
\t  'cpu_competition_status=unresolved' \\
\t  'claim_boundary=PLL timing-gated on-chip generator and reducer; not physical-board or host end-to-end' \\
\t  > $(BUILD_75)/evidence.txt
\tcd $(BUILD_75) && sha256sum \\
\t  $(notdir $(PLL_75)) \\
\t  $(notdir $(JSON_75)) \\
\t  $(notdir $(CONFIG_75)) \\
\t  $(notdir $(BIT_75)) \\
\t  $(notdir $(REPORT_75)) \\
\t  evidence.txt \\
\t  > SHA256SUMS
\tgrep -E 'Max frequency|Device utilisation|TRELLIS_SLICE|Timing' $(BUILD_75)/nextpnr.log > $(BUILD_75)/timing-summary.txt || true

'''
makefile = makefile[:start] + pll_evidence + makefile[end:]
write(makefile_path, makefile)

# ---------------------------------------------------------------------------
# P2: reset handshake, independent C oracle, and position-bound self-test.
# ---------------------------------------------------------------------------
replace_once(
    "rtl/bardo_tx1.sv",
    "    assign in_ready = !out_valid || out_ready;\n",
    "    assign in_ready = rst_n && (!out_valid || out_ready);\n",
)

replace_once(
    "hardware/tb/bardo_tx1_tb.sv",
    '''        repeat (3) @(posedge clk);
        rst_n = 1'b1;
''',
    '''        // A producer must never observe a ready/valid handshake while
        // reset discards the bundle.
        @(negedge clk);
        in_valid = 1'b1;
        in_lines = {3'b110, 3'b110, 3'b010};
        repeat (2) begin
            @(posedge clk);
            #1;
            if (in_ready)
                fail("input ready asserted while reset was active");
            if (out_valid)
                fail("output valid asserted while reset was active");
        end
        @(negedge clk);
        in_valid = 1'b0;
        rst_n = 1'b1;
''',
)

# Generate an independent, frozen Python oracle for all 512 C input addresses.
sys.path.insert(0, str(ROOT / "src"))
from bardocompute.hardware_contract import evaluate_trigram, unpack_trigram_lines


def pack_result(bundle: int) -> int:
    result = evaluate_trigram(unpack_trigram_lines(bundle))
    if not result.valid:
        return 0
    lower, middle, upper = result.settled_lines
    settled = lower | (middle << 3) | (upper << 6)
    return (
        result.trigram_index
        | (int(result.policy_allow) << 8)
        | (settled << 9)
        | (int(result.any_discontinuous) << 18)
        | (int(result.any_transition) << 19)
        | (result.target_count << 20)
        | (int(result.valid) << 22)
    )


oracle = [pack_result(bundle) for bundle in range(512)]
header_lines = [
    "#ifndef BARDO_TX1_EXPECTED_TABLE_H",
    "#define BARDO_TX1_EXPECTED_TABLE_H",
    "",
    "#include <stdint.h>",
    "",
    "/* Frozen from bardocompute.hardware_contract for all 512 9-bit inputs. */",
    "static const uint32_t BARDO_TX1_EXPECTED_RESULT[512] = {",
]
for offset in range(0, 512, 8):
    values = ", ".join(
        f"UINT32_C(0x{value:08x})" for value in oracle[offset : offset + 8]
    )
    header_lines.append(f"    {values},")
header_lines.extend(["};", "", "#endif", ""])
write("native/bardo_tx1_expected_table.h", "\n".join(header_lines))

c_path = "native/bardo_tx1_cpu_baseline.c"
c_source = read(c_path)
include_marker = "#include <time.h>\n"
if c_source.count(include_marker) != 1:
    raise RuntimeError("C baseline include marker changed unexpectedly")
c_source = c_source.replace(
    include_marker,
    include_marker + '\n#include "bardo_tx1_expected_table.h"\n',
    1,
)
old_lut = '''    uint32_t result_lut[512];
    for (unsigned bundle = 0; bundle < 512u; ++bundle) {
        result_lut[bundle] = evaluate_bundle((uint16_t)bundle);
    }
'''
new_lut = '''    uint32_t result_lut[512];
    for (unsigned bundle = 0; bundle < 512u; ++bundle) {
        const uint32_t actual = evaluate_bundle((uint16_t)bundle);
        const uint32_t expected = BARDO_TX1_EXPECTED_RESULT[bundle];
        if (actual != expected) {
            fprintf(
                stderr,
                "independent oracle mismatch bundle=%u actual=0x%08" PRIx32
                " expected=0x%08" PRIx32 "\\n",
                bundle,
                actual,
                expected
            );
            return 8;
        }
        result_lut[bundle] = expected;
    }
'''
if c_source.count(old_lut) != 1:
    raise RuntimeError("C baseline LUT block changed unexpectedly")
c_source = c_source.replace(old_lut, new_lut, 1)
c_source = c_source.replace(
    '    printf("correct=true\\n");\n',
    '    printf("independent_oracle=python_frozen_512\\n");\n'
    '    printf("independent_oracle_states=512\\n");\n'
    '    printf("correct=true\\n");\n',
    1,
)
write(c_path, c_source)

hardware_make = read("hardware/Makefile")
hardware_make = hardware_make.replace(
    "CPU_SRC := ../native/bardo_tx1_cpu_baseline.c\n",
    "CPU_SRC := ../native/bardo_tx1_cpu_baseline.c\n"
    "CPU_ORACLE := ../native/bardo_tx1_expected_table.h\n",
    1,
)
hardware_make = hardware_make.replace(
    "$(CPU_BIN): $(CPU_SRC) | $(BUILD)\n",
    "$(CPU_BIN): $(CPU_SRC) $(CPU_ORACLE) | $(BUILD)\n",
    1,
)
hardware_make = hardware_make.replace(
    "\tgrep -Fqx 'correct=true' $(BUILD)/cpu-baseline.log\n",
    "\tgrep -Fqx 'independent_oracle=python_frozen_512' $(BUILD)/cpu-baseline.log\n"
    "\tgrep -Fqx 'independent_oracle_states=512' $(BUILD)/cpu-baseline.log\n"
    "\tgrep -Fqx 'correct=true' $(BUILD)/cpu-baseline.log\n",
    1,
)
write("hardware/Makefile", hardware_make)

oracle_test = '''from __future__ import annotations

import re
from pathlib import Path

from bardocompute.hardware_contract import evaluate_trigram, unpack_trigram_lines

REPO_ROOT = Path(__file__).resolve().parents[1]


def _pack_result(bundle: int) -> int:
    result = evaluate_trigram(unpack_trigram_lines(bundle))
    if not result.valid:
        return 0
    lower, middle, upper = result.settled_lines
    settled = lower | (middle << 3) | (upper << 6)
    return (
        result.trigram_index
        | (int(result.policy_allow) << 8)
        | (settled << 9)
        | (int(result.any_discontinuous) << 18)
        | (int(result.any_transition) << 19)
        | (result.target_count << 20)
        | (int(result.valid) << 22)
    )


def test_frozen_c_oracle_matches_python_contract_for_all_512_inputs() -> None:
    header = (REPO_ROOT / "native/bardo_tx1_expected_table.h").read_text(
        encoding="utf-8"
    )
    frozen = [
        int(value, 16)
        for value in re.findall(r"UINT32_C\\(0x([0-9a-fA-F]{8})\\)", header)
    ]

    assert len(frozen) == 512
    assert frozen == [_pack_result(bundle) for bundle in range(512)]


def test_native_lut_consumes_independent_oracle() -> None:
    source = (REPO_ROOT / "native/bardo_tx1_cpu_baseline.c").read_text(
        encoding="utf-8"
    )

    assert '#include "bardo_tx1_expected_table.h"' in source
    assert "result_lut[bundle] = expected;" in source
    assert "result_lut[bundle] = evaluate_bundle" not in source
    assert "independent_oracle=python_frozen_512" in source
'''
write("tests/test_cpu_oracle.py", oracle_test)


def rotl64(value: int, amount: int) -> int:
    amount &= 63
    value &= MASK64
    if amount == 0:
        return value
    return ((value << amount) & MASK64) | (value >> (64 - amount))


def board_payload(bundle: int) -> int:
    result = evaluate_trigram(unpack_trigram_lines(bundle))
    lower, middle, upper = result.settled_lines
    settled = lower | (middle << 3) | (upper << 6)
    return (
        (int(result.valid) << 31)
        | (result.target_count << 29)
        | (int(result.any_transition) << 28)
        | (int(result.any_discontinuous) << 27)
        | (settled << 18)
        | (int(result.policy_allow) << 17)
        | (result.trigram_index << 9)
    )


def lane_mix(lane: int, bundle: int) -> int:
    payload = board_payload(bundle)
    token = (
        (0xB1 << 56)
        | (lane << 49)
        | (bundle << 40)
        | (payload << 8)
        | 0x5A
    )
    salt = 0x9E3779B97F4A7C15 ^ (
        (0x0101010101010101 * (lane + 1)) & MASK64
    )
    rot_a = (lane * 7 + 1) % 64
    rot_b = (lane * 13 + 11) % 64
    return (
        rotl64(token ^ salt, rot_a)
        ^ rotl64(rotl64(token, 33) ^ ((~salt) & MASK64), rot_b)
    ) & MASK64


def epoch_signature() -> int:
    signature = 0x424152444F545831
    for position in range(512):
        cycle = 0
        for lane in range(71):
            cycle ^= lane_mix(lane, (position + lane) & 0x1FF)
        signature = rotl64(signature, 1) ^ cycle ^ position
    return signature & MASK64


expected_signature = epoch_signature()

selftest_block = '''    // Preserve the exact accepted input beside the registered result. This
    // catches lane slicing and source/result association defects, including
    // invalid bundles whose fail-closed semantic payload is all zero.
    reg [(LANES * 9) - 1:0] accepted_lines;
    always @(posedge CORE_CLOCK) begin
        if (!rst_n)
            accepted_lines <= {(LANES * 9){1'b0}};
        else if (in_valid && in_ready)
            accepted_lines <= in_lines;
    end

    function automatic [63:0] rotl64;
        input [63:0] value;
        input [5:0] amount;
        begin
            if (amount == 0)
                rotl64 = value;
            else
                rotl64 = (value << amount) | (value >> (64 - amount));
        end
    endfunction

    // One 32-bit semantic word per lane, plus a 64-bit position-bound mix.
    // All multiplications below are elaboration-time constants; the resulting
    // datapath is rotations and XOR only, with no runtime DSP requirement.
    wire [(LANES * 32) - 1:0] lane_payload;
    wire [(LANES * 64) - 1:0] lane_position_mix;

    genvar payload_lane;
    generate
        for (payload_lane = 0; payload_lane < LANES; payload_lane = payload_lane + 1) begin : generate_payload
            localparam [6:0] LANE_ID = payload_lane;
            localparam [5:0] ROT_A = ((payload_lane * 7) + 1) % 64;
            localparam [5:0] ROT_B = ((payload_lane * 13) + 11) % 64;
            localparam [63:0] LANE_SALT = 64'h9e3779b97f4a7c15
                ^ (64'h0101010101010101 * (payload_lane + 1));
            wire [63:0] lane_token;

            assign lane_payload[(payload_lane * 32) +: 32] = {
                out_valid_mask[payload_lane],
                out_target_count[(payload_lane * 2) +: 2],
                out_any_transition[payload_lane],
                out_any_discontinuous[payload_lane],
                out_settled_lines[(payload_lane * 9) +: 9],
                out_policy_allow[payload_lane],
                out_trigram_index[(payload_lane * 8) +: 8],
                9'b0
            };
            assign lane_token = {
                8'hb1,
                LANE_ID,
                accepted_lines[(payload_lane * 9) +: 9],
                lane_payload[(payload_lane * 32) +: 32],
                8'h5a
            };
            assign lane_position_mix[(payload_lane * 64) +: 64] =
                rotl64(lane_token ^ LANE_SALT, ROT_A)
                ^ rotl64(rotl64(lane_token, 6'd33) ^ ~LANE_SALT, ROT_B);
        end
    endgenerate

    reg [63:0] cycle_mix;
    integer fold_lane;
    always @* begin
        cycle_mix = 64'h0000000000000000;
        for (fold_lane = 0; fold_lane < LANES; fold_lane = fold_lane + 1)
            cycle_mix = cycle_mix
                ^ lane_position_mix[(fold_lane * 64) +: 64];
    end

'''

for harness, core_clock in (
    ("fpga/ulx3s-85f/bardo_tx1_ulx3s_bench.sv", "clk_25mhz"),
    ("fpga/ulx3s-85f/bardo_tx1_ulx3s_bench_75.sv", "clk_75mhz"),
):
    text = read(harness)
    start = text.find("    // One 32-bit semantic word per lane.")
    end = text.find("    reg [63:0] signature;", start)
    if start < 0 or end < 0:
        raise RuntimeError(f"{harness}: legacy self-test reducer not found")
    block = selftest_block.replace("CORE_CLOCK", core_clock)
    text = text[:start] + block + text[end:]
    text = text.replace(
        "        ^ {32'h00000000, cycle_xor}\n",
        "        ^ cycle_mix\n",
        1,
    )
    old_match = re.search(
        r"localparam \[63:0\] EXPECTED_SIGNATURE = 64'h[0-9a-fA-F]{16};",
        text,
    )
    if old_match is None:
        raise RuntimeError(f"{harness}: expected signature constant not found")
    text = (
        text[: old_match.start()]
        + f"localparam [63:0] EXPECTED_SIGNATURE = 64'h{expected_signature:016x};"
        + text[old_match.end() :]
    )
    write(harness, text)

fpga_test = f'''from __future__ import annotations

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
EXPECTED_SIGNATURE = 0x{expected_signature:016X}
MASK64 = (1 << 64) - 1
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


def _rotate_left_64(value: int, amount: int) -> int:
    amount &= 63
    value &= MASK64
    if amount == 0:
        return value
    return ((value << amount) & MASK64) | (value >> (64 - amount))


def _lane_mix(lane: int, bundle: int) -> int:
    token = (
        (0xB1 << 56)
        | (lane << 49)
        | (bundle << 40)
        | (_payload_word(bundle) << 8)
        | 0x5A
    )
    salt = 0x9E3779B97F4A7C15 ^ (
        (0x0101010101010101 * (lane + 1)) & MASK64
    )
    return (
        _rotate_left_64(token ^ salt, (lane * 7 + 1) % 64)
        ^ _rotate_left_64(
            _rotate_left_64(token, 33) ^ ((~salt) & MASK64),
            (lane * 13 + 11) % 64,
        )
    ) & MASK64


def _cycle_mix(bundles: tuple[int, ...]) -> int:
    value = 0
    for lane, bundle in enumerate(bundles):
        value ^= _lane_mix(lane, bundle)
    return value


def _epoch_signature() -> tuple[int, int, int]:
    signature = SIGNATURE_SEED
    valid_outputs = 0
    policy_allows = 0
    for epoch_position in range(512):
        bundles = tuple((epoch_position + lane) & 0x1FF for lane in range(LANES))
        for bundle in bundles:
            result = evaluate_trigram(unpack_trigram_lines(bundle))
            valid_outputs += int(result.valid)
            policy_allows += int(result.policy_allow)
        signature = (
            _rotate_left_64(signature, 1)
            ^ _cycle_mix(bundles)
            ^ epoch_position
        ) & MASK64
    return signature, valid_outputs, policy_allows


def test_ulx3s_epoch_signature_matches_rtl_constant() -> None:
    signature, valid_outputs, policy_allows = _epoch_signature()

    assert valid_outputs == 216 * LANES == 15_336
    assert policy_allows == 28 * LANES == 1_988
    assert signature == EXPECTED_SIGNATURE
    expected_literal = f"EXPECTED_SIGNATURE = 64'h{{EXPECTED_SIGNATURE:016x}}"
    for harness in (
        "bardo_tx1_ulx3s_bench.sv",
        "bardo_tx1_ulx3s_bench_75.sv",
    ):
        text = (REPO_ROOT / "fpga/ulx3s-85f" / harness).read_text(
            encoding="utf-8"
        )
        assert expected_literal in text
        assert "accepted_lines" in text
        assert "lane_position_mix" in text
        assert "cycle_mix" in text


def test_position_bound_mix_detects_every_pairwise_lane_swap() -> None:
    baseline_bundles = tuple((lane * 37 + 11) & 0x1FF for lane in range(LANES))
    baseline = _cycle_mix(baseline_bundles)

    for left in range(LANES):
        for right in range(left + 1, LANES):
            swapped = list(baseline_bundles)
            swapped[left], swapped[right] = swapped[right], swapped[left]
            assert _cycle_mix(tuple(swapped)) != baseline


def test_invalid_input_identity_is_not_erased_by_fail_closed_payload() -> None:
    assert _payload_word(0b001_000_000) == 0
    assert _payload_word(0b111_000_000) == 0
    assert _lane_mix(3, 0b001_000_000) != _lane_mix(3, 0b111_000_000)


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
        "synth_ecp5 -top $(TOP_75)",
        "--freq 75",
        "core_mtrigrams_s=5325",
    ):
        assert required in makefile

    assert "hierarchy -check -top $(TOP_75)" not in makefile
    assert "if (!pll_locked)" in harness
    assert "reset_shift <= 8'h00" in harness
    assert ".clk(clk_75mhz)" in harness
'''
write("tests/test_fpga_harness.py", fpga_test)

# ---------------------------------------------------------------------------
# Tests and workflow triggers for every repaired boundary.
# ---------------------------------------------------------------------------
claim_tests_path = "tests/test_hardware_claims.py"
claim_tests = read(claim_tests_path)
if "import hashlib\n" not in claim_tests:
    claim_tests = claim_tests.replace(
        "from __future__ import annotations\n\n",
        "from __future__ import annotations\n\nimport hashlib\n",
        1,
    )
start = claim_tests.index(
    "def test_real_host_stream_can_pass_throughput_per_watt_gate() -> None:\n"
)
end = claim_tests.index(
    "def test_synthetic_host_stream_cannot_promote_claim() -> None:\n", start
)
complete_gate_tests = '''def _complete_host_stream_measurement() -> dict[str, object]:
    measurement = measurement_base("host_stream")
    measurement.update(
        {
            "workload": "payment recovery transition trace v1",
            "workload_kind": "real",
            "output_mode": "full_results",
            "items": 1_000_000,
            "elapsed_seconds": 0.002,
            "input_bytes": math.ceil(1_000_000 * 9 / 8),
            "output_bytes": math.ceil(1_000_000 * 23 / 8),
            "includes_host_device_transfer": True,
            "includes_setup_overhead": True,
            "same_workload_as_cpu": True,
            "same_host_cpu_baseline": True,
            "cpu_mtrigrams_s": 500.0,
            "board_power_w": 10.0,
            "cpu_power_w": 50.0,
            "fpga_p99_ns": 100.0,
            "cpu_p99_ns": 250.0,
            "equal_throughput": True,
        }
    )
    return measurement


def test_real_host_stream_requires_both_energy_and_p99_gates() -> None:
    report = build(_complete_host_stream_measurement())

    assert report["status"] == "CPU_COMPETITIVE_PASS"
    assert report["claim_allowed"] is True
    physical = report["physical_measurement"]
    assert physical["throughput_mtrigrams_s"] == pytest.approx(500.0)
    assert physical["throughput_per_watt_ratio"] == pytest.approx(5.0)
    assert physical["p99_latency_improvement_ratio"] == pytest.approx(2.5)
    assert physical["throughput_comparable"] is True


def test_energy_only_evidence_cannot_promote_claim() -> None:
    measurement = _complete_host_stream_measurement()
    measurement.pop("fpga_p99_ns")
    measurement.pop("cpu_p99_ns")

    report = build(measurement)

    assert report["status"] == "END_TO_END_NOT_PROVEN"
    assert report["claim_allowed"] is False


def test_latency_only_evidence_cannot_promote_claim() -> None:
    measurement = _complete_host_stream_measurement()
    measurement.pop("board_power_w")
    measurement.pop("cpu_power_w")

    report = build(measurement)

    assert report["status"] == "END_TO_END_NOT_PROVEN"
    assert report["claim_allowed"] is False


def test_equal_throughput_boolean_cannot_override_measurements() -> None:
    measurement = _complete_host_stream_measurement()
    measurement["elapsed_seconds"] = 0.001

    with pytest.raises(EvidenceError, match="contradicts measured"):
        build(measurement)


'''
claim_tests = claim_tests[:start] + complete_gate_tests + claim_tests[end:]
old_sums = '''    sums_path.write_text(
        f"{BITSTREAM_SHA256}  build/bardo_tx1.bit\\n", encoding="utf-8"
    )
'''
new_sums = '''    sums_path.write_text(
        "\\n".join(
            (
                f"{hashlib.sha256(fpga_path.read_bytes()).hexdigest()}  evidence.txt",
                f"{hashlib.sha256(report_path.read_bytes()).hexdigest()}  nextpnr.json",
                f"{BITSTREAM_SHA256}  bardo_tx1.bit",
            )
        )
        + "\\n",
        encoding="utf-8",
    )
'''
if claim_tests.count(old_sums) != 1:
    raise RuntimeError("claim CLI checksum fixture changed unexpectedly")
claim_tests = claim_tests.replace(old_sums, new_sums, 1)
require_line = '    assert main([*common, "--require-competitive"]) == 3\n'
if claim_tests.count(require_line) != 1:
    raise RuntimeError("claim CLI require assertion changed unexpectedly")
claim_tests = claim_tests.replace(
    require_line,
    require_line
    + '''

    # Omitting a claim input from the manifest must fail closed.
    sums_path.write_text(
        f"{BITSTREAM_SHA256}  bardo_tx1.bit\\n", encoding="utf-8"
    )
    assert main(common) == 1
''',
    1,
)
write(claim_tests_path, claim_tests)

workflow_path = ".github/workflows/hardware-v0.1.yml"
workflow = read(workflow_path)
packed_marker = '      - "src/bardocompute/hardware_contract.py"\n'
if workflow.count(packed_marker) != 2:
    raise RuntimeError("hardware workflow path lists changed unexpectedly")
workflow = workflow.replace(
    packed_marker,
    packed_marker + '      - "src/bardocompute/packed.py"\n',
)
test_marker = '      - "tests/test_cpu_control.py"\n'
if workflow.count(test_marker) != 2:
    raise RuntimeError("hardware workflow test path lists changed unexpectedly")
workflow = workflow.replace(
    test_marker,
    test_marker + '      - "tests/test_cpu_oracle.py"\n',
)
workflow = workflow.replace(
    "          tests/test_cpu_control.py\n          tests/test_hardware_claims.py\n",
    "          tests/test_cpu_control.py\n"
    "          tests/test_cpu_oracle.py\n"
    "          tests/test_hardware_claims.py\n",
    1,
)
write(workflow_path, workflow)

# Keep human-readable documentation synchronized with the new physical signature.
old_signature = "b0058cd5263c1fc3"
new_signature = f"{expected_signature:016x}"
for path in (
    "docs/hardware-v0.1.md",
    "fpga/ulx3s-85f/README.md",
    "README.md",
):
    target = ROOT / path
    if target.exists():
        text = target.read_text(encoding="utf-8")
        if old_signature in text:
            target.write_text(
                text.replace(old_signature, new_signature), encoding="utf-8"
            )

print(f"hw21_patch=prepared expected_signature=0x{expected_signature:016x}")

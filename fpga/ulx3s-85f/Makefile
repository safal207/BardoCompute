SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

BUILD := build
TOP := bardo_tx1_ulx3s_bench
RTL := ../../rtl/bardo_tx1.sv $(TOP).sv
LPF := ulx3s_bardo_tx1.lpf
REPORT_CHECK := check_report.py
JSON := $(BUILD)/$(TOP).json
CONFIG := $(BUILD)/$(TOP).config
BIT := $(BUILD)/$(TOP).bit
REPORT := $(BUILD)/nextpnr-report.json

BUILD_75 := build-75mhz
TOP_75 := bardo_tx1_ulx3s_bench_75
PLL_75 := $(BUILD_75)/bardo_tx1_pll75.v
RTL_75 := ../../rtl/bardo_tx1.sv $(PLL_75) $(TOP_75).sv
JSON_75 := $(BUILD_75)/$(TOP_75).json
CONFIG_75 := $(BUILD_75)/$(TOP_75).config
BIT_75 := $(BUILD_75)/$(TOP_75).bit
REPORT_75 := $(BUILD_75)/nextpnr-report.json

.PHONY: all profiles bitstream resource-check evidence tool-versions \
	all-75 bitstream-75 resource-check-75 evidence-75 tool-versions-75 clean

# Preserve the original native-clock profile as the default build.
all: bitstream resource-check evidence

# Explicit aggregate target for CI or local comparison of both profiles.
profiles: all all-75

$(BUILD):
	mkdir -p $(BUILD)

$(JSON): $(RTL) | $(BUILD)
	yosys -l $(BUILD)/yosys-ecp5.log -p 'read_verilog -sv $(RTL); hierarchy -check -top $(TOP); synth_ecp5 -abc9 -json $(JSON); stat'

$(CONFIG): $(JSON) $(LPF)
	nextpnr-ecp5 --85k --package CABGA381 --json $(JSON) --lpf $(LPF) --textcfg $(CONFIG) --freq 25 --report $(REPORT) 2>&1 | tee $(BUILD)/nextpnr.log

$(BIT): $(CONFIG)
	ecppack --compress --freq 62.0 --input $(CONFIG) --bit $(BIT)
	test -s $(BIT)

bitstream: $(BIT)

resource-check: $(CONFIG) $(REPORT_CHECK)
	python3 $(REPORT_CHECK) $(REPORT) 2>&1 | tee $(BUILD)/resource-check.txt
	grep -Fqx 'resource_check=pass' $(BUILD)/resource-check.txt

tool-versions: | $(BUILD)
	{ \
	  yosys -V; \
	  nextpnr-ecp5 --version; \
	  ecppack --version || true; \
	  ecppll --help | head -n 2 || true; \
	} > $(BUILD)/tool-versions.txt 2>&1

evidence: $(BIT) resource-check tool-versions
	sha256sum $(JSON) $(CONFIG) $(BIT) > $(BUILD)/SHA256SUMS
	printf '%s\n' \
	  'board=ULX3S-85F' \
	  'device=LFE5U-85F' \
	  'package=CABGA381' \
	  'profile=native_25mhz' \
	  'input_clock_mhz=25' \
	  'clock_source=board_oscillator' \
	  'clock_mhz=25' \
	  'lanes=71' \
	  'core_mtrigrams_s=1775' \
	  'cpu_competition_status=unresolved' \
	  'claim_boundary=on-chip generator and reducer; not physical-board or host end-to-end' \
	  > $(BUILD)/evidence.txt
	grep -E 'Max frequency|Device utilisation|TRELLIS_SLICE|Timing' $(BUILD)/nextpnr.log > $(BUILD)/timing-summary.txt || true

$(BUILD_75):
	mkdir -p $(BUILD_75)

# Generate rather than hand-maintain the ECP5 PLL primitive. The pinned ecppll
# tool must derive 25 -> 75 MHz inside the legal ECP5 PFD/VCO range.
$(PLL_75): | $(BUILD_75)
	ecppll -i 25 -o 75 -n bardo_tx1_pll75 \
	  --clkin_name clkin --clkout0_name clkout0 -f $(PLL_75)
	test -s $(PLL_75)
	grep -Fq 'module bardo_tx1_pll75' $(PLL_75)
	grep -Fq 'output locked' $(PLL_75)
	grep -Fq '.CLKI_DIV(1)' $(PLL_75)
	grep -Fq '.CLKFB_DIV(3)' $(PLL_75)
	grep -Fq '.CLKOP_DIV(8)' $(PLL_75)

$(JSON_75): $(RTL_75) | $(BUILD_75)
	yosys -l $(BUILD_75)/yosys-ecp5.log -p 'read_verilog -sv $(RTL_75); hierarchy -check -top $(TOP_75); synth_ecp5 -abc9 -json $(JSON_75); stat'

$(CONFIG_75): $(JSON_75) $(LPF)
	nextpnr-ecp5 --85k --package CABGA381 --json $(JSON_75) --lpf $(LPF) --textcfg $(CONFIG_75) --freq 75 --report $(REPORT_75) 2>&1 | tee $(BUILD_75)/nextpnr.log

$(BIT_75): $(CONFIG_75)
	ecppack --compress --freq 62.0 --input $(CONFIG_75) --bit $(BIT_75)
	test -s $(BIT_75)

bitstream-75: $(BIT_75)

resource-check-75: $(CONFIG_75) $(REPORT_CHECK)
	python3 $(REPORT_CHECK) $(REPORT_75) 2>&1 | tee $(BUILD_75)/resource-check.txt
	grep -Fqx 'resource_check=pass' $(BUILD_75)/resource-check.txt

tool-versions-75: $(PLL_75)
	{ \
	  yosys -V; \
	  nextpnr-ecp5 --version; \
	  ecppack --version || true; \
	  printf '%s\n' 'pll_generator=ecppll'; \
	  sha256sum $(PLL_75); \
	} > $(BUILD_75)/tool-versions.txt 2>&1

evidence-75: $(BIT_75) resource-check-75 tool-versions-75
	sha256sum $(PLL_75) $(JSON_75) $(CONFIG_75) $(BIT_75) > $(BUILD_75)/SHA256SUMS
	printf '%s\n' \
	  'board=ULX3S-85F' \
	  'device=LFE5U-85F' \
	  'package=CABGA381' \
	  'profile=pll_25_to_75mhz' \
	  'input_clock_mhz=25' \
	  'clock_source=ecp5_pll' \
	  'clock_mhz=75' \
	  'lanes=71' \
	  'core_mtrigrams_s=5325' \
	  'cpu_competition_status=unresolved' \
	  'claim_boundary=PLL timing-gated on-chip generator and reducer; not physical-board or host end-to-end' \
	  > $(BUILD_75)/evidence.txt
	grep -E 'Max frequency|Device utilisation|TRELLIS_SLICE|Timing' $(BUILD_75)/nextpnr.log > $(BUILD_75)/timing-summary.txt || true

all-75: bitstream-75 resource-check-75 evidence-75

clean:
	rm -rf $(BUILD) $(BUILD_75)

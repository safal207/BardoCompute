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

.PHONY: all bitstream resource-check evidence tool-versions clean

all: bitstream resource-check evidence

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
	} > $(BUILD)/tool-versions.txt 2>&1

evidence: $(BIT) resource-check tool-versions
	sha256sum $(JSON) $(CONFIG) $(BIT) > $(BUILD)/SHA256SUMS
	printf '%s\n' \
	  'board=ULX3S-85F' \
	  'device=LFE5U-85F' \
	  'package=CABGA381' \
	  'clock_mhz=25' \
	  'lanes=71' \
	  'core_mtrigrams_s=1775' \
	  'cpu_competition_status=unresolved' \
	  'claim_boundary=on-chip generator and reducer; not host end-to-end' \
	  > $(BUILD)/evidence.txt
	grep -E 'Max frequency|Device utilisation|TRELLIS_SLICE|Timing' $(BUILD)/nextpnr.log > $(BUILD)/timing-summary.txt || true

clean:
	rm -rf $(BUILD)

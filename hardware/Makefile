SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

BUILD := build
RTL := ../rtl/bardo_tx1.sv
TB := tb/bardo_tx1_tb.sv
CPU_SRC := ../native/bardo_tx1_cpu_baseline.c
CPU_BIN := $(BUILD)/bardo_tx1_cpu_baseline
SIM_PASS := PASS: exhaustive 512-bundle contract, 216-state bijection, and backpressure

.PHONY: all sim synth cpu-smoke clean

all: sim synth cpu-smoke

$(BUILD):
	mkdir -p $(BUILD)

sim: | $(BUILD)
	iverilog -g2012 -Wall -s bardo_tx1_tb -o $(BUILD)/bardo_tx1_tb $(RTL) $(TB)
	vvp $(BUILD)/bardo_tx1_tb 2>&1 | tee $(BUILD)/simulation.log
	grep -Fqx '$(SIM_PASS)' $(BUILD)/simulation.log

synth: | $(BUILD)
	yosys -l $(BUILD)/yosys.log yosys/bardo_tx1.ys

$(CPU_BIN): $(CPU_SRC) | $(BUILD)
	$(CC) -O3 -std=c11 -Wall -Wextra -Werror $(CPU_SRC) -o $(CPU_BIN)

cpu-smoke: $(CPU_BIN)
	$(CPU_BIN) 1000000 2>&1 | tee $(BUILD)/cpu-baseline.log
	grep -Fqx 'correct=true' $(BUILD)/cpu-baseline.log

clean:
	rm -rf $(BUILD)

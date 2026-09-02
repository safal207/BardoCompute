SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c

BUILD := build
RTL := ../rtl/bardo_tx1.sv
TB := tb/bardo_tx1_tb.sv
CPU_SRC := ../native/bardo_tx1_cpu_baseline.c
CPU_BIN := $(BUILD)/bardo_tx1_cpu_baseline
CPU_ORACLE := $(BUILD)/bardo_tx1_oracle.h
CPU_CFLAGS ?= -O3 -march=native -mtune=native -std=c11 -Wall -Wextra -Werror
CPU_ITEMS ?= 16000000
CPU_REPEATS ?= 4
SIM_PASS := PASS: reset-safe handshake, exhaustive 512-bundle contract, 216-state bijection, and backpressure

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

$(CPU_ORACLE): ../src/bardocompute/hardware_contract.py ../src/bardocompute/hardware_oracle.py ../src/bardocompute/packed.py | $(BUILD)
	PYTHONPATH=../src python3 -m bardocompute.hardware_oracle --output $(CPU_ORACLE)

$(CPU_BIN): $(CPU_SRC) $(CPU_ORACLE) | $(BUILD)
	$(CC) $(CPU_CFLAGS) -I$(BUILD) $(CPU_SRC) -o $(CPU_BIN)

cpu-smoke: $(CPU_BIN)
	$(CPU_BIN) $(CPU_ITEMS) $(CPU_REPEATS) 2>&1 | tee $(BUILD)/cpu-baseline.log
	grep -Fqx 'oracle_verified=true' $(BUILD)/cpu-baseline.log
	grep -Fqx 'correct=true' $(BUILD)/cpu-baseline.log
	grep -Fqx 'cpu_baseline_model=materialize_and_reduction' $(BUILD)/cpu-baseline.log
	grep -Eq '^best_materialized_cpu_mtrigrams_s=[0-9]+([.][0-9]+)?$$' $(BUILD)/cpu-baseline.log
	grep -Eq '^best_reduced_cpu_mtrigrams_s=[0-9]+([.][0-9]+)?$$' $(BUILD)/cpu-baseline.log
	grep -Eq '^best_cpu_mtrigrams_s=[0-9]+([.][0-9]+)?$$' $(BUILD)/cpu-baseline.log

clean:
	rm -rf $(BUILD)

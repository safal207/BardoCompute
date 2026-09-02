`timescale 1ns/1ps

// Functional PLL model for the full-harness regression. The synthesis build
// still uses the generated ECP5 primitive; this model only supplies the same
// 25 MHz input / 75 MHz output / lock interface to the simulator.
module bardo_tx1_pll75 (
    input  wire clkin,
    output reg  clkout0,
    output reg  locked
);
    integer input_edges;

    initial begin
        clkout0 = 1'b0;
        locked = 1'b0;
        input_edges = 0;
    end

    always #6.667 clkout0 = ~clkout0;

    always @(posedge clkin) begin
        if (!locked) begin
            input_edges = input_edges + 1;
            if (input_edges == 3)
                locked <= 1'b1;
        end
    end
endmodule

module bardo_tx1_ulx3s_bench_75_tb;
    localparam [63:0] SIGNATURE_SEED = 64'h424152444f545831;
    localparam [63:0] EXPECTED_SIGNATURE = 64'hf8cc45c1e3244a5a;

    reg clk_25mhz = 1'b0;
    wire [7:0] led;

    integer cycle_count;
    integer observed_fold_count;
    reg [63:0] observed_signature;
    reg [63:0] next_observed_signature;
    reg frozen_signature_seen;

    bardo_tx1_ulx3s_bench_75 dut (
        .clk_25mhz(clk_25mhz),
        .led(led)
    );

    always #20 clk_25mhz = ~clk_25mhz;

    task automatic fail;
        input [1023:0] message;
        begin
            $display("FAIL: %0s", message);
            $fatal(1);
        end
    endtask

    // Independently consume the first complete ordered-fold epoch. This pins
    // every delayed epoch identity as well as the exact frozen signature, then
    // the checks below require the harness itself to latch the same result.
    always @(posedge dut.clk_75mhz) begin
        #1;
        if (!dut.rst_n) begin
            observed_fold_count = 0;
            observed_signature = SIGNATURE_SEED;
            frozen_signature_seen = 1'b0;
        end else if (dut.fold_valid && (observed_fold_count < 512)) begin
            if (dut.fold_epoch_position !== observed_fold_count[8:0])
                fail("full harness changed ordered-fold epoch identity");

            next_observed_signature = {
                observed_signature[62:0], observed_signature[63]
            } ^ dut.fold_value ^ {55'h00000000000000, dut.fold_epoch_position};

            if (dut.fold_epoch_position == 9'd511) begin
                if (next_observed_signature !== EXPECTED_SIGNATURE)
                    fail("full harness did not produce the frozen self-test signature");
                frozen_signature_seen = 1'b1;
                observed_signature = SIGNATURE_SEED;
            end else begin
                observed_signature = next_observed_signature;
            end

            observed_fold_count = observed_fold_count + 1;
        end
    end

    initial begin
        cycle_count = 0;
        observed_fold_count = 0;
        observed_signature = SIGNATURE_SEED;
        next_observed_signature = SIGNATURE_SEED;
        frozen_signature_seen = 1'b0;

        // Reset qualification, the core pipeline, the two-stage fold, and one
        // 512-frame epoch all complete comfortably inside this bound.
        for (cycle_count = 0; cycle_count < 700; cycle_count = cycle_count + 1) begin
            @(posedge dut.clk_75mhz);
            #2;
            if ((led[0] === 1'b1) || (led[1] === 1'b1))
                cycle_count = 700;
        end

        if (led[1] !== 1'b0)
            fail("full harness latched its sticky failure output");
        if (led[0] !== 1'b1)
            fail("full harness did not latch a passing epoch before timeout");
        if (!frozen_signature_seen)
            fail("independent harness monitor did not see the frozen signature");
        if (observed_fold_count != 512)
            fail("full harness did not emit exactly one checked ordered epoch");
        if (dut.EXPECTED_SIGNATURE !== EXPECTED_SIGNATURE)
            fail("full harness expected-signature constant drifted");
        if (dut.epoch_count !== 32'd1)
            fail("full harness epoch counter did not advance exactly once");
        if (dut.signature !== SIGNATURE_SEED)
            fail("full harness signature accumulator did not reset after the epoch");
        if (led[2] !== 1'b1 || led[3] !== 1'b1 || led[4] !== 1'b1 || led[5] !== 1'b1)
            fail("full harness lock or full-throughput stream status is incomplete");

        $display("PASS: 75 MHz harness completes frozen ordered-fold signature epoch");
        $finish;
    end
endmodule

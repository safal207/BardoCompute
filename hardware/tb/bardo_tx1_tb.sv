`timescale 1ns/1ps

module bardo_tx1_tb;
    localparam integer LANES = 1;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg in_valid = 1'b0;
    wire in_ready;
    // Start away from the first exhaustive vector (000/000/000). This makes
    // the initial combinational evaluation explicit across simulators instead
    // of depending on declaration-time event ordering.
    reg [8:0] in_lines = 9'b111_111_111;
    wire out_valid;
    reg out_ready = 1'b1;
    wire [0:0] out_valid_mask;
    wire [7:0] out_trigram_index;
    wire [0:0] out_policy_allow;
    wire [8:0] out_settled_lines;
    wire [0:0] out_any_discontinuous;
    wire [0:0] out_any_transition;
    wire [1:0] out_target_count;

    integer lower;
    integer middle;
    integer upper;
    integer valid_count;
    integer expected_index;
    integer expected_targets;
    reg expected_valid;
    reg expected_discontinuous;
    reg expected_transition;
    reg expected_policy;
    reg [8:0] expected_settled;
    reg [215:0] seen_indices;

    bardo_tx1 #(.LANES(LANES)) dut (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(in_valid),
        .in_ready(in_ready),
        .in_lines(in_lines),
        .out_valid(out_valid),
        .out_ready(out_ready),
        .out_valid_mask(out_valid_mask),
        .out_trigram_index(out_trigram_index),
        .out_policy_allow(out_policy_allow),
        .out_settled_lines(out_settled_lines),
        .out_any_discontinuous(out_any_discontinuous),
        .out_any_transition(out_any_transition),
        .out_target_count(out_target_count)
    );

    always #5 clk = ~clk;

    function automatic expected_line_valid;
        input [2:0] code;
        begin
            case (code)
                3'b000,
                3'b010,
                3'b011,
                3'b100,
                3'b101,
                3'b110: expected_line_valid = 1'b1;
                default: expected_line_valid = 1'b0;
            endcase
        end
    endfunction

    function automatic integer expected_digit;
        input [2:0] code;
        begin
            case (code)
                3'b000: expected_digit = 0;
                3'b010: expected_digit = 1;
                3'b011: expected_digit = 2;
                3'b100: expected_digit = 3;
                3'b101: expected_digit = 4;
                3'b110: expected_digit = 5;
                default: expected_digit = 0;
            endcase
        end
    endfunction

    function automatic [2:0] expected_settle_line;
        input [2:0] code;
        begin
            expected_settle_line = code[1] ? 3'b110 : 3'b000;
        end
    endfunction

    task automatic fail;
        input [1023:0] message;
        begin
            $display("FAIL: %0s", message);
            $fatal(1);
        end
    endtask

    task automatic print_context;
        input [2:0] a;
        input [2:0] b;
        input [2:0] c;
        begin
            $display(
                "CONTEXT lower=%03b middle=%03b upper=%03b valid(got/expected)=%b/%b index(got/expected)=%0d/%0d policy(got/expected)=%b/%b settled(got/expected)=%09b/%09b discontinuity(got/expected)=%b/%b transition(got/expected)=%b/%b targets(got/expected)=%0d/%0d",
                a,
                b,
                c,
                out_valid_mask[0],
                expected_valid,
                out_trigram_index,
                expected_index,
                out_policy_allow[0],
                expected_policy,
                out_settled_lines,
                expected_settled,
                out_any_discontinuous[0],
                expected_discontinuous,
                out_any_transition[0],
                expected_transition,
                out_target_count,
                expected_targets
            );
        end
    endtask

    task automatic drive_and_check;
        input [2:0] a;
        input [2:0] b;
        input [2:0] c;
        begin
            expected_valid = expected_line_valid(a)
                && expected_line_valid(b)
                && expected_line_valid(c);
            expected_index = expected_digit(a)
                + (6 * expected_digit(b))
                + (36 * expected_digit(c));
            expected_discontinuous = a[0] | b[0] | c[0];
            expected_transition = (a[2] ^ a[1]) | (b[2] ^ b[1]) | (c[2] ^ c[1]);
            expected_targets = (a[1] ? 1 : 0) + (b[1] ? 1 : 0) + (c[1] ? 1 : 0);
            expected_policy = expected_valid
                && !expected_discontinuous
                && (expected_targets >= 2)
                && expected_transition;
            expected_settled = {
                expected_settle_line(c),
                expected_settle_line(b),
                expected_settle_line(a)
            };

            @(negedge clk);
            if (!in_ready)
                fail("input unexpectedly backpressured during exhaustive pass");
            in_lines = {c, b, a};
            in_valid = 1'b1;

            @(posedge clk);
            #1;
            if (!out_valid) begin
                print_context(a, b, c);
                fail("output valid did not follow accepted input");
            end
            if (out_valid_mask[0] !== expected_valid) begin
                print_context(a, b, c);
                fail("valid-mask mismatch");
            end

            if (!expected_valid) begin
                if (out_trigram_index !== 8'b0) begin
                    print_context(a, b, c);
                    fail("invalid bundle leaked a trigram index");
                end
                if (out_policy_allow[0] !== 1'b0) begin
                    print_context(a, b, c);
                    fail("invalid bundle did not fail policy closed");
                end
                if (out_settled_lines !== 9'b0) begin
                    print_context(a, b, c);
                    fail("invalid bundle leaked settled state");
                end
                if (out_any_discontinuous[0] !== 1'b0) begin
                    print_context(a, b, c);
                    fail("invalid bundle leaked discontinuity feature");
                end
                if (out_any_transition[0] !== 1'b0) begin
                    print_context(a, b, c);
                    fail("invalid bundle leaked transition feature");
                end
                if (out_target_count !== 2'b0) begin
                    print_context(a, b, c);
                    fail("invalid bundle leaked target count");
                end
            end else begin
                valid_count = valid_count + 1;
                if (out_trigram_index !== expected_index[7:0]) begin
                    print_context(a, b, c);
                    fail("radix-6 trigram index mismatch");
                end
                if (seen_indices[expected_index]) begin
                    print_context(a, b, c);
                    fail("two valid sparse trigrams aliased to one dense index");
                end
                seen_indices[expected_index] = 1'b1;
                if (out_policy_allow[0] !== expected_policy) begin
                    print_context(a, b, c);
                    fail("reference policy mismatch");
                end
                if (out_settled_lines !== expected_settled) begin
                    print_context(a, b, c);
                    fail("settled bundle mismatch");
                end
                if (out_any_discontinuous[0] !== expected_discontinuous) begin
                    print_context(a, b, c);
                    fail("discontinuity feature mismatch");
                end
                if (out_any_transition[0] !== expected_transition) begin
                    print_context(a, b, c);
                    fail("transition feature mismatch");
                end
                if (out_target_count !== expected_targets[1:0]) begin
                    print_context(a, b, c);
                    fail("target-count mismatch");
                end
            end
        end
    endtask

    initial begin
        valid_count = 0;
        seen_indices = {216{1'b0}};

        // A producer may leave valid asserted or exit reset before this core.
        // The core must not advertise a handshake while its reset branch would
        // discard the transfer.
        repeat (2) @(posedge clk);
        @(negedge clk);
        in_lines = {3'b110, 3'b110, 3'b010};
        in_valid = 1'b1;
        #1;
        if (in_ready !== 1'b0)
            fail("input ready asserted during reset");
        @(posedge clk);
        #1;
        if (in_ready !== 1'b0)
            fail("input ready asserted after a reset clock edge");
        if (out_valid !== 1'b0)
            fail("reset-time input was captured despite no legal handshake");

        @(negedge clk);
        rst_n = 1'b1;
        in_valid = 1'b0;
        #1;
        if (in_ready !== 1'b1)
            fail("input ready did not assert after reset release");

        for (upper = 0; upper < 8; upper = upper + 1)
            for (middle = 0; middle < 8; middle = middle + 1)
                for (lower = 0; lower < 8; lower = lower + 1)
                    drive_and_check(lower[2:0], middle[2:0], upper[2:0]);

        if (valid_count != 216)
            fail("valid state count was not 216");
        if (seen_indices !== {216{1'b1}})
            fail("dense radix-6 output did not cover every index 0..215");

        // Drain the final item.
        @(negedge clk);
        in_valid = 1'b0;
        @(posedge clk);
        #1;
        if (out_valid)
            fail("output valid did not clear after an empty accepted cycle");

        // Backpressure contract: once full, all result fields must hold.
        @(negedge clk);
        out_ready = 1'b0;
        in_lines = {3'b110, 3'b110, 3'b010};
        in_valid = 1'b1;
        @(posedge clk);
        #1;
        if (!out_valid || !out_policy_allow[0])
            fail("failed to load backpressure fixture");
        if (in_ready)
            fail("input ready remained high while output was stalled");

        @(negedge clk);
        in_lines = {3'b001, 3'b001, 3'b001};
        repeat (3) begin
            @(posedge clk);
            #1;
            if (!out_valid || !out_policy_allow[0])
                fail("stalled output changed under backpressure");
            if (out_trigram_index !== 8'd211)
                fail("stalled trigram index changed under backpressure");
        end

        @(negedge clk);
        in_valid = 1'b0;
        out_ready = 1'b1;
        @(posedge clk);
        #1;
        if (out_valid)
            fail("stalled item did not retire when ready returned");

        $display("PASS: reset-safe handshake, exhaustive 512-bundle contract, 216-state bijection, and backpressure");
        $finish;
    end
endmodule

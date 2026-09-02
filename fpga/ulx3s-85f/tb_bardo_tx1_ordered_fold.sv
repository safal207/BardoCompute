`timescale 1ns/1ps

module bardo_tx1_ordered_fold_tb;
    localparam integer LANES = 71;
    localparam integer MAX_FRAMES = 64;

    reg clk = 1'b0;
    reg rst_n = 1'b0;
    reg in_valid = 1'b0;
    reg [8:0] in_epoch_position = 9'h000;
    reg [(LANES * 32) - 1:0] in_lane_payload = {(LANES * 32){1'b0}};

    wire out_valid;
    wire [8:0] out_epoch_position;
    wire [63:0] out_fold;

    reg [8:0] expected_epochs [0:MAX_FRAMES - 1];
    reg [63:0] expected_folds [0:MAX_FRAMES - 1];
    reg expected_stage1_valid = 1'b0;
    reg expected_out_valid = 1'b0;

    integer accepted_count;
    integer output_count;
    integer cycle_index;
    integer frame_index;

    bardo_tx1_ordered_fold dut (
        .clk(clk),
        .rst_n(rst_n),
        .in_valid(in_valid),
        .in_epoch_position(in_epoch_position),
        .in_lane_payload(in_lane_payload),
        .out_valid(out_valid),
        .out_epoch_position(out_epoch_position),
        .out_fold(out_fold)
    );

    always #5 clk = ~clk;

    function automatic [63:0] position_term;
        input [31:0] payload;
        input integer lane_index;
        integer shift_a;
        integer shift_b;
        reg [63:0] expanded_payload;
        begin
            if (lane_index < 32) begin
                shift_a = 0;
                shift_b = lane_index + 1;
            end else if (lane_index < 63) begin
                shift_a = 1;
                shift_b = lane_index - 30;
            end else begin
                shift_a = 2;
                shift_b = lane_index - 60;
            end

            expanded_payload = {32'h00000000, payload};
            position_term = (expanded_payload << shift_a)
                ^ (expanded_payload << shift_b);
        end
    endfunction

    task automatic fail;
        input [1023:0] message;
        begin
            $display("FAIL: %0s", message);
            $fatal(1);
        end
    endtask

    task automatic drive_cycle;
        input valid_value;
        input integer frame_sequence;
        integer lane_index;
        reg [31:0] payload;
        reg [63:0] expected_fold;
        begin
            @(negedge clk);
            in_valid = valid_value;

            if (valid_value) begin
                if (accepted_count >= MAX_FRAMES)
                    fail("testbench expected-frame storage exhausted");

                in_epoch_position = ((frame_sequence * 73) + 19) & 9'h1ff;
                expected_fold = 64'h0000000000000000;
                for (lane_index = 0; lane_index < LANES; lane_index = lane_index + 1) begin
                    payload = 32'h9e3779b9
                        ^ (frame_sequence * 32'h01010101)
                        ^ (lane_index * 32'h045d9f3b);
                    in_lane_payload[(lane_index * 32) +: 32] = payload;
                    expected_fold = expected_fold
                        ^ position_term(payload, lane_index);
                end

                expected_epochs[accepted_count] = in_epoch_position;
                expected_folds[accepted_count] = expected_fold;
                accepted_count = accepted_count + 1;
            end else begin
                // Invalid cycles carry poison so an accidental capture cannot
                // look like a valid all-zero frame.
                in_epoch_position = 9'hxxx;
                in_lane_payload = {(LANES * 32){1'bx}};
            end
        end
    endtask

    always @(posedge clk) begin
        if (!rst_n) begin
            expected_stage1_valid = 1'b0;
            expected_out_valid = 1'b0;
            #1;
            if (out_valid !== 1'b0)
                fail("ordered-fold output valid asserted during reset");
        end else begin
            expected_out_valid = expected_stage1_valid;
            expected_stage1_valid = in_valid;
            #1;

            if (out_valid !== expected_out_valid)
                fail("ordered-fold valid latency or bubble mismatch");

            if (out_valid) begin
                if (output_count >= accepted_count)
                    fail("ordered-fold emitted an unaccepted frame");
                if (out_epoch_position !== expected_epochs[output_count])
                    fail("ordered-fold changed frame epoch identity or order");
                if (out_fold !== expected_folds[output_count])
                    fail("ordered-fold output differs from dynamic lane fold");
                output_count = output_count + 1;
            end
        end
    end

    initial begin
        accepted_count = 0;
        output_count = 0;
        frame_index = 0;

        repeat (3) @(posedge clk);
        @(negedge clk);
        rst_n = 1'b1;

        // Mix long back-to-back runs with isolated bubbles. Epoch identities
        // are intentionally non-monotonic, so order cannot pass by coincidence.
        for (cycle_index = 0; cycle_index < 48; cycle_index = cycle_index + 1) begin
            if (((cycle_index % 7) == 2) || ((cycle_index % 11) == 6))
                drive_cycle(1'b0, 0);
            else begin
                drive_cycle(1'b1, frame_index);
                frame_index = frame_index + 1;
            end
        end

        repeat (4) drive_cycle(1'b0, 0);
        @(posedge clk);
        #2;

        if (accepted_count < 32)
            fail("dynamic regression did not exercise enough accepted frames");
        if (output_count != accepted_count)
            fail("ordered-fold pipeline did not drain every accepted frame");
        if (out_valid !== 1'b0)
            fail("ordered-fold output remained valid after pipeline drain");

        $display("PASS: dynamic ordered-fold pipeline preserves exact output and epoch order");
        $finish;
    end
endmodule

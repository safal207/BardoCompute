`timescale 1ns/1ps

// BARDO-TX1 v0.1
//
// A parameterized streaming transition-state accelerator. Each lane consumes
// three ordered packed Bardo line codes (lower, middle, upper), each using the
// existing three-bit [source, target, discontinuity] representation.
//
// The core is deliberately small and falsifiable:
//   * validate all six legal line states;
//   * fail closed on the two reserved line codes;
//   * compress a valid trigram to one radix-6 byte (0..215);
//   * settle every line to its target stable state;
//   * expose transition/discontinuity/target-count features;
//   * evaluate the existing joint reference policy.
//
// One registered bundle is accepted per cycle when in_ready is high. Output
// is held stable under backpressure.
module bardo_tx1 #(
    parameter integer LANES = 8
) (
    input  wire                         clk,
    input  wire                         rst_n,

    input  wire                         in_valid,
    output wire                         in_ready,
    input  wire [(LANES * 9) - 1:0]    in_lines,

    output reg                          out_valid,
    input  wire                         out_ready,
    output reg  [LANES - 1:0]          out_valid_mask,
    output reg  [(LANES * 8) - 1:0]    out_trigram_index,
    output reg  [LANES - 1:0]          out_policy_allow,
    output reg  [(LANES * 9) - 1:0]    out_settled_lines,
    output reg  [LANES - 1:0]          out_any_discontinuous,
    output reg  [LANES - 1:0]          out_any_transition,
    output reg  [(LANES * 2) - 1:0]    out_target_count
);

    function automatic line_valid;
        input [2:0] code;
        begin
            case (code)
                3'b000,
                3'b010,
                3'b011,
                3'b100,
                3'b101,
                3'b110: line_valid = 1'b1;
                default: line_valid = 1'b0;
            endcase
        end
    endfunction

    function automatic [2:0] line_digit;
        input [2:0] code;
        begin
            case (code)
                3'b000: line_digit = 3'd0;
                3'b010: line_digit = 3'd1;
                3'b011: line_digit = 3'd2;
                3'b100: line_digit = 3'd3;
                3'b101: line_digit = 3'd4;
                3'b110: line_digit = 3'd5;
                default: line_digit = 3'd0;
            endcase
        end
    endfunction

    function automatic [2:0] settle_line;
        input [2:0] code;
        begin
            settle_line = code[1] ? 3'b110 : 3'b000;
        end
    endfunction

    function automatic bundle_valid;
        input [8:0] bundle;
        begin
            bundle_valid = line_valid(bundle[2:0])
                && line_valid(bundle[5:3])
                && line_valid(bundle[8:6]);
        end
    endfunction

    function automatic [7:0] trigram_index_fn;
        input [8:0] bundle;
        reg [7:0] lower_digit;
        reg [7:0] middle_digit;
        reg [7:0] upper_digit;
        begin
            lower_digit = {5'b0, line_digit(bundle[2:0])};
            middle_digit = {5'b0, line_digit(bundle[5:3])};
            upper_digit = {5'b0, line_digit(bundle[8:6])};
            trigram_index_fn = lower_digit
                + (middle_digit * 8'd6)
                + (upper_digit * 8'd36);
        end
    endfunction

    function automatic bundle_any_discontinuous;
        input [8:0] bundle;
        begin
            bundle_any_discontinuous = bundle[0] | bundle[3] | bundle[6];
        end
    endfunction

    function automatic bundle_any_transition;
        input [8:0] bundle;
        begin
            bundle_any_transition =
                (bundle[2] ^ bundle[1])
                | (bundle[5] ^ bundle[4])
                | (bundle[8] ^ bundle[7]);
        end
    endfunction

    function automatic [1:0] bundle_target_count;
        input [8:0] bundle;
        begin
            bundle_target_count = {1'b0, bundle[1]}
                + {1'b0, bundle[4]}
                + {1'b0, bundle[7]};
        end
    endfunction

    function automatic bundle_policy_allow;
        input [8:0] bundle;
        reg [1:0] targets;
        begin
            targets = bundle_target_count(bundle);
            bundle_policy_allow = bundle_valid(bundle)
                && !bundle_any_discontinuous(bundle)
                && (targets >= 2)
                && bundle_any_transition(bundle);
        end
    endfunction

    function automatic [8:0] bundle_settled;
        input [8:0] bundle;
        begin
            bundle_settled = {
                settle_line(bundle[8:6]),
                settle_line(bundle[5:3]),
                settle_line(bundle[2:0])
            };
        end
    endfunction

    reg [LANES - 1:0]       next_valid_mask;
    reg [(LANES * 8) - 1:0] next_trigram_index;
    reg [LANES - 1:0]       next_policy_allow;
    reg [(LANES * 9) - 1:0] next_settled_lines;
    reg [LANES - 1:0]       next_any_discontinuous;
    reg [LANES - 1:0]       next_any_transition;
    reg [(LANES * 2) - 1:0] next_target_count;

    integer lane;
    reg [8:0] lane_bundle;
    reg lane_is_valid;

    always @* begin
        next_valid_mask = {LANES{1'b0}};
        next_trigram_index = {(LANES * 8){1'b0}};
        next_policy_allow = {LANES{1'b0}};
        next_settled_lines = {(LANES * 9){1'b0}};
        next_any_discontinuous = {LANES{1'b0}};
        next_any_transition = {LANES{1'b0}};
        next_target_count = {(LANES * 2){1'b0}};
        lane_bundle = 9'b0;
        lane_is_valid = 1'b0;

        for (lane = 0; lane < LANES; lane = lane + 1) begin
            lane_bundle = in_lines[(lane * 9) +: 9];
            lane_is_valid = bundle_valid(lane_bundle);
            next_valid_mask[lane] = lane_is_valid;

            if (lane_is_valid) begin
                next_trigram_index[(lane * 8) +: 8] = trigram_index_fn(lane_bundle);
                next_policy_allow[lane] = bundle_policy_allow(lane_bundle);
                next_settled_lines[(lane * 9) +: 9] = bundle_settled(lane_bundle);
                next_any_discontinuous[lane] = bundle_any_discontinuous(lane_bundle);
                next_any_transition[lane] = bundle_any_transition(lane_bundle);
                next_target_count[(lane * 2) +: 2] = bundle_target_count(lane_bundle);
            end
        end
    end

    assign in_ready = !out_valid || out_ready;

    always @(posedge clk) begin
        if (!rst_n) begin
            out_valid <= 1'b0;
            out_valid_mask <= {LANES{1'b0}};
            out_trigram_index <= {(LANES * 8){1'b0}};
            out_policy_allow <= {LANES{1'b0}};
            out_settled_lines <= {(LANES * 9){1'b0}};
            out_any_discontinuous <= {LANES{1'b0}};
            out_any_transition <= {LANES{1'b0}};
            out_target_count <= {(LANES * 2){1'b0}};
        end else if (in_ready) begin
            out_valid <= in_valid;
            if (in_valid) begin
                out_valid_mask <= next_valid_mask;
                out_trigram_index <= next_trigram_index;
                out_policy_allow <= next_policy_allow;
                out_settled_lines <= next_settled_lines;
                out_any_discontinuous <= next_any_discontinuous;
                out_any_transition <= next_any_transition;
                out_target_count <= next_target_count;
            end else begin
                out_valid_mask <= {LANES{1'b0}};
                out_trigram_index <= {(LANES * 8){1'b0}};
                out_policy_allow <= {LANES{1'b0}};
                out_settled_lines <= {(LANES * 9){1'b0}};
                out_any_discontinuous <= {LANES{1'b0}};
                out_any_transition <= {LANES{1'b0}};
                out_target_count <= {(LANES * 2){1'b0}};
            end
        end
    end

endmodule

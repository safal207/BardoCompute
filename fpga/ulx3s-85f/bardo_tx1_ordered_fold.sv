`timescale 1ns/1ps

// Two-stage, multiplier-free ordered fold for the 71-lane ULX3S self-test.
//
// Stage 1 reduces at most eight lane-bound semantic records per group.
// Stage 2 combines nine registered groups. The pipeline accepts one frame
// every cycle while removing the 71-lane fold from the signature feedback path.
module bardo_tx1_ordered_fold (
    input  wire                  clk,
    input  wire                  rst_n,
    input  wire                  in_valid,
    input  wire [8:0]            in_epoch_position,
    input  wire [(71 * 32) - 1:0] in_lane_payload,

    output reg                   out_valid,
    output reg  [8:0]            out_epoch_position,
    output reg  [63:0]           out_fold
);

    localparam integer LANES = 71;

    wire [(LANES * 64) - 1:0] lane_position_term;
    genvar lane;
    generate
        for (lane = 0; lane < LANES; lane = lane + 1) begin : generate_position_terms
            localparam integer SHIFT_A =
                (lane < 32) ? 0 : ((lane < 63) ? 1 : 2);
            localparam integer SHIFT_B =
                (lane < 32) ? (lane + 1)
                : ((lane < 63) ? (lane - 30) : (lane - 60));
            wire [63:0] expanded_payload;

            assign expanded_payload = {
                32'h00000000,
                in_lane_payload[(lane * 32) +: 32]
            };
            assign lane_position_term[(lane * 64) +: 64] =
                (expanded_payload << SHIFT_A) ^ (expanded_payload << SHIFT_B);
        end
    endgenerate

    wire [63:0] group_fold_comb_0;
    assign group_fold_comb_0 = lane_position_term[(0 * 64) +: 64]
        ^ lane_position_term[(1 * 64) +: 64]
        ^ lane_position_term[(2 * 64) +: 64]
        ^ lane_position_term[(3 * 64) +: 64]
        ^ lane_position_term[(4 * 64) +: 64]
        ^ lane_position_term[(5 * 64) +: 64]
        ^ lane_position_term[(6 * 64) +: 64]
        ^ lane_position_term[(7 * 64) +: 64];

    wire [63:0] group_fold_comb_1;
    assign group_fold_comb_1 = lane_position_term[(8 * 64) +: 64]
        ^ lane_position_term[(9 * 64) +: 64]
        ^ lane_position_term[(10 * 64) +: 64]
        ^ lane_position_term[(11 * 64) +: 64]
        ^ lane_position_term[(12 * 64) +: 64]
        ^ lane_position_term[(13 * 64) +: 64]
        ^ lane_position_term[(14 * 64) +: 64]
        ^ lane_position_term[(15 * 64) +: 64];

    wire [63:0] group_fold_comb_2;
    assign group_fold_comb_2 = lane_position_term[(16 * 64) +: 64]
        ^ lane_position_term[(17 * 64) +: 64]
        ^ lane_position_term[(18 * 64) +: 64]
        ^ lane_position_term[(19 * 64) +: 64]
        ^ lane_position_term[(20 * 64) +: 64]
        ^ lane_position_term[(21 * 64) +: 64]
        ^ lane_position_term[(22 * 64) +: 64]
        ^ lane_position_term[(23 * 64) +: 64];

    wire [63:0] group_fold_comb_3;
    assign group_fold_comb_3 = lane_position_term[(24 * 64) +: 64]
        ^ lane_position_term[(25 * 64) +: 64]
        ^ lane_position_term[(26 * 64) +: 64]
        ^ lane_position_term[(27 * 64) +: 64]
        ^ lane_position_term[(28 * 64) +: 64]
        ^ lane_position_term[(29 * 64) +: 64]
        ^ lane_position_term[(30 * 64) +: 64]
        ^ lane_position_term[(31 * 64) +: 64];

    wire [63:0] group_fold_comb_4;
    assign group_fold_comb_4 = lane_position_term[(32 * 64) +: 64]
        ^ lane_position_term[(33 * 64) +: 64]
        ^ lane_position_term[(34 * 64) +: 64]
        ^ lane_position_term[(35 * 64) +: 64]
        ^ lane_position_term[(36 * 64) +: 64]
        ^ lane_position_term[(37 * 64) +: 64]
        ^ lane_position_term[(38 * 64) +: 64]
        ^ lane_position_term[(39 * 64) +: 64];

    wire [63:0] group_fold_comb_5;
    assign group_fold_comb_5 = lane_position_term[(40 * 64) +: 64]
        ^ lane_position_term[(41 * 64) +: 64]
        ^ lane_position_term[(42 * 64) +: 64]
        ^ lane_position_term[(43 * 64) +: 64]
        ^ lane_position_term[(44 * 64) +: 64]
        ^ lane_position_term[(45 * 64) +: 64]
        ^ lane_position_term[(46 * 64) +: 64]
        ^ lane_position_term[(47 * 64) +: 64];

    wire [63:0] group_fold_comb_6;
    assign group_fold_comb_6 = lane_position_term[(48 * 64) +: 64]
        ^ lane_position_term[(49 * 64) +: 64]
        ^ lane_position_term[(50 * 64) +: 64]
        ^ lane_position_term[(51 * 64) +: 64]
        ^ lane_position_term[(52 * 64) +: 64]
        ^ lane_position_term[(53 * 64) +: 64]
        ^ lane_position_term[(54 * 64) +: 64]
        ^ lane_position_term[(55 * 64) +: 64];

    wire [63:0] group_fold_comb_7;
    assign group_fold_comb_7 = lane_position_term[(56 * 64) +: 64]
        ^ lane_position_term[(57 * 64) +: 64]
        ^ lane_position_term[(58 * 64) +: 64]
        ^ lane_position_term[(59 * 64) +: 64]
        ^ lane_position_term[(60 * 64) +: 64]
        ^ lane_position_term[(61 * 64) +: 64]
        ^ lane_position_term[(62 * 64) +: 64]
        ^ lane_position_term[(63 * 64) +: 64];

    wire [63:0] group_fold_comb_8;
    assign group_fold_comb_8 = lane_position_term[(64 * 64) +: 64]
        ^ lane_position_term[(65 * 64) +: 64]
        ^ lane_position_term[(66 * 64) +: 64]
        ^ lane_position_term[(67 * 64) +: 64]
        ^ lane_position_term[(68 * 64) +: 64]
        ^ lane_position_term[(69 * 64) +: 64]
        ^ lane_position_term[(70 * 64) +: 64];

    reg [63:0] group_fold_stage1_0;
    reg [63:0] group_fold_stage1_1;
    reg [63:0] group_fold_stage1_2;
    reg [63:0] group_fold_stage1_3;
    reg [63:0] group_fold_stage1_4;
    reg [63:0] group_fold_stage1_5;
    reg [63:0] group_fold_stage1_6;
    reg [63:0] group_fold_stage1_7;
    reg [63:0] group_fold_stage1_8;
    reg        stage1_valid;
    reg [8:0]  stage1_epoch_position;

    wire [63:0] combined_fold_stage2 =
        group_fold_stage1_0
        ^ group_fold_stage1_1
        ^ group_fold_stage1_2
        ^ group_fold_stage1_3
        ^ group_fold_stage1_4
        ^ group_fold_stage1_5
        ^ group_fold_stage1_6
        ^ group_fold_stage1_7
        ^ group_fold_stage1_8;

    always @(posedge clk) begin
        if (!rst_n) begin
            group_fold_stage1_0 <= 64'h0000000000000000;
            group_fold_stage1_1 <= 64'h0000000000000000;
            group_fold_stage1_2 <= 64'h0000000000000000;
            group_fold_stage1_3 <= 64'h0000000000000000;
            group_fold_stage1_4 <= 64'h0000000000000000;
            group_fold_stage1_5 <= 64'h0000000000000000;
            group_fold_stage1_6 <= 64'h0000000000000000;
            group_fold_stage1_7 <= 64'h0000000000000000;
            group_fold_stage1_8 <= 64'h0000000000000000;
            stage1_valid <= 1'b0;
            stage1_epoch_position <= 9'h000;
            out_valid <= 1'b0;
            out_epoch_position <= 9'h000;
            out_fold <= 64'h0000000000000000;
        end else begin
            stage1_valid <= in_valid;
            if (in_valid) begin
                group_fold_stage1_0 <= group_fold_comb_0;
                group_fold_stage1_1 <= group_fold_comb_1;
                group_fold_stage1_2 <= group_fold_comb_2;
                group_fold_stage1_3 <= group_fold_comb_3;
                group_fold_stage1_4 <= group_fold_comb_4;
                group_fold_stage1_5 <= group_fold_comb_5;
                group_fold_stage1_6 <= group_fold_comb_6;
                group_fold_stage1_7 <= group_fold_comb_7;
                group_fold_stage1_8 <= group_fold_comb_8;
                stage1_epoch_position <= in_epoch_position;
            end

            out_valid <= stage1_valid;
            if (stage1_valid) begin
                out_epoch_position <= stage1_epoch_position;
                out_fold <= combined_fold_stage2;
            end
        end
    end

endmodule

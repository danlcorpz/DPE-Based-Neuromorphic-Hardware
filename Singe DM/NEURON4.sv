module SynapseUnit #(
    parameter int WEIGHT_W = 6
)(
    input  logic                       enable,
    input  logic                       spike_in,
    input  logic signed [WEIGHT_W-1:0] weight,
    output logic signed [WEIGHT_W-1:0] syn_out
);
    assign syn_out = (enable && spike_in) ? weight : '0;
endmodule

module Accumulator #(
    parameter int N_INPUTS = 4,
    parameter int WEIGHT_W = 6,
    parameter int MP_W     = 10,
    parameter int THRESH_W = 10,
    parameter int LEAK_W   = 4,
    parameter int REFRAC_W = 4
)(
    input  logic                       clk,
    input  logic                       rst,
    input  logic                       enable,

    input  logic signed [WEIGHT_W-1:0] syn_in [N_INPUTS],

    input  logic signed [THRESH_W-1:0] threshold,
    input  logic [LEAK_W-1:0]          leak_rate,
    input  logic [REFRAC_W-1:0]        refractory_period,

    input  logic                       force_reset,
    input  logic                       beat_clear,
    output logic                       fire
);
    logic signed [MP_W-1:0] mp;
    logic [LEAK_W-1:0]      leak_counter;
    logic [REFRAC_W-1:0]    refrac_cnt;
    logic                   in_refractory;

    assign in_refractory = (refrac_cnt != '0);

    logic signed [MP_W-1:0] syn_total;
    always_comb begin
        syn_total = '0;
        if (enable && !in_refractory) begin
            for (int i = 0; i < N_INPUTS; i++)
                syn_total = syn_total + MP_W'(syn_in[i]);
        end
    end

    localparam int MP_HI = (1 << (MP_W-1)) - 1;   //  +511 for MP_W=10
    localparam int MP_LO = -(1 << (MP_W-1));       //  -512 for MP_W=10

    logic signed [MP_W+1:0] acc_wide;              // 2 guard bits: mp + up to N_INPUTS weights
    assign acc_wide = $signed(mp) + $signed(syn_total);

    logic signed [MP_W-1:0] next_accum;
    assign next_accum = (acc_wide > MP_HI) ? MP_W'(MP_HI) :
                        (acc_wide < MP_LO) ? MP_W'(MP_LO) :
                                             acc_wide[MP_W-1:0];

    logic leak_tick;
    assign leak_tick = (leak_counter >= leak_rate);

    logic signed [MP_W-1:0] mp_next;
    assign mp_next = (!leak_tick)      ? next_accum :
                     (next_accum > 0)  ? (next_accum - 1) :
                     (next_accum < 0)  ? (next_accum + 1) : next_accum;

    always_ff @(posedge clk or posedge rst) begin
        if (rst || !enable) begin
            mp <= '0; leak_counter <= '0; refrac_cnt <= '0; fire <= 1'b0;
        end else if (beat_clear) begin
            mp <= '0; leak_counter <= '0; refrac_cnt <= '0; fire <= 1'b0;
        end else if (force_reset) begin
            mp <= '0; leak_counter <= '0; fire <= 1'b0;
        end else if (in_refractory) begin
            refrac_cnt   <= refrac_cnt - 1'b1;
            mp           <= mp_next;
            leak_counter <= leak_tick ? '0 : (leak_counter + 1'b1);
            fire         <= 1'b0;
        end else if (mp_next >= threshold) begin
            mp           <= '0;
            leak_counter <= '0;
            refrac_cnt   <= refractory_period;
            fire         <= 1'b1;
        end else begin
            mp           <= mp_next;
            leak_counter <= leak_tick ? '0 : (leak_counter + 1'b1);
            fire         <= 1'b0;
        end
    end
endmodule
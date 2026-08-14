module DotProductEngine5 #(
    parameter int N_INPUTS  = 4,
    parameter int N_NEURONS = 5,
    parameter int WEIGHT_W  = 6,
    parameter int MP_W      = 10,
    parameter int THRESH_W  = 10,
    parameter int LEAK_W    = 4,
    parameter int REFRAC_W  = 4
)(
    input  logic clk,
    input  logic rst,
    input  logic enable,

    input  logic [N_INPUTS-1:0]        spikes,

    input  logic signed [WEIGHT_W-1:0] weights    [N_INPUTS*N_NEURONS],
    input  logic signed [THRESH_W-1:0] thresholds [N_NEURONS],

    input  logic [LEAK_W-1:0]          leak_rate,
    input  logic [REFRAC_W-1:0]        refractory_period,

    input  logic [N_NEURONS-1:0]       reset_others,
    input  logic                       beat_clear,

    output logic [N_NEURONS-1:0]       fire
);
    logic signed [WEIGHT_W-1:0] syn_out [N_INPUTS*N_NEURONS];

    genvar i, j, k;
    generate
        for (i = 0; i < N_INPUTS; i++) begin : gen_inputs
            for (j = 0; j < N_NEURONS; j++) begin : gen_outputs
                SynapseUnit #(
                    .WEIGHT_W(WEIGHT_W)
                ) u_syn (
                    .enable(enable),
                    .spike_in(spikes[i]),
                    .weight(weights[N_NEURONS*i + j]),
                    .syn_out(syn_out[N_NEURONS*i + j])
                );
            end
        end
    endgenerate

    generate
        for (k = 0; k < N_NEURONS; k++) begin : gen_cols
            logic signed [WEIGHT_W-1:0] syn_col [N_INPUTS];
            for (genvar r = 0; r < N_INPUTS; r++) begin : gen_syn_map
                assign syn_col[r] = syn_out[N_NEURONS*r + k];
            end

            Accumulator #(
                .N_INPUTS(N_INPUTS),
                .WEIGHT_W(WEIGHT_W),
                .MP_W(MP_W),
                .THRESH_W(THRESH_W),
                .LEAK_W(LEAK_W),
                .REFRAC_W(REFRAC_W)
            ) u_accum (
                .clk(clk),
                .rst(rst),
                .enable(enable),
                .syn_in(syn_col),
                .threshold(thresholds[k]),
                .leak_rate(leak_rate),
                .refractory_period(refractory_period),
                .force_reset(reset_others[k]),
                .beat_clear(beat_clear),
                .fire(fire[k])
            );
        end
    endgenerate
endmodule
module ScanChainWrapper6 #(
    parameter int N_INPUTS_1  = 2,
    parameter int N_NEURONS_1 = 5,
    parameter int N_INPUTS_2  = N_NEURONS_1,
    parameter int N_NEURONS_2  = 5,

    parameter int DATA_W    = 11,
    parameter int STEP_W    = 4,
    parameter int MAX_VAL   = 2047,
    parameter int MIN_VAL   = 0,

    parameter int MP_W      = 10,
    parameter int THRESH_W  = 10,
    parameter int LEAK_W    = 4,
    parameter int REFRAC_W  = 4,

    parameter int WEIGHT_W   = 6,
    parameter int N_WEIGHTS_1 = N_INPUTS_1 * N_NEURONS_1,
    parameter int N_WEIGHTS_2 = N_INPUTS_2 * N_NEURONS_2,
    parameter int N_WEIGHTS  = N_WEIGHTS_1 + N_WEIGHTS_2,

    parameter int CLS_W      = $clog2(N_NEURONS_2 + 1),
    parameter int SCAN_W     = N_WEIGHTS*WEIGHT_W
                             + (N_NEURONS_1 + N_NEURONS_2)*THRESH_W
                             + 2 * LEAK_W
                             + 2 * REFRAC_W 
                             + STEP_W
)(
    input  logic              clk,
    input  logic              rst,

    input  logic [DATA_W-1:0] ecg_in,
    input  logic              scan_en,
    input  logic              scan_in,
    output logic              scan_out,
    input  logic              load,
    input  logic              beat_clear,

    output logic [CLS_W-1:0]          winner_class,
    output logic                      valid,
    output logic [N_NEURONS_2 - 1:0]  fire,
    output logic [N_NEURONS_1 - 1:0]  fire_l1,
    output logic                  sys_en
);

    //serial register offsets

    localparam int OFF_WEIGHTS_1  = 0;
    localparam int OFF_WEIGHTS_2  = OFF_WEIGHTS_1 + N_WEIGHTS_1*WEIGHT_W;
    localparam int OFF_THRESH_1   = OFF_WEIGHTS_2 + N_WEIGHTS_2*WEIGHT_W;
    localparam int OFF_THRESH_2   = OFF_THRESH_1  + N_NEURONS_1*THRESH_W;
    localparam int OFF_LEAK_1     = OFF_THRESH_2  + N_NEURONS_2*THRESH_W;
    localparam int OFF_LEAK_2     = OFF_LEAK_1    + LEAK_W;
    localparam int OFF_REFRAC_1   = OFF_LEAK_2    + LEAK_W;
    localparam int OFF_REFRAC_2   = OFF_REFRAC_1  + REFRAC_W;
    localparam int OFF_DM_STEP    = OFF_REFRAC_2  + REFRAC_W;

    //scan chain register logic

    logic [SCAN_W-1:0] scan_reg;
    always_ff @(posedge clk or posedge rst) begin
        if (rst)          scan_reg <= '0;
        else if (scan_en) scan_reg <= {scan_reg[SCAN_W-2:0], scan_in};
    end
    assign scan_out = scan_reg[SCAN_W-1];

    //parameter loading finished logic

    always_ff @(posedge clk or posedge rst) begin
        if (rst)        sys_en <= 1'b0;
        else if (load)  sys_en <= 1'b1;
    end

    //2x5 ARRAY parameters

    logic signed [WEIGHT_W-1:0] weights_r1    [N_WEIGHTS_1];
    logic signed [THRESH_W-1:0] thresholds_r1 [N_NEURONS_1];
    logic [LEAK_W-1:0]          leak_rate_r1;
    logic [REFRAC_W-1:0]        refractory_period_r1;

    logic signed [WEIGHT_W-1:0] weights_r2    [N_WEIGHTS_2];
    logic signed [THRESH_W-1:0] thresholds_r2 [N_NEURONS_2];
    logic [LEAK_W-1:0]          leak_rate_r2;
    logic [REFRAC_W-1:0]        refractory_period_r2;

    logic [STEP_W-1:0]          dm_step;


    //load parameters!

    integer wi, ti;
    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            for (wi = 0; wi < N_WEIGHTS_1; wi++) weights_r1[wi]    <= '0;
            for (wi = 0; wi < N_WEIGHTS_2; wi++) weights_r2[wi]    <= '0;
            for (ti = 0; ti < N_NEURONS_1; ti++) thresholds_r1[ti] <= '0;
            for (ti = 0; ti < N_NEURONS_2; ti++) thresholds_r2[ti] <= '0;
            leak_rate_r1         <= '0;
            refractory_period_r1 <= '0;
            leak_rate_r2         <= '0;
            refractory_period_r2 <= '0;
            dm_step              <= '0;
        end else if (load) begin
            for (wi = 0; wi < N_WEIGHTS_1; wi++)
                weights_r1[wi]    <= scan_reg[OFF_WEIGHTS_1 + wi*WEIGHT_W +: WEIGHT_W];
            for (wi = 0; wi < N_WEIGHTS_2; wi++)
                weights_r2[wi]    <= scan_reg[OFF_WEIGHTS_2 + wi*WEIGHT_W +: WEIGHT_W];
            for (ti = 0; ti < N_NEURONS_1; ti++)
                thresholds_r1[ti] <= scan_reg[OFF_THRESH_1  + ti*THRESH_W +: THRESH_W];
            for (ti = 0; ti < N_NEURONS_2; ti++)
                thresholds_r2[ti] <= scan_reg[OFF_THRESH_2  + ti*THRESH_W +: THRESH_W];
            leak_rate_r1         <= scan_reg[OFF_LEAK_1     +: LEAK_W];
            leak_rate_r2         <= scan_reg[OFF_LEAK_2     +: LEAK_W];
            refractory_period_r1 <= scan_reg[OFF_REFRAC_1   +: REFRAC_W];
            refractory_period_r2 <= scan_reg[OFF_REFRAC_2   +: REFRAC_W];
            dm_step              <= scan_reg[OFF_DM_STEP    +: STEP_W];
        end
    end

    logic dm_rst;
    assign dm_rst = rst | ~sys_en | beat_clear;

    logic [1:0] dm_spikes;
    logic [N_NEURONS_1-1:0] dpe1_fire;
    logic [N_NEURONS_2-1:0] reset_others;

    // Instantiation and Connections!

    DeltaModulator6 #(
        .DATA_W(DATA_W), .STEP_W(STEP_W), .MAX_VAL(MAX_VAL), .MIN_VAL(MIN_VAL)
    ) u_dm (
        .clk(clk), .dm_rst(dm_rst), .analog_in(ecg_in), 
        .step_size(dm_step), .spike_out(dm_spikes), .approx_signal()
    );

    logic [N_INPUTS_1-1:0] spikes;
    assign spikes[0] = dm_spikes[0];
    assign spikes[1] = dm_spikes[1];

    assign fire_l1 = dpe1_fire;

    DotProductEngine6 #(
        .N_INPUTS(N_INPUTS_1), .N_NEURONS(N_NEURONS_1), .WEIGHT_W(WEIGHT_W),
        .MP_W(MP_W), .THRESH_W(THRESH_W), .LEAK_W(LEAK_W), .REFRAC_W(REFRAC_W)
    ) u_dpe1 (
        .clk(clk), .rst(rst), .enable(sys_en),
        .spikes(spikes),
        .weights(weights_r1), .thresholds(thresholds_r1),
        .leak_rate(leak_rate_r1), .refractory_period(refractory_period_r1),
        .reset_others({N_NEURONS_1{1'b0}}), .beat_clear(beat_clear),
        .fire(dpe1_fire)
    );

    DotProductEngine6 #(
        .N_INPUTS(N_INPUTS_2), .N_NEURONS(N_NEURONS_2), .WEIGHT_W(WEIGHT_W),
        .MP_W(MP_W), .THRESH_W(THRESH_W), .LEAK_W(LEAK_W), .REFRAC_W(REFRAC_W)
    ) u_dpe2 (
        .clk(clk), .rst(rst), .enable(sys_en),
        .spikes(dpe1_fire),
        .weights(weights_r2), .thresholds(thresholds_r2),
        .leak_rate(leak_rate_r2), .refractory_period(refractory_period_r2),
        .reset_others(reset_others), .beat_clear(beat_clear),
        .fire(fire)
    );

    WinnerTakeAll6 #(
        .N_NEURONS(N_NEURONS_2)
    ) u_wta (
        .enable(sys_en),
        .fire(fire),
        .winner_class(winner_class),
        .valid(valid),
        .reset_others(reset_others)
    );
endmodule
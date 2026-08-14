module ScanChainWrapper5 #(
    parameter int N_INPUTS  = 4,
    parameter int N_NEURONS = 5,
    
    parameter int DATA_W    = 11,
    parameter int C_STEP_W  = 8,
    parameter int F_STEP_W  = 6,
    parameter int MAX_VAL   = 2047,
    parameter int MIN_VAL   = 0,

    parameter int MP_W      = 10,
    parameter int THRESH_W  = 10,
    parameter int LEAK_W    = 4,
    parameter int REFRAC_W  = 4,

    parameter int WEIGHT_W  = 6,
    parameter int N_WEIGHTS = N_INPUTS * N_NEURONS,
    parameter int CLS_W     = $clog2(N_NEURONS + 1),
    parameter int SCAN_W    = N_WEIGHTS*WEIGHT_W + 
                  N_NEURONS*THRESH_W + LEAK_W + 
                  REFRAC_W + C_STEP_W + F_STEP_W
)(
    input  logic              clk,
    input  logic              rst,

    input  logic [DATA_W-1:0] ecg_in,
    input  logic              scan_en,
    input  logic              scan_in,
    output logic              scan_out,
    input  logic              load,
    input  logic              beat_clear,
    output logic [CLS_W-1:0]      winner_class,
    output logic                  valid,
    output logic [N_NEURONS-1:0]  fire,
    output logic                  sys_en
);

    //serial register offsets

    localparam int OFF_WEIGHTS  = 0;
    localparam int OFF_THRESH   = OFF_WEIGHTS + N_WEIGHTS*WEIGHT_W;
    localparam int OFF_LEAK     = OFF_THRESH  + N_NEURONS*THRESH_W;
    localparam int OFF_REFRAC   = OFF_LEAK    + LEAK_W;
    localparam int OFF_DM_STEP_COARSE  = OFF_REFRAC  + REFRAC_W;
    localparam int OFF_DM_STEP_FINE    = OFF_DM_STEP_COARSE + C_STEP_W;


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

    logic signed [WEIGHT_W-1:0] weights_r    [N_WEIGHTS];
    logic signed [THRESH_W-1:0] thresholds_r [N_NEURONS];
    logic [LEAK_W-1:0]          leak_rate_r;
    logic [REFRAC_W-1:0]        refractory_period_r;
    logic [C_STEP_W-1:0]          dm_step_coarse;
    logic [F_STEP_W-1:0]          dm_step_fine;

    //load parameters!

    integer wi, ti;
    always_ff @(posedge clk or posedge rst) begin
        if (rst) begin
            for (wi = 0; wi < N_WEIGHTS; wi++) weights_r[wi]    <= '0;
            for (ti = 0; ti < N_NEURONS; ti++) thresholds_r[ti] <= '0;
            leak_rate_r         <= '0;
            refractory_period_r <= '0;
            dm_step_coarse      <= '0;
            dm_step_fine        <= '0;
        end else if (load) begin
            for (wi = 0; wi < N_WEIGHTS; wi++)
                weights_r[wi]    <= scan_reg[OFF_WEIGHTS + wi*WEIGHT_W +: WEIGHT_W];
            for (ti = 0; ti < N_NEURONS; ti++)
                thresholds_r[ti] <= scan_reg[OFF_THRESH  + ti*THRESH_W +: THRESH_W];
            leak_rate_r         <= scan_reg[OFF_LEAK     +: LEAK_W];
            refractory_period_r <= scan_reg[OFF_REFRAC   +: REFRAC_W];
            dm_step_coarse      <= scan_reg[OFF_DM_STEP_COARSE  +: C_STEP_W];
            dm_step_fine        <= scan_reg[OFF_DM_STEP_FINE    +: F_STEP_W];
        end
    end

    // Interconnect signals

    logic dm_rst;
    assign dm_rst = rst | ~sys_en | beat_clear;

    logic [1:0] dm_spikes_coarse;
    logic [1:0] dm_spikes_fine;

    logic [N_NEURONS-1:0] reset_others;

    // Instantiation and Connections!

    DeltaModulator5 #(
        .DATA_W(DATA_W), .STEP_W(C_STEP_W), .MAX_VAL(MAX_VAL), .MIN_VAL(MIN_VAL)
    ) u_dm_coarse (
        .clk(clk), .dm_rst(dm_rst), .analog_in(ecg_in), 
        .step_size(dm_step_coarse), .spike_out(dm_spikes_coarse), .approx_signal()
    );

    DeltaModulator5 #(
        .DATA_W(DATA_W), .STEP_W(F_STEP_W), .MAX_VAL(MAX_VAL), .MIN_VAL(MIN_VAL)
    ) u_dm_fine (
        .clk(clk), .dm_rst(dm_rst), .analog_in(ecg_in), 
        .step_size(dm_step_fine), .spike_out(dm_spikes_fine), .approx_signal()
    );

    logic [N_INPUTS-1:0] spikes;
    assign spikes[0] = dm_spikes_coarse[0];
    assign spikes[1] = dm_spikes_coarse[1];
    assign spikes[2] = dm_spikes_fine[0];
    assign spikes[3] = dm_spikes_fine[1];

    DotProductEngine5 #(
        .N_INPUTS(N_INPUTS), .N_NEURONS(N_NEURONS), .WEIGHT_W(WEIGHT_W),
        .MP_W(MP_W), .THRESH_W(THRESH_W), .LEAK_W(LEAK_W), .REFRAC_W(REFRAC_W)
    ) u_dpe (
        .clk(clk), .rst(rst), .enable(sys_en),
        .spikes(spikes),
        .weights(weights_r), .thresholds(thresholds_r),
        .leak_rate(leak_rate_r), .refractory_period(refractory_period_r),
        .reset_others(reset_others), .beat_clear(beat_clear),
        .fire(fire)
    );

    WinnerTakeAll5 #(
        .N_NEURONS(N_NEURONS)
    ) u_wta (
        .enable(sys_en),
        .fire(fire),
        .winner_class(winner_class),
        .valid(valid),
        .reset_others(reset_others)
    );
endmodule
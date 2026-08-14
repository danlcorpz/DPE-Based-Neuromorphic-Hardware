// SCNCHN4_TB.sv -- top-level self-checking TB for the V4 single-DM scan chain.
// Programs the config over the scan chain, pulses load, then drives a synthetic
// triangle ECG: a rising ramp should make the UP-tuned neuron 0 fire and win,
// a beat_clear resets state, a falling ramp should make the DOWN-tuned neuron 1
// fire and win. Prints a per-cycle trace and a PASS/FAIL summary.
`timescale 1ns/1ps
module SCNCHN4_TB;
    // ---- must mirror ScanChainWrapper4 defaults ----
    localparam int N_INPUTS  = 2;
    localparam int N_NEURONS = 5;
    localparam int DATA_W    = 11;
    localparam int STEP_W    = 4;
    localparam int WEIGHT_W  = 6;
    localparam int THRESH_W  = 10;
    localparam int LEAK_W    = 4;
    localparam int REFRAC_W  = 4;
    localparam int N_WEIGHTS = N_INPUTS*N_NEURONS;
    localparam int CLS_W     = $clog2(N_NEURONS + 1);
    localparam int SCAN_W    = N_WEIGHTS*WEIGHT_W + N_NEURONS*THRESH_W
                               + LEAK_W + REFRAC_W + STEP_W;

    localparam int OFF_WEIGHTS = 0;
    localparam int OFF_THRESH  = OFF_WEIGHTS + N_WEIGHTS*WEIGHT_W;
    localparam int OFF_LEAK    = OFF_THRESH  + N_NEURONS*THRESH_W;
    localparam int OFF_REFRAC  = OFF_LEAK    + LEAK_W;
    localparam int OFF_DM_STEP = OFF_REFRAC  + REFRAC_W;

    // ---- DUT I/O ----
    logic clk = 0, rst = 1;
    logic [DATA_W-1:0] ecg_in = '0;
    logic scan_en = 0, scan_in = 0, load = 0, beat_clear = 0;
    logic scan_out, valid, sys_en;
    logic [CLS_W-1:0]     winner_class;
    logic [N_NEURONS-1:0] fire;

    ScanChainWrapper4 #(
        .N_INPUTS(N_INPUTS), .N_NEURONS(N_NEURONS), .DATA_W(DATA_W),
        .STEP_W(STEP_W), .WEIGHT_W(WEIGHT_W), .THRESH_W(THRESH_W),
        .LEAK_W(LEAK_W), .REFRAC_W(REFRAC_W)
    ) dut (
        .clk(clk), .rst(rst), .ecg_in(ecg_in),
        .scan_en(scan_en), .scan_in(scan_in), .scan_out(scan_out), .load(load),
        .beat_clear(beat_clear),
        .winner_class(winner_class), .valid(valid), .fire(fire), .sys_en(sys_en)
    );

    always #5 clk = ~clk;

    // ---- config assembly ----
    logic [SCAN_W-1:0]          cfg;
    logic signed [WEIGHT_W-1:0] w  [N_WEIGHTS];
    logic        [THRESH_W-1:0] th [N_NEURONS];

    task automatic build_cfg(input logic [LEAK_W-1:0]   leak,
                             input logic [REFRAC_W-1:0] refr,
                             input logic [STEP_W-1:0]   step);
        cfg = '0;
        for (int p = 0; p < N_WEIGHTS; p++)
            cfg[OFF_WEIGHTS + p*WEIGHT_W +: WEIGHT_W] = w[p];
        for (int q = 0; q < N_NEURONS; q++)
            cfg[OFF_THRESH + q*THRESH_W +: THRESH_W] = th[q];
        cfg[OFF_LEAK    +: LEAK_W]   = leak;
        cfg[OFF_REFRAC  +: REFRAC_W] = refr;
        cfg[OFF_DM_STEP +: STEP_W]   = step;
    endtask

    // shift MSB-first so cfg[k] lands at scan_reg[k], then pulse load
    task automatic program_chain;
        scan_en = 1'b1;
        for (int b = SCAN_W-1; b >= 0; b--) begin
            scan_in = cfg[b];
            @(posedge clk);
        end
        scan_en = 1'b0;
        @(posedge clk);
        load = 1'b1; @(posedge clk); load = 1'b0;
        @(posedge clk);
    endtask

    // ---- bookkeeping ----
    logic saw_fire0, saw_fire1;
    integer cyc;

    task automatic drive(input int val);
        ecg_in = val[DATA_W-1:0];
        @(posedge clk);
        cyc = cyc + 1;
        if (fire[0]) saw_fire0 = 1'b1;
        if (fire[1]) saw_fire1 = 1'b1;
        $display("  t=%0t cyc=%0d ecg=%4d spk=%b fire=%b valid=%b win=%0d",
                 $time, cyc, ecg_in, dut.spikes, fire, valid, winner_class);
    endtask

    initial begin
        saw_fire0 = 0; saw_fire1 = 0; cyc = 0;

        // weights: row0=UP, row1=DOWN; index w[row*N_NEURONS + j]
        for (int p = 0; p < N_WEIGHTS; p++) w[p] = '0;
        w[0*N_NEURONS + 0] = 6'sd20;   // UP   -> neuron 0
        w[1*N_NEURONS + 1] = 6'sd20;   // DOWN -> neuron 1
        for (int q = 0; q < N_NEURONS; q++) th[q] = 10'd30;

        // reset
        repeat (3) @(posedge clk);
        rst = 1'b0;
        @(posedge clk);

        // program: leak_rate=15 (slow), refractory=2, dm_step=4
        build_cfg(4'd15, 4'd2, 4'd4);
        program_chain();
        if (sys_en !== 1'b1) $display("FAIL: sys_en did not assert after load");
        else                 $display("ok: sys_en high after load");

        // ---- BEAT 1: rising ramp -> UP spikes -> neuron 0 ----
        $display("-- rising ramp (expect neuron 0) --");
        for (int v = 200; v <= 1600; v = v + 70) drive(v);

        // per-beat clear (resets DM + neurons)
        beat_clear = 1'b1; @(posedge clk); beat_clear = 1'b0; @(posedge clk);
        $display("-- beat_clear pulsed --");

        // ---- BEAT 2: falling ramp -> DOWN spikes -> neuron 1 ----
        $display("-- falling ramp (expect neuron 1) --");
        for (int v = 1600; v >= 200; v = v - 70) drive(v);

        // ---- summary ----
        $display("========================================");
        $display("saw_fire0 (UP/neuron0)  = %0b", saw_fire0);
        $display("saw_fire1 (DOWN/neuron1)= %0b", saw_fire1);
        if (saw_fire0 && saw_fire1) $display("RESULT: PASS");
        else                        $display("RESULT: FAIL");
        $display("========================================");
        $finish;
    end
endmodule

// SCNCHN6_TB.sv -- top-level self-checking TB for the V6 cascaded design.
// Programs the 330-bit config over the scan chain, pulses load, then drives a
// synthetic triangle ECG. A rising ramp should make L1 neuron 0 fire, which
// should drive L2 neuron 0 to fire and win. beat_clear resets state. A falling
// ramp should make L1 neuron 1 fire, driving L2 neuron 1 to fire and win.
//
// Beyond PASS/FAIL, this prints per-neuron fire counts for BOTH layers. Those
// counts are the actual diagnostic: if L1 counts are all zero the cascade is
// starved, and if all five L1 counts are identical the layer is in lockstep.
`timescale 1ns/1ps
module SCNCHN6_TB;
    // ---- must mirror ScanChainWrapper6 defaults ----
    localparam int N_INPUTS_1  = 2;
    localparam int N_NEURONS_1 = 5;
    localparam int N_INPUTS_2  = N_NEURONS_1;
    localparam int N_NEURONS_2 = 5;

    localparam int DATA_W    = 11;
    localparam int STEP_W    = 4;
    localparam int WEIGHT_W  = 6;
    localparam int THRESH_W  = 10;
    localparam int LEAK_W    = 4;
    localparam int REFRAC_W  = 4;

    localparam int N_WEIGHTS_1 = N_INPUTS_1 * N_NEURONS_1;   // 10
    localparam int N_WEIGHTS_2 = N_INPUTS_2 * N_NEURONS_2;   // 25
    localparam int N_WEIGHTS   = N_WEIGHTS_1 + N_WEIGHTS_2;  // 35

    localparam int CLS_W  = $clog2(N_NEURONS_2 + 1);
    localparam int SCAN_W = N_WEIGHTS*WEIGHT_W
                          + (N_NEURONS_1 + N_NEURONS_2)*THRESH_W
                          + 2*LEAK_W + 2*REFRAC_W + STEP_W;   // 330

    // ---- offsets: must match SCNCHN6.sv exactly ----
    localparam int OFF_WEIGHTS_1 = 0;
    localparam int OFF_WEIGHTS_2 = OFF_WEIGHTS_1 + N_WEIGHTS_1*WEIGHT_W;
    localparam int OFF_THRESH_1  = OFF_WEIGHTS_2 + N_WEIGHTS_2*WEIGHT_W;
    localparam int OFF_THRESH_2  = OFF_THRESH_1  + N_NEURONS_1*THRESH_W;
    localparam int OFF_LEAK_1    = OFF_THRESH_2  + N_NEURONS_2*THRESH_W;
    localparam int OFF_LEAK_2    = OFF_LEAK_1    + LEAK_W;
    localparam int OFF_REFRAC_1  = OFF_LEAK_2    + LEAK_W;
    localparam int OFF_REFRAC_2  = OFF_REFRAC_1  + REFRAC_W;
    localparam int OFF_DM_STEP   = OFF_REFRAC_2  + REFRAC_W;

    // ---- DUT I/O ----
    logic clk = 0, rst = 1;
    logic [DATA_W-1:0] ecg_in = '0;
    logic scan_en = 0, scan_in = 0, load = 0, beat_clear = 0;
    logic scan_out, valid, sys_en;
    logic [CLS_W-1:0]       winner_class;
    logic [N_NEURONS_2-1:0] fire;
    logic [N_NEURONS_1-1:0] fire_l1;

    ScanChainWrapper6 #(
        .N_INPUTS_1(N_INPUTS_1), .N_NEURONS_1(N_NEURONS_1),
        .N_INPUTS_2(N_INPUTS_2), .N_NEURONS_2(N_NEURONS_2),
        .DATA_W(DATA_W), .STEP_W(STEP_W), .WEIGHT_W(WEIGHT_W),
        .THRESH_W(THRESH_W), .LEAK_W(LEAK_W), .REFRAC_W(REFRAC_W)
    ) dut (
        .clk(clk), .rst(rst), .ecg_in(ecg_in),
        .scan_en(scan_en), .scan_in(scan_in), .scan_out(scan_out), .load(load),
        .beat_clear(beat_clear),
        .winner_class(winner_class), .valid(valid),
        .fire(fire), .fire_l1(fire_l1), .sys_en(sys_en)
    );

    always #5 clk = ~clk;

    // ---- config assembly ----
    logic [SCAN_W-1:0]          cfg;
    logic signed [WEIGHT_W-1:0] w1  [N_WEIGHTS_1];
    logic signed [WEIGHT_W-1:0] w2  [N_WEIGHTS_2];
    logic        [THRESH_W-1:0] th1 [N_NEURONS_1];
    logic        [THRESH_W-1:0] th2 [N_NEURONS_2];

    task automatic build_cfg(input logic [LEAK_W-1:0]   leak1,
                             input logic [LEAK_W-1:0]   leak2,
                             input logic [REFRAC_W-1:0] refr1,
                             input logic [REFRAC_W-1:0] refr2,
                             input logic [STEP_W-1:0]   step);
        cfg = '0;
        for (int p = 0; p < N_WEIGHTS_1; p++)
            cfg[OFF_WEIGHTS_1 + p*WEIGHT_W +: WEIGHT_W] = w1[p];
        for (int p = 0; p < N_WEIGHTS_2; p++)
            cfg[OFF_WEIGHTS_2 + p*WEIGHT_W +: WEIGHT_W] = w2[p];
        for (int q = 0; q < N_NEURONS_1; q++)
            cfg[OFF_THRESH_1 + q*THRESH_W +: THRESH_W] = th1[q];
        for (int q = 0; q < N_NEURONS_2; q++)
            cfg[OFF_THRESH_2 + q*THRESH_W +: THRESH_W] = th2[q];
        cfg[OFF_LEAK_1   +: LEAK_W]   = leak1;
        cfg[OFF_LEAK_2   +: LEAK_W]   = leak2;
        cfg[OFF_REFRAC_1 +: REFRAC_W] = refr1;
        cfg[OFF_REFRAC_2 +: REFRAC_W] = refr2;
        cfg[OFF_DM_STEP  +: STEP_W]   = step;
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
    integer l1_cnt [N_NEURONS_1];
    integer l2_cnt [N_NEURONS_2];
    integer win_cnt[N_NEURONS_2];
    integer cyc;

    task automatic clear_win;
        for (int i = 0; i < N_NEURONS_2; i++) win_cnt[i] = 0;
    endtask

    task automatic drive(input int val);
        ecg_in = val[DATA_W-1:0];
        @(posedge clk);
        cyc = cyc + 1;
        for (int i = 0; i < N_NEURONS_1; i++) if (fire_l1[i]) l1_cnt[i] = l1_cnt[i] + 1;
        for (int i = 0; i < N_NEURONS_2; i++) if (fire[i])    l2_cnt[i] = l2_cnt[i] + 1;
        if (valid) win_cnt[winner_class] = win_cnt[winner_class] + 1;
        $display("  cyc=%0d ecg=%4d spk=%b L1=%b L2=%b valid=%b win=%0d",
                 cyc, ecg_in, dut.spikes, fire_l1, fire, valid, winner_class);
    endtask

    // majority-vote classification over the beat (what HW_Net does in Python)
    function automatic int beat_winner;
        int best, bi;
        best = 0; bi = -1;
        for (int i = 0; i < N_NEURONS_2; i++)
            if (win_cnt[i] > best) begin best = win_cnt[i]; bi = i; end
        return bi;
    endfunction

    int beat1_class, beat2_class;

    initial begin
        for (int i = 0; i < N_NEURONS_1; i++) l1_cnt[i] = 0;
        for (int i = 0; i < N_NEURONS_2; i++) l2_cnt[i] = 0;
        clear_win();
        cyc = 0;

        $display("SCAN_W = %0d (TB)   dut.SCAN_W = %0d", SCAN_W, dut.SCAN_W);
        if (SCAN_W !== dut.SCAN_W)
            $display("FAIL: TB and DUT disagree on SCAN_W -- bit packing will be wrong");

        // ---- layer 1 weights: row0=UP, row1=DOWN; w1[row*N_NEURONS_1 + j] ----
        for (int p = 0; p < N_WEIGHTS_1; p++) w1[p] = '0;
        w1[0*N_NEURONS_1 + 0] = 6'sd20;   // UP   -> L1 neuron 0
        w1[1*N_NEURONS_1 + 1] = 6'sd20;   // DOWN -> L1 neuron 1

        // ---- layer 2 weights: row = L1 neuron index; w2[row*N_NEURONS_2 + j] ----
        for (int p = 0; p < N_WEIGHTS_2; p++) w2[p] = '0;
        w2[0*N_NEURONS_2 + 0] = 6'sd20;   // L1 n0 -> L2 neuron 0
        w2[1*N_NEURONS_2 + 1] = 6'sd20;   // L1 n1 -> L2 neuron 1

        // L1 threshold low (fires on a single input spike), L2 needs 2 L1 fires
        for (int q = 0; q < N_NEURONS_1; q++) th1[q] = 10'd20;
        for (int q = 0; q < N_NEURONS_2; q++) th2[q] = 10'd40;

        // reset
        repeat (3) @(posedge clk);
        rst = 1'b0;
        @(posedge clk);

        // leak1=15 leak2=15 (both slow), refrac1=2 refrac2=2, dm_step=4
        build_cfg(4'd15, 4'd15, 4'd2, 4'd2, 4'd4);
        program_chain();
        if (sys_en !== 1'b1) $display("FAIL: sys_en did not assert after load");
        else                 $display("ok: sys_en high after load");

        // ---- BEAT 1: rising ramp -> UP -> L1 n0 -> L2 n0 ----
        $display("-- rising ramp (expect L1 n0, then L2 n0) --");
        clear_win();
        for (int v = 200; v <= 1600; v = v + 50) drive(v);
        beat1_class = beat_winner();
        $display("   beat 1 majority-vote class = %0d", beat1_class);

        // per-beat clear (resets DM + both layers)
        beat_clear = 1'b1; @(posedge clk); beat_clear = 1'b0; @(posedge clk);
        $display("-- beat_clear pulsed --");

        // ---- BEAT 2: falling ramp -> DOWN -> L1 n1 -> L2 n1 ----
        $display("-- falling ramp (expect L1 n1, then L2 n1) --");
        clear_win();
        for (int v = 1600; v >= 200; v = v - 50) drive(v);
        beat2_class = beat_winner();
        $display("   beat 2 majority-vote class = %0d", beat2_class);

        // ---- summary ----
        $display("========================================");
        $display("layer 1 fire counts:");
        for (int i = 0; i < N_NEURONS_1; i++) $display("   L1 n%0d = %0d", i, l1_cnt[i]);
        $display("layer 2 fire counts:");
        for (int i = 0; i < N_NEURONS_2; i++) $display("   L2 n%0d = %0d", i, l2_cnt[i]);
        $display("beat 1 class = %0d (expect 0)", beat1_class);
        $display("beat 2 class = %0d (expect 1)", beat2_class);

        if (l1_cnt[0] == 0 && l1_cnt[1] == 0)
            $display("DIAG: layer 1 never fired -- lower th1 or raise w1");
        else if (l2_cnt[0] == 0 && l2_cnt[1] == 0)
            $display("DIAG: layer 1 fired but layer 2 did not -- lower th2 or slow leak2");

        if (l1_cnt[0] > 0 && l1_cnt[1] > 0 &&
            beat1_class == 0 && beat2_class == 1)
             $display("RESULT: PASS -- cascade propagates and classifies");
        else $display("RESULT: FAIL");
        $display("========================================");
        $finish;
    end
endmodule

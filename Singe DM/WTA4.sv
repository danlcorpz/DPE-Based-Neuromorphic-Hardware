module WinnerTakeAll4 #(
    parameter int N_NEURONS = 5,
    parameter int CLS_W     = $clog2(N_NEURONS + 1)
)(
    input  logic                 enable,
    input  logic [N_NEURONS-1:0] fire,
    output logic [CLS_W-1:0]     winner_class,
    output logic                 valid,
    output logic [N_NEURONS-1:0] reset_others
);
    logic any_fire;
    logic [N_NEURONS-1:0] winner;
    always_comb begin
        winner_class  = {CLS_W{1'b1}};
        valid         = 1'b0;
        winner      = '0;
        reset_others  = '0;
        if (enable) begin
            any_fire = |fire;
            for (int i = 0; i < N_NEURONS; i++) begin
                if (fire[i]) begin
                    winner_class     = CLS_W'(i);
                    winner[i] = 1'b1;
                    valid            = 1'b1;
                    break;
                end
            end
            reset_others = valid ? ~winner : '0;
        end
    end
endmodule
module DeltaModulator4#(
    parameter int DATA_W = 11,
    parameter int STEP_W  = 4,
    parameter int MAX_VAL = 2047,
    parameter int MIN_VAL = 0
)(
    input logic                   clk,
    input logic                   dm_rst,
    input logic [STEP_W-1:0]      step_size, //threshold for spiking
    input logic [DATA_W-1:0]      analog_in,
    output logic [1:0]            spike_out, //[0] UP, [1] DOWN
    output logic [DATA_W-1:0]     approx_signal
);

    logic init;
    logic last_cycle_spiked;
    
    wire [DATA_W-1:0] next_up = (approx_signal + step_size > MAX_VAL) ? MAX_VAL : (approx_signal + step_size);
    wire [DATA_W-1:0] next_down = (approx_signal < step_size) ? MIN_VAL : (approx_signal - step_size);

always_ff @(posedge clk or posedge dm_rst) begin
    if (dm_rst) begin

        approx_signal <= '0;
        spike_out[0] <= 1'b0;
        spike_out[1] <= 1'b0;
        init <= 1'b0;
        last_cycle_spiked <= 1'b0;

        end else begin

        spike_out[0] <= 1'b0;
        spike_out[1] <= 1'b0;

            if (!init) begin
                approx_signal <= analog_in;
                init <= 1'b1;
            end else if (last_cycle_spiked) begin
                last_cycle_spiked <= 1'b0;
            end else begin
                if (analog_in > approx_signal + step_size) begin
                    spike_out[0] <= 1'b1;
                    last_cycle_spiked <= 1'b1;
                    approx_signal <= next_up;
                end else if (analog_in + step_size < approx_signal) begin
                    spike_out[1] <= 1'b1;
                    last_cycle_spiked <= 1'b1;
                    approx_signal <= next_down;
                end
            end
        end
    end
endmodule
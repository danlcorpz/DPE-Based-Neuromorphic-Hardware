onbreak {resume}
if [file exists work] { vdel -all }
vlib work
vlog DM4.sv NEURON4.sv DPE4.sv WTA4.sv SCNCHN4.sv SCNCHN4_TB.sv
vsim -voptargs=+acc work.SCNCHN4_TB
view list
view waves
add wave -hex      /SCNCHN4_TB/clk
add wave -hex      /SCNCHN4_TB/rst
add wave -hex      /SCNCHN4_TB/sys_en
add wave -hex      /SCNCHN4_TB/scan_en
add wave -hex      /SCNCHN4_TB/scan_in
add wave -hex      /SCNCHN4_TB/load
add wave -hex      /SCNCHN4_TB/beat_clear
add wave -unsigned /SCNCHN4_TB/ecg_in
add wave -hex      /SCNCHN4_TB/dut/dm_spikes
add wave -hex      /SCNCHN4_TB/dut/spikes
add wave -unsigned /SCNCHN4_TB/dut/u_dm/approx_signal
add wave -hex      /SCNCHN4_TB/fire
add wave -hex      /SCNCHN4_TB/dut/reset_others
add wave -unsigned /SCNCHN4_TB/winner_class
add wave -hex      /SCNCHN4_TB/valid
TreeUpdate [SetDefaultTree]
WaveRestoreZoom {0 ps} {600 ns}
configure wave -namecolwidth 240
configure wave -valuecolwidth 100
run -all
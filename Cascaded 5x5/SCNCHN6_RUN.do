onbreak {resume}
if [file exists work] { vdel -all }
vlib work
vlog DM6.sv NEURON6.sv DPE6.sv WTA6.sv SCNCHN6.sv SCNCHN6_TB.sv
vsim -voptargs=+acc work.SCNCHN6_TB
view list
view waves
add wave -hex      /SCNCHN6_TB/clk
add wave -hex      /SCNCHN6_TB/rst
add wave -hex      /SCNCHN6_TB/sys_en
add wave -hex      /SCNCHN6_TB/scan_en
add wave -hex      /SCNCHN6_TB/scan_in
add wave -hex      /SCNCHN6_TB/load
add wave -hex      /SCNCHN6_TB/beat_clear
add wave -unsigned /SCNCHN6_TB/ecg_in
add wave -hex      /SCNCHN6_TB/dut/dm_spikes
add wave -hex      /SCNCHN6_TB/dut/spikes
add wave -unsigned /SCNCHN6_TB/dut/u_dm/approx_signal
add wave -divider  {LAYER 1}
add wave -decimal  /SCNCHN6_TB/dut/u_dpe1/gen_cols[0]/u_accum/mp
add wave -decimal  /SCNCHN6_TB/dut/u_dpe1/gen_cols[1]/u_accum/mp
add wave -hex      /SCNCHN6_TB/fire_l1
add wave -divider  {LAYER 2}
add wave -decimal  /SCNCHN6_TB/dut/u_dpe2/gen_cols[0]/u_accum/mp
add wave -decimal  /SCNCHN6_TB/dut/u_dpe2/gen_cols[1]/u_accum/mp
add wave -hex      /SCNCHN6_TB/fire
add wave -hex      /SCNCHN6_TB/dut/reset_others
add wave -divider  {OUTPUT}
add wave -unsigned /SCNCHN6_TB/winner_class
add wave -hex      /SCNCHN6_TB/valid
TreeUpdate [SetDefaultTree]
WaveRestoreZoom {3300 ns} {4200 ns}
configure wave -namecolwidth 240
configure wave -valuecolwidth 100
run -all

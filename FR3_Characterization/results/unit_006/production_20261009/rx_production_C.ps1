# Unit #6 RX production test, SET-UP C: "RX-side FR3 RF In" -> FR3 cable -> FieldFox analyzer input; "RX-side FR1 IF Out" and
# both TX ports terminated in 50 ohm; FieldFox source OFF. R7: LO / 2xLO leaking out of "RX-side FR3 RF In" at the 3 test LOs
# (2xLO only where it is <= 26.5 GHz, i.e. LO 8 GHz), TX side normal with Unit #6's nulls; at each LO the reading is repeated with
# the TX bias 5 mV off its null (as in the golden run).
$d = "results\unit_006\production_20261009"
$env:FR3_CAL_HOT = "$d\lo_cal_grid_*_table.csv"
"$(Get-Date -Format s) START R7_rx_leakage" | Out-File -Encoding utf8 "$d\rx_production_C_status.txt"
$p = Start-Process python -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru `
     -ArgumentList "rx_port_leakage.py --los 8,16,20 --expect-unit 6 --out-dir $d --note prod_rx_leak --setup `"Unit 6 production test, set-up C`"" `
     -RedirectStandardOutput "$d\R7_rx_leakage.out.txt" -RedirectStandardError "$d\R7_rx_leakage.err.txt"
Wait-Process -Id $p.Id
"$(Get-Date -Format s) END   R7_rx_leakage" | Out-File -Encoding utf8 -Append "$d\rx_production_C_status.txt"

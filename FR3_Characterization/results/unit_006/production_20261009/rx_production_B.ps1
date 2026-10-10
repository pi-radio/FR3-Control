# Unit #6 RX production test, SET-UP B: "RX-side FR3 RF In" terminated in 50 ohm; "RX-side FR1 IF Out" -> FR1 cable -> FieldFox
# analyzer input; TX ports terminated. R6: NF noise step at the 17 points (optimal filter, TX side normal with Unit #6's nulls),
# then the NF combine (FieldFox floor subtracted, noise referred to the connector).
$d = "results\unit_006\production_20261009"
$pts = "low:1:9,low:1:17,low:1:21,high:1:7,high:1:15,high:1:19,low:2:10,low:2:18,low:2:22,high:2:6,high:2:14,high:2:18,low:3.5:11.5,low:3.5:19.5,low:3.5:23.5,high:3.5:12.5,high:3.5:16.5"
$env:FR3_CAL_HOT = "$d\lo_cal_grid_*_table.csv"
"$(Get-Date -Format s) START R6_nf_noise" | Out-File -Encoding utf8 "$d\rx_production_B_status.txt"
$p = Start-Process python -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru `
     -ArgumentList "rx_nf_campaign.py --phase 2 --filter optimal --tx-normal --campaign production_20261009\rx_nf --only $pts" `
     -RedirectStandardOutput "$d\R6_nf_noise.out.txt" -RedirectStandardError "$d\R6_nf_noise.err.txt"
Wait-Process -Id $p.Id
python rx_nf_campaign.py --phase combine --campaign "production_20261009/rx_nf" > "$d\R6_nf_combine.out.txt"
"$(Get-Date -Format s) END   R6_nf_noise + combine" | Out-File -Encoding utf8 -Append "$d\rx_production_B_status.txt"

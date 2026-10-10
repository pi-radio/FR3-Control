# Unit #6 RX production test, SET-UP A: "RX-side FR3 RF In" <- FR3 cable <- FieldFox source; "RX-side FR1 IF Out" -> FR1 cable ->
# FieldFox analyzer input; "TX-side FR1 IF In" and "TX-side FR3 RF Out" terminated in 50 ohm. Same 3 LOs as the TX test (8 / 16 /
# 20 GHz); the TX side in normal use with Unit #6's OWN T1 nulls (FR3_CAL_HOT -> this folder's tables). -5 dBm RX input cap.
#  R1 gain, R2 flatness: 17 points x bypassed/optimal   R3 compression: 3 panels   R4 image rejection: 17 x 2   R5 NF gain step: 17
$d = "results\unit_006\production_20261009"
$status = "$d\rx_production_A_status.txt"
$cal = "results\unit_005\flatness_rx_20261005\cal.csv"      # loopback of the source + FR3 cable (no unit involved)
$pts = "low:1:9,low:1:17,low:1:21,high:1:7,high:1:15,high:1:19,low:2:10,low:2:18,low:2:22,high:2:6,high:2:14,high:2:18,low:3.5:11.5,low:3.5:19.5,low:3.5:23.5,high:3.5:12.5,high:3.5:16.5"
$env:FR3_CAL_HOT = "$d\lo_cal_grid_*_table.csv"
# NF phases 0 (source level at the end of the FR3 cable) and 1 (FieldFox noise floor) do not involve the unit: reuse them
New-Item -ItemType Directory -Force "$d\rx_nf" | Out-Null
foreach ($f in "phase0_source_loopback.csv", "phase1_ff_noise_floor.csv") {
  if (-not (Test-Path "$d\rx_nf\$f")) { Copy-Item "results\unit_005\rx_nf_optimal_20261009\$f" "$d\rx_nf\$f" }
}
$steps = @(
  @{ name = "R1_gain"; args = "flatness_campaign.py --chain rx --phase measure --campaign production_20261009\gain_rx --cal-from $cal --only $pts" },
  @{ name = "R2_flatness"; args = "flatness_campaign.py --chain rx --phase measure --campaign production_20261009\flatness_rx --cal-from $cal --only $pts" },
  @{ name = "R3_compression"; args = "rx_compression_campaign.py --campaign production_20261009\compression_rx --expect-unit 6 --only low:1:9,high:2:14,low:2:22" },
  @{ name = "R4_image"; args = "rx_image_campaign.py --campaign production_20261009\image_rx --expect-unit 6 --only $pts" },
  @{ name = "R5_nf_gain"; args = "rx_nf_campaign.py --phase 3 --filter optimal --tx-normal --campaign production_20261009\rx_nf --only $pts" }
)
"$(Get-Date -Format s) chain started" | Out-File -Encoding utf8 $status
foreach ($s in $steps) {
  "$(Get-Date -Format s) START $($s.name)" | Out-File -Encoding utf8 -Append $status
  $p = Start-Process python -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru -ArgumentList $s.args `
       -RedirectStandardOutput "$d\$($s.name).out.txt" -RedirectStandardError "$d\$($s.name).err.txt"
  Wait-Process -Id $p.Id
  "$(Get-Date -Format s) END   $($s.name)" | Out-File -Encoding utf8 -Append $status
  Start-Sleep 3
}
"$(Get-Date -Format s) chain finished" | Out-File -Encoding utf8 -Append $status

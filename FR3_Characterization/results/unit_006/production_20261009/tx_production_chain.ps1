# Unit #6 TX production test (user go-ahead 2026-10-09 ~16:55): started cold-window (LMX 55-65 C, no warm-up), case closed with
# hand-placed MCS pieces. 3 LOs (8 / 16 / 20 GHz = drive 0 / 2 / 4); every other TX test on points sharing those LOs, so they
# use Unit #6's OWN nulls (FR3_CAL_HOT -> this folder's tables; Unit #5's tables are never loaded).
#  T1+T2  null with the reference filter at each LO, LO leakage in every usable filter setting (+ 2xLO at LO 8 GHz)
#  T3 gain, T4 flatness, T5 sideband suppression: 17 points x bypassed/optimal   T6 compression: 3 panels
$d = "results\unit_006\production_20261009"
$status = "$d\tx_production_status.txt"
$cal = "results\unit_005\flatness_tx_20261005\cal.csv"      # loopback of the source + FR1 cable (no unit involved)
$pts = "upper:1:9,upper:1:17,upper:1:21,lower:1:7,lower:1:15,lower:1:19,upper:2:10,upper:2:18,upper:2:22,lower:2:6,lower:2:14,lower:2:18,upper:3.5:11.5,upper:3.5:19.5,upper:3.5:23.5,lower:3.5:12.5,lower:3.5:16.5"
$env:FR3_CAL_HOT = "$d\lo_cal_grid_*_table.csv"
$steps = @(
  @{ name = "T1_null_lo8_2lo"; args = "lo_cal_grid_scan.py --los 8.0 --read-2lo --null-span-hz 1e6 --expect-unit 6 --out-dir $d --note prod_lo8 --setup `"Unit 6 production test, TX set-up, cold window, case closed + MCS (hand-placed)`"" },
  @{ name = "T1_null_lo16_20"; args = "lo_cal_grid_scan.py --los 16.0,20.0 --null-span-hz 1e6 --expect-unit 6 --out-dir $d --note prod_lo16_20 --setup `"Unit 6 production test, TX set-up, cold window, case closed + MCS (hand-placed)`"" },
  @{ name = "T3_gain"; args = "flatness_campaign.py --chain tx --phase measure --campaign production_20261009\gain_tx --cal-from $cal --only $pts" },
  @{ name = "T4_flatness"; args = "flatness_campaign.py --chain tx --phase measure --campaign production_20261009\flatness_tx --cal-from $cal --only $pts" },
  @{ name = "T5_sideband"; args = "sideband_campaign.py --campaign production_20261009\sideband_tx --expect-unit 6 --only $pts" },
  @{ name = "T6_compression"; args = "compression_campaign.py --campaign production_20261009\compression_tx --expect-unit 6 --only upper:1:9,lower:2:14,upper:2:22" }
)
"$(Get-Date -Format s) chain started" | Out-File -Encoding utf8 $status
foreach ($s in $steps) {
  "$(Get-Date -Format s) START $($s.name)" | Out-File -Encoding utf8 -Append $status
  $p = Start-Process python -WorkingDirectory (Get-Location).Path -WindowStyle Hidden -PassThru -ArgumentList $s.args `
       -RedirectStandardOutput "$d\$($s.name).out.txt" -RedirectStandardError "$d\$($s.name).err.txt"
  Wait-Process -Id $p.Id
  "$(Get-Date -Format s) END   $($s.name)" | Out-File -Encoding utf8 -Append $status
  if ($s.name -eq "T1_null_lo16_20") {
    $n = (Get-ChildItem "$d\lo_cal_grid_*_table.csv" | ForEach-Object { @(Import-Csv $_.FullName).Count } | Measure-Object -Sum).Sum
    if ($n -lt 3) { "$(Get-Date -Format s) ABORT: only $n of 3 LOs nulled -- not starting T3-T6" | Out-File -Encoding utf8 -Append $status; exit 1 }
  }
  Start-Sleep 3
}
"$(Get-Date -Format s) chain finished" | Out-File -Encoding utf8 -Append $status

# Datasheet measurements: which scripts produce each section

Internal document (not part of the datasheet). It records, for every section of the FR3-1ch datasheet, the scripts that
take the measurement, turn it into figures and numbers, and the shared code they depend on. **Keep every script listed
here**: they may later be open-sourced so users can repeat the measurements on their own units.

Status as of 2026-10-09 evening: **every measured section is final** (first revision of the datasheet). Section numbers
are the printed numbers in `FR3-1ch-Datasheet/main.pdf`; the `.tex` file names still carry older numbers. The dated "Update"
sections at the end of this file are the history of how we got here.

## Measurement configuration (all datasheet data)

- LMX2820 drive by LO frequency (`lmx_drive.py`): 0 for LO <= 13 GHz, 2 for 13-20 GHz, 4 for LO >= 20 GHz.
- Hot: case closed as shipped (MCS absorber pieces fitted), fan OFF; each section quotes its measured LMX die range.
- TX LO-null bias: the unit's stored cold/hot calibration, interpolated to the LMX die temperature (`lo_cal_tables.py`).
- RX runs: the TX side in normal use at every point (`rx_tx_side.py`); unused ports terminated in 50 ohm.
- "Optimal" filter: `rx_nf_campaign.optimal_rx_filter` (best desired-band power, then most image rejection within 3 dB).
- Cable losses: `cables.py`, from the S21 files captured with `capture_cable_s21.py` (FR1 cable, FR3 cable).
- FieldFox N9918B over SCPI (`fieldfox.py`); never `INIT:CONT OFF`; source always switched off and read back at the end.

## Per section (current index)

Data paths are under `results/unit_005/`. Measurement chains: `2026-10-09/tx_full_rerun_chain.ps1` (TX),
`2026-10-09/rx_chain_A.ps1` (RX set-up A).

| # | Section | Measurement | Data | Figures / numbers |
|---|---|---|---|---|
| 1 | Key Specifications | (the sections' outputs) | - | `make_summary_table.py`; conditions `make_tx_conditions.py`, `make_rx_conditions.py` |
| 2 | Hardware Primer | (none) | - | TikZ in the `.tex`; photo `images/hw_photo_labeled.png` (labels edited by hand) |
| 3, 4 | TX conversion gain | `flatness_campaign.py --chain tx --phase measure --cal-from flatness_tx_20261005/cal.csv` | `gain_tx_20261009/` | `plot_datasheet_gain.py` |
| 5 | TX gain flatness | same script | `flatness_tx_20261009/` | `plot_datasheet_flatness.py` |
| 6 | TX sideband suppression | `sideband_campaign.py` | `sideband_tx_20261009/` | `plot_datasheet_sideband.py` |
| 7, 8 | TX compression | `compression_campaign.py` | `compression_tx_20261009/` | `plot_datasheet_compression.py` |
| 9 | TX LO suppression (calibration) | `lo_cal_grid_scan.py` (cold, then hot) | `2026-10-09/lo_cal_grid_100MHz_*_full_cal_{cold,hot}_drive_rule_*` | `plot_datasheet_lo_cal.py`, `make_sec6_cal_numbers.py` |
| 10.1 | TX 2xLO spur | `lo_cal_grid_scan.py --read-2lo` | `2026-10-09/lo_cal_grid_100MHz_20261009_044140_sec10_1_2lo_hot_*` | `plot_datasheet_2lo.py`, `make_sec10_1_numbers.py` |
| 10.2 | RX-side LO / 2xLO leakage | `rx_port_leakage.py` | `2026-10-09/rx_port_leakage_20261009_163240_rx_hot_drive_rule.csv` | `plot_datasheet_spurs.py` (Figures 10.2, 10.3) |
| 11, 12 | RX conversion gain | `flatness_campaign.py --chain rx --phase measure --cal-from flatness_rx_20261005/cal.csv` | `gain_rx_20261009/` | `plot_datasheet_gain.py --chain rx` |
| 13 | RX gain flatness | same script | `flatness_rx_20261009/` | `plot_datasheet_flatness.py` |
| 14, 15 | RX compression | `rx_compression_campaign.py` | `compression_rx_20261009/` | `plot_datasheet_compression.py --chain rx` |
| 16 | RX image rejection | `rx_image_campaign.py` | `image_rx_20261009/` | `plot_datasheet_image.py` |
| 17 | RX noise figure (optimal filter) | `rx_nf_campaign.py --phase 3`, `--phase 2` (`--filter optimal --tx-normal`), then `--phase combine` | `rx_nf_optimal_20261009/` (phases 0, 1 copied from `rx_nf_filter_optimal_20261005`) | `plot_datasheet_nf.py` |
| 18 | Phase noise | `phase_noise_capture.py` (UXA); `measure_external_lo.py` for an external LO | earlier capture (before the drive rule; accepted) | `plot_datasheet_pn.py` |

(Section 19 "Tips for Correct Usage" and the appendices have no measurements.)

## Shared code every measurement needs

- `board.py`: serial access to the unit; `MeasurementSession` turns flash persistence off for a run and restores the unit's
  configuration afterwards. Depends on the GUI's protocol layer in `FR3_GUI/` (`fr3_gui`).
- `fieldfox.py`: FieldFox SCPI driver. `cables.py` + `capture_cable_s21.py`: cable losses.
- `results_layout.py`: where results go (`results/unit_<serial>/...`).
- `lo_null.py`: the LO-null search. `lo_cal_tables.py`: the stored calibration at runtime.
- `rx_nf_campaign.optimal_rx_filter`, `rx_nf_campaign.get_response`: the filter rule and the AM3153 model responses.
- Offline tests: `test_board.py`, `test_compression_and_cables.py`, `test_flatness.py`.

## Before open-sourcing (to do)

- Hard-coded values to make configurable: FieldFox IP (`192.168.137.61`), UXA IP, `--expect-unit 5`, the `results\unit_005\2026-10-0x\...`
  campaign names and glob patterns (e.g. in the plot scripts, `make_rx_conditions.py`), in `lo_cal_tables.py`, `plot_datasheet_lo_cal.py`, `make_sec6_cal_numbers.py`, `plot_full_cal_progress.py`.
- Windows path separators in several glob patterns.
- The `FR3_GUI` dependency of `board.py` (ship it together, or vendor the protocol layer).
- Diagnostic / investigation scripts (`_*.py`, `tx_2lo_vs_*`, `analyze_*`, `plot_floor_configs_13_16.py`, ...) are not
  needed for the datasheet and need not be published.


## Update 2026-10-09: definitive TX data (hot, LMX drive rule) and the scripts that make the figures

All TX sections now come from the full re-run of 2026-10-09 02:29-05:10 (LMX drive 0 / 2 / 4 by LO, `lmx_drive.py`; reference-filter
LO nulls; case closed + MCS pieces; fan OFF, LMX 79-86 C), nothing reused from earlier runs.

| # | Section | Data | Figures / numbers (re-run to regenerate) |
|---|---|---|---|
| 1 | Key Specifications | the sections' outputs | `make_summary_table.py` (TX sideband from `sec_sideband_numbers.tex`, LO rows from `sec6_cal_numbers.tex`) |
| - | Test conditions quoted everywhere | all TX runs | `make_tx_conditions.py` -> `sec_tx_conditions.tex` (`\lmxDriveRule`, `\cond<Run>MinC/MaxC`, `\attn{}`) |
| 3, 4 | TX conversion gain | `results/unit_005/gain_tx_20261009/` | `plot_datasheet_gain.py` -> `images/sec1_fig1-9`, `sec2_fig1-9` |
| 5 | TX gain flatness | `results/unit_005/flatness_tx_20261009/` | `plot_datasheet_flatness.py --tx-campaign flatness_tx_20261009` |
| 6 | TX sideband suppression | `results/unit_005/sideband_tx_20261009/` | `plot_datasheet_sideband.py` -> `images/sec3_fig1-8`, `sec_sideband_numbers.tex` |
| 7, 8 | TX compression | `results/unit_005/compression_tx_20261009/` | `plot_datasheet_compression.py` -> `images/sec4_fig1-9`, `sec5_fig1-9` (panels 7.6 -> 3.0/17.0, 7.9 -> 3.5/23.5) |
| 9 | LO suppression | hot: `2026-10-09/lo_cal_grid_100MHz_20261009_022928_full_cal_hot_drive_rule_*`; cold: pending (fan on) | `plot_datasheet_lo_cal.py`, `make_sec6_cal_numbers.py`; runtime tables `lo_cal_tables.py` |
| 10.1 | 2xLO spur | `2026-10-09/lo_cal_grid_100MHz_20261009_044140_sec10_1_2lo_hot_*` (`lo_cal_grid_scan.py --read-2lo`) | not in the datasheet yet (pending discussion) |

Measurement scripts as run: `lo_cal_grid_scan.py`, `flatness_campaign.py` (gain and flatness, `--cal-from` the 2026-10-05 loopback),
`sideband_campaign.py`, `compression_campaign.py`; the chain: `results/unit_005/2026-10-09/tx_full_rerun_chain.ps1`.


## Update 2026-10-09 (afternoon): Section 9 cold run, new figures, and housekeeping

| Item | Data | Script |
|---|---|---|
| Section 9 cold calibration (fan ON, LMX 57-63 C) | `2026-10-09/lo_cal_grid_100MHz_20261009_112919_full_cal_cold_drive_rule_*` | `lo_cal_grid_scan.py` (started by `2026-10-09/start_cold_when_cool.ps1`) |
| Figures 9.2, 9.3 (cold / hot leakage), 9.4 (histograms), 9.5 (tables), 9.6 (hot minus cold) | cold + hot tables above | `plot_datasheet_lo_cal.py` (also writes `sec6_tempdiff_numbers.tex`) |
| Section 9 numbers (pass rule 85 % at or below -20 dBm since 2026-10-09) | cold + hot | `make_sec6_cal_numbers.py` |
| Section 10.1 figure (median and min-max over all filter settings, Fail/Pass, % better than -20 dBm) | `2026-10-09/lo_cal_grid_100MHz_20261009_044140_sec10_1_2lo_hot_*` | `plot_datasheet_2lo.py` |
| Section 10.1 and Key Specs 2xLO numbers | same | `make_sec10_1_numbers.py` -> `sec_2lo_numbers.tex` |
| Fan-on compression checks of panels 7.9 / 8.9 (NOT in the datasheet figures; quoted in the captions' tips) | `compression_tx_20261009_fanon_check_7p9_8p9/`, `compression_tx_20261009_fanon_check_8p9_ss50to40/` | `compression_campaign.py --only ... [--ss-window=-50,-40]` |

New script options: `compression_campaign.py --only side:fr1:fr3,...` (selected panels) and `--ss-window=lo,hi` (small-signal gain as
a plain mean over that source range, no consistency check); `sideband_campaign.py` uses the 26.5 GHz cable value for a tone found
just above 26.5 GHz instead of skipping the point; `lo_cal_grid_scan.py --read-2lo`; `lmx_drive.py` (drive rule) is used by all
campaigns; `warm_lmx_until.py` (warm the LMX before a hot run); `watch_lmx_temperature.py` (read-only temperature log).

Removed from the datasheet (unused): `images/sec6_fig1-3.pdf`, `images/sec_spur_fig1.pdf`, `sections/sec6_numbers.tex`, the
`\calMultiSettingCount` macro. `plot_datasheet_lo.py` is superseded (kept only for the style helpers that `plot_datasheet_lo_cal.py` imports).

Still to do for Section 6: re-measure the one point lower FR1 4.0 / FR3 18.5 GHz (image at exactly 26.5 GHz), hot, now that the
script no longer skips it.


## RX hot re-run, 2026-10-09 (all RX sections re-measured)

Common: fan off, case closed, LMX drive rule, TX side in normal use at every point (`rx_tx_side.py`: stored cold/hot calibration,
IQ state, optimal TX filter; TX ports terminated). Reused, not re-measured: cable S21 files, the RX loopback cal
`flatness_rx_20261005/cal.csv`, NF phase 0/1 files from `rx_nf_filter_optimal_20261005`. Chain script: `2026-10-09/rx_chain_A.ps1`.

| Run | Section | Set-up | Data | Measure | Plot / numbers |
|---|---|---|---|---|---|
| 1 | 11-12 RX gain | A | `gain_rx_20261009/` | `flatness_campaign.py --chain rx --phase measure --cal-from ...` | `plot_datasheet_gain.py --chain rx` (sec7/sec8_fig1-9) |
| 2 | 13 RX flatness | A | `flatness_rx_20261009/` | same | `plot_datasheet_flatness.py --tx-campaign flatness_tx_20261009 --rx-campaign flatness_rx_20261009` |
| 3 | 14-15 RX compression | A | `compression_rx_20261009/` | `rx_compression_campaign.py` (new; -5 dBm input cap via `conversion_gain_small_case.MAX_INPUT_AT_DUT_DBM`) | `plot_datasheet_compression.py --chain rx` (sec9/sec10_fig1-9) |
| 4 | 16 Image rejection | A | `image_rx_20261009/` | `rx_image_campaign.py` (new) | `plot_datasheet_image.py` (new; sec11_fig1-8, `sec_image_numbers.tex`, outlier-circle positions) |
| 5 | 17 NF gain step | A | `rx_nf_optimal_20261009/phase3_gain.csv` | `rx_nf_campaign.py --phase 3 --filter optimal --tx-normal` | |
| 6 | 17 NF noise step | B | `rx_nf_optimal_20261009/phase2_cold_noise.csv` | `rx_nf_campaign.py --phase 2 --filter optimal --tx-normal`; then `--phase combine` | `plot_datasheet_nf.py` (optimal only; sec12_fig1-4, `sec12_numbers.tex`) |
| 7 | 10.2-10.3 RX LO / 2xLO leakage | C | `2026-10-09/rx_port_leakage_20261009_163240_rx_hot_drive_rule.csv` | `rx_port_leakage.py` (100 MHz grid, drive rule, stored cal) | `plot_datasheet_spurs.py` (sec_spur_fig2/3) |

Temperatures of every RX run: `make_rx_conditions.py` -> `sec_rx_conditions.tex`. Key Specs: `make_summary_table.py` (image
rejection now from `sec_image_numbers.tex`; NF rows are the optimal filter).

NF calculation fix (user, 2026-10-09): `rx_nf_campaign.py` combine now subtracts the FieldFox's own noise floor (linear) and refers
the noise to the unit's connector (adds the FR1 cable loss), as the gain already was. Before this, every NF (including the
10-04/10-05 campaigns) came out 0.5-1.1 dB too low. Section 17 now shows the optimal filter only, with a paragraph that the NF is
lower with the filter bypassed (user decision).


## Update 2026-10-10: production testing, firmware 1.4.1 calibration upload, GUI appendix images

| Tool | Where | What |
|---|---|---|
| `compare_production.py --chain tx\|rx` | here | A production-tested unit vs golden Unit #5, point by point (writes `results/unit_<n>/<folder>/comparison_{tx,rx}.md`) |
| Production chains | `results/unit_006/production_20261009/{tx_production_chain,rx_production_A,B,C}.ps1` | The 3-LO TX and RX production tests (`--only` point lists; `FR3_CAL_HOT` points the scripts at the unit's own tables) |
| `lo_cal_tables.py` | here | `FR3_CAL_COLD` / `FR3_CAL_HOT` environment overrides: another unit's tables (Unit #5's are never used for it) |
| `upload_lo_cal.py --unit <n>` | here | Writes a unit's cold + hot LO-null tables into its flash (firmware 1.4.1 `CAL` commands), commits, reads every entry back. Set `SET BOARD SERIAL` first (the commit stamps it) |
| `tools/crop_gui_screenshots.py` | datasheet repo | GUI screenshots (Downloads/Capture90-91.PNG, 2026-10-10) -> the four Appendix A section images + `sections/gui_shot_callouts.tex` |
| `tools/render_gui_screens.py` | datasheet repo | Renders the GUI off-screen against a simulated unit -> the two colour-state images of Appendix A (external LO; TX filter set by hand) |

Unit #6 full calibration: `results/unit_006/2026-10-09/lo_cal_grid_100MHz_20261009_175612_full_cal_cold_drive_rule_*` (cold, 86.9 %)
and `..._20261010_095852_full_cal_hot_drive_rule_*` (hot, 90.1 %); uploaded to its flash on 2026-10-10 (firmware 1.4.1).

FieldFox: `fieldfox.setup_spectrum_analyzer()` keeps continuous sweep ON and `read_tone()` waits for fresh sweeps
(`FieldFox.wait_fresh_sweeps()`); every script that used `INIT:CONT OFF` / `INIT:IMM` was converted on 2026-10-10.
`capture_cable_s21.py` (network-analyzer mode) now uses `SENS:SWE:TIME?` for its sweep time: check that query in the
FieldFox programming guide before its next run. `_ff_continuous_restart_test.py` is disabled (it existed to compare
CONT OFF with continuous sweep). `phase_noise_capture.py` drives the UXA, not the FieldFox, and is unchanged.

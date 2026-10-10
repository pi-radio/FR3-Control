"""LO-null scan: for every LO frequency of a range, find the I_V / Q_V bias that nulls the LO leakage of the board (lo_null.Nuller: coarse
search, then two elliptical fits, refit and polish; see lo_null.py). One calibration per board, at whatever temperature it is at.

    python lo_null_scan.py --campaign lo_null_<date> [--lo-start-ghz 7.0 --lo-stop-ghz 22.6 --lo-step-ghz 0.1] [--warm-start]
                           [--max-minutes N] [--live-plot] [--redo-ghz f1,f2,...] [--redo-above-dbm L]

Conditions: LMX output power 7, TX filter in bypass, FieldFox source OFF (nothing into the FR1 IF input), fixed analyzer settings.
Every LO starts from (0, 0), or with --warm-start from the previous frequency's null (a cold start if that failed or reads too high).
Resumable: LOs already in lo_null_table.csv are skipped, so an interrupted scan is started again with the same command (only the
algorithm's settings must match; a finer scan of the same campaign fills in the frequencies between). --max-minutes ends a run cleanly
between two LOs; --max-lmx-temp-c ends it cleanly (exit code 3) when the LMX reads that hot before an LO (every such reading goes
to --temp-log); --min-lmx-temp-c waits for the LMX to reach a minimum before each LO and redoes an LO whose search dipped below it.
--redo-* redo LOs whatever the table says (weak or failed ones with --redo-above-dbm); the old rows go to
lo_null_table_superseded.csv. --live-plot redraws the three-graph picture (plot_null_sweep.py) and live.html every --plot-every LOs.
The LMX is left running at the end.

Output, in results/unit_<serial>/<campaign>/: lo_null_table.csv (one row per LO, sorted), lo_suppression_unit_<serial>.csv (freq_ghz,i_v,q_v,
the format of the GUI's shipped data/lo_suppression.csv), campaign.json (settings, and for every run its command line, note and
parameters). For a post-mortem of how the algorithm ran: logs/lo_<GHz>GHz.csv (every reading of every LO: bias, level, averaging, LMX
temperature), logs/run_<time>.txt (everything the run printed: every iteration, fit, refit and polish), and code/<time>/ (the exact
lo_null.py and lo_null_scan.py of the run). Nothing is copied to the board's flash here."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from pathlib import Path

import lo_null
from board import MeasurementSession
from cables import CableLoss
from conversion_gain_small_case import configure_board, must, tune_and_lock
from fieldfox import SETTLE_S, FieldFox
from lo_null import Nuller
from results_layout import unit_dir

LMX_POWER = 7
EXIT_TOO_HOT = 3                   # exit code: stopped by --max-lmx-temp-c
TEMP_POLL_S = 10.0                 # --min-lmx-temp-c: reading interval while waiting for the LMX to warm up
MAX_TEMP_ATTEMPTS = 10             # --min-lmx-temp-c: an LO whose search dipped below the minimum is redone up to this many times
RETRY_MARGIN_C = 1.0               # --min-lmx-temp-c: a redo first waits for minimum + this (one 0.85 C sensor step of headroom)
CONFIG_LO_HZ = 7.0e9              # the LMX is put in a known state here; every LO is then tuned before its search
FIELDS = ["freq_ghz", "i_v", "q_v", "leakage_dbm_at_board", "first_fit_i_v", "first_fit_q_v", "leakage_after_first_fit_dbm",
          "second_fit_shift_mv", "first_fit_step_mv", "second_fit_step_mv", "base_dbm_at_first_fit", "misfit1_db", "misfit2_db",
          "lmx_temp_c", "search_s", "first_fit_s", "second_fit_s", "total_s", "iterations", "refits", "polishes", "warm_start",
          "start_dbm", "outcome"]


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class _Tee:
    """A stream that writes to several streams (the console and a transcript file)."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, text):
        for stream in self.streams:
            stream.write(text)
        return len(text)

    def flush(self):
        for stream in self.streams:
            stream.flush()


@contextmanager
def transcript(path):
    """Copy everything printed inside the block into a text file (line-buffered, so it survives a crash or a kill)."""
    with open(path, "a", encoding="utf-8", buffering=1) as fh:
        console = sys.stdout
        sys.stdout = _Tee(console, fh)
        try:
            yield
        finally:
            sys.stdout = console


def snapshot_code(outdir: Path, stamp: str) -> None:
    """Keep the exact code of this run next to its data."""
    dest = outdir / "code" / stamp
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("lo_null.py", "lo_null_scan.py"):
        shutil.copy(Path(__file__).with_name(name), dest / name)


@contextmanager
def awake():
    """Windows: keep the PC from sleeping while a long scan runs (the display may still turn off); no power setting is changed."""
    import ctypes
    kernel32 = ctypes.windll.kernel32 if sys.platform == "win32" else None
    if kernel32:
        kernel32.SetThreadExecutionState(0x80000000 | 0x00000001)          # ES_CONTINUOUS | ES_SYSTEM_REQUIRED
    try:
        yield
    finally:
        if kernel32:
            kernel32.SetThreadExecutionState(0x80000000)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--campaign", required=True)
    p.add_argument("--lo-start-ghz", type=float, default=7.0)
    p.add_argument("--lo-stop-ghz", type=float, default=22.6)
    p.add_argument("--lo-step-ghz", type=float, default=0.1)
    p.add_argument("--warm-start", action="store_true",
                   help="start each LO from the previous frequency's null (if it is in the table and did not fail); a start that reads "
                        "too high falls back to the cold start from (0, 0)")
    p.add_argument("--max-minutes", type=float, default=0.0, help="stop cleanly between two LOs after this long (0 = no limit)")
    p.add_argument("--max-lmx-temp-c", type=float, default=0.0,
                   help="read the LMX temperature before every LO; at or above this, stop cleanly and exit with code "
                        f"{EXIT_TOO_HOT} so the caller can let the board cool (0 = no limit)")
    p.add_argument("--min-lmx-temp-c", type=float, default=0.0,
                   help="before every LO wait (LMX on) until the LMX reads at least this; an LO with any reading of its search below it "
                        f"is redone (up to {MAX_TEMP_ATTEMPTS} attempts, earlier logs kept), else kept with the outcome flagged (0 = no minimum)")
    p.add_argument("--temp-log", default="", help="CSV to append every pre-LO LMX temperature reading to (time, phase, lmx_on, temp)")
    p.add_argument("--live-plot", action="store_true", help="redraw live_null_vs_freq.png and write live.html")
    p.add_argument("--plot-every", type=int, default=1, help="with --live-plot: redraw after every N LOs (a 300 dpi picture takes seconds)")
    p.add_argument("--note", default="", help="free text stored with the run in campaign.json (fan state, set-up, purpose)")
    p.add_argument("--redo-ghz", default="", help="redo these LOs (comma-separated GHz values) whatever their result")
    p.add_argument("--redo-above-dbm", type=float, default=None,
                   help="redo every LO whose leakage at the null is above this level (dBm) or whose outcome is not ok")
    p.add_argument("--host", default="192.168.137.61")
    p.add_argument("--port", default=None)
    return p.parse_args()


# ---- the table ----

def write_table(path, rows) -> None:
    """(Re)write the table sorted by frequency; rows from an older table lacking a column get an empty entry."""
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS, restval="")
        writer.writeheader()
        writer.writerows(sorted(rows, key=lambda r: float(r["freq_ghz"])))


def load_table(path) -> dict[float, dict]:
    """The rows of an existing table by frequency (an older table is rewritten with the current columns)."""
    if not path.exists():
        return {}
    with open(path, newline="") as fh:
        reader = csv.DictReader(fh)
        header, rows = reader.fieldnames, list(reader)
    done = {round(float(r["freq_ghz"]), 4): r for r in rows}
    if header != FIELDS:
        write_table(path, list(done.values()))
    return done


def append_row(path, row: dict) -> None:
    new = not path.exists()
    with open(path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)


def write_suppression(path, done: dict) -> None:
    """freq_ghz,i_v,q_v of every LO that did not fail: the format of the GUI's shipped lo_suppression.csv."""
    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["freq_ghz", "i_v", "q_v"])
        for k in sorted(done):
            if not done[k]["outcome"].startswith("failed"):
                writer.writerow([f"{float(done[k]['freq_ghz']):g}", done[k]["i_v"], done[k]["q_v"]])


def pick_redo(done: dict, grid: list[float], args) -> list[float] | None:
    """The LOs to redo (None: no redo was asked for)."""
    listed = {round(float(x), 4) for x in args.redo_ghz.split(",")} if args.redo_ghz else set()
    if args.redo_above_dbm is None and not listed:
        return None

    def weak(row):
        return args.redo_above_dbm is not None and (float(row["leakage_dbm_at_board"]) > args.redo_above_dbm
                                                    or not row["outcome"].startswith("ok"))
    return [k for k in grid if k in done and (k in listed or weak(done[k]))]


def supersede(outdir, table_path, done: dict, redo: list[float]) -> None:
    """Move the rows of the LOs to redo out of the table into lo_null_table_superseded.csv."""
    path = outdir / "lo_null_table_superseded.csv"
    new = not path.exists() or path.stat().st_size == 0
    stamp = now()
    with open(path, "a", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS + ["superseded_at"], restval="")
        if new:
            writer.writeheader()
        for k in redo:
            writer.writerow({**done.pop(k), "superseded_at": stamp})
    write_table(table_path, list(done.values()))


def result_row(f_ghz: float, res: lo_null.NullResult, outcome: str, total_s: float) -> dict:
    return {"freq_ghz": f"{f_ghz:.3f}", "i_v": f"{res.i_v:.5f}", "q_v": f"{res.q_v:.5f}", "leakage_dbm_at_board": f"{res.level_dbm:.2f}",
            "first_fit_i_v": f"{res.first_fit_i_v:.5f}", "first_fit_q_v": f"{res.first_fit_q_v:.5f}",
            "leakage_after_first_fit_dbm": f"{res.level_first_fit_dbm:.2f}", "second_fit_shift_mv": f"{res.second_fit_shift_mv:.2f}",
            "first_fit_step_mv": f"{res.first_fit_step_v * 1e3:.3f}", "second_fit_step_mv": f"{res.second_fit_step_v * 1e3:.3f}",
            "base_dbm_at_first_fit": f"{res.base_dbm_at_first_fit:.2f}", "misfit1_db": f"{res.misfit1_db:.2f}",
            "misfit2_db": f"{res.misfit2_db:.2f}", "lmx_temp_c": f"{res.lmx_temp_c:.1f}", "search_s": f"{res.search_s:.1f}",
            "first_fit_s": f"{res.first_fit_s:.1f}", "second_fit_s": f"{res.second_fit_s:.1f}", "total_s": f"{total_s:.1f}",
            "iterations": res.iterations, "refits": res.refits, "polishes": res.polishes, "warm_start": int(res.warm_start),
            "start_dbm": "" if res.start_dbm != res.start_dbm else f"{res.start_dbm:.2f}", "outcome": outcome}


def summary_line(f_ghz: float, n_done: int, n_total: int, res: lo_null.NullResult, outcome: str, total_s: float) -> str:
    count = lambda n, one, many: f"  ({n} {one if n == 1 else many})" if n else ""
    return (f"  LO {f_ghz:7.3f} GHz [{n_done}/{n_total}]  I_V {res.i_v:+.5f}  Q_V {res.q_v:+.5f}  leakage {res.level_dbm:+6.1f} dBm  "
            f"{total_s:.1f} s  LMX {res.lmx_temp_c:.1f} C" + count(res.refits, "refit", "refits") + count(res.polishes, "polish", "polishes")
            + ("  (warm start)" if res.warm_start else "") + ("" if outcome == "ok" else f"   ({outcome})"))


# ---- the campaign ----

def algorithm_settings() -> dict:
    """What a campaign is compared on when it is resumed."""
    return {"lmx_power": LMX_POWER, "tx_filter": "bypass", "fieldfox_source": "off (IF input unloaded)",
            "start_step_v": lo_null.START_STEP_V, "min_step_v": lo_null.MIN_STEP_V, "fit_start_dbm": lo_null.FIT_START_DBM,
            "search_averages": lo_null.SEARCH_AVERAGES, "first_fit_averages": lo_null.FIRST_FIT_AVERAGES,
            "second_fit_averages": lo_null.SECOND_FIT_AVERAGES, "second_fit_step_fraction": lo_null.SECOND_FIT_STEP_FRACTION,
            "improvement_margin_db": lo_null.IMPROVEMENT_MARGIN_DB, "plateau_margin_db": lo_null.PLATEAU_MARGIN_DB,
            "span_hz": lo_null.NULL_SPAN_HZ, "attenuation_db": lo_null.FIXED_ATTENUATION_DB, "ref_level_dbm": lo_null.REF_LEVEL_DBM}


def update_campaign(outdir, args, board, cable_rf, serial: int) -> None:
    """Create campaign.json, or add this run to it. Only the algorithm settings must match; the frequency range and step may differ from run
    to run. The refit, polish, stall and warm-start parameters are recorded but not compared (they only act when needed)."""
    run = {"started": now(), "command": sys.argv[1:], "note": args.note, "lo_step_ghz": args.lo_step_ghz,
           "lmx_temp_c_at_start": board.get_lmx_temperature_c(),
           "refit": {"misfit_db": lo_null.REFIT_MISFIT_DB, "max_refits": lo_null.MAX_REFITS,
                     "min_second_fit_step_v": lo_null.MIN_SECOND_FIT_STEP_V, "stall_fit_step_v": lo_null.STALL_FIT_STEP_V,
                     "polish_above_dbm": lo_null.POLISH_ABOVE_DBM, "max_polishes": lo_null.MAX_POLISHES},
           "redo_above_dbm": args.redo_above_dbm, "redo_ghz": args.redo_ghz,
           "warm_start": {"averages": lo_null.WARM_START_AVERAGES, "grid_factor": lo_null.WARM_GRID_FACTOR,
                          "grid_min_v": lo_null.WARM_GRID_MIN_V, "grid_max_v": lo_null.WARM_GRID_MAX_V} if args.warm_start else None}
    path = outdir / "campaign.json"
    if path.exists():
        campaign = json.loads(path.read_text())
        if campaign["settings"] != algorithm_settings():
            raise RuntimeError(f"campaign {args.campaign} exists with different algorithm settings")
        campaign["lo_start_ghz"] = min(campaign["lo_start_ghz"], args.lo_start_ghz)
        campaign["lo_stop_ghz"] = max(campaign["lo_stop_ghz"], args.lo_stop_ghz)
        campaign["runs"].append(run)
    else:
        campaign = {"settings": algorithm_settings(), "unit_serial": serial, "fr3_cable_file": cable_rf.path.name,
                    "lo_start_ghz": args.lo_start_ghz, "lo_stop_ghz": args.lo_stop_ghz, "runs": [run]}
    path.write_text(json.dumps(campaign, indent=2))


def log_temp(path: str, phase: str, lmx_on: bool, temp_c: float) -> None:
    """Append one LMX temperature reading to the shared temperature log (hot_lo_null_watch.py writes the same file)."""
    if not path:
        return
    new = not Path(path).exists()
    with open(path, "a", newline="") as fh:
        w = csv.writer(fh)
        if new:
            w.writerow(["time", "phase", "lmx_on", "lmx_temp_c"])
        w.writerow([now(), phase, int(lmx_on), f"{temp_c:.1f}"])


def previous_null(done: dict, f_ghz: float, step_ghz: float):
    """The previous frequency's null (I_V, Q_V) for a warm start, or None (not in the table, or that LO failed)."""
    prev = done.get(round(f_ghz - step_ghz, 4))
    if prev is None or prev["outcome"].startswith("failed"):
        return None
    return float(prev["i_v"]), float(prev["q_v"])


def measure_lo(ff, board, cable_rf, outdir, f_ghz: float, start):
    """Retune, lock and run the algorithm at one LO frequency. Returns (result, outcome, seconds for the whole LO)."""
    t0 = time.monotonic()
    tune_and_lock(board, f_ghz * 1e9)
    time.sleep(SETTLE_S)
    ff.set_span(lo_null.NULL_SPAN_HZ)
    nuller = Nuller(ff, board, f_ghz * 1e9, cable_rf, outdir / "logs" / f"lo_{f_ghz:07.3f}GHz.csv")
    try:
        res = nuller.run(start)
    finally:
        nuller.close()
        ff.write("TRAC1:TYPE CLRW")                        # (restored to AVG by the next Nuller)
    lock = board.get_lmx_lock()
    return res, res.outcome if lock == "LOCKED" else f"{res.outcome}; LMX {lock}", time.monotonic() - t0


def scan(args: argparse.Namespace, stack: ExitStack) -> int:
    n = int(round((args.lo_stop_ghz - args.lo_start_ghz) / args.lo_step_ghz)) + 1
    grid = [round(args.lo_start_ghz + i * args.lo_step_ghz, 4) for i in range(n)]
    cable_rf = CableLoss("fr3_cable")
    for f in grid:
        cable_rf.s21_db(f * 1e9 + 3e6)                      # raise now if outside the cable data

    session = MeasurementSession(port=args.port)
    with session as board, FieldFox(args.host, span_hz=1e6) as ff:
        serial = board.get_board_serial()
        outdir = unit_dir(serial) / args.campaign
        (outdir / "logs").mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        stack.enter_context(transcript(outdir / "logs" / f"run_{stamp}.txt"))       # everything printed from here on is kept
        snapshot_code(outdir, stamp)
        print(f"{now()}  lo_null_scan.py {' '.join(sys.argv[1:])}" + (f"   note: {args.note}" if args.note else ""))
        table_path = outdir / "lo_null_table.csv"
        done = load_table(table_path)
        redo = pick_redo(done, grid, args)
        if redo is not None:
            if redo:
                supersede(outdir, table_path, done, redo)
            print(f"{len(redo)} LOs to redo: " + " ".join(f"{k:g}" for k in redo))
        todo = [f for f in grid if f not in done]
        update_campaign(outdir, args, board, cable_rf, serial)
        print(f"Unit #{serial}: {len(grid)} LOs ({grid[0]:g}-{grid[-1]:g} GHz in {args.lo_step_ghz:g} GHz steps), {len(todo)} to do. {outdir}")
        draw = None
        if args.live_plot:
            from plot_null_sweep import plot_campaign, write_live_page
            write_live_page(outdir)

            def draw() -> None:
                try:                                        # never let the picture break the measurement
                    plot_campaign(outdir, len(grid))
                except Exception as err:                    # noqa: BLE001
                    print("  (live plot failed:", err, ")")
            draw()                                          # a first picture so the page has something to show
        n_measured = 0
        too_hot = False

        t_run = time.monotonic()
        try:
            ff.setup_spectrum_analyzer(ref_level_dbm=lo_null.REF_LEVEL_DBM)
            ff.source_enable(False)
            configure_board(board, CONFIG_LO_HZ, "upper")   # LO INT, PWR 7, IQ THRU, bypass
            must(board.get_lmx_power() == LMX_POWER, f"LMX power is {board.get_lmx_power()}, expected {LMX_POWER}")
            for f_ghz in todo:
                if args.max_minutes and (time.monotonic() - t_run) / 60 > args.max_minutes:
                    print(f"Time budget of {args.max_minutes:g} min used; stopping cleanly before LO {f_ghz:g} GHz.")
                    break
                for attempt in range(1, MAX_TEMP_ATTEMPTS + 1):
                    if args.max_lmx_temp_c or args.min_lmx_temp_c or args.temp_log:
                        t_lmx = board.get_lmx_temperature_c()
                        log_temp(args.temp_log, f"scan, before LO {f_ghz:.3f} GHz", True, t_lmx)
                        if args.max_lmx_temp_c and t_lmx >= args.max_lmx_temp_c:
                            print(f"LMX at {t_lmx:.1f} C >= the {args.max_lmx_temp_c:g} C limit; stopping cleanly before LO {f_ghz:g} GHz.")
                            too_hot = True
                            break
                        need_c = args.min_lmx_temp_c + (RETRY_MARGIN_C if attempt > 1 else 0.0)
                        if args.min_lmx_temp_c and t_lmx < need_c:
                            print(f"LMX at {t_lmx:.1f} C < {need_c:g} C; waiting (LMX on) before LO {f_ghz:g} GHz.")
                            while t_lmx < need_c:
                                time.sleep(TEMP_POLL_S)
                                t_lmx = board.get_lmx_temperature_c()
                                log_temp(args.temp_log, f"scan, waiting for {need_c:g} C before LO {f_ghz:.3f} GHz",
                                         True, t_lmx)
                            print(f"LMX at {t_lmx:.1f} C; continuing.")
                    assert not ff.source_state(), "FieldFox source must be OFF"
                    start = previous_null(done, f_ghz, args.lo_step_ghz) if args.warm_start else None
                    res, outcome, total_s = measure_lo(ff, board, cable_rf, outdir, f_ghz, start)
                    if not args.min_lmx_temp_c:
                        break
                    log_path = outdir / "logs" / f"lo_{f_ghz:07.3f}GHz.csv"
                    with open(log_path, newline="") as fh:
                        t_min = min(float(r["lmx_temp_c"]) for r in csv.DictReader(fh))
                    if t_min >= args.min_lmx_temp_c:
                        break
                    kept = log_path.with_name(f"{log_path.stem}_below_{args.min_lmx_temp_c:g}C_attempt{attempt}.csv")
                    log_path.replace(kept)
                    if attempt == MAX_TEMP_ATTEMPTS:
                        outcome += f"; LMX below {args.min_lmx_temp_c:g} C (min {t_min:.1f} C)"
                        print(f"  LO {f_ghz:g} GHz: LMX dipped to {t_min:.1f} C on every attempt; kept with the outcome flagged.")
                        log_path.write_bytes(kept.read_bytes())
                        break
                    print(f"  LO {f_ghz:g} GHz: LMX dipped to {t_min:.1f} C during the search (< {args.min_lmx_temp_c:g} C); "
                          f"discarded (log kept as {kept.name}), redoing.")
                if too_hot:
                    break
                row = result_row(f_ghz, res, outcome, total_s)
                done[round(f_ghz, 4)] = row
                append_row(table_path, row)
                write_suppression(outdir / f"lo_suppression_unit_{serial:03d}.csv", done)
                n_measured += 1
                print(summary_line(f_ghz, sum(g in done for g in grid), len(grid), res, outcome, total_s))
                if errs := ff.errors():
                    print("  FieldFox errors:", errs)
                if draw and n_measured % args.plot_every == 0:
                    draw()
            if draw:
                draw()                                      # the final state
        finally:
            try:
                if done:
                    write_table(table_path, list(done.values()))      # leave the table sorted by frequency
            except Exception as err:                                  # noqa: BLE001
                print("  (could not sort the table:", err, ")")
            ff.source_enable(False)
            try:
                ff.set_span(1e6)
                ff.set_rbw(None)
            finally:
                ff.restore_instrument_state()
            time.sleep(SETTLE_S)
            off = not ff.source_state()
            session.snapshot = board.snapshot()              # keep the LMX running (steady temperature between runs)
            print("FieldFox source confirmed OFF (read back)." if off else "*** WARNING: FieldFox source STILL ON!")
    print(f"Run done: {sum(g in done for g in grid)} of {len(grid)} LOs of this range are in the table. "
          "Board left with the LMX on; flash persistence back ON.")
    return EXIT_TOO_HOT if too_hot else 0


def main() -> int:
    args = parse_args()
    with awake(), ExitStack() as stack:                     # the transcript file (entered inside scan) closes after the last print
        return scan(args, stack)


if __name__ == "__main__":
    sys.exit(main())

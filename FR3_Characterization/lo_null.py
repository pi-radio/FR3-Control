"""LO-leakage nulling of the FR3 board: finds the I_V / Q_V bias voltages that cancel the LO leakage at one LO frequency.

Near its null the leakage power is an elliptical bowl in the (I_V, Q_V) plane, P = a x^2 + b y^2 + c x y + d x + e y + f: the I and Q
curvatures differ and the axes can be rotated. For one LO frequency the algorithm is:

  0. Warm start (optional). Read the previous frequency's null (4 averages). Below -10 dBm, skip the coarse search and go straight to
     the first fit with a grid sized from the reading (about 2.5 x the distance it implies, 2.5 to 25 mV). Otherwise, or if that first
     fit is not usable, do the cold start.
  1. Coarse search (cold start). From (0, 0) with a 200 mV step, five readings per iteration (the unchanged point and I_V, Q_V +- step,
     1 average each); move to the best point, or halve the step when the unchanged point is best (the step never grows). It ends at the
     first iteration whose unchanged point reads below -10 dBm. If it runs out of steps above that level it has stalled in a long
     diagonal valley, and the fit stage starts there with a 25 mV grid.
  2. First fit. Nine readings (3 x 3 grid at the current step, 8 averages) and an elliptical fit: its minimum is the first null.
  3. Second fit. The same around the first null with 10 % of the spacing (16 averages; the centre reading is the leakage at the first
     null). Its minimum is the final null, and the leakage is measured there.
  4. Polish. While that leakage is above -45 dBm (at most twice), repeat the second fit around the final null with half the spacing
     (not below 0.3 mV) and keep the new null only if it measures better.
  Refits. A first fit with a misfit above 0.3 dB is repeated with half the spacing around the best point of its grid; so is a first fit
  whose second fit is not usable (around the first null). At most three refits.

Every reading: set the bias, wait 0.1 s, restart the FieldFox's trace averaging (INIT:REST), wait for it to converge, read marker 1.
The FieldFox source stays OFF (nothing into the FR1 IF input); span, attenuation, reference level, RBW and VBW are fixed, only the
averaging count changes (1 / 8 / 16)."""

from __future__ import annotations

import csv
import math
import time
from dataclasses import dataclass

import numpy as np

from cables import CableLoss
from fieldfox import SETTLE_S, FieldFox

# ---- algorithm parameters ----
START_STEP_V = 0.2                 # coarse search: first step (it only ever shrinks) ...
MIN_STEP_V = 1e-4                  # ... and the finest step
FIT_START_DBM = -10.0              # the fit stage starts when the unchanged point reads below this (dBm at the board)
IMPROVEMENT_MARGIN_DB = 0.3        # a probe must beat the unchanged point by this much to win an iteration ...
PLATEAU_MARGIN_DB = 0.15           # ... or by this much before the first move (the PA is saturated at (0, 0))
STALL_FIT_STEP_V = 0.025           # first grid when the coarse search has stalled above FIT_START_DBM
MAX_ITERATIONS = 120
MAX_MINUTES = 5.0                  # time limit per LO frequency

SEARCH_AVERAGES = 1                # FieldFox averaging: coarse search
FIRST_FIT_AVERAGES = 8             # ... first fit
SECOND_FIT_AVERAGES = 16           # ... second fit, final measurement and polish
SECOND_FIT_STEP_FRACTION = 0.1     # second-fit grid spacing as a fraction of the first fit's ...
MIN_SECOND_FIT_STEP_V = 3e-4       # ... but never below 300 uV (about 4 DAC codes)
REFIT_MISFIT_DB = 0.3              # a first fit with a larger misfit is repeated (recentred on its best point) ...
MAX_REFITS = 3                     # ... at most this many refits in all
POLISH_ABOVE_DBM = -45.0           # a final null that measures above this is polished ...
MAX_POLISHES = 2                   # ... at most this many times

WARM_START_AVERAGES = 4            # warm start: averaging of the reading of the previous null
WARM_GRID_FACTOR = 2.5             # ... first grid = this x the estimated distance to the null,
WARM_GRID_MIN_V = 2.5e-3           # ... kept between these limits
WARM_GRID_MAX_V = 25e-3
BOWL_DBM_AT_390UV = -37.2          # mean leakage 391 uV from the null (measured over 157 frequencies), 6 dB per doubling

# ---- hardware and analyzer ----
BIAS_LIMIT_V = 0.5                 # firmware limit on I_V and Q_V
DAC_SPAN_V = 2.5                   # 16-bit DAC over +-2.5 V (76 uV per code)
NULL_SPAN_HZ = 20e3
REF_LEVEL_DBM = 10.0
FIXED_ATTENUATION_DB = 20
VOLTAGE_SETTLE_S = 0.1             # for the board to apply a new I_V / Q_V
WAIT_SCALE = 0.5                   # averaging wait = this x (0.3 s + n x 2 x sweep time), verified against a 3 x longer wait
MIN_WAIT_S = 0.15

GRID9 = {"c": (0, 0), "I+": (1, 0), "I-": (-1, 0), "Q+": (0, 1), "Q-": (0, -1),
         "I+Q+": (1, 1), "I+Q-": (1, -1), "I-Q+": (-1, 1), "I-Q-": (-1, -1)}
NAN = float("nan")


def quantize(volts: float) -> float:
    """The voltage the 16-bit LTC2668 actually outputs for a request."""
    code = min(65535, max(0, int(round((volts + DAC_SPAN_V) / (2 * DAC_SPAN_V) * 65535))))
    return code / 65535 * 2 * DAC_SPAN_V - DAC_SPAN_V


def warm_grid_step(start_dbm: float) -> float:
    """First-fit grid spacing for a warm start reading start_dbm. Leakage grows as the distance squared, so the reading implies a
    distance d = 0.39 mV x 10^((level - BOWL_DBM_AT_390UV) / 20); the grid is WARM_GRID_FACTOR x d, clamped."""
    d = 0.39e-3 * 10 ** ((start_dbm - BOWL_DBM_AT_390UV) / 20)
    return min(max(WARM_GRID_FACTOR * d, WARM_GRID_MIN_V), WARM_GRID_MAX_V)


@dataclass
class NullResult:
    ok: bool                              # False: no usable fit; i_v, q_v, level_dbm are then the best point of the coarse search
    outcome: str                          # "ok", "first fit only" (second fit not usable), "failed: <reason>"; "... (stall fallback)"
    i_v: float                            # the final null (V)
    q_v: float
    level_dbm: float                      # leakage measured at the final null (dBm at the board connector)
    lmx_temp_c: float                     # LMX temperature at the last reading
    search_s: float                       # time of the coarse search (including the analyzer set-up)
    first_fit_s: float                    # time of the first fit's grids
    second_fit_s: float                   # time of the second fit, the polish and the final measurement
    iterations: int                       # coarse-search iterations
    first_fit_step_v: float = NAN         # grid spacing of the accepted first fit ...
    second_fit_step_v: float = NAN        # ... and of the second fit
    base_dbm_at_first_fit: float = NAN    # level of the point the fit stage started from
    first_fit_i_v: float = NAN
    first_fit_q_v: float = NAN
    level_first_fit_dbm: float = NAN      # leakage at the first null
    second_fit_shift_mv: float = NAN      # distance from the first to the final null
    misfit1_db: float = NAN               # rms difference between fitted and measured levels: first fit ...
    misfit2_db: float = NAN               # ... and second fit
    refits: int = 0
    polishes: int = 0
    warm_start: bool = False              # the result came from a warm start (no coarse search)
    start_dbm: float = NAN                # level of the warm-start reading (nan: none was taken)


@dataclass
class _Fit:
    """A fitted null: bias, misfit, the grid spacing it came from, and the leakage measured there (dBm at the board, once known)."""
    i: float
    q: float
    misfit: float
    h: float
    level: float | None = None

    def distance_mv(self, i: float, q: float) -> float:
        return math.hypot(self.i - i, self.q - q) * 1e3


class _Clock:
    """Accumulating stopwatch: the time spent inside `with clock:` blocks adds up in clock.total."""

    def __init__(self):
        self.total = 0.0

    def __enter__(self):
        self._t = time.monotonic()

    def __exit__(self, *exc):
        self.total += time.monotonic() - self._t


class Nuller:
    """One LO frequency: create it after the LMX is locked, call run(), then close()."""

    def __init__(self, ff: FieldFox, board, f_lo: float, cable_rf: CableLoss, log_path):
        self.ff, self.board, self.f_lo = ff, board, f_lo
        self.s21 = cable_rf.s21_db(f_lo)                  # negative: level at the board = level at the FieldFox - s21
        self.center = f_lo                                # the analyzer's centre; follows the tone if it wanders
        self.plan: tuple[int, float] | None = None        # (attenuation dB, RBW Hz) once the analyzer is configured
        self.n_avg, self.sweep_s, self.temp_c, self._offset = 0, 0.03, NAN, 0.0
        self.log = open(log_path, "w", newline="")
        self.w = csv.writer(self.log)
        self.w.writerow(["t_s", "iter", "step_v", "averages", "att_db", "rbw_hz", "point", "i_v", "q_v", "level_dbm_at_ff",
                         "level_dbm_at_board", "tone_offset_hz", "lmx_temp_c"])
        self.t0 = time.monotonic()

    def close(self) -> None:
        self.log.close()

    def _elapsed(self) -> float:
        return time.monotonic() - self.t0

    def _dbm(self, level_at_ff: float) -> float:
        """A FieldFox level as dBm at the board connector."""
        return level_at_ff - self.s21

    # ---- analyzer and readings ----

    def configure_analyzer(self) -> None:
        """Fix every analyzer setting once (span, attenuation, reference level, RBW/VBW automatic, trace AVG); only the averaging count
        changes afterwards."""
        if self.plan is not None:
            return
        ff = self.ff
        ff.set_attenuation(FIXED_ATTENUATION_DB)
        ff.set_ref_level(REF_LEVEL_DBM)
        ff.set_span(NULL_SPAN_HZ)
        ff.set_rbw(None)
        ff.set_vbw_auto()
        ff.write(f"SENS:AVER:COUN {SEARCH_AVERAGES}")
        self.n_avg = SEARCH_AVERAGES
        ff.write("TRAC1:TYPE AVG")
        ff.write("INIT:CONT ON")
        time.sleep(SETTLE_S)
        self.sweep_s = float(ff.query("SENS:SWE:MTIM?"))
        rbw_hz = ff.rbw_hz
        self.plan = (FIXED_ATTENUATION_DB, rbw_hz)
        waits = ", ".join(f"{self.convergence_wait_s_for(n):.2f} s (x{n})" for n in (SEARCH_AVERAGES, FIRST_FIT_AVERAGES, SECOND_FIT_AVERAGES))
        print(f"  analyzer (fixed for every reading): span {NULL_SPAN_HZ / 1e3:g} kHz, attenuation {FIXED_ATTENUATION_DB} dB, reference level "
              f"{REF_LEVEL_DBM:+g} dBm, RBW automatic ({rbw_hz:g} Hz), VBW automatic; averaging x{SEARCH_AVERAGES} in the search, "
              f"x{FIRST_FIT_AVERAGES} first fit, x{SECOND_FIT_AVERAGES} second fit; sweep {self.sweep_s * 1e3:.0f} ms; wait after each restart {waits}")

    def convergence_wait_s_for(self, n: int) -> float:
        """Wait after INIT:REST for n sweeps to be averaged: half of the old conservative 0.3 s + n x max(30 ms, 2 x sweep time)."""
        return max(MIN_WAIT_S, WAIT_SCALE * (0.3 + n * max(0.03, 2.0 * self.sweep_s)))

    def _marker(self) -> tuple[float, float]:
        self.ff.write("CALC:MARK1:FUNC:MAX")
        return float(self.ff.query("CALC:MARK1:X?")), float(self.ff.query("CALC:MARK1:Y?"))

    def _restart_and_read(self) -> float:
        """Restart the averaging, wait, read marker 1; re-centre on the tone if the independent clocks let it wander to the span's edge."""
        for _ in range(2):
            self.ff.write("INIT:REST")
            time.sleep(self.convergence_wait_s_for(self.n_avg))
            x, y = self._marker()
            self._offset = x - self.f_lo
            if abs(x - self.center) <= 0.3 * self.ff.span_hz:
                break
            self.center = x
            self.ff.tune(x)
        return y

    def set_iq(self, i_v: float, q_v: float) -> bool:
        if abs(i_v) > BIAS_LIMIT_V or abs(q_v) > BIAS_LIMIT_V:
            return False
        ok = self.board.set_i_v(i_v) and self.board.set_q_v(q_v)
        time.sleep(VOLTAGE_SETTLE_S)
        return bool(ok)

    def measure_point(self, it: int, step: float, name: str, i_v: float, q_v: float, averages: int) -> float:
        """One reading: set the bias, restart the averaging, read. Returns the level at the FieldFox in dBm (+inf if the bias is out of
        range). Every reading is logged."""
        if averages != self.n_avg:
            self.ff.write(f"SENS:AVER:COUN {averages}")
            self.n_avg = averages
        if not self.set_iq(i_v, q_v):
            return math.inf
        level = self._restart_and_read()
        self.temp_c = self.board.get_lmx_temperature_c()
        self.w.writerow([f"{self._elapsed():.1f}", it, f"{step:.6f}", self.n_avg, *self.plan, name, f"{i_v:.6f}", f"{q_v:.6f}",
                         f"{level:.2f}", f"{self._dbm(level):.2f}", f"{self._offset:.0f}", f"{self.temp_c:.1f}"])
        self.log.flush()
        return level

    # ---- grids and the elliptical fit ----

    def _grid_readings(self, it: int, centre: tuple[float, float], h: float, averages: int, tag: str) -> list[tuple[float, float, float]]:
        """Nine readings (I_V, Q_V, level at the FieldFox) on a 3 x 3 grid of spacing h around centre, the centre first."""
        readings = []
        for name, (dx, dy) in GRID9.items():
            i, q = quantize(centre[0] + dx * h), quantize(centre[1] + dy * h)
            readings.append((i, q, self.measure_point(it, h, f"{tag}-{name}", i, q, averages)))
        return readings

    def _fit_ellipse(self, points: list[tuple[float, float, float]], centre: tuple[float, float], h: float):
        """Null of the bowl fitted to a grid's nine readings. The linear power is fitted by least squares with relative weights (the
        readings scatter in proportion to their power); x, y are the voltages relative to the centre in units of h. Returns
        (I_V, Q_V, misfit_dB), or None if the fit is not usable: not a bowl, minimum farther than 5 spacings from the centre or beyond
        the bias limit. The misfit is the rms difference between fitted and measured levels."""
        p = np.array([((i - centre[0]) / h, (q - centre[1]) / h, 10 ** (self._dbm(lv) / 10)) for i, q, lv in points if math.isfinite(lv)])
        if len(p) < 7:
            return None
        x, y, power = p.T
        basis = np.column_stack([x * x, y * y, x * y, x, y, np.ones_like(x)])
        coef = np.linalg.lstsq(basis / power[:, None], np.ones_like(power), rcond=None)[0]      # weights 1/power
        a, b, c, d, e, _ = coef
        det = 4 * a * b - c * c
        if a <= 0 or b <= 0 or det <= 0:
            return None
        x0, y0 = (c * e - 2 * b * d) / det, (c * d - 2 * a * e) / det
        i_null, q_null = centre[0] + x0 * h, centre[1] + y0 * h
        if math.hypot(x0, y0) > 5 or abs(i_null) > BIAS_LIMIT_V or abs(q_null) > BIAS_LIMIT_V:
            return None
        misfit = float(np.sqrt(np.mean((10 * np.log10(np.maximum(basis @ coef, 1e-15) / power)) ** 2)))
        return quantize(float(i_null)), quantize(float(q_null)), misfit

    # ---- the fit stage ----

    def _second_fit(self, it: int, first: _Fit, tag: str) -> tuple[_Fit | None, float]:
        """Second fit around the first null; sets first.level from its centre reading. Returns (second null measured, or None if the
        fit is not usable; the grid spacing used)."""
        h2 = max(SECOND_FIT_STEP_FRACTION * first.h, MIN_SECOND_FIT_STEP_V)
        grid = self._grid_readings(it, (first.i, first.q), h2, SECOND_FIT_AVERAGES, f"g2{tag}")
        first.level = self._dbm(grid[0][2])
        print(f"  measured at the first fitted null: {first.level:+.2f} dBm at the board connector")
        est = self._fit_ellipse(grid, (first.i, first.q), h2)
        if est is None:
            return None, h2
        second = _Fit(*est, h2, self._dbm(self.measure_point(it, h2, "fit2", est[0], est[1], SECOND_FIT_AVERAGES)))
        print(f"  second fit (3 x 3 grid, {h2 * 1e3:g} mV): null I {second.i:+.5f} Q {second.q:+.5f} "
              f"({second.distance_mv(first.i, first.q):.2f} mV from the first, misfit {second.misfit:.2f} dB); measured there: {second.level:+.2f} dBm")
        return second, h2

    def _polish(self, it: int, second: _Fit) -> tuple[_Fit, int]:
        """While the final null still measures above POLISH_ABOVE_DBM (at most MAX_POLISHES times), refit around it with half the grid
        spacing and keep the new null only if it measures better. Returns (the null kept, polishes done)."""
        h, polishes = second.h, 0
        while second.level > POLISH_ABOVE_DBM and polishes < MAX_POLISHES:
            h, polishes = max(h / 2, MIN_SECOND_FIT_STEP_V), polishes + 1
            grid = self._grid_readings(it, (second.i, second.q), h, SECOND_FIT_AVERAGES, f"g3p{polishes}")
            est = self._fit_ellipse(grid, (second.i, second.q), h)
            if est is None:
                print(f"  polish {polishes} (3 x 3 grid, {h * 1e3:g} mV) not usable: the null is kept")
                break
            new = _Fit(*est, h, self._dbm(self.measure_point(it, h, "fitp", est[0], est[1], SECOND_FIT_AVERAGES)))
            better = new.level < second.level
            print(f"  polish {polishes} (3 x 3 grid, {h * 1e3:g} mV): null I {new.i:+.5f} Q {new.q:+.5f} "
                  f"({new.distance_mv(second.i, second.q):.2f} mV from the previous, misfit {new.misfit:.2f} dB); measured there: "
                  f"{new.level:+.2f} dBm (was {second.level:+.2f}): " + ("kept" if better else "not better, the previous null is kept"))
            if better:
                second = new
        self.set_iq(second.i, second.q)                    # the last point read may not be the null that was kept
        return second, polishes

    def _fits(self, it: int, centre: tuple[float, float], step: float, base_dbm: float, search_s: float, iterations: int):
        """The fit stage around the coarse search's current point (see the module docstring): first fit, second fit, refits, polish.
        Returns a NullResult, or None if the very first fit is not usable (the coarse search then carries on)."""
        t_first, t_second = _Clock(), _Clock()
        c, h = centre, step                                # centre and spacing of the current first-fit grid
        first = second = None
        h2, refits = NAN, 0
        for attempt in range(MAX_REFITS + 1):
            last = attempt == MAX_REFITS
            tag = f"r{attempt}" if attempt else ""
            with t_first:
                grid = self._grid_readings(it, c, h, FIRST_FIT_AVERAGES, f"g1{tag}")
            est = self._fit_ellipse(grid, c, h)
            if est is None:
                if first is None:
                    return None                            # not even the first first fit works: the coarse search carries on
                print(f"  refit (grid {h * 1e3:g} mV) not usable: the previous first-fit null is kept")
                break
            first = _Fit(*est, h)
            why = f"is below {FIT_START_DBM:g} dBm" if base_dbm < FIT_START_DBM else "(the search has stalled)"
            print(f"  it {it:2d} " + (f"step {step:.5f}: base {base_dbm:+.2f} dBm {why} -> " if attempt == 0 else "")
                  + f"first fit (3 x 3 grid, {h * 1e3:g} mV): null I {first.i:+.5f} Q {first.q:+.5f} "
                  f"({first.distance_mv(*c):.2f} mV from the centre, misfit {first.misfit:.2f} dB)")
            if first.misfit > REFIT_MISFIT_DB and not last:
                ib, qb, lb = min((p for p in grid if math.isfinite(p[2])), key=lambda p: p[2])    # a poor fit's null is not trusted
                print(f"  misfit above {REFIT_MISFIT_DB:g} dB: the first fit is repeated around the best point of this grid "
                      f"({ib:+.5f}, {qb:+.5f}; {self._dbm(lb):+.1f} dBm) with half the grid spacing")
                c, h, refits = (ib, qb), h / 2, refits + 1
                continue
            with t_second:
                second, h2 = self._second_fit(it, first, tag)
            if second is not None:
                break
            if last:
                print("  second fit not usable: the first fitted null is kept")
                break
            print("  second fit not usable: the first fit is repeated around this null with half the grid spacing")
            c, h, refits = (first.i, first.q), h / 2, refits + 1

        polishes = 0
        if second is not None:
            with t_second:
                second, polishes = self._polish(it, second)
        elif first.level is None:                          # a refit that was not usable followed a first fit that was never measured
            with t_second:
                first.level = self._dbm(self.measure_point(it, first.h, "fit1", first.i, first.q, SECOND_FIT_AVERAGES))
        if second is None:
            self.set_iq(first.i, first.q)                  # the last point read may be a probe
        final = second or first
        return NullResult(
            ok=True, outcome="ok" if second else "first fit only", i_v=final.i, q_v=final.q, level_dbm=final.level,
            lmx_temp_c=self.temp_c, search_s=search_s, first_fit_s=t_first.total, second_fit_s=t_second.total, iterations=iterations,
            first_fit_step_v=first.h, second_fit_step_v=h2, base_dbm_at_first_fit=base_dbm, first_fit_i_v=first.i, first_fit_q_v=first.q,
            level_first_fit_dbm=first.level, second_fit_shift_mv=second.distance_mv(first.i, first.q) if second else 0.0,
            misfit1_db=first.misfit, misfit2_db=second.misfit if second else NAN, refits=refits, polishes=polishes)

    # ---- warm start, coarse search, entry point ----

    def run(self, start: tuple[float, float] | None = None) -> NullResult:
        """The whole algorithm for this LO frequency. With `start` (the previous frequency's null) a warm start is tried first;
        if it does not apply, the cold start runs."""
        self.configure_analyzer()
        self.ff.tune(self.center)
        start_dbm = NAN
        if start is not None:
            result, start_dbm = self._warm_start(start)
            if result is not None:
                return result
        result = self._cold_run()
        result.start_dbm = start_dbm
        return result

    def _warm_start(self, start: tuple[float, float]):
        """Read the start point. Below FIT_START_DBM go straight to the fit stage with a grid sized from the reading. Returns
        (NullResult or None, start level in dBm); None means: use the cold start."""
        i0, q0 = quantize(start[0]), quantize(start[1])
        level = self._dbm(self.measure_point(0, START_STEP_V, "warm-start", i0, q0, WARM_START_AVERAGES))
        print(f"  warm start from the previous null ({i0:+.5f}, {q0:+.5f}): {level:+.2f} dBm at the board connector")
        if level >= FIT_START_DBM:
            print(f"  not below {FIT_START_DBM:g} dBm: cold start from (0, 0)")
            return None, level
        h = warm_grid_step(level)
        print(f"  below {FIT_START_DBM:g} dBm: straight to the first fit, grid {h * 1e3:.2f} mV")
        result = self._fits(0, (i0, q0), h, level, self._elapsed(), 0)
        if result is None:
            print("  the first fit is not usable: cold start from (0, 0)")
            return None, level
        result.warm_start, result.start_dbm = True, level
        return result, level

    def _cold_run(self) -> NullResult:
        """Coarse search from (0, 0), then the fit stage. If no usable fit turns up before the search runs out of steps, iterations or
        time, the result is not ok and holds the best point of the search."""
        i_v = q_v = quantize(0.0)
        step, moved, it, outcome = START_STEP_V, False, 0, "failed: iteration limit"
        rule = "  " + "-" * 100
        print(rule)
        base = self.measure_point(0, step, "start", i_v, q_v, SEARCH_AVERAGES)
        print(f"  start: I_V {i_v:+.4f}  Q_V {q_v:+.4f}  level {self._dbm(base):+.2f} dBm at the board connector")
        for it in range(1, MAX_ITERATIONS + 1):
            if self._elapsed() / 60 > MAX_MINUTES:
                outcome = "failed: time limit"
                break
            print(rule)
            cands = {"base": (i_v, q_v), "I+": (quantize(i_v + step), q_v), "I-": (quantize(i_v - step), q_v),
                     "Q+": (i_v, quantize(q_v + step)), "Q-": (i_v, quantize(q_v - step))}
            res = {name: self.measure_point(it, step, name, ci, cq, SEARCH_AVERAGES) for name, (ci, cq) in cands.items()}
            level = self._dbm(res["base"])
            if level < FIT_START_DBM:
                result = self._fits(it, (i_v, q_v), step, level, self._elapsed(), it)
                if result is not None:
                    return result
                print(f"  it {it:2d} below {FIT_START_DBM:g} dBm but the first fit is not usable: the search carries on")
            best = min(res, key=res.get)
            margin = PLATEAU_MARGIN_DB if (not moved and level > FIT_START_DBM) else IMPROVEMENT_MARGIN_DB
            if best != "base" and res[best] < res["base"] - margin:
                moved = True
                i_v, q_v = cands[best]
                base = res[best]
                print(f"  it {it:2d} step {step:.5f}: {best:>2} wins  {level:+7.2f} -> {self._dbm(base):+7.2f} dBm "
                      f"(I {i_v:+.5f} Q {q_v:+.5f})   avg x{self.n_avg}")
                continue
            base = res["base"]
            if step <= MIN_STEP_V * 1.0001:
                # Out of steps and still above the fit threshold: stalled, typically on the floor of a long diagonal valley. The fit
                # stage starts here with a wide grid: the fitted ellipse points along the valley.
                print(f"  it {it:2d} the search has stalled at {level:+.2f} dBm: fit stage from here with a {STALL_FIT_STEP_V * 1e3:g} mV grid")
                result = self._fits(it, (i_v, q_v), STALL_FIT_STEP_V, level, self._elapsed(), it)
                if result is not None:
                    result.outcome += " (stall fallback)"
                    return result
                outcome = f"failed: no usable fit down to a step of {MIN_STEP_V * 1e6:.0f} uV"
                break
            step = max(step / 2, MIN_STEP_V)
            print(f"  it {it:2d} step -> {step:.6f}: no better point ({self._dbm(res[best]):+.2f} vs unchanged {level:+.2f} dBm)   avg x{self.n_avg}")
        self.set_iq(i_v, q_v)                              # failed: leave the bias at the best point of the search
        return NullResult(ok=False, outcome=outcome, i_v=i_v, q_v=q_v, level_dbm=self._dbm(base), lmx_temp_c=self.temp_c,
                          search_s=self._elapsed(), first_fit_s=0.0, second_fit_s=0.0, iterations=it)

"""Minimal SCPI-over-TCP driver for a Keysight FieldFox (tested on N9918B,
firmware A.13.25). Standard library only.

Measurement rules for this project (the FieldFox's RBW is poor):
  * The spectrum-analyzer span stays small (default DEFAULT_SPAN_HZ = 1 MHz,
    which lowers the noise floor; it was 10 MHz earlier). To look at a
    different frequency, retune the center frequency instead of widening the
    span.
  * After every retune, wait SETTLE_S (100 ms) before taking a reading.
  * The FieldFox and the board under test run on independent clocks, so with
    a span this small a tone appears slightly off its nominal frequency.
    measure_at() therefore re-centers on the tone if it lands far from the
    center; the marker frequency it reports is the tone's true position.

All SCPI syntax here comes from Keysight's "FieldFox SCPI Programming Help"
(SA mode, "Independent Source"): SOURce:ENABle / :MODE / :FREQuency[:CW] /
:POWer, INITiate:IMMediate, TRACe<n>:TYPE, and CALCulate:MARKer<n>
(:STATe / :FUNCtion:MAXimum / :X? / :Y?). SA mode does not accept the
optional [:SELected] node on CALCulate.

Readings come from marker 1 (peak search in the span), never from a full
trace download."""

from __future__ import annotations

import socket
import time
from dataclasses import dataclass

SCPI_PORT = 5025
DEFAULT_SPAN_HZ = 1e6
RECENTER_FRACTION = 0.25  # re-center if the tone is more than this fraction of the span off-center
SETTLE_S = 0.100
# SA-mode independent source. The SCPI guide says -45..0 dBm, but this N9918B
# (firmware A.13.25) accepts down to -60 dBm (confirmed: -60 reads back, -65 is
# clipped to -60), as the owner said.
SOURCE_POWER_RANGE_DBM = (-60.0, 0.0)
REF_MAX_DBM = 20.0   # highest reference level used (input attenuator ~35 dB)
REF_MIN_DBM = -50.0  # lowest reference level used


class FieldFoxError(Exception):
    """Instrument reported an SCPI error, or a query got no answer."""


@dataclass(frozen=True)
class ToneReading:
    """Marker 1 after a peak search inside the span."""
    center_hz: float
    freq_hz: float
    power_dbm: float


class FieldFox:
    def __init__(self, host: str, timeout_s: float = 15.0, port: int = SCPI_PORT,
                 span_hz: float = DEFAULT_SPAN_HZ):
        self.host = host
        self.span_hz = span_hz
        self._sock = socket.create_connection((host, port), timeout=timeout_s)
        self._sock.settimeout(timeout_s)
        self._rx = b""
        self._saved_trace_type: str | None = None
        self._saved_attenuation: tuple[bool, float] | None = None

    def close(self) -> None:
        try:
            self._sock.close()
        except OSError:
            pass

    def __enter__(self) -> "FieldFox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- raw SCPI ----

    def write(self, cmd: str) -> None:
        self._sock.sendall((cmd + "\n").encode("ascii"))

    def query(self, cmd: str) -> str:
        self.write(cmd)
        while b"\n" not in self._rx:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise FieldFoxError(f"connection closed during {cmd!r}")
            self._rx += chunk
        line, _, self._rx = self._rx.partition(b"\n")
        return line.decode("ascii", "replace").strip()

    def errors(self) -> list[str]:
        """Drains and returns the instrument's error queue."""
        found = []
        for _ in range(32):
            reply = self.query("SYST:ERR?")
            if reply.startswith("0,"):
                break
            found.append(reply)
        return found

    def check(self, what: str) -> None:
        errs = self.errors()
        if errs:
            raise FieldFoxError(f"{what}: {'; '.join(errs)}")

    # ---- setup ----

    def identify(self) -> str:
        return self.query("*IDN?")

    def select_mode(self, mode: str, timeout_s: float = 20.0) -> None:
        """Switches the FieldFox mode (e.g. "SA", "NA") and waits until it
        actually reports that mode - a mode change can take seconds, and
        *OPC? alone does not reliably cover it. Nothing else should be sent
        until this returns."""
        wanted = f'"{mode}"'
        if self.query("INST:SEL?") != wanted:
            self.write(f'INST:SEL "{mode}"')
            self.query("*OPC?")
        deadline = time.monotonic() + timeout_s
        while self.query("INST:SEL?") != wanted:
            if time.monotonic() > deadline:
                raise FieldFoxError(f"FieldFox did not switch to {mode} mode within {timeout_s:.0f} s")
            time.sleep(0.25)
        time.sleep(0.5)  # let the new mode's display/state settle

    def setup_spectrum_analyzer(self, ref_level_dbm: float = -10.0) -> None:
        """SA mode, fixed span (self.span_hz), clear/write trace, single-sweep
        triggering so every reading is one complete, fresh, un-averaged sweep.

        Trace type matters: the instrument can be left with trace 1 in AVG
        (running average) from earlier use, which silently blends each new
        sweep with previous ones - a step in signal level then shows up only
        partially, and only gradually, in the readings."""
        self.write("*CLS")
        self.select_mode("SA")
        self._saved_trace_type = self.query("TRAC1:TYPE?")
        self._saved_attenuation = (self.query("SENS:POW:ATT:AUTO?") in ("1", "ON"),
                                   float(self.query("SENS:POW:ATT?")))
        self.write("TRAC1:TYPE CLRW")
        self.write(f"SENS:FREQ:SPAN {self.span_hz:.0f}")
        self.write(f"DISP:WIND:TRAC:Y:RLEV {ref_level_dbm:.1f}")
        self.write("CALC:MARK1:STAT NORM")
        # NEVER INIT:CONT OFF on this instrument (standing user rule). Until 2026-10-09 this helper sent it, and every
        # reading triggered single sweeps (INIT:IMM); the FieldFox crashed seconds after one such set-up. Continuous sweep
        # stays ON; read_tone() waits for two complete fresh sweeps instead.
        self.write("INIT:CONT ON")
        self.check("spectrum analyzer setup")

    def set_ref_level(self, dbm: float) -> None:
        """Reference level. In SA mode the input attenuator follows it
        (auto), so this also sets the noise floor and the overload margin.
        Waits SETTLE_S like every other analyzer retune."""
        self.write(f"DISP:WIND:TRAC:Y:RLEV {dbm:.1f}")
        time.sleep(SETTLE_S)

    @property
    def attenuation_db(self) -> float:
        return float(self.query("SENS:POW:ATT?"))

    def set_attenuation(self, db: float) -> None:
        """Holds the input attenuator FIXED at db (this also switches auto
        attenuation off), then reads it back and refuses to continue unless
        it really took. With a fixed attenuator, changes in signal level
        cannot be confused with attenuator steps."""
        self.write(f"SENS:POW:ATT {db:.0f}")
        time.sleep(SETTLE_S)
        if self.query("SENS:POW:ATT:AUTO?") in ("1", "ON") or abs(self.attenuation_db - db) > 0.01:
            raise FieldFoxError(f"could not hold the input attenuation fixed at {db:.0f} dB")

    def restore_instrument_state(self) -> None:
        """Undo the trace-type, attenuation and sweep-mode changes made by
        setup_spectrum_analyzer()/set_attenuation()."""
        saved = getattr(self, "_saved_trace_type", None)
        if saved:
            self.write(f"TRAC1:TYPE {saved}")
        if self._saved_attenuation is not None:
            was_auto, was_db = self._saved_attenuation
            if was_auto:
                self.write("SENS:POW:ATT:AUTO ON")
            else:
                self.write(f"SENS:POW:ATT {was_db:.0f}")
        self.write("INIT:CONT ON")

    def set_span(self, hz: float) -> None:
        """Changes the analyzer span (and the span read_tone() expects). The default 1 MHz span is the project
        rule; a narrower span is for calibrations that need a lower noise floor (e.g. LO nulling)."""
        self.write(f"SENS:FREQ:SPAN {hz:.0f}")
        self.span_hz = hz
        time.sleep(SETTLE_S)

    def set_rbw(self, hz: float | None) -> None:
        """Resolution bandwidth in Hz, or None for automatic."""
        if hz is None:
            self.write("SENS:BAND:RES:AUTO ON")
        else:
            self.write(f"SENS:BAND:RES {hz:.0f}")
        time.sleep(SETTLE_S)

    def set_vbw_auto(self) -> None:
        """Video bandwidth automatic ([:SENSe]:BANDwidth:VIDeo:AUTO)."""
        self.write("SENS:BAND:VID:AUTO ON")
        time.sleep(SETTLE_S)

    @property
    def rbw_hz(self) -> float:
        return float(self.query("SENS:BAND:RES?"))

    @property
    def points(self) -> int:
        return int(self.query("SENS:SWE:POIN?"))

    # ---- CW source (SA-mode "Independent Source", Port 1) ----

    def source_configure(self, freq_hz: float, power_dbm: float) -> None:
        lo, hi = SOURCE_POWER_RANGE_DBM
        if not lo <= power_dbm <= hi:
            raise ValueError(f"source power {power_dbm} dBm outside {lo}..{hi} dBm")
        self.write("SOUR:MODE CW")
        self.write(f"SOUR:FREQ {freq_hz:.0f}")
        self.write(f"SOUR:POW {power_dbm:.2f}")

    def source_enable(self, on: bool) -> None:
        self.write(f"SOUR:ENAB {'ON' if on else 'OFF'}")

    def source_state(self) -> bool:
        return self.query("SOUR:ENAB?") in ("1", "ON")

    # ---- spectrum analyzer readings ----

    def tune(self, center_hz: float) -> None:
        """Retune the SA center frequency (span unchanged) and wait the
        mandatory settling time before returning."""
        self.write(f"SENS:FREQ:CENT {center_hz:.0f}")
        time.sleep(SETTLE_S)

    def wait_fresh_sweeps(self, sweeps: float = 2.2, sweep_time_query: str = "SENS:SWE:MTIM?") -> None:
        """Continuous-sweep replacement for INIT:IMM;*OPC? (never INIT:CONT OFF on this instrument): waits long
        enough for `sweeps` complete sweeps after a change, so the trace read next is entirely fresh. SA mode reports
        its measured sweep time with SENS:SWE:MTIM?; other modes pass their own sweep-time query."""
        time.sleep(max(0.15, sweeps * float(self.query(sweep_time_query))))

    def read_tone(self) -> ToneReading:
        """One complete sweep at the current center frequency, then marker 1
        is moved to the highest point in the span and read. Only the marker's
        frequency and level cross the network - never the full trace. Call
        tune() first (it includes the 100 ms wait)."""
        center = float(self.query("SENS:FREQ:CENT?"))
        span = float(self.query("SENS:FREQ:SPAN?"))
        if abs(span - self.span_hz) > 1.0:
            raise FieldFoxError(f"span is {span:.0f} Hz, expected {self.span_hz:.0f} Hz")
        # continuous sweep (never INIT:CONT OFF / INIT:IMM): wait for two complete sweeps after the retune, so the
        # clear-write trace is entirely fresh, then peak-search it
        t_sweep = float(self.query("SENS:SWE:MTIM?"))
        time.sleep(max(0.15, 2.2 * t_sweep))
        self.write("CALC:MARK1:FUNC:MAX")
        freq = float(self.query("CALC:MARK1:X?"))
        power = float(self.query("CALC:MARK1:Y?"))
        return ToneReading(center_hz=center, freq_hz=freq, power_dbm=power)

    def measure_at(self, center_hz: float, recenter: bool = True) -> ToneReading:
        """Tune, read, and - because the instrument and the device under test
        have independent clocks - if the tone landed far from the center,
        re-center on it (with the usual settling wait) and read again, so it
        sits mid-span and cannot drift out of a narrow span."""
        self.tune(center_hz)
        r = self.read_tone()
        if recenter and abs(r.freq_hz - r.center_hz) > RECENTER_FRACTION * self.span_hz:
            self.tune(r.freq_hz)
            r = self.read_tone()
        return r

    def measure_tone_adaptive(self, center_hz: float, ref_hint_dbm: float,
                              apply_ref: bool = True) -> tuple[ToneReading, float]:
        """Tunes to center_hz and reads the tone, adjusting the reference
        level (amplitude setting) until the tone sits comfortably below it:
        raise it if the tone is within 4 dB of the top (overload risk), lower
        it if the tone is more than 25 dB below (noise floor needlessly high).
        Returns the reading and the final reference level.

        Pass apply_ref=False if the caller has already set ref_hint_dbm."""
        ref = min(max(ref_hint_dbm, REF_MIN_DBM), REF_MAX_DBM)
        if apply_ref:
            self.set_ref_level(ref)
        r = self.measure_at(center_hz)
        for _ in range(3):
            if r.power_dbm > ref - 4.0 and ref < REF_MAX_DBM:
                ref = min(r.power_dbm + 7.0, REF_MAX_DBM)
            elif r.power_dbm < ref - 25.0 and ref > REF_MIN_DBM:
                ref = max(r.power_dbm + 12.0, REF_MIN_DBM)
            else:
                break
            self.set_ref_level(ref)
            r = self.read_tone()
        return r, ref

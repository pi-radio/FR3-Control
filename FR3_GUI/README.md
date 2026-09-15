# FR3 Board Control — GUI & Firmware Reference

This document explains how the FR3 Board Control GUI is put together, which
functionality lives on the STM32 firmware versus in the host application,
gives a full reference for the serial command protocol the two sides speak,
and calls out specifically which numbers you can trust as exact versus which
are estimates.

---

## 1. Overview

**FR3 Board Control** is a cross-platform (Windows/Linux) desktop application
built with PySide6 (Qt) for discovering and controlling "FR3 1CH" and
"OctoLO" RF boards over a USB CDC (virtual serial port) connection. Each
connected board gets its own tab; the GUI auto-detects boards as they are
plugged in or removed, adapts its controls to what that specific board
revision actually supports, and talks to the board using a simple
line-based ASCII command protocol described in full in Section 5.

The GUI never assumes what a board can do — it identifies the board and
firmware revision with `*IDN?` and looks up a capability table (mirrored on
both sides) before showing any control for a feature that revision doesn't
have.

A connected board's tab is organized into up to four top-level sections
("Configuration Helper", "Clocking and LO", "TX Settings", "RX Settings"),
each collapsible by clicking its heading — all four start expanded, but
collapsing the ones you're not using avoids scrolling a long page. Mouse-
wheel scrolling is also blocked on every numeric field, dropdown, and
slider application-wide, so scrolling down the page can never silently
change a value the cursor happens to pass over.

---

## 2. System Architecture

```
 ┌─────────────────────────┐        USB CDC ACM         ┌───────────────────────────┐
 │   FR3 Board Control      │  ASCII commands, 1 line   │   STM32H573VIT6 firmware   │
 │   (this GUI, PySide6)    │ ─────────────────────────▶ │   (FR3 1CH / OctoLO)       │
 │                          │ ◀───────────────────────── │                            │
 │  - Device discovery      │      1 response line       │  - LMX2820 LO synthesizer  │
 │  - Per-board tabs        │                             │  - LTC2668 I/Q bias DAC    │
 │  - Configuration Helper  │                             │  - Clock/LO/IQ GPIO switch │
 │  - Suggest I_V/Q_V       │                             │  - AM3153 RF filter control│
 │  - Local settings cache  │                             │  - EDATA settings storage  │
 └─────────────────────────┘                             └───────────────────────────┘
```

The GUI is a thin, stateless client: on every reconnect it re-reads the
board's current state with a snapshot of `GET`/`?` queries rather than
caching what it last sent. All actual hardware state — the LMX2820's tuned
frequency, the DAC voltages, filter selections, and so on — lives on the
board and survives a power cycle via the STM32H5's EDATA flash region (see
Section 4.1).

---

## 3. GUI Codebase Structure

All GUI code lives under `fr3_gui/`, with bundled calibration data under
`data/` and automated tests under `tests/`.

| File | Responsibility |
|---|---|
| `device.py` | The protocol layer. One `Device` object wraps one open serial port; every method sends one command and parses one response line. Thread-safe (internal lock), no Qt dependency, fully unit-testable against a mock serial port. |
| `capabilities.py` | A static `(board name, revision) → BoardCapabilities` lookup table, mirroring the firmware's own `BOARD_HAS_*` compile-time flags (Section 7). |
| `discovery.py` | A background `QThread` that polls for USB devices matching the target VID/PID, probes new ones with `*IDN?`, and emits Qt signals when a board appears or disappears. Never touches a `Device` again once ownership is handed off to a tab, to avoid two threads racing on the same serial port. |
| `worker.py` | One `DeviceWorker` `QThread` per connected board. All serial traffic for that board — commands queued from the GUI thread, plus a periodic LMX2820 lock-status poll — happens on this thread only, so the UI never blocks on I/O. |
| `main_window.py` | The main window: turns discovery's connect/disconnect signals into tabs appearing and disappearing, and does a one-time auto-size of the window at startup to fit the first tab's content. |
| `device_tab.py` | The per-board tab UI: builds the collapsible "Configuration Helper", "Clocking and LO", "TX Settings", and "RX Settings" sections shown for a given board's capabilities, and reflects live values read back from the board. |
| `widgets.py` | Small reusable input widgets used by `device_tab.py`: a debounced slider+spinbox voltage control, a Bank/Configuration filter control (used for both TX and RX), and a spinbox that displays uppercase hex. |
| `configuration_helper.py` | The "Configuration Helper": takes the desired FR1 (IF) frequency, FR3 (RF) frequency, and sideband, computes the LMX2820 frequency that produces that FR3 output, and tunes it automatically. Also plots where the desired sideband, undesired sideband, and LO leakage land, overlaid with a candidate filter's real measured response, and offers "Suggest Filter"/"Automatically Select Filter" to recommend one - the recommendation itself isn't TX- or RX-specific, it's just published for TX/RX Settings to apply if they choose to. |
| `no_wheel_filter.py` | An application-wide Qt event filter (installed once in `main.py`) that blocks mouse-wheel scrolling from changing any spin box, combo box, or slider's value anywhere in the app. |
| `am3153_filter.py` | Loads the 49 bundled AM3153 filter S-parameter measurement files and maps a filter control byte to its measured S21 response. |
| `lo_suppression.py` | Loads the bundled LO-suppression calibration table and interpolates a suggested I_V/Q_V pair for a given LO frequency (used by "Suggest I_V and Q_V"). |
| `local_settings.py` | Per-machine, per-physical-unit GUI preferences (currently the Configuration Helper's FR1/FR3/bandwidth inputs), stored as JSON under the app data directory (see `paths.py`). Entirely separate from the board's own firmware persistence. |
| `lmx_register_dialog.py` | A non-modal bring-up/debug dialog for reading raw LMX2820 registers directly. |
| `logging_setup.py` | Console + rotating file logging, written under the app data directory (see `paths.py`). |
| `paths.py` | The OS-appropriate, persistent, always-writable directory for settings/logs (`%LOCALAPPDATA%` on Windows, `~/Library/Application Support` on macOS, `~/.local/share` on Linux) — deliberately not `__file__`-relative, since that breaks once packaged (Section 8). |
| `main.py` | Application entry point. |

### 3.1 Data files (`data/`)

- `am3153_sparams/*.s2p` — 49 Touchstone S-parameter files, one measured
  sweep per filter bank/sub-state combination (see Section 6 for what this
  data does and doesn't tell you).
- `lo_suppression.csv` — 157 rows of `freq_ghz, i_v, q_v`: I/Q bias voltages
  measured on **one** calibration unit that null out the LMX2820's own LO
  leakage at each frequency (see Section 6).

### 3.2 Tests (`tests/`)

26 automated tests (`pytest`) covering the serial protocol layer
(`test_device.py`, including the echo-skipping logic), the S-parameter
lookup (`test_am3153_filter.py`), local settings persistence
(`test_local_settings.py`), and the LO-suppression interpolation
(`test_lo_suppression.py`). Run with:

```
pytest tests/ -q
```

---

## 4. Division of Responsibility: Firmware vs. Host GUI

This is the most important thing to understand before trusting any number
the GUI shows you: **the firmware only ever does exactly what a command
tells it to** (tune to this frequency, set this voltage, select this
filter). Every piece of *advice* — which filter to pick, which voltages to
try — is computed by the host GUI from data files bundled with it, and the
firmware has no idea any of that reasoning happened.

### 4.1 Implemented on the board (firmware, `FR3_1CH_Firmware`)

- Driving the LMX2820 LO synthesizer: computing all 123 PLL registers for a
  requested frequency and writing them over SPI, reading back lock status,
  setting output power, and full mute/power-down.
- Driving the LTC2668 DAC to set the I and Q bias voltages.
- Reading and switching the Clock Source, LO Source, and IQ Swap GPIOs.
- Reading and driving the AM3153 TX/RX filter control lines (rev 1.4 only).
- Persisting every one of the above settings to the STM32H5's EDATA flash
  region on every change (`Settings_Save()`), so the board comes back up in
  the same state after a power cycle — without the GUI (or anything else)
  needing to resend anything.
- Storing the board's own serial number (factory-programmed once via `SET
  BOARD SERIAL`), used by the GUI purely to identify a physical unit
  independent of which COM port it enumerates on.
- Two general-purpose test-point GPIOs (`TP1`, `TP2`) for bring-up
  diagnostics.

### 4.2 Implemented on the host (this GUI, no firmware involvement)

- **Device discovery**, capability lookup, and per-tab UI construction.
- **The Configuration Helper's LO frequency computation** — from your
  entered FR1 (IF) frequency, FR3 (RF) frequency, and sideband choice, the
  GUI solves for the LMX2820 frequency that produces that FR3 output
  (`f_lo = FR3 − FR1` for upper sideband, `f_lo = FR3 + FR1` for lower) and
  sends one `LMX TUNE` command to apply it — the firmware has no concept
  of "FR1"/"FR3", it only ever receives a plain frequency to tune to.
- **The Configuration Helper's graph** — the desired/undesired sideband
  and LO leakage positions are computed from the LO frequency, sideband
  choice, and your entered FR1/bandwidth; none of this is measured or read
  back from the board.
- **"Suggest Filter" / "Automatically Select Filter"** — searches all 48
  non-Bypass filter configurations against the bundled S-parameter data and
  picks the one that best passes the desired sideband while rejecting the
  undesired one, purely as a calculation over the data file. With
  "Automatically Select Filter" checked (the default), this re-runs live
  every time FR1, FR3, bandwidth, or sideband changes; unchecking it makes
  "Suggest Filter" a manual button instead. Either way, the result is only
  a recommendation - the Configuration Helper never sends `SET TXFILTER`/
  `SET RXFILTER` itself.
- **TX/RX Settings' "Automatically apply the Suggested Filter from the
  Configuration Helper"** — each checkbox (checked by default, independent
  of the other) is what actually sends `SET TXFILTER`/`SET RXFILTER`,
  keeping that filter's Bank/Configuration control greyed out and in sync
  with the current recommendation above. Unchecking either one hands that
  specific filter back to manual Bank/Configuration selection - TX and RX
  can be in "automatic" and "manual" mode independently of each other.
- **"Suggest I_V and Q_V" / "Automatically set I_V and Q_V"** — looks up
  the bundled calibration table (Section 3.1) for the current LO frequency
  and interpolates a suggested bias voltage pair. With "Automatically set"
  checked (the default), this re-applies live via `SET I_V`/`SET Q_V`
  every time the LO is retuned, and greys out the I_V/Q_V sliders;
  unchecking it hands them back to manual control.
- **Per-machine settings** (Configuration Helper's FR1/FR3/bandwidth
  inputs) — stored in a local JSON file next to the GUI, not on the board.

---

## 5. Serial Command Reference

### 5.1 Conventions

- Transport is USB CDC ACM (a virtual COM port); the configured baud rate
  is ignored by CDC but pyserial requires one to be given (115200 is used).
- Every command is a single ASCII line. The firmware accepts either a bare
  CR or CRLF as the line ending (PuTTY's default "Serial" mode sends bare
  CR, which the parser handles).
- Commands are **case-insensitive**.
- The firmware always sends back exactly one response line for one command
  line: `OK` for a successful action, `ERR` (or an `ERR:[...]` echo for an
  unrecognized command) for a failure, or a value for a query (`?`).
- Below, `>` marks what the host sends and `<` what the board replies.

### 5.2 Identity & Persistence

| Command | Direction | Response | Notes |
|---|---|---|---|
| `*IDN?` | query | `<board name> REV<revision>,STM32H573VIT6,FW<fw version>` | Used by discovery to identify the board and revision. `<fw version>` is the firmware's `FIRMWARE_VERSION` (`board_config.h`) - kept matching the GUI's own version (`fr3_gui/version.py`). |
| `SET BOARD SERIAL <n>` | set | `OK` | One-time factory step; `n` is an unsigned integer. Persists across power cycles. |
| `GET BOARD SERIAL` | query | `<n>` | Defaults to `0` until set. Used as this unit's stable identity, independent of COM port. |

```
> *IDN?
< FR3 1CH REV1.4,STM32H573VIT6,FW1.00

> GET BOARD SERIAL
< 7
```

### 5.3 LMX2820 Local Oscillator

| Command | Direction | Response | Range |
|---|---|---|---|
| `LMX TUNE <freq_hz>` | set | `OK` / `ERR` | 6,000,000,000 – 22,600,000,000 Hz |
| `LMX FREQ?` | query | `<freq_hz>` | — |
| `LMX PWR <0-7>` | set | `OK` / `ERR` | 0–7 (output drive level) |
| `LMX PWR?` | query | `<0-7>` | — |
| `LMX MUTE ON` / `LMX MUTE OFF` | set | `OK` / `ERR` | `ON` fully powers the chip down; `OFF` re-tunes it and can take a couple of seconds |
| `LMX MUTE?` | query | `ON` / `OFF` | — |
| `LMX LOCK?` | query | `LOCKED` / `UNLOCKED` | Fresh SPI read every call |
| `LMX TEMP?` | query | `<decimal, 1 place>` (°C) | Die temperature from the LMX2820's own sensor; approximate, see Section 6 |
| `LMX REG<n>?` | query | `0x<hex>` | Raw register readback, `n` = 0–122, bring-up/debug only |

```
> LMX TUNE 12000000000
< OK
> LMX FREQ?
< 12000000000
> LMX LOCK?
< LOCKED
> LMX TEMP?
< 42.3
```

### 5.4 LTC2668 I/Q Bias DAC

| Command | Direction | Response | Range |
|---|---|---|---|
| `SET I_V <volts>` | set | `OK` / `ERR` | −0.5 to +0.5 V (software-limited; DAC's own span is ±2.5V) |
| `GET I_V` | query | `<volts>` (6 decimals) | — |
| `SET Q_V <volts>` | set | `OK` / `ERR` | −0.5 to +0.5 V |
| `GET Q_V` | query | `<volts>` (6 decimals) | — |

```
> SET I_V -0.180000
< OK
> GET I_V
< -0.180000
```

### 5.5 Clock / LO / IQ Source Switching

| Command | Direction | Response |
|---|---|---|
| `SET CLOCK INT` / `SET CLOCK EXT` | set | `OK` |
| `GET CLOCK` | query | `INT` / `EXT` |
| `SET LO INT` / `SET LO EXT` | set | `OK` / `ERR` |
| `GET LO` | query | `INT` / `EXT` |
| `SET IQ THRU` / `SET IQ SWAP` | set | `OK` |
| `GET IQ` | query | `THRU` / `SWAP` |

Selecting `SET LO EXT` also mutes the internal LMX2820 (and `SET LO INT`
un-mutes and re-tunes it) so the internal and external LO paths can never
both drive the output at once.

### 5.6 RF Filters (FR3 1CH rev 1.4 only)

| Command | Direction | Response |
|---|---|---|
| `SET TXFILTER 0x<hh>` | set | `OK` |
| `GET TXFILTER` | query | `0x<hh>` |
| `SET RXFILTER 0x<hh>` | set | `OK` |
| `GET RXFILTER` | query | `0x<hh>` |

`<hh>` is the low 6 bits of a control byte, MSB to LSB: `VA VB V3 V2 V1 V0`
(bit 5 down to bit 0). `VA`/`VB` select Bypass, Band 1 (~6–12GHz), Band 2
(~12–18GHz), or Band 3 (~18–26GHz) on the AM3153; `V3-V0` select one of 16
sub-states within that band. These commands are silent no-ops (compile to
nothing) on any board without `BOARD_HAS_RF_FILTERS` — including FR3 1CH
rev 1.1, where those same pins are hard-wired to ground.

```
> SET TXFILTER 0x31
< OK
> GET TXFILTER
< 0x31
```

### 5.7 Test Point Diagnostics

| Command | Direction | Response |
|---|---|---|
| `TP<n>?` | query | `0` / `1` / `ERR` |
| `TP<n> ON` / `TP<n> OFF` | set | `OK` |

`n` is `1` or `2`. General-purpose bring-up/health-check test points, not
tied to any RF function.

---

## 6. Accuracy & Precision Notes

Some numbers in this system are exact, deterministic outputs of firmware
that does exactly what it's told. Others are estimates built from measured
data on a small number of samples, or from illustrative reference levels.
**Treat the two very differently:**

| Value | Precision | Why |
|---|---|---|
| **LMX2820 LO frequency** (`LMX TUNE`/`LMX FREQ?`) | **Exact.** | The firmware computes PLL_N/PLL_NUM/PLL_DEN directly from the requested frequency using a fractional-N denominator large enough to hit any requested integer Hz exactly (confirmed bit-exact against reference TI TICS Pro register dumps). What you ask for is what gets programmed. |
| **LO frequency computed by the Configuration Helper from FR1/FR3/sideband** | **Exact.** | `f_lo = FR3 − FR1` (upper sideband) or `f_lo = FR3 + FR1` (lower sideband) is plain arithmetic on the frequencies you typed, not an estimate — the result is applied via the same exact `LMX TUNE` path as a manually entered frequency. If the required `f_lo` falls outside the LMX2820's 6.0–22.6GHz range, the GUI says so and does not apply it. |
| **DAC bias voltages** (`SET I_V`/`SET Q_V`, `GET I_V`/`GET Q_V`) | **Exact, as digital-to-analog conversions.** | The 16-bit LTC2668 converts a requested voltage to a DAC code deterministically; this is not an estimate. |
| **I_V/Q_V values suggested by "Suggest I_V and Q_V"** | **Estimate.** | These come from a table measured on **one** calibration unit's LO leakage at each frequency, linearly interpolated between the nearest two measured points. Actual optimal values will vary somewhat from unit to unit and with temperature — treat the suggestion as a good starting point to fine-tune from, not a guaranteed null. The table only covers 7.0–22.6GHz; below that the recommended approach is a high-side LO with the lower sideband instead (the GUI will tell you this rather than guessing). |
| **AM3153 filter S21 response shown in the Configuration Helper graph** | **Real measured data, but from one filter sample.** | The 49 `.s2p` files are actual network-analyzer sweeps of one AM3153 filter, not simulated or datasheet-typical curves. Unit-to-unit variation between filters is not captured. |
| **Desired/undesired sideband and LO leakage *levels* drawn in the Configuration Helper graph** | **Illustrative only — not measured amplitudes.** | Their vertical extents (0 to −50dB for desired/LO, −15 to −50dB for undesired) are reference conventions chosen to make the plot readable, not a measurement of your actual signal chain. Only their horizontal (frequency) positions are computed from real inputs. |
| **Rejection dB figure shown for a filter selection or by "Suggest Filter"** | **Estimate.** | It is the real filter's own measured S21 difference between the desired and undesired sideband frequencies, **plus** a fixed assumed baseline mixer suppression (15dB, matching the graph's illustrative desired/undesired gap) that is not separately measured for your specific mixer. Treat it as a useful ranking between filter choices, not a guaranteed system-level rejection number. The display is also capped at ">50dB" above that threshold, since real filter behavior won't track the measured S-parameter data that precisely at very high rejection. |
| **LMX lock status** (`LMX LOCK?`) | **Exact.** | A fresh SPI readback of the synthesizer's own lock-detect register, decoded into LOCKED or UNLOCKED. The register's own rb_LD field actually has a third, "invalid" state (0b11) per TI's register map, but the firmware reports that as UNLOCKED too rather than exposing it as a distinct third value. |
| **LMX2820 die temperature** (`LMX TEMP?`) | **Estimate — ±5°C per datasheet.** | Computed from a fresh SPI readback of the chip's own `rb_TEMP_SENS` field using TI's published `Temp_C = 0.85 × code − 415` formula (0.6°C/code resolution). TI's own E2E forum has an open, TI-acknowledged discrepancy between this formula and their own characterization data, so treat the displayed value as a rough indicator, not a calibrated measurement. |
| **Board serial number, filter bit readback, clock/LO/IQ source state** | **Exact.** | All are direct digital readbacks (persisted settings or live GPIO levels), not estimates. |

---

## 7. Board Capability Matrix

The GUI only shows controls a board revision actually has, based on a
static table (`capabilities.py`) that mirrors the firmware's own
`BOARD_HAS_*` compile-time flags (`board_config.h`) exactly:

| Board | Revision | LMX2820 | LTC2668 I/Q DAC | Clock Switch | LO Switch | IQ Swap | RF Filters |
|---|---|---|---|---|---|---|---|
| FR3 1CH | 1.1 | Yes | Yes | Yes | Yes | Yes | No |
| FR3 1CH | 1.4 | Yes | Yes | Yes | Yes | Yes | Yes |
| OctoLO | 1.4 | Yes | No | No | No | No | No |

FR3 1CH rev 1.1 does not have the RF filter or power-sequencing hardware at
all — on that revision, the pins rev 1.4 uses for those features are
hard-wired to ground on the PCB, and the firmware's `#if BOARD_HAS_*` guards
ensure a rev 1.1 build never contains any code path capable of driving them.

---

## 8. Distributing the GUI as a Standalone Executable

For sharing this GUI with users who shouldn't need to install Python or any
dependencies, see **[PACKAGING.md](PACKAGING.md)** — it covers building a
Windows/Linux/macOS executable with PyInstaller, the automated GitHub
Actions build for all three platforms, and platform-specific caveats
(Linux glibc/distro compatibility, unsigned-app warnings on macOS).

If the GUI won't start on Linux, it's almost always one of two known,
easy, one-time fixes covered there in detail: a missing `libxcb-cursor0`
(Qt6's platform plugin dependency) or the current user not being in the
`dialout` group yet (needed to open `/dev/ttyACM*` for the board's serial
connection) — see **[PACKAGING.md](PACKAGING.md#platform-specific-notes)**
for the exact commands.

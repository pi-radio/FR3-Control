"""Generate the datasheet's one-page "Key Specifications" table (sections/sec0_summary_table.tex) from the numbers the
datasheet itself already shows, so the summary can never disagree with the sections (user request, 2026-10-05).

Sources (all in FR3-1ch-Datasheet/):
  conversion gain   the (FR1, FR3, gain) cell labels printed on the gain heatmaps images/sec{1,2,7,8}_fig{8,9}.pdf
  P1dB              the values printed on the compression panels images/sec{4,5,9,10}_fig*.pdf
  sideband / image  the bar charts images/sec3_fig{2,4,6,8}.pdf and sec11_fig{2,4,6,8}.pdf (the raw data are not in this
                    repo): medians as printed; the 10th percentile is read from the bars, so it is good to one bin (1.3 dB)
  NF, phase noise,  the generated macro files sections/sec12_numbers.tex, sec14_numbers.tex, sec14_table.tex,
  LO leakage        sec6_cal_numbers.tex; 2xLO sec_2lo_numbers.tex; TX sideband sec_sideband_numbers.tex
"In spec" throughout: FR3 <= 24 GHz and FR1 centre <= 3.5 GHz (the FR1 = 4.0 GHz window runs 250 MHz past the IF spec).

    python make_summary_table.py
"""
from __future__ import annotations

import re

import numpy as np
import pymupdf

from plot_datasheet_nf import DATASHEET, IMAGES

SECTIONS = DATASHEET / "sections"
FR3_MAX, FR1_MAX = 24.0, 3.5
MINUS = "\u2212"


def signed_float(s: str) -> float:
    """A number as printed in a figure: a hyphen or a true minus sign."""
    return float(s.replace(MINUS, "-"))


def macros(name: str) -> dict[str, str]:
    text = (SECTIONS / name).read_text(encoding="utf-8")
    return dict(re.findall(r"\\newcommand\{\\(\w+)\}\{([^}]*)\}", text))


def heatmap_cells(fig: str) -> list[tuple[float, float, float]]:
    t = pymupdf.open(IMAGES / fig)[0].get_text()
    return [(float(a), float(b), float(c)) for a, b, c in re.findall(r"^\s*([\d.]+), ([\d.]+), (-?[\d.]+)\s*$", t, re.M)]


def in_spec_gain(fig: str) -> np.ndarray:
    return np.array([g for fr1, fr3, g in heatmap_cells(fig) if fr3 <= FR3_MAX and fr1 <= FR1_MAX])


def compression(prefix: str) -> dict[str, np.ndarray]:
    """Input/output P1dB of every compression panel with FR3 <= 24 GHz."""
    out = {"in": [], "out": []}
    for k in range(1, 10):
        t = pymupdf.open(IMAGES / f"{prefix}_fig{k}.pdf")[0].get_text()
        fr3 = float(re.search(r"FR3 ?= ?([\d.]+) GHz", t).group(1))
        if fr3 > FR3_MAX:
            continue
        out["in"].append(signed_float(re.search(r"Input P1dB: ([-−]?[\d.]+)", t).group(1)))
        out["out"].append(signed_float(re.search(r"Output P1dB: ([-−]?[\d.]+)", t).group(1)))
    return {k: np.array(v) for k, v in out.items()}


def histogram(fig: str) -> tuple[float, float]:
    """(printed median, 10th percentile read from the bars) of one of the old-style bar-chart histograms."""
    p = pymupdf.open(IMAGES / fig)[0]
    t = p.get_text()
    median = signed_float(re.search(r"[Mm]edian(?:=|: )([-−]?[\d.]+)", t).group(1))
    num = lambda s: float(s.replace(MINUS, "-"))
    nums = [(w[0], w[2], w[1], num(w[4])) for w in p.get_text("words") if w[4].replace(".", "").lstrip(MINUS + "-").isdigit()]
    ybot = max(n[2] for n in nums)
    ticks = sorted(((n[0] + n[1]) / 2, n[3]) for n in nums if abs(n[2] - ybot) < 2)
    (x0, v0), (x1, v1) = ticks[0], ticks[-1]
    tov = lambda x: v0 + (x - x0) * (v1 - v0) / (x1 - x0)
    bars = sorted((tov(r.x0), tov(r.x1), r.height) for d in p.get_drawings() if d.get("fill")
                  for it in d["items"] if it[0] == "re" for r in [it[1]] if r.height > 0.3 and r.width < 40)
    total, acc = sum(b[2] for b in bars), 0.0
    for lo, hi, h in bars:                                    # 10th percentile, linear within the bin
        if acc + h >= 0.1 * total:
            return median, lo + (0.1 * total - acc) / h * (hi - lo)
        acc += h
    raise RuntimeError(fig)


def fmt(v: float, d: int = 1, sign: bool = False) -> str:
    s = f"{v:+.{d}f}" if sign else f"{v:.{d}f}"
    return s.replace("-", MINUS)


def mmm(a: np.ndarray) -> tuple[str, str, str]:
    return fmt(a.min()), fmt(float(np.median(a))), fmt(a.max())


def main() -> None:
    nf, pn = macros("sec12_numbers.tex"), macros("sec14_numbers.tex")
    fl = macros("flatness_numbers.tex")
    sp = macros("sec_spur_numbers.tex")

    def flat_rows(chain: str, sides, sec: str) -> None:
        for key, side in sides:
            for filt, word in (("Optimal", "filter optimal"), ("Bypass", "filter bypassed")):
                tag = f"flat{chain}{key}{filt}"
                row(chain.upper(), "Gain flatness (RMS)", f"{side}, {word}", fl[tag + "Min"],
                    fl[tag + "Median"], fl[tag + "Max"], "dB", sec)
    pn_rows = {m.group(1): m.group(2) for m in re.finditer(r"^(\d+)\\,GHz &(.*?)\\\\", (SECTIONS / "sec14_table.tex")
                                                              .read_text(encoding="utf-8"), re.M)}
    pn100k_10 = pn_rows["10"].split("&")[3].strip()
    rows = []                                                 # (group, parameter, condition, min, typ, max, unit, section)

    def row(*r):
        rows.append(r)

    # ---- TX ----
    for side, fig_b, fig_o, sec in (("upper sideband", "sec1_fig8.pdf", "sec1_fig9.pdf", "2"),
                                    ("lower sideband", "sec2_fig8.pdf", "sec2_fig9.pdf", "3")):
        row("TX", "Conversion gain", f"{side}, filter optimal", *mmm(in_spec_gain(fig_o)), "dB", sec)
        row("TX", "Conversion gain", f"{side}, filter bypassed", *mmm(in_spec_gain(fig_b)), "dB", sec)
    flat_rows("Tx", (("Upper", "upper sideband"), ("Lower", "lower sideband")), "txflat")
    for side, prefix, sec in (("upper sideband", "sec4", "5"), ("lower sideband", "sec5", "6")):
        c = compression(prefix)
        row("TX", "Output P1dB", f"{side}, {len(c['out'])} test points", *mmm(c["out"]), "dBm", sec)
        row("TX", "Input P1dB", f"{side}, {len(c['in'])} test points", *mmm(c["in"]), "dBm", sec)
    sb = macros("sec_sideband_numbers.tex")                  # TX sideband: exact numbers from plot_datasheet_sideband.py
    for side in ("Upper", "Lower"):
        for filt, word in (("Optimal", "filter optimal"), ("Bypass", "filter bypassed")):
            t = f"sb{side}{filt}"
            row("TX", "Sideband suppression", f"{side.lower()} desired, {word}", sb[t + "Pten"] + "\\raisebox{0.55ex}{\\scriptsize a}",
                sb[t + "Median"], "", "dB", "4")
    nb = "\\raisebox{0.55ex}{\\scriptsize b}"                        # note b: the LO section's calibration scans
    cal = macros("sec6_cal_numbers.tex")
    row("TX", "LO leakage, other filter settings", "calibrated, hot (LMX " + cal["calHotMinC"] + "--" + cal["calHotMaxC"] + "\\,\\textdegree C)",
        "", cal["calHotMedian"] + nb, cal["calHotWorst"], "dBm", "7")
    row("TX", "LO leakage below " + cal["calThreshold"] + "\\,dBm", "calibrated, hot, all (LO, filter) readings", "",
        cal["calHotPct"], "", "\\%", "7")
    # hot only (user, 2026-10-09): the Key Specs quote the worst-case (hot) calibration
    tl = macros("sec_2lo_numbers.tex")                        # 10.1: all filter settings per LO (make_sec10_1_numbers.py)
    row("TX", "2×LO spur", f"LO {tl['twoLoLoMin']}--{tl['twoLoLoMax']}\\,GHz, all filter settings, no input\\raisebox{{0.55ex}}{{\\scriptsize c}}",
        "", tl["twoLoMedian"], tl["twoLoMax"], "dBm", "spur")

    # ---- RX ----
    for side, fig_b, fig_o, sec in (("low-side LO", "sec7_fig8.pdf", "sec7_fig9.pdf", "8"),
                                    ("high-side LO", "sec8_fig8.pdf", "sec8_fig9.pdf", "9")):
        row("RX", "Conversion gain", f"{side}, filter optimal", *mmm(in_spec_gain(fig_o)), "dB", sec)
        row("RX", "Conversion gain", f"{side}, filter bypassed", *mmm(in_spec_gain(fig_b)), "dB", sec)
    flat_rows("Rx", (("Low", "low-side LO"), ("High", "high-side LO")), "rxflat")
    for side, prefix, sec in (("low-side LO", "sec9", "10"), ("high-side LO", "sec10", "11")):
        c = compression(prefix)
        row("RX", "Input P1dB", f"{side}, {len(c['in'])} test points", *mmm(c["in"]), "dBm", sec)
        row("RX", "Output P1dB", f"{side}, {len(c['out'])} test points", *mmm(c["out"]), "dBm", sec)
        im = macros("sec_image_numbers.tex")                     # RX image rejection: exact numbers (plot_datasheet_image.py)
    for side, t in (("low-side LO", "imgLowOptimal"), ("high-side LO", "imgHighOptimal")):
        row("RX", "Image rejection", f"{side}, filter optimal", im[t + "Pten"] + "\\raisebox{0.55ex}{\\scriptsize a}",
            im[t + "Median"], "", "dB", "12")
    # NF: optimal filter only since 2026-10-09 (user); sec12_numbers.tex holds that campaign's numbers
    row("RX", "Noise figure (SSB)", "low-side LO, filter optimal", nf["nfLowMin"], nf["nfLowMedian"], nf["nfLowMax"], "dB", "13")
    row("RX", "Noise figure (SSB)", "high-side LO, filter optimal", nf["nfHighMin"], nf["nfHighMedian"], nf["nfHighMax"], "dB", "13")
    row("RX", "Noise floor at RF input", "median NF, filter optimal, 100\\,MHz bandwidth", "", nf["sensHundredM"].replace("-", MINUS), "", "dBm", "13")
    row("RX", "LO leakage at RF input", f"LO {sp['rxLeakLoMin']}--{sp['rxLeakLoTop']}\\,GHz, TX LO nulled\\raisebox{{0.55ex}}{{\\scriptsize d}}",
        "", sp["rxLeakLoMedian"], sp["rxLeakLoMax"], "dBm", "spurrx")
    row("RX", "2×LO leakage at RF input", f"LO {sp['rxLeakLoMin']}--{sp['rxLeakLoFineMax']}\\,GHz, TX LO nulled\\raisebox{{0.55ex}}{{\\scriptsize d}}",
        "", sp["rxLeakTwoLoMedian"], sp["rxLeakTwoLoMax"], "dBm", "spurrx")

    # ---- LO ----
    row("LO", "RMS phase error", f"100\\,Hz--1\\,MHz, internal LO, {pn['pnLoLow']}--{pn['pnLoHigh']}\\,GHz", pn["pnRmsLow"], "",
        pn["pnRmsHigh"], "degrees", "14")
    row("LO", "Phase noise", "100\\,kHz offset, internal LO at 10\\,GHz", "", pn100k_10, "", "dBc/Hz", "14")
    row("LO", "RMS phase error", "Pi-Radio OctoLO (external LO) at 10\\,GHz", "", pn["pnOctoRms"], "", "degrees", "14")

    labels = {"2": "tx-gain-upper", "3": "tx-gain-lower", "4": "sideband-suppression", "5": "compression-upper",
              "6": "compression-lower", "7": "lo-suppression", "8": "rx-gain-lowside", "9": "rx-gain-highside",
              "10": "rx-compression-lowside", "11": "rx-compression-highside", "12": "rx-image-rejection",
              "13": "rx-noise-figure", "14": "phase-noise",
              "txflat": "tx-flatness", "rxflat": "rx-flatness", "spur": "spur-tx-2lo", "spurrx": "spur-rx-lo"}       # the "Sec." column uses \ref, never a typed number
    rows = [(*r[:-1], f"\\ref{{sec:{labels[r[-1]]}}}") for r in rows]
    # One table per group (user, 2026-10-05), each split into small sub-headed blocks by parameter.
    sub = {"Conversion gain": "Conversion gain and flatness", "Gain flatness (RMS)": "Conversion gain and flatness",
           "Output P1dB": "Compression", "Input P1dB": "Compression", "Sideband suppression": "Sideband suppression",
           "Image rejection": "Image rejection", "Noise figure (SSB)": "Noise figure and sensitivity",
           "Noise floor at RF input": "Noise figure and sensitivity",
           "2×LO spur": "Spurious outputs", "LO leakage at RF input": "Spurious outputs",
           "2×LO leakage at RF input": "Spurious outputs"}
    titles = {"TX": ("tx", "Transmit (FR1 $\\rightarrow$ FR3)",
                     "Measured across all (FR1, FR3) combinations unless noted."),
              "RX": ("rx", "Receive (FR3 $\\rightarrow$ FR1)",
                     "Measured across all (FR1, FR3) combinations unless noted."),
              "LO": ("lo", "LO and phase noise", "")}
    for g, (stem, title, note) in titles.items():
        body, block = [], None
        for gg, *r in rows:
            if gg != g:
                continue
            b = sub.get(r[0], "LO leakage" if r[0].startswith("LO leakage") else None) if g != "LO" else None
            if b != block and b is not None:
                body.append("\\hline\n\\multicolumn{7}{|l|}{\\textit{" + b + "}} \\\\\n\\hline")
            block = b
            body.append(" & ".join(r) + " \\\\")
        head = "\\textbf{" + title + "}" + (". " + note if note else "")
        tex = ("% Generated by FR3_Characterization/make_summary_table.py -- do not edit by hand.\n"
               "\\begin{tabularx}{\\summarywidth}{|l|X|ccc|l|c|}\n\\hline\n"
               "\\textbf{Parameter} & \\textbf{Condition} & \\textbf{Min} & \\textbf{Typ} & \\textbf{Max} & "
               "\\textbf{Unit} & \\textbf{Sec.} \\\\\n" + ("" if g == "LO" else "") + "\n".join(body if g != "LO" else ["\\hline"] + body)
               + "\n\\hline\n\\end{tabularx}\n")
        out = SECTIONS / f"sec0_summary_{stem}.tex"
        out.write_text(tex, encoding="utf-8")
        print(out)


if __name__ == "__main__":
    main()

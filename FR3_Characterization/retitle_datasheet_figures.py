"""Make the text inside the datasheet's older figures consistent (user request, 2026-10-05): descriptive titles,
"Median: 12.3dB" statistics, true minus signs, descriptive Title-Case axis labels.

The original data behind these figures (Sections 2-6 and 8-12) no longer exists, so they cannot be re-plotted; instead
each matching text line in the vector PDF is removed (redaction of text only -- no graphics or images are touched) and
the new text is written at the same position, size and colour in IBM Plex Sans. Axis labels stay centred on their old
centre, everything else keeps its left edge; text that would run into other text or off the page is shrunk to fit.
Figures that are generated from data (Sections 7, 13, 14) are changed in their own scripts instead.

Every input is backed up once to FR3-1ch-Datasheet/images_backup_retitle/ and always read from there, so re-running
never stacks edits. The *_orig.pdf inputs of label_heatmap_from_colors.py get the same edits, so re-labelling keeps them.

    python retitle_datasheet_figures.py            (all figures)
    python retitle_datasheet_figures.py sec4_fig1  (some)
"""
from __future__ import annotations

import re
import shutil
import sys

import pymupdf

from plot_datasheet_nf import DATASHEET, IMAGES

BACKUP = DATASHEET / "images_backup_retitle"
FONTS = DATASHEET / "fonts"
MINUS = "−"

SIDE = {"sec1": "Upper Sideband", "sec2": "Lower Sideband", "sec4": "Upper Sideband", "sec5": "Lower Sideband",
        "sec7": "Low-Side LO", "sec8": "High-Side LO", "sec9": "Low-Side LO", "sec10": "High-Side LO"}
CHAIN = {"sec1": "TX", "sec2": "TX", "sec4": "TX", "sec5": "TX", "sec7": "RX", "sec8": "RX", "sec9": "RX", "sec10": "RX"}


def num(s: str) -> str:
    return s.replace("-", MINUS)


def stat(m) -> str:
    """median=13.7 dB (in spec) -> Median: 13.7dB (in spec)"""
    return f"{m.group(1).capitalize()}: {num(m.group(2))}dB{m.group(3) or ''}"


def rules(sec: str):
    """(regex, replacement, anchor) per figure family; anchor 'centre' keeps the line's centre (axis labels)."""
    side, chain = SIDE.get(sec, ""), CHAIN.get(sec, "")
    r = [
        # ---- statistics (histograms) ----
        (r"^(median|mean)=(-?[\d.]+) dB( \(in spec\))?$", stat, "left"),
        # ---- axis labels ----
        (r"^Count$", "Number of (FR1, FR3) Points", "centre"),
        (r"^Suppression \(dB\)$", "Sideband Suppression (dB)", "centre"),
        (r"^Image rejection \(dB\)$", "Image Rejection (dB)", "centre"),
        (r"^Conversion gain \(dB\)$", "Conversion Gain (dB)", "centre"),
        (r"^Conversion Gain \(dB\)$", "Average Conversion Gain (dB)", "centre"),
        (r"^Pin \(dBm\)$", "Input Power (dBm)", "centre"),
        (r"^Pout \(dBm\)$", "Output Power (dBm)", "centre"),
        # ---- true minus signs, wording ----
        (r"^LO = FR3 - FR1$", f"LO = FR3 {MINUS} FR1", "left"),
        (r"^(Input|Output) (P[13]dB): (-?[\d.]+) dBm$", lambda m: f"{m.group(1)} {m.group(2)}: {num(m.group(3))} dBm", "left"),
        (r"^small-signal gain: ([\d.]+) dB$", lambda m: f"Small-signal gain: {m.group(1)} dB", "left"),
        (r"^Input IF spans ([\d.]+)-([\d.]+) GHz here -- (\d+) MHz of this$",
         lambda m: f"Input IF spans {m.group(1)}{chr(0x2013)}{m.group(2)} GHz here: {m.group(3)} MHz of this", "left"),
        (r"^exceeds the board's nominal ([\d.]+)-([\d.]+) GHz IF spec\.$",
         lambda m: f"exceeds the unit's nominal {m.group(1)}{chr(0x2013)}{m.group(2)} GHz IF spec.", "left"),
        # ---- titles ----
        (r"^Input FR1 Center Freq: ([\d.]+) GHz$", lambda m: f"{chain} Conversion Gain, {side}: FR1 = {m.group(1)} GHz", "left"),
        (r"^Output FR1 Center Freq: ([\d.]+) GHz$", lambda m: f"{chain} Conversion Gain, {side}: FR1 = {m.group(1)} GHz", "left"),
        (r"^Full measured grid, Filter: (Bypassed|Optimal)$",
         lambda m: f"{chain} Conversion Gain, {side}: All (FR1, FR3) Points, Filter {m.group(1)}", "left"),
        (r"^FR1=([\d.]+) GHz, FR3=([\d.]+) GHz$", lambda m: f"{chain} Compression at FR1 = {m.group(1)} GHz, FR3 = {m.group(2)} GHz",
         "left"),
        (r"^Desired: (Upper|Lower)  \|  Filter: (Bypass|Optimal)$",
         lambda m: f"TX Sideband Suppression, {m.group(1)} Sideband Desired, Filter "
                   f"{'Bypassed' if m.group(2) == 'Bypass' else 'Optimal'}", "left"),
        (r"^LO: (Low|High)-side  \|  Filter: (Bypass|Optimal)$",
         lambda m: f"RX Image Rejection, {m.group(1)}-Side LO, Filter {'Bypassed' if m.group(2) == 'Bypass' else 'Optimal'}",
         "left"),
    ]
    return [(re.compile(p), rep, anc) for p, rep, anc in r]


def fontfile(span_font: str) -> str:
    return str(FONTS / ("IBMPlexSans-SemiBold.ttf" if "SmBld" in span_font or "Bold" in span_font else "IBMPlexSans-Regular.ttf"))


def process(name: str, src, dst) -> list[str]:
    sec = name.split("_")[0]
    rs = rules(sec)
    doc = pymupdf.open(src)
    page = doc[0]
    lines = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            text = "".join(s["text"] for s in ln["spans"]).strip()
            lines.append((text, ln))
    jobs = []
    for text, ln in lines:
        for rx, rep, anc in rs:
            m = rx.match(text)
            if m:
                new = rep(m) if callable(rep) else rep
                if new != text:
                    jobs.append((text, new, anc, ln))
                break
    if not jobs:
        doc.close()
        return []
    for _, _, _, ln in jobs:
        r = pymupdf.Rect(ln["bbox"])
        page.add_redact_annot(r + (0.2, 0.2, -0.2, -0.2))      # shrink a hair so neighbours are never clipped
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    others = [pymupdf.Rect(ln["bbox"]) for t, ln in lines]                 # every label, rewritten or not, is an obstacle
    log = []
    for old, new, anc, ln in jobs:
        span = max(ln["spans"], key=lambda s: s["size"])
        size, color = span["size"], pymupdf.sRGB_to_pdf(span["color"])
        ff = fontfile(span["font"])
        font = pymupdf.Font(fontfile=ff)
        vertical = abs(ln["dir"][1]) > 0.5
        box = pymupdf.Rect(ln["bbox"])
        width = font.text_length(new, fontsize=size)
        if not vertical:
            if anc == "centre":
                x0 = (box.x0 + box.x1) / 2 - width / 2
            else:
                x0 = box.x0
            # room to the right: page edge, or the nearest other text on the same row
            limit = page.rect.x1 - 4
            for o in others:
                if o != box and o.y1 > box.y0 + 1 and o.y0 < box.y1 - 1 and o.x0 >= box.x1 - 1:
                    limit = min(limit, o.x0 - 14)   # a clear gap before a neighbouring label
            if x0 + width > limit:
                size = size * (limit - x0) / width
                width = font.text_length(new, fontsize=size)
            y = span["origin"][1]
            page.insert_text((x0, y), new, fontsize=size, fontfile=ff, fontname="plex" + ("sb" if "SemiBold" in ff else "r"),
                             color=color)
        else:                                                    # rotated y-axis label, reading bottom to top
            yc = (box.y0 + box.y1) / 2
            x = span["origin"][0]
            page.insert_text((x, yc + width / 2), new, fontsize=size, fontfile=ff,
                             fontname="plex" + ("sb" if "SemiBold" in ff else "r"), color=color, rotate=90)
        log.append(f"{old!r} -> {new!r}" + (f" (shrunk to {size:.1f} pt)" if size < span["size"] - 0.05 else ""))
    doc.save(dst, garbage=3, deflate=True)
    doc.close()
    return log


def _piece(raw, span, chars) -> dict:
    """A text piece (some characters of one span) in the same shape as a get_text('dict') line with one span."""
    vis = [c for c in chars if c["c"].strip()] or chars
    bbox = (min(c["bbox"][0] for c in vis), min(c["bbox"][1] for c in vis),
            max(c["bbox"][2] for c in vis), max(c["bbox"][3] for c in vis))
    sp = {"text": "".join(c["c"] for c in chars), "font": span["font"], "size": span["size"], "color": span["color"],
          "origin": vis[0]["origin"], "bbox": bbox}
    return {"dir": raw["dir"], "spans": [sp], "bbox": bbox}


def center_title(path) -> str | None:
    """Centre a figure's title on the full figure width (user rule, 2026-10-05), in place. The title is the largest
    semibold text line in the top 15% of the figure. If other text shares its row (e.g. "LO = 8 GHz" at the right),
    the title is shrunk just enough to stay clear of it. Idempotent: a centred title is left as it is."""
    doc = pymupdf.open(path)
    page = doc[0]
    # split every extracted line at wide gaps: two labels on one row (title ... "LO = FR3 - FR1") are separate pieces
    # split at character level: a gap of more than ~2 spaces between visible characters starts a new piece, even
    # inside one extracted span (two same-font labels on one row get merged into one span by the extractor)
    lines = []
    for b in page.get_text("rawdict")["blocks"]:
        for raw in b.get("lines", []):
            horizontal = abs(raw["dir"][1]) < 0.5
            for s in raw["spans"]:
                piece, last_x1 = [], None
                for ch in s["chars"]:
                    if ch["c"].strip() and last_x1 is not None and horizontal and ch["bbox"][0] - last_x1 > 1.0 * s["size"]:
                        lines.append(_piece(raw, s, piece))
                        piece = []
                    piece.append(ch)
                    if ch["c"].strip():
                        last_x1 = ch["bbox"][2]
                if piece:
                    lines.append(_piece(raw, s, piece))
    cands = [ln for ln in lines if abs(ln["dir"][1]) < 0.5 and ln["bbox"][1] < 0.15 * page.rect.height
             and any("SmBld" in s["font"] or "SemiBold" in s["font"] or "Bold" in s["font"] for s in ln["spans"])
             and max(s["size"] for s in ln["spans"]) >= 9.5]
    if not cands:
        doc.close()
        return None
    top = max(max(s["size"] for s in l["spans"]) for l in cands)       # the title: largest; then the longest text
    ln = max((l for l in cands if max(s["size"] for s in l["spans"]) >= top - 1.0),
             key=lambda l: len("".join(s["text"] for s in l["spans"]).strip()))
    text = "".join(s["text"] for s in ln["spans"]).strip()
    span = max(ln["spans"], key=lambda s: s["size"])
    box = pymupdf.Rect(ln["bbox"])
    # user rule: centre ONLY a title that runs past the right edge of the figure's graphics (plot + colour bar)
    pw, ph = page.rect.width, page.rect.height
    right_edge = max([d["rect"].x1 for d in page.get_drawings()
                      if not (d["rect"].width > 0.9 * pw and d["rect"].height > 0.9 * ph)]     # not the background
                     + [i["bbox"][2] for i in page.get_image_info()])
    if box.x1 <= right_edge + 1.0:
        doc.close()
        return None
    cx = page.rect.width / 2
    if abs((box.x0 + box.x1) / 2 - cx) < 1.0:
        doc.close()
        return None
    ff = fontfile(span["font"])
    font = pymupdf.Font(fontfile=ff)
    size = span["size"]
    left, right = 4.0, page.rect.width - 4.0                    # clear of any other text on the title's row
    for o in lines:
        if o is ln:
            continue
        r = pymupdf.Rect(o["bbox"])
        if r.y1 > box.y0 + 1 and r.y0 < box.y1 - 1:
            if r.x0 >= box.x1 - 1:
                right = min(right, r.x0 - 6)
            elif r.x1 <= box.x0 + 1:
                left = max(left, r.x1 + 6)
    half = min(cx - left, right - cx)
    if half < 40:                                                # no sensible room to centre in: leave it alone
        doc.close()
        return f"NOT centred {text!r} (no room)"
    width = font.text_length(text, fontsize=size)
    if width > 2 * half:
        size *= 2 * half / width
        width = font.text_length(text, fontsize=size)
    page.add_redact_annot(box + (0.2, 0.2, -0.2, -0.2))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    page.insert_text((cx - width / 2, span["origin"][1]), text, fontsize=size, fontfile=ff, fontname="plexsb",
                     color=pymupdf.sRGB_to_pdf(span["color"]))
    doc.saveIncr() if False else doc.save(str(path) + ".tmp", garbage=3, deflate=True)
    doc.close()
    import os
    os.replace(str(path) + ".tmp", path)
    return f"centred {text!r}" + (f" (shrunk to {size:.1f} pt)" if size < span["size"] - 0.05 else "")


def main() -> None:
    BACKUP.mkdir(exist_ok=True)
    wanted = sys.argv[1:]
    for f in sorted(IMAGES.glob("sec*_fig*.pdf")):
        name = f.stem
        sec = name.split("_")[0]
        if sec in ("sec6", "sec12", "sec14", "sec0"):              # generated from data: edited in their own scripts
            continue
        if wanted and not any(name == w or name.startswith(w + "_") for w in wanted):
            continue
        bak = BACKUP / f.name
        if not bak.exists():
            shutil.copy2(f, bak)
        log = process(name, bak, f)
        if not log:
            shutil.copy2(bak, f)                                 # nothing to retitle: start from the backup anyway
        c = center_title(f)
        if c:
            log.append(c)
        if log:
            print(f"{name}: " + "; ".join(log))
    if not wanted:                                               # generated figures: centre their titles too
        for f in sorted(IMAGES.glob("sec*_fig*.pdf")):
            if f.stem.split("_")[0] in ("sec6", "sec12", "sec14"):
                c = center_title(f)
                if c:
                    print(f"{f.stem}: {c}")


if __name__ == "__main__":
    main()

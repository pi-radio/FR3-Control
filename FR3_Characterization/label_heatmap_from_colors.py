"""Add tiny per-cell value labels to an existing datasheet heatmap PDF, recovering each cell's value
from its fill colour (the original measurement data for the TX/RX gain sections no longer exists).

    python label_heatmap_from_colors.py sec1_fig8 [--fontsize 1.6]

How: the heatmap is vector -- every cell is a filled rectangle with an exact RGB colour -- and its colour
bar is an embedded image. Each colour-bar row is assigned its value from the colour bar's tick labels; each
cell colour is matched to the nearest colour-bar colour (an exact match is expected, since both come from
the same 256-entry colormap). Value quantization is (colour-bar range) / 256, ~0.13 dB for these figures.
FR1/FR3 come from the cell's position against the axis tick labels.

The labelled figure overwrites images/<name>.pdf; the untouched original is kept as
images/<name>_orig.pdf (and is always the input, so re-running never stacks labels). The recovered values
are written to FR3-1ch-Datasheet/data_recovered/<name>_values_from_colors.csv.
"""
from __future__ import annotations

import argparse
import collections
import csv
import shutil
import sys
from pathlib import Path

import numpy as np
import pymupdf

HERE = Path(__file__).resolve().parent
DATASHEET = HERE.parent / "FR3-1ch-Datasheet"
IMAGES = DATASHEET / "images"
FONT = DATASHEET / "fonts" / "IBMPlexSans-Regular.ttf"
EMPTY_RGB = (0.847, 0.839, 0.804)   # grey "not measured" cells


def num(s: str) -> float | None:
    try:
        return float(s)
    except ValueError:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("name")
    ap.add_argument("--fontsize", type=float, default=1.6)
    ap.add_argument("--oos-above", type=float, default=None,
                    help="draw a red 'out of spec' box over every FR3 row above this many GHz")
    ap.add_argument("--vrange", type=float, nargs=2, metavar=("LO", "HI"), default=None,
                    help="re-map the colour scale to LO..HI dB: repaint every cell and re-tick the colour bar")
    ap.add_argument("--tick-step", type=float, default=10.0, help="colour-bar tick spacing with --vrange")
    ap.add_argument("--oos-note-lines", nargs="+", default=None,
                    help="replace the red 'Partly out of spec' note with these lines (same font/size/colour)")
    args = ap.parse_args()
    target, orig = IMAGES / f"{args.name}.pdf", IMAGES / f"{args.name}_orig.pdf"
    if not orig.exists():
        shutil.copy(target, orig)
    doc = pymupdf.open(orig)
    page = doc[0]
    if args.oos_note_lines:
        # Remove only the red note's text (graphics and images untouched), then re-set it with the new wording
        # in the original font, size and colour, centred on the old block, keeping its line pitch.
        spans = [s for b in page.get_text("dict")["blocks"] if b["type"] == 0 for l in b["lines"]
                 for s in l["spans"] if s["color"] == 0xC0392B]
        assert spans, "no red note text found"
        block = pymupdf.Rect(spans[0]["bbox"])
        for s in spans[1:]:
            block |= pymupdf.Rect(s["bbox"])
        pitch = (spans[-1]["bbox"][1] - spans[0]["bbox"][1]) / max(len(spans) - 1, 1)
        size, red = spans[0]["size"], tuple(((0xC0392B >> k) & 255) / 255 for k in (16, 8, 0))
        for s in spans:
            page.add_redact_annot(pymupdf.Rect(s["bbox"]))
        page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE)
        sb_font = DATASHEET / "fonts" / "IBMPlexSans-SemiBold.ttf"
        sbf = pymupdf.Font(fontfile=str(sb_font))
        cx, cy = (block.x0 + block.x1) / 2, (block.y0 + block.y1) / 2
        n_lines = len(args.oos_note_lines)
        # keep the (possibly taller) new block inside the red box with a small margin
        box = next(it[1].rect if it[0] == "qu" else it[1] for d in page.get_drawings()
                   if d["type"] == "s" and d.get("color") and d["color"][0] > 0.7 and d["color"][1] < 0.3
                   for it in d["items"] if it[0] in ("re", "qu"))
        margin = 3.0
        top = cy - (n_lines - 1) / 2 * pitch - 0.65 * size
        bottom = cy + (n_lines - 1) / 2 * pitch + 0.45 * size
        if top < box.y0 + margin:
            cy += box.y0 + margin - top
        elif bottom > box.y1 - margin:
            cy -= bottom - (box.y1 - margin)
        for i, line in enumerate(args.oos_note_lines):
            baseline = cy + (i - (n_lines - 1) / 2) * pitch + 0.35 * size
            tw = sbf.text_length(line, fontsize=size)
            page.insert_text((cx - tw / 2, baseline), line, fontsize=size, fontname="plexsbn",
                             fontfile=str(sb_font), color=red)
    words = page.get_text("words")
    drawings = page.get_drawings()

    # colour bar: the one embedded image; its tick labels sit just to its right
    img = [b for b in page.get_text("dict")["blocks"] if b["type"] == 1][0]
    bx0, by0, bx1, by1 = img["bbox"]
    pix = pymupdf.Pixmap(doc, page.get_images(full=True)[0][0])
    if pix.n != 3:
        pix = pymupdf.Pixmap(pymupdf.csRGB, pix)
    arr = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3)
    bar_rgb = arr[:, pix.width // 2, :].astype(float) / 255.0          # one colour per row, top to bottom
    bar_y = by0 + (np.arange(pix.height) + 0.5) * (by1 - by0) / pix.height
    cb_ticks = [((w[1] + w[3]) / 2, num(w[4])) for w in words
                if w[0] > bx1 and num(w[4]) is not None and w[0] < bx1 + 25]
    slope, icpt = np.polyfit(*np.array(cb_ticks).T, 1)
    bar_val = slope * bar_y + icpt

    # axes: FR1 tick labels under the plot (x), FR3 tick labels left of it (y)
    page_area = page.rect.width * page.rect.height
    plot = max((d for d in drawings if d.get("fill") and d["rect"].height > 200 and d["rect"].width > 200
                and d["rect"].width * d["rect"].height < 0.9 * page_area),       # not the page background
               key=lambda d: d["rect"].width)["rect"]
    x_ticks = [((w[0] + w[2]) / 2, num(w[4])) for w in words if w[1] > plot.y1 and num(w[4]) is not None
               and w[1] < plot.y1 + 15]
    y_ticks = [((w[1] + w[3]) / 2, num(w[4])) for w in words if w[2] < plot.x0 and num(w[4]) is not None]
    xs, xi = np.polyfit(*np.array(x_ticks).T, 1)
    ys, yi = np.polyfit(*np.array(y_ticks).T, 1)

    # cells: the most common filled-rectangle size inside the plot (7.16 pt tall on the TX figures)
    in_plot = [d for d in drawings if d.get("fill") and plot.x0 - 1 <= d["rect"].x0 <= plot.x1
               and d["rect"].height > 1 and d["rect"].width < plot.width / 2]
    sizes = collections.Counter((round(d["rect"].width, 1), round(d["rect"].height, 1)) for d in in_plot)
    cw, ch = sizes.most_common(1)[0][0]
    cells = [d for d in in_plot if abs(d["rect"].width - cw) < 0.1 and abs(d["rect"].height - ch) < 0.1]
    font = pymupdf.Font(fontfile=str(FONT))
    rows, worst_match, painted = [], 0.0, []
    for d in cells:
        rgb = np.array(d["fill"])
        if np.max(np.abs(rgb - EMPTY_RGB)) < 0.01:
            continue
        dist = np.max(np.abs(bar_rgb - rgb), axis=1)
        k = int(np.argmin(dist))
        same = np.where(dist <= dist[k] + 1e-9)[0]                       # rows sharing that colour
        val = float(np.mean(bar_val[same]))
        worst_match = max(worst_match, float(dist[k]))
        r = d["rect"]
        fr1 = round((xs * (r.x0 + r.x1) / 2 + xi) * 2) / 2
        fr3 = round((ys * (r.y0 + r.y1) / 2 + yi) * 2) / 2
        rows.append({"fr1_ghz": fr1, "fr3_ghz": fr3, "value_db": round(val, 2), "colour_match_err": dist[k]})
        painted.append((r, rgb, fr1, fr3, val))

    if args.vrange is not None:
        # The colour-bar image already holds the whole colormap (top row = top of scale). Re-map: each cell gets
        # the colormap colour at its value's position in LO..HI, painted over the original cell; then the stroked
        # lines drawn after the cells (grid lines, the red box edge) are replayed on top, and the colour bar's
        # ticks/labels are covered and redrawn for the new range.
        lo, hi = args.vrange
        assert lo <= min(p[4] for p in painted) and max(p[4] for p in painted) <= hi, "values outside --vrange"
        n = len(bar_rgb)
        first_cell = min(drawings.index(d) for d in cells)
        for i, (r, _, fr1, fr3, val) in enumerate(painted):
            row = (1.0 - (val - lo) / (hi - lo)) * (n - 1)                 # fractional colour-bar row
            k0 = int(np.floor(row)); k1 = min(k0 + 1, n - 1)
            new = bar_rgb[k0] + (row - k0) * (bar_rgb[k1] - bar_rgb[k0])
            page.draw_rect(r, color=None, fill=tuple(new), overlay=True)
            painted[i] = (r, new, fr1, fr3, val)
        for d in drawings[first_cell:]:
            if d["type"] == "s" and plot.x0 - 1 <= d["rect"].x0 <= plot.x1 + 1 and d["rect"].y1 <= plot.y1 + 1:
                for it in d["items"]:
                    if it[0] == "l":
                        page.draw_line(it[1], it[2], color=d["color"], width=d["width"],
                                       stroke_opacity=d.get("stroke_opacity") or 1, overlay=True)
                    elif it[0] in ("re", "qu"):   # the red "Partly out of spec" box is stored as a quad
                        rect = it[1] if it[0] == "re" else it[1].rect
                        page.draw_rect(rect, color=d["color"], width=d["width"],
                                       stroke_opacity=d.get("stroke_opacity") or 1, overlay=True)
        ticks = [d for d in drawings if d["rect"].x0 >= bx1 - 0.5 and d["rect"].width < 5 and d.get("color")]
        labels = [s for b in page.get_text("dict")["blocks"] if b["type"] == 0 for l in b["lines"]
                  for s in l["spans"] if s["bbox"][0] > bx1 and num(s["text"].strip()) is not None]
        bg = (0.988, 0.988, 0.984)
        x_right = max(s["bbox"][2] for s in labels) + 1.0
        page.draw_rect(pymupdf.Rect(bx1 + 0.3, by0 - 8, x_right, by1 + 8), color=None, fill=bg, overlay=True)
        tick_col, tick_w = ticks[0]["color"], ticks[0]["width"]
        tick_len = ticks[0]["rect"].width
        lab = labels[0]
        lab_rgb = tuple(((lab["color"] >> s) & 255) / 255 for s in (16, 8, 0))
        lab_x, lab_size = lab["bbox"][0], lab["size"]
        for v in np.arange(lo, hi + 1e-9, args.tick_step):
            y = by1 - (v - lo) / (hi - lo) * (by1 - by0)
            page.draw_line((bx1, y), (bx1 + tick_len, y), color=tick_col, width=tick_w, overlay=True)
            page.insert_text((lab_x, y + 0.35 * lab_size), f"{v:g}", fontsize=lab_size, fontname="plex",
                             fontfile=str(FONT), color=lab_rgb)

    # Redraw the red "out of spec" box outline(s) on top, unclipped: in the original they are clipped to the plot
    # area (shaving the outer half off the top/right/bottom edges) and repainted cells can cover them.
    for d in drawings:
        col = d.get("color")
        if d["type"] == "s" and col and col[0] > 0.7 and col[1] < 0.3 and col[2] < 0.3:
            for it in d["items"]:
                if it[0] in ("re", "qu"):
                    page.draw_rect(it[1] if it[0] == "re" else it[1].rect, color=col, width=d["width"],
                                   overlay=True)

    for r, rgb, fr1, fr3, val in painted:
        text = f"{fr1:.1f}, {fr3:.1f}, {val:.1f}"
        tw = font.text_length(text, fontsize=args.fontsize)
        lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
        colour = (1, 1, 1) if lum < 0.55 else (0.09, 0.09, 0.09)
        page.insert_text(((r.x0 + r.x1 - tw) / 2, (r.y0 + r.y1) / 2 + 0.35 * args.fontsize), text,
                         fontsize=args.fontsize, fontname="plex", fontfile=str(FONT), color=colour)
    if args.oos_above is not None:
        # horizontal box over the FR3 rows above the rated maximum, from the cell edge just above that row to
        # the top of the plot; same red, tint and line weight as the existing "Partly out of spec" box
        red = (0.753, 0.224, 0.169)
        y_edge = (args.oos_above + 0.25 - yi) / ys
        box = pymupdf.Rect(plot.x0, plot.y0, plot.x1, y_edge)
        page.draw_rect(box, color=None, fill=red, fill_opacity=0.08, overlay=True)
        page.draw_rect(box, color=red, width=1.4, overlay=True)
        bold = DATASHEET / "fonts" / "IBMPlexSans-SemiBold.ttf"
        page.insert_text((box.x0 + 3, box.y0 + 7.5), f"FR3 > {args.oos_above:g} GHz: out of design spec",
                         fontsize=6.5, fontname="plexsb", fontfile=str(bold), color=red)
    doc.save(target, garbage=3, deflate=True)

    out = DATASHEET / "data_recovered"
    out.mkdir(exist_ok=True)
    with open(out / f"{args.name}_values_from_colors.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    step = abs(bar_val[0] - bar_val[-1]) / len({tuple(c) for c in np.round(bar_rgb, 4)})
    print(f"{len(rows)} cells labelled; colour bar {bar_val.min():.2f}-{bar_val.max():.2f} dB, "
          f"~{step:.3f} dB per colour level; worst colour match {worst_match:.4f} (0 = exact)")
    print(f"FR1 fit residual check: {sorted({r['fr1_ghz'] for r in rows})}")
    print(f"wrote {target.name} (original kept as {orig.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

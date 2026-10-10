"""Remove the dashed band-boundary lines from a datasheet heatmap's original PDF (images/<name>_orig.pdf),
by turning each dashed stroke into a no-paint path in the content stream -- nothing is painted over the
cells. The untouched file is kept once as images/<name>_orig_with_dashes.pdf. Re-run
label_heatmap_from_colors.py <name> afterwards to rebuild the labelled images/<name>.pdf.

    python remove_heatmap_dashed_lines.py sec1_fig9 sec2_fig9
"""
import re
import shutil
import sys
from pathlib import Path

import pymupdf

IMAGES = Path(__file__).resolve().parent.parent / "FR3-1ch-Datasheet" / "images"
# a dashed stroke: dash setting, colour/colour-space, one move-to + line-to, then S (stroke)
DASHED_STROKE = re.compile(rb"(\[ [\d.]+ [\d.]+ \] 0 d\n[^\n]*\n[\d.\- ]+ m\n[\d.\- ]+ l\n\n)S\n")

for name in sys.argv[1:]:
    orig = IMAGES / f"{name}_orig.pdf"
    keep = IMAGES / f"{name}_orig_with_dashes.pdf"
    if not keep.exists():
        shutil.copy(orig, keep)
    doc = pymupdf.open(keep)
    page = doc[0]
    total = 0
    for xref in page.get_contents():
        stream, n = DASHED_STROKE.subn(rb"\1n\n", doc.xref_stream(xref))
        if n:
            doc.update_stream(xref, stream)
            total += n
    left = [d for d in page.get_drawings() if d.get("dashes") not in (None, "[] 0")]
    doc.save(orig, garbage=3, deflate=True)
    print(f"{name}: removed {total} dashed line(s); dashed paths left: {len(left)}")

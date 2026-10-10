"""Keep the figure numbers drawn INSIDE datasheet figures correct after sections are inserted or moved.

    python renumber_figure_refs.py          (fix every figure; prints what changed)

The conversion-gain heatmaps (images/sec<k>_fig8/9.pdf) carry a "(Figure N.7)" label in their "Partly out of design
spec" box, pointing at that section's FR1 = 4 GHz figure (images/sec<k>_fig7.pdf). LaTeX renumbers its own \\ref's but
cannot reach text inside a PDF figure, so this script computes the right number from main.tex -- the section number is
the position of the .tex file (counting numbered \\section{...} only) that includes images/sec<k>_fig7.pdf -- and
rewrites the label in place (same position, size, colour; IBM Plex) in every copy that can feed the datasheet:
the figure, its *_orig / *_orig_with_dashes inputs (label_heatmap_from_colors.py, remove_heatmap_dashed_lines.py) and
the retitle backup (retitle_datasheet_figures.py), so no tool can bring an old number back.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pymupdf

from retitle_datasheet_figures import fontfile

DATASHEET = Path(__file__).resolve().parent.parent / "FR3-1ch-Datasheet"
FOLDERS = [DATASHEET / "images", DATASHEET / "images_backup_retitle"]
REF = re.compile(r"\(Figure (\d+)\.(\d+)\)")


def section_numbers() -> dict[str, int]:
    """{image prefix 'sec7': its section number} from the \\input order in main.tex."""
    main = (DATASHEET / "main.tex").read_text(encoding="utf-8")
    n, out = 0, {}
    for name in re.findall(r"^\\input\{(sections/[^}]+)\}", main, flags=re.M):
        tex = (DATASHEET / f"{name}.tex").read_text(encoding="utf-8")
        if not re.search(r"^\\section\{", tex, flags=re.M):        # \section* (Key Specifications) is unnumbered
            continue
        if "appendix" in name:
            break
        n += 1
        for prefix in set(re.findall(r"images/(sec\d+)_fig7\.pdf", tex)):
            out[prefix] = n
    return out


def fix(path: Path, number: int) -> str | None:
    doc = pymupdf.open(path)
    page = doc[0]
    jobs = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines", []):
            for sp in ln["spans"]:
                m = REF.search(sp["text"])
                if m and int(m.group(1)) != number:
                    jobs.append((sp, REF.sub(f"(Figure {number}.{m.group(2)})", sp["text"])))
    if not jobs:
        doc.close()
        return None
    for sp, _ in jobs:
        page.add_redact_annot(pymupdf.Rect(sp["bbox"]) + (0.2, 0.2, -0.2, -0.2))
    page.apply_redactions(images=pymupdf.PDF_REDACT_IMAGE_NONE, graphics=pymupdf.PDF_REDACT_LINE_ART_NONE,
                          text=pymupdf.PDF_REDACT_TEXT_REMOVE)
    for sp, new in jobs:
        ff = fontfile(sp["font"])
        font = pymupdf.Font(fontfile=ff)
        cx = (sp["bbox"][0] + sp["bbox"][2]) / 2                    # the label is centred in its box: keep its centre
        w = font.text_length(new, fontsize=sp["size"])
        page.insert_text((cx - w / 2, sp["origin"][1]), new, fontsize=sp["size"], fontfile=ff,
                         fontname="plexsb" if "SemiBold" in ff else "plexr", color=pymupdf.sRGB_to_pdf(sp["color"]))
    tmp = path.with_suffix(".pdf.tmp")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(path)
    return ", ".join(f"{sp['text']} -> {new}" for sp, new in jobs)


def main() -> int:
    nums = section_numbers()
    changed = 0
    for folder in FOLDERS:
        for f in sorted(folder.glob("sec*_fig*.pdf")):
            prefix = f.name.split("_")[0]
            if prefix not in nums:
                continue
            msg = fix(f, nums[prefix])
            if msg:
                changed += 1
                print(f"{folder.name}/{f.name}: {msg}")
    print(f"{changed} file(s) changed; section numbers: {dict(sorted(nums.items(), key=lambda kv: kv[1]))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

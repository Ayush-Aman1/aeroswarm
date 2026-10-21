#!/usr/bin/env python3
"""Convert docs/*.docx and docs/*.pdf to Markdown in docs/md/, then write docs/md/INDEX.txt
(every heading with file:line) so agents can read the guide section by section.
Uses pandoc / pdftotext when installed (best fidelity, keeps code blocks); falls back to
python-docx / pypdf."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "md"
OUT.mkdir(parents=True, exist_ok=True)


def docx_fallback(src: Path, dst: Path) -> None:
    try:
        import docx
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        sys.exit("Need pandoc (brew install pandoc) or python-docx (pip install python-docx)")
    d = docx.Document(str(src))
    lines = []
    for child in d.element.body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p = Paragraph(child, d)
            t = p.text.rstrip()
            style = (p.style.name or "").lower() if p.style is not None else ""
            if not t.strip():
                lines.append("")
            elif style.startswith("heading"):
                try:
                    lvl = int(style.split()[-1])
                except ValueError:
                    lvl = 2
                lines.append("#" * min(lvl, 6) + " " + t.strip())
            elif style == "title":
                lines.append("# " + t.strip())
            elif "list" in style:
                lines.append("- " + t.strip())
            elif "code" in style or "source" in style:
                lines.append("    " + t)
            else:
                lines.append(t)
        elif tag == "tbl":
            rows = [[c.text.strip().replace("\n", " ") for c in r.cells] for r in Table(child, d).rows]
            if rows:
                lines.append("| " + " | ".join(rows[0]) + " |")
                lines.append("|" + "---|" * len(rows[0]))
                lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
            lines.append("")
    dst.write_text("\n".join(lines), encoding="utf-8")


def pdf_fallback(src: Path, dst: Path) -> None:
    try:
        from pypdf import PdfReader
    except ImportError:
        sys.exit("Need pdftotext (brew install poppler) or pypdf (pip install pypdf)")
    r = PdfReader(str(src))
    dst.write_text("\n\n".join(f"<!-- page {i + 1} -->\n{p.extract_text() or ''}"
                               for i, p in enumerate(r.pages)), encoding="utf-8")


converted = 0
for src in sorted(DOCS.iterdir()):
    ext = src.suffix.lower()
    if ext not in {".docx", ".pdf"}:
        continue
    dst = OUT / (src.stem + ".md")
    if ext == ".docx" and shutil.which("pandoc"):
        subprocess.run(["pandoc", str(src), "-t", "gfm", "--wrap=none", "-o", str(dst)], check=True)
    elif ext == ".pdf" and shutil.which("pdftotext"):
        subprocess.run(["pdftotext", "-layout", str(src), str(dst)], check=True)
    elif ext == ".docx":
        docx_fallback(src, dst)
    else:
        pdf_fallback(src, dst)
    converted += 1
    print(f"converted docs/{src.name} -> docs/md/{dst.name}")

if converted == 0:
    sys.exit("No .docx or .pdf found in docs/. Put the build guide there first (see docs/README.md).")

index = []
for md in sorted(OUT.glob("*.md")):
    for i, line in enumerate(md.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
        if line.startswith("#") or line.lstrip().startswith("### P") or line.lstrip().startswith("Task P"):
            index.append(f"{md.name}:{i}: {line.strip()[:140]}")
(OUT / "INDEX.txt").write_text("\n".join(index) + "\n", encoding="utf-8")
print(f"wrote docs/md/INDEX.txt ({len(index)} entries)")

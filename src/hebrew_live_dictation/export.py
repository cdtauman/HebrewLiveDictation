"""Export transcripts to TXT and RTL-correct DOCX (python-docx).

DOCX paragraphs are marked right-to-left (w:bidi on the paragraph, w:rtl on runs)
so Hebrew renders correctly in Word without manual fixing.
"""

import logging
import time


logger = logging.getLogger("Export")


def entries_to_text(entries):
    lines = []
    for entry in entries:
        ts = entry.get("ts")
        stamp = time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else ""
        target = entry.get("target", "")
        header = " ".join(x for x in [stamp, f"[{target}]" if target else ""] if x)
        if header:
            lines.append(header)
        lines.append(entry.get("text", ""))
        lines.append("")
    return "\n".join(lines).strip()


def write_txt(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")
    return path


def write_docx(path, text, rtl=True):
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml.ns import qn

    document = Document()
    for line in (text or "").split("\n"):
        paragraph = document.add_paragraph(line)
        if rtl:
            paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
            p_pr = paragraph._p.get_or_add_pPr()
            p_pr.append(p_pr.makeelement(qn("w:bidi"), {}))
            for run in paragraph.runs:
                r_pr = run._r.get_or_add_rPr()
                r_pr.append(r_pr.makeelement(qn("w:rtl"), {}))
    document.save(path)
    return path

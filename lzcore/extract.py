"""Deterministic text extraction from an uploaded SOW (pdf, docx, txt, md). Runs in a Lambda, not in the agent."""
import io

MAX_CHARS = 400_000  # ~100k tokens; larger SOWs fail loudly instead of being silently truncated


def extract_pdf(body):
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(body))
    if reader.is_encrypted:
        raise ValueError("PDF is password protected")
    parts = [f"[page {i}]\n{(p.extract_text() or '').strip()}" for i, p in enumerate(reader.pages, 1)]
    text = "\n\n".join(parts)
    if len("".join(p.split("\n", 1)[1] if "\n" in p else "" for p in parts).strip()) < 50:
        raise ValueError("PDF has no extractable text (scanned images?). OCR is not supported; upload a text PDF or DOCX")
    return text


def extract_docx(body):
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    doc = Document(io.BytesIO(body))
    out = []
    for child in doc.element.body.iterchildren():
        if child.tag.endswith("}p"):
            t = Paragraph(child, doc).text.strip()
            if t:
                out.append(t)
        elif child.tag.endswith("}tbl"):
            for row in Table(child, doc).rows:
                cells = []
                for c in row.cells:
                    if not cells or c.text.strip() != cells[-1]:  # merged cells repeat
                        cells.append(c.text.strip())
                out.append(" | ".join(cells))
    return "\n".join(out)


def extract(body, ext):
    ext = ext.lower()
    if ext == "pdf":
        return extract_pdf(body)
    if ext == "docx":
        return extract_docx(body)
    if ext in ("txt", "md"):
        return body.decode("utf-8", errors="replace")
    raise ValueError(f"unsupported file type: {ext}")

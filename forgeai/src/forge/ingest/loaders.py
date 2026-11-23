"""Loaders: turn any supported file into structured blocks (paragraphs + tables).

A malformed file never kills the run: callers catch and quarantine, the run
continues, the report confesses.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TableBlock:
    columns: list[str]
    rows: list[list[str]]
    caption: str | None = None
    page: int | None = None

    def to_markdown(self) -> str:
        header = "| " + " | ".join(self.columns) + " |"
        sep = "|" + "|".join(["---"] * len(self.columns)) + "|"
        lines = [header, sep]
        for row in self.rows:
            lines.append("| " + " | ".join(str(c) for c in row) + " |")
        cap = f"[table: {self.caption}]" if self.caption else "[table]"
        return cap + "\n" + "\n".join(lines)


@dataclass
class ParagraphBlock:
    text: str
    page: int | None = None


@dataclass
class LoadedDoc:
    kind: str
    paragraphs: list[ParagraphBlock] = field(default_factory=list)
    tables: list[TableBlock] = field(default_factory=list)
    dataframe: object | None = None  # pandas DataFrame for csv/xlsx


SUPPORTED = {".pdf", ".csv", ".xlsx", ".docx", ".md", ".txt"}


def load(path: Path) -> LoadedDoc:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return _load_pdf(path)
    if ext == ".csv":
        return _load_csv(path)
    if ext == ".xlsx":
        return _load_xlsx(path)
    if ext == ".docx":
        return _load_docx(path)
    if ext in (".md", ".txt"):
        return _load_text(path)
    raise ValueError(f"unsupported extension: {ext}")


def _load_pdf(path: Path) -> LoadedDoc:
    from pypdf import PdfReader
    reader = PdfReader(str(path))
    doc = LoadedDoc(kind="pdf")
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        if text:
            doc.paragraphs.append(ParagraphBlock(text=text, page=i + 1))
    return doc


def _load_csv(path: Path) -> LoadedDoc:
    import pandas as pd
    df = pd.read_csv(path, dtype=str).fillna("")
    return LoadedDoc(kind="csv", dataframe=df)


def _load_xlsx(path: Path) -> LoadedDoc:
    import pandas as pd
    df = pd.read_excel(path, dtype=str).fillna("")
    return LoadedDoc(kind="xlsx", dataframe=df)


def _load_docx(path: Path) -> LoadedDoc:
    import docx
    d = docx.Document(str(path))
    doc = LoadedDoc(kind="docx")
    # interleave paragraphs and tables in document order
    body = d.element.body
    tbl_idx, para_idx = 0, 0
    from docx.table import Table
    from docx.text.paragraph import Paragraph
    for child in body.iterchildren():
        tag = child.tag.split("}")[-1]
        if tag == "p":
            paras = d.paragraphs
            if para_idx < len(paras):
                text = paras[para_idx].text.strip()
                if text:
                    doc.paragraphs.append(ParagraphBlock(text=text))
                para_idx += 1
        elif tag == "tbl":
            tables = d.tables
            if tbl_idx < len(tables):
                t = tables[tbl_idx]
                columns = [c.text.strip() for c in t.rows[0].cells]
                rows = [[c.text.strip() for c in r.cells] for r in t.rows[1:]]
                doc.tables.append(TableBlock(columns=columns, rows=rows))
                tbl_idx += 1
    return doc


def _load_text(path: Path) -> LoadedDoc:
    text = path.read_text(encoding="utf-8", errors="replace")
    doc = LoadedDoc(kind="md" if path.suffix.lower() == ".md" else "txt")
    for para in text.split("\n\n"):
        para = para.strip()
        if para:
            doc.paragraphs.append(ParagraphBlock(text=para))
    return doc

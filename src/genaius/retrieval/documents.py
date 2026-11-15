"""Kaynak izli PDF ve DOCX belge çıkarımı, bölüm temelli parçalama ve manifest üretimi."""

from __future__ import annotations

import hashlib
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pypdf


class RetrievalDocumentError(ValueError):
    """Belge okuma, PDF/DOCX doğrulama veya parçalama hatası."""


@dataclass(frozen=True)
class DocumentSpec:
    """Kanonik belge kaynağı sözleşmesi."""

    document_id: str
    investigation_id: str
    title: str
    report_number: str
    official_citation_url: str
    official_download_url: str | None
    relative_path: str
    source_format: str
    printed_page_regex: str | None = None
    extraction_method: str = ""


DOCUMENT_SPECS: tuple[DocumentSpec, ...] = (
    DocumentSpec(
        document_id="FLEX_TP_2015",
        investigation_id="PSI-69",
        title="Detailed Results From the Flame Extinguishment Experiment (FLEX) March 2009 to December 2011",
        report_number="NASA/TP-2015-216046",
        official_citation_url="https://ntrs.nasa.gov/citations/20150023456",
        official_download_url="https://ntrs.nasa.gov/api/citations/20150023456/downloads/20150023456.pdf",
        relative_path="data/raw/nasa_docs/20150023456_flex.pdf",
        source_format="pdf",
        printed_page_regex=r"NASA/TP[—\-–]+2015-216046\s+([ivxlcdm]+|\d+)\b",
        extraction_method="pypdf PDF metin katmanı + bookmark/bölüm sınırı + sayfa başlığı basılı sayfa doğrulama",
    ),
    DocumentSpec(
        document_id="BASS_II_TM_2021",
        investigation_id="PSI-25",
        title="Burning and Suppression of Solids–II (BASS-II) Summary Report",
        report_number="NASA/TM-20210011385",
        official_citation_url="https://ntrs.nasa.gov/citations/20210011385",
        official_download_url="https://ntrs.nasa.gov/api/citations/20210011385/downloads/TM-20210011385.pdf",
        relative_path="data/raw/nasa_docs/20210011385_bass_ii.pdf",
        source_format="pdf",
        printed_page_regex=r"NASA/TM[—\-–]+20210011385\s+([ivxlcdm]+|\d+)\b",
        extraction_method="pypdf PDF metin katmanı + bookmark/bölüm sınırı + sayfa başlığı basılı sayfa doğrulama",
    ),
    DocumentSpec(
        document_id="BASS_II_README",
        investigation_id="PSI-25",
        title="PSI-25 BASS-II Science Documents ReadMe",
        report_number="PSI-25_BASS-II_ReadMe",
        official_citation_url="https://doi.org/10.60555/4qc4-de67",
        official_download_url=None,
        relative_path="data/raw/psi/matrices_and_readmes/PSI-25/PSI-25_Science Documents_BASS-II_ReadMe.docx",
        source_format="docx",
        printed_page_regex=None,
        extraction_method="Python stdlib zipfile + XML word/document.xml paragraf/bölüm ayrıştırma",
    ),
)

_MAX_CHUNK_CHARS = 1800
_MIN_CHUNK_CHARS = 240
_TABLE_LINE_RE = re.compile(r"^\s*(?:TABLE|Table)\s+[IVXLC0-9A-Z]+[\.—\-]")
_SECTION_NUM_RE = re.compile(
    r"^(Appendix\s+[A-Z]|Section\s+\d+(?:\.\d+)*|\d+(?:\.\d+)+|\d+\.0|[A-Z]\.\d+)\b[\.—:\s\-]*(.*)$"
)


@dataclass(frozen=True)
class DocumentManifestEntry:
    """Bir kaynağın kimlik, erişim durumu, hash ve sayfa/parça özeti."""

    document_id: str
    investigation_id: str
    title: str
    report_number: str
    official_citation_url: str
    official_download_url: str | None
    relative_path: str
    source_format: str
    access_status: str
    extraction_method: str
    sha256: str | None
    file_bytes: int | None
    total_pdf_pages: int | None
    verified_printed_page_count: int | None
    empty_pdf_pages: tuple[int, ...]
    chunk_count: int
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu sözlük gösterimi döndürür."""
        return {
            "document_id": self.document_id,
            "investigation_id": self.investigation_id,
            "title": self.title,
            "report_number": self.report_number,
            "official_citation_url": self.official_citation_url,
            "official_download_url": self.official_download_url,
            "relative_path": self.relative_path,
            "source_format": self.source_format,
            "access_status": self.access_status,
            "extraction_method": self.extraction_method,
            "sha256": self.sha256,
            "file_bytes": self.file_bytes,
            "total_pdf_pages": self.total_pdf_pages,
            "verified_printed_page_count": self.verified_printed_page_count,
            "empty_pdf_pages": list(self.empty_pdf_pages),
            "chunk_count": self.chunk_count,
            "error_message": self.error_message,
        }


@dataclass(frozen=True)
class DocumentChunk:
    """Ham metni değiştirilmeden korunan, kaynak konumu tam izlenebilir belge parçası."""

    chunk_id: str
    chunk_ordinal: int
    document_id: str
    investigation_id: str
    section_number: str | None
    section_title: str
    section_path: tuple[str, ...]
    source_text: str
    pdf_page_start: int | None
    pdf_page_end: int | None
    printed_page_start: str | None
    printed_page_end: str | None
    printed_pages: tuple[str, ...]
    paragraph_index_start: int | None
    paragraph_index_end: int | None
    source_url: str
    source_relpath: str
    source_sha256: str
    extraction_warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu sözlük gösterimi döndürür."""
        return {
            "chunk_id": self.chunk_id,
            "chunk_ordinal": self.chunk_ordinal,
            "document_id": self.document_id,
            "investigation_id": self.investigation_id,
            "section_number": self.section_number,
            "section_title": self.section_title,
            "section_path": list(self.section_path),
            "source_text": self.source_text,
            "pdf_page_start": self.pdf_page_start,
            "pdf_page_end": self.pdf_page_end,
            "printed_page_start": self.printed_page_start,
            "printed_page_end": self.printed_page_end,
            "printed_pages": list(self.printed_pages),
            "paragraph_index_start": self.paragraph_index_start,
            "paragraph_index_end": self.paragraph_index_end,
            "source_url": self.source_url,
            "source_relpath": self.source_relpath,
            "source_sha256": self.source_sha256,
            "extraction_warnings": list(self.extraction_warnings),
        }


@dataclass(frozen=True)
class _OutlineNode:
    depth: int
    raw_title: str
    section_number: str | None
    section_title: str
    start_pdf_page: int


@dataclass(frozen=True)
class _PageSegment:
    pdf_page: int
    printed_page: str | None
    section_number: str | None
    section_title: str
    section_path: tuple[str, ...]
    text: str


@dataclass(frozen=True)
class _DocxParagraph:
    index: int
    style: str | None
    text: str


def _compute_sha256(path: Path) -> tuple[str, int]:
    h = hashlib.sha256()
    size = 0
    with path.open("rb") as f:
        while block := f.read(65536):
            h.update(block)
            size += len(block)
    return h.hexdigest(), size


def _make_stable_chunk_id(
    document_id: str,
    ordinal: int,
    location_key: str,
    source_text: str,
) -> str:
    digest = hashlib.sha256(f"{document_id}|{location_key}|{source_text}".encode("utf-8")).hexdigest()[:10]
    return f"{document_id}:{ordinal:04d}:{digest}"


def _parse_section_label(raw_title: str) -> tuple[str | None, str]:
    cleaned = " ".join(raw_title.split()).strip()
    match = _SECTION_NUM_RE.match(cleaned)
    if match:
        sec_num = match.group(1).strip()
        sec_title = match.group(2).strip(" .—:-") or cleaned
        return sec_num, sec_title
    return None, cleaned


def _normalize_heading_match_text(text: str) -> str:
    folded = text.replace("—", " ").replace("–", " ").replace("-", " ").replace("’", "'")
    return " ".join(folded.lower().split())


def _walk_pdf_outline(reader: pypdf.PdfReader) -> list[_OutlineNode]:
    outline_nodes: list[_OutlineNode] = []

    def _visit(items: Sequence[Any], depth: int) -> None:
        for item in items:
            if isinstance(item, list):
                _visit(item, depth + 1)
                continue
            title = " ".join(str(getattr(item, "title", "")).split()).strip()
            if not title:
                continue
            try:
                page_idx = reader.get_destination_page_number(item)
            except Exception:
                continue
            if page_idx is None or page_idx < 0:
                continue
            sec_num, sec_title = _parse_section_label(title)
            outline_nodes.append(
                _OutlineNode(
                    depth=depth,
                    raw_title=title,
                    section_number=sec_num,
                    section_title=sec_title,
                    start_pdf_page=page_idx + 1,
                )
            )

    if reader.outline:
        _visit(reader.outline, 0)

    # Kök belge kapsayıcı yer imini (depth=0, sayfa=1) atla ki alt bölümler kendi başlığını korusun
    if outline_nodes and outline_nodes[0].depth == 0 and outline_nodes[0].start_pdf_page == 1 and len(outline_nodes) > 1:
        outline_nodes = outline_nodes[1:]
    return outline_nodes


def _detect_verified_printed_page(page_text: str, regex: re.Pattern[str] | None) -> str | None:
    if regex is None or not page_text.strip():
        return None
    # Sadece üst bilgi satırlarından doğrula (ilk 4 dolu satır)
    top_lines = "\n".join([ln.strip() for ln in page_text.splitlines() if ln.strip()][:4])
    m = regex.search(top_lines)
    if m:
        return m.group(1)
    # Tablo sayfalarında bazen son satırda yer alma ihtimaline karşı yalnızca rapor kodu eşleşmesiyle kontrol
    tail_lines = "\n".join([ln.strip() for ln in page_text.splitlines() if ln.strip()][-3:])
    m_tail = regex.search(tail_lines)
    return m_tail.group(1) if m_tail else None


def _find_heading_line_index(lines: list[str], node: _OutlineNode, start_idx: int) -> int | None:
    target = _normalize_heading_match_text(node.raw_title)
    num_norm = _normalize_heading_match_text(node.section_number) if node.section_number else ""
    title_words = _normalize_heading_match_text(node.section_title).split()[:4]

    for idx in range(start_idx, len(lines)):
        line_norm = _normalize_heading_match_text(lines[idx])
        if not line_norm:
            continue
        if target in line_norm:
            return idx
        if num_norm and line_norm.startswith(num_norm):
            if not title_words or any(w in line_norm for w in title_words[:2]):
                return idx
    return None


def _build_section_path(stack: list[tuple[int, str]], node: _OutlineNode) -> tuple[str, ...]:
    while stack and stack[-1][0] >= node.depth:
        stack.pop()
    stack.append((node.depth, node.raw_title))
    return tuple(label for _, label in stack)


def _detect_chunk_warnings(
    *,
    source_text: str,
    section_title: str,
    section_number: str | None,
    pdf_page_start: int | None,
    pdf_page_end: int | None,
    printed_pages: tuple[str, ...],
    is_docx: bool,
) -> tuple[str, ...]:
    warnings: list[str] = []
    if is_docx:
        warnings.append("docx_source_no_pdf_page: DOCX kaynağıdır; yalnızca paragraf ve bölüm konumu vardır.")
    else:
        if not printed_pages:
            warnings.append("printed_page_unverified: PDF sayfa başlığında basılı sayfa numarası doğrulanamadı.")
        elif pdf_page_start is not None and pdf_page_end is not None:
            expected_span = pdf_page_end - pdf_page_start + 1
            if len(printed_pages) < expected_span:
                warnings.append(
                    "partial_printed_page_verification: Çok sayfalı parçadaki bazı PDF sayfalarında basılı sayfa numarası doğrulanamadı."
                )

    combined_title = f"{section_number or ''} {section_title}".lower()
    is_table_section = (
        any(tok in combined_title for tok in ("test matrix", "experiment results", "test matrices"))
        or bool(_TABLE_LINE_RE.search(source_text))
    )
    if not is_docx and is_table_section:
        warnings.append(
            "pdf_table_text_not_for_calculation: PDF tablosundan metin olarak çıkarılmıştır; sayısal hesap/filtre için CSV veri çekirdeğini kullanın."
        )
    return tuple(warnings)


def _split_text_preserving_lines(text: str, max_chars: int = _MAX_CHUNK_CHARS) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    if len(stripped) <= max_chars:
        return [stripped]

    lines = stripped.splitlines()
    parts: list[str] = []
    current_lines: list[str] = []
    current_len = 0

    for line in lines:
        add_len = len(line) + (1 if current_lines else 0)
        if current_lines and current_len + add_len > max_chars:
            part = "\n".join(current_lines).strip()
            if part:
                parts.append(part)
            current_lines = [line]
            current_len = len(line)
        else:
            current_lines.append(line)
            current_len += add_len

    if current_lines:
        tail = "\n".join(current_lines).strip()
        if tail:
            if parts and len(tail) < _MIN_CHUNK_CHARS and len(parts[-1]) + 1 + len(tail) <= int(max_chars * 1.25):
                parts[-1] = f"{parts[-1]}\n{tail}".strip()
            else:
                parts.append(tail)
    return parts


def _extract_pdf_chunks(spec: DocumentSpec, file_path: Path, sha256: str) -> tuple[list[DocumentChunk], dict[str, Any]]:
    raw_head = file_path.read_bytes()[:8]
    if not raw_head.startswith(b"%PDF-"):
        raise RetrievalDocumentError(f"{spec.relative_path} geçerli bir %PDF- imzası taşımıyor.")

    try:
        reader = pypdf.PdfReader(str(file_path))
    except Exception as exc:
        raise RetrievalDocumentError(f"{spec.relative_path} pypdf ile açılamadı: {exc}") from exc

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise RetrievalDocumentError(f"{spec.relative_path} hiç sayfa içermiyor.")

    printed_rx = re.compile(spec.printed_page_regex, re.IGNORECASE) if spec.printed_page_regex else None
    outline_nodes = _walk_pdf_outline(reader)

    nodes_by_page: dict[int, list[_OutlineNode]] = {}
    for node in outline_nodes:
        nodes_by_page.setdefault(node.start_pdf_page, []).append(node)

    empty_pages: list[int] = []
    verified_printed_count = 0
    page_segments: list[_PageSegment] = []

    stack: list[tuple[int, str]] = []
    active_node = _OutlineNode(
        depth=1,
        raw_title="Front Matter",
        section_number=None,
        section_title="Front Matter",
        start_pdf_page=1,
    )
    active_path: tuple[str, ...] = ("Front Matter",)

    for page_idx, page in enumerate(reader.pages, 1):
        raw_page_text = page.extract_text() or ""
        printed_page = _detect_verified_printed_page(raw_page_text, printed_rx)
        if printed_page is not None:
            verified_printed_count += 1

        if not raw_page_text.strip():
            empty_pages.append(page_idx)
            # Bölüm ağacı takibini bozmamak için sadece başlangıç yer imlerini güncelle
            for node in nodes_by_page.get(page_idx, ()):
                active_node = node
                active_path = _build_section_path(stack, node)
            continue

        lines = raw_page_text.splitlines()
        starts_here = nodes_by_page.get(page_idx, [])
        if not starts_here:
            page_segments.append(
                _PageSegment(
                    pdf_page=page_idx,
                    printed_page=printed_page,
                    section_number=active_node.section_number,
                    section_title=active_node.section_title,
                    section_path=active_path,
                    text=raw_page_text.strip(),
                )
            )
            continue

        matched_splits: list[tuple[int, _OutlineNode, tuple[str, ...]]] = []
        cursor = 0
        for node in starts_here:
            new_path = _build_section_path(stack, node)
            found_idx = _find_heading_line_index(lines, node, cursor)
            if found_idx is not None:
                matched_splits.append((found_idx, node, new_path))
                cursor = found_idx + 1

        if not matched_splits:
            # Sayfada başlık var ama metinde birebir satır bulunamadıysa son alt başlığı veya ilk başlığı bağla
            for node in starts_here[:-1]:
                _build_section_path(stack, node)
            last_node = starts_here[-1]
            last_path = _build_section_path(stack, last_node)
            page_segments.append(
                _PageSegment(
                    pdf_page=page_idx,
                    printed_page=printed_page,
                    section_number=last_node.section_number,
                    section_title=last_node.section_title,
                    section_path=last_path,
                    text=raw_page_text.strip(),
                )
            )
            active_node = last_node
            active_path = last_path
            continue

        # Eşleşen ilk başlık öncesi satırlar önceki aktif bölüme aittir (yalnızca sayfa üst bilgisi değilse)
        first_split_idx = matched_splits[0][0]
        if first_split_idx > 0:
            prefix_lines = [ln for ln in lines[:first_split_idx] if ln.strip()]
            non_header_prefix = [
                ln for ln in prefix_lines if not (printed_rx is not None and printed_rx.fullmatch(ln.strip()))
            ]
            prefix_text = "\n".join(lines[:first_split_idx]).strip()
            if prefix_text and non_header_prefix:
                page_segments.append(
                    _PageSegment(
                        pdf_page=page_idx,
                        printed_page=printed_page,
                        section_number=active_node.section_number,
                        section_title=active_node.section_title,
                        section_path=active_path,
                        text=prefix_text,
                    )
                )

        for pos, (split_idx, node, path_tuple) in enumerate(matched_splits):
            next_idx = matched_splits[pos + 1][0] if pos + 1 < len(matched_splits) else len(lines)
            seg_text = "\n".join(lines[split_idx:next_idx]).strip()
            if seg_text:
                page_segments.append(
                    _PageSegment(
                        pdf_page=page_idx,
                        printed_page=printed_page,
                        section_number=node.section_number,
                        section_title=node.section_title,
                        section_path=path_tuple,
                        text=seg_text,
                    )
                )
            active_node = node
            active_path = path_tuple

        # Sayfadaki son eşleşmeden sonra alt başlıklar varsa son aktif düğümü ilerlet
        last_node = starts_here[-1]
        if last_node is not active_node:
            active_node = last_node
            active_path = tuple(p for _, p in stack)

    # Ardışık aynı bölüm segmentlerini grupla ve kontrollü boyutta parçalara ayır
    grouped: list[list[_PageSegment]] = []
    for seg in page_segments:
        if (
            grouped
            and grouped[-1][0].section_path == seg.section_path
            and grouped[-1][0].section_title == seg.section_title
        ):
            grouped[-1].append(seg)
        else:
            grouped.append([seg])

    chunks: list[DocumentChunk] = []
    ordinal = 1
    for group in grouped:
        sec_num = group[0].section_number
        sec_title = group[0].section_title
        sec_path = group[0].section_path

        # Sayfa bazlı biriktirerek kontrollü parçalar oluştur (sayfa izi kaybolmasın)
        buf_segments: list[_PageSegment] = []
        buf_chars = 0

        def _flush_segments(segs: list[_PageSegment]) -> None:
            nonlocal ordinal
            if not segs:
                return
            combined_text = "\n".join(s.text for s in segs).strip()
            if not combined_text:
                return
            p_start = segs[0].pdf_page
            p_end = segs[-1].pdf_page
            printed_list = tuple(dict.fromkeys(s.printed_page for s in segs if s.printed_page is not None))
            pr_start = segs[0].printed_page
            pr_end = segs[-1].printed_page
            sub_parts = _split_text_preserving_lines(combined_text, max_chars=_MAX_CHUNK_CHARS)
            for sub_idx, part_text in enumerate(sub_parts):
                warnings = _detect_chunk_warnings(
                    source_text=part_text,
                    section_title=sec_title,
                    section_number=sec_num,
                    pdf_page_start=p_start,
                    pdf_page_end=p_end,
                    printed_pages=printed_list,
                    is_docx=False,
                )
                loc_key = f"pdf:{p_start}-{p_end}:part{sub_idx}"
                chunks.append(
                    DocumentChunk(
                        chunk_id=_make_stable_chunk_id(spec.document_id, ordinal, loc_key, part_text),
                        chunk_ordinal=ordinal,
                        document_id=spec.document_id,
                        investigation_id=spec.investigation_id,
                        section_number=sec_num,
                        section_title=sec_title,
                        section_path=sec_path,
                        source_text=part_text,
                        pdf_page_start=p_start,
                        pdf_page_end=p_end,
                        printed_page_start=pr_start,
                        printed_page_end=pr_end,
                        printed_pages=printed_list,
                        paragraph_index_start=None,
                        paragraph_index_end=None,
                        source_url=spec.official_citation_url,
                        source_relpath=spec.relative_path,
                        source_sha256=sha256,
                        extraction_warnings=warnings,
                    )
                )
                ordinal += 1

        for seg in group:
            seg_len = len(seg.text)
            if buf_segments and (buf_chars + 1 + seg_len > _MAX_CHUNK_CHARS):
                _flush_segments(buf_segments)
                buf_segments = [seg]
                buf_chars = seg_len
            else:
                buf_segments.append(seg)
                buf_chars += (1 if buf_segments[:-1] else 0) + seg_len
        _flush_segments(buf_segments)

    return chunks, {
        "total_pdf_pages": total_pages,
        "verified_printed_page_count": verified_printed_count,
        "empty_pdf_pages": tuple(empty_pages),
    }


def _extract_docx_chunks(spec: DocumentSpec, file_path: Path, sha256: str) -> list[DocumentChunk]:
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    try:
        with zipfile.ZipFile(file_path) as zf:
            xml_bytes = zf.read("word/document.xml")
    except Exception as exc:
        raise RetrievalDocumentError(f"{spec.relative_path} DOCX olarak okunamadı: {exc}") from exc

    root = ET.fromstring(xml_bytes)
    body = root.find("w:body", ns)
    if body is None:
        raise RetrievalDocumentError(f"{spec.relative_path} içinde w:body bulunamadı.")

    paragraphs: list[_DocxParagraph] = []
    for idx, child in enumerate(list(body)):
        tag = child.tag.split("}")[-1]
        if tag == "p":
            p_pr = child.find("w:pPr", ns)
            p_style_el = p_pr.find("w:pStyle", ns) if p_pr is not None else None
            p_style = p_style_el.attrib.get(f"{{{ns['w']}}}val") if p_style_el is not None else None
            txt = "".join(t.text or "" for t in child.findall(".//w:t", ns)).strip()
            if txt:
                paragraphs.append(_DocxParagraph(index=idx, style=p_style, text=txt))
        elif tag == "tbl":
            rows_text: list[str] = []
            for tr in child.findall(".//w:tr", ns):
                cells = [
                    " ".join("".join(t.text or "" for t in tc.findall(".//w:t", ns)).split())
                    for tc in tr.findall("w:tc", ns)
                ]
                rows_text.append(" | ".join(cells))
            tbl_txt = "\n".join(rows_text).strip()
            if tbl_txt:
                paragraphs.append(_DocxParagraph(index=idx, style="Table", text=tbl_txt))

    if not paragraphs:
        raise RetrievalDocumentError(f"{spec.relative_path} hiç metin paragrafı içermiyor.")

    heading_prefixes = (
        "Test Matrix explanation",
        "Columns in test matrix",
        "Videos:",
        "Presentations and Publications to date",
    )

    sections: list[tuple[str, list[_DocxParagraph]]] = []
    current_title = "Overview and Spreadsheets"
    current_paras: list[_DocxParagraph] = []

    for para in paragraphs:
        matched_heading = next((h for h in heading_prefixes if para.text.startswith(h)), None)
        if matched_heading is not None and current_paras:
            sections.append((current_title, current_paras))
            current_title = matched_heading.rstrip(":")
            current_paras = [para]
        elif para.text.startswith("Videos:") and not current_paras:
            current_title = "Videos"
            current_paras.append(para)
        else:
            current_paras.append(para)
    if current_paras:
        sections.append((current_title, current_paras))

    chunks: list[DocumentChunk] = []
    ordinal = 1
    for sec_title, sec_paras in sections:
        buf: list[_DocxParagraph] = []
        buf_len = 0

        def _flush_docx(items: list[_DocxParagraph]) -> None:
            nonlocal ordinal
            if not items:
                return
            combined = "\n".join(p.text for p in items).strip()
            if not combined:
                return
            p_start = items[0].index
            p_end = items[-1].index
            warnings = _detect_chunk_warnings(
                source_text=combined,
                section_title=sec_title,
                section_number=None,
                pdf_page_start=None,
                pdf_page_end=None,
                printed_pages=(),
                is_docx=True,
            )
            loc_key = f"docx:{p_start}-{p_end}"
            chunks.append(
                DocumentChunk(
                    chunk_id=_make_stable_chunk_id(spec.document_id, ordinal, loc_key, combined),
                    chunk_ordinal=ordinal,
                    document_id=spec.document_id,
                    investigation_id=spec.investigation_id,
                    section_number=None,
                    section_title=sec_title,
                    section_path=(sec_title,),
                    source_text=combined,
                    pdf_page_start=None,
                    pdf_page_end=None,
                    printed_page_start=None,
                    printed_page_end=None,
                    printed_pages=(),
                    paragraph_index_start=p_start,
                    paragraph_index_end=p_end,
                    source_url=spec.official_citation_url,
                    source_relpath=spec.relative_path,
                    source_sha256=sha256,
                    extraction_warnings=warnings,
                )
            )
            ordinal += 1

        for para in sec_paras:
            if buf and (buf_len + 1 + len(para.text) > _MAX_CHUNK_CHARS):
                _flush_docx(buf)
                buf = [para]
                buf_len = len(para.text)
            else:
                buf.append(para)
                buf_len += (1 if buf[:-1] else 0) + len(para.text)
        _flush_docx(buf)

    return chunks


def extract_document_chunks(
    spec: DocumentSpec,
    repo_root: str | Path = ".",
) -> tuple[list[DocumentChunk], DocumentManifestEntry]:
    """Tek bir kanonik belgeyi çıkarıp parçalar ve manifest girdisi oluşturur."""
    root = Path(repo_root)
    file_path = root / spec.relative_path
    if not file_path.exists():
        entry = DocumentManifestEntry(
            document_id=spec.document_id,
            investigation_id=spec.investigation_id,
            title=spec.title,
            report_number=spec.report_number,
            official_citation_url=spec.official_citation_url,
            official_download_url=spec.official_download_url,
            relative_path=spec.relative_path,
            source_format=spec.source_format,
            access_status="missing_local_file",
            extraction_method=spec.extraction_method,
            sha256=None,
            file_bytes=None,
            total_pdf_pages=None,
            verified_printed_page_count=None,
            empty_pdf_pages=(),
            chunk_count=0,
            error_message=f"Yerel belge dosyası bulunamadı: {spec.relative_path}",
        )
        return [], entry

    sha256, file_bytes = _compute_sha256(file_path)
    try:
        if spec.source_format == "pdf":
            chunks, stats = _extract_pdf_chunks(spec, file_path, sha256)
            entry = DocumentManifestEntry(
                document_id=spec.document_id,
                investigation_id=spec.investigation_id,
                title=spec.title,
                report_number=spec.report_number,
                official_citation_url=spec.official_citation_url,
                official_download_url=spec.official_download_url,
                relative_path=spec.relative_path,
                source_format=spec.source_format,
                access_status="verified_readable",
                extraction_method=spec.extraction_method,
                sha256=sha256,
                file_bytes=file_bytes,
                total_pdf_pages=stats["total_pdf_pages"],
                verified_printed_page_count=stats["verified_printed_page_count"],
                empty_pdf_pages=stats["empty_pdf_pages"],
                chunk_count=len(chunks),
            )
            return chunks, entry

        if spec.source_format == "docx":
            chunks = _extract_docx_chunks(spec, file_path, sha256)
            entry = DocumentManifestEntry(
                document_id=spec.document_id,
                investigation_id=spec.investigation_id,
                title=spec.title,
                report_number=spec.report_number,
                official_citation_url=spec.official_citation_url,
                official_download_url=spec.official_download_url,
                relative_path=spec.relative_path,
                source_format=spec.source_format,
                access_status="verified_readable",
                extraction_method=spec.extraction_method,
                sha256=sha256,
                file_bytes=file_bytes,
                total_pdf_pages=None,
                verified_printed_page_count=None,
                empty_pdf_pages=(),
                chunk_count=len(chunks),
            )
            return chunks, entry

        raise RetrievalDocumentError(f"Desteklenmeyen belge biçimi: {spec.source_format!r}")
    except RetrievalDocumentError as exc:
        entry = DocumentManifestEntry(
            document_id=spec.document_id,
            investigation_id=spec.investigation_id,
            title=spec.title,
            report_number=spec.report_number,
            official_citation_url=spec.official_citation_url,
            official_download_url=spec.official_download_url,
            relative_path=spec.relative_path,
            source_format=spec.source_format,
            access_status="unreadable_or_corrupt",
            extraction_method=spec.extraction_method,
            sha256=sha256,
            file_bytes=file_bytes,
            total_pdf_pages=None,
            verified_printed_page_count=None,
            empty_pdf_pages=(),
            chunk_count=0,
            error_message=str(exc),
        )
        return [], entry


def load_retrieval_corpus(
    repo_root: str | Path = ".",
    specs: Sequence[DocumentSpec] = DOCUMENT_SPECS,
    *,
    strict: bool = True,
) -> tuple[list[DocumentChunk], list[DocumentManifestEntry]]:
    """Tüm kanonik belgeleri çıkarır; strict=True iken okunamayan kaynakta hata fırlatır."""
    all_chunks: list[DocumentChunk] = []
    manifest_entries: list[DocumentManifestEntry] = []
    for spec in specs:
        chunks, entry = extract_document_chunks(spec, repo_root=repo_root)
        manifest_entries.append(entry)
        if strict and entry.access_status != "verified_readable":
            raise RetrievalDocumentError(entry.error_message or f"{spec.document_id} erişilemedi.")
        all_chunks.extend(chunks)
    return all_chunks, manifest_entries


def generate_retrieval_artifacts(repo_root: str | Path = ".") -> tuple[Path, Path]:
    """psi_document_manifest.json ve psi_document_chunks.json dosyalarını deterministik üretir."""
    root = Path(repo_root)
    processed_dir = root / "data" / "processed"
    processed_dir.mkdir(parents=True, exist_ok=True)

    chunks, manifest_entries = load_retrieval_corpus(root, strict=False)
    total_by_inv: dict[str, int] = {}
    for chunk in chunks:
        total_by_inv[chunk.investigation_id] = total_by_inv.get(chunk.investigation_id, 0) + 1

    manifest_payload = {
        "package": "Paket C — Kaynak İzli Belge Çıkarımı",
        "notes": [
            "Araştırma notları veya README özetleri birincil PDF raporlarının yerine geçmez.",
            "Basılı sayfa numaraları yalnızca sayfa başlığında doğrulandığı ölçüde kaydedilir; tüm belgeye kör sabit offset uygulanmaz.",
            "PDF'den çıkarılan tablo metni sayısal hesap için kullanılmaz; hesaplar Paket A/B CSV çekirdeğinden yapılır.",
        ],
        "summary": {
            "total_documents_configured": len(manifest_entries),
            "verified_readable_documents": sum(1 for e in manifest_entries if e.access_status == "verified_readable"),
            "missing_or_failed_documents": sum(1 for e in manifest_entries if e.access_status != "verified_readable"),
            "total_chunks": len(chunks),
            "chunks_by_investigation": dict(sorted(total_by_inv.items())),
        },
        "documents": [entry.to_dict() for entry in manifest_entries],
    }

    chunks_payload = {
        "schema_version": "1.0",
        "total_chunks": len(chunks),
        "chunks": [chunk.to_dict() for chunk in chunks],
    }

    manifest_path = processed_dir / "psi_document_manifest.json"
    chunks_path = processed_dir / "psi_document_chunks.json"
    manifest_path.write_text(
        json.dumps(manifest_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    chunks_path.write_text(
        json.dumps(chunks_payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path, chunks_path


if __name__ == "__main__":
    target_root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
    m_path, c_path = generate_retrieval_artifacts(target_root)
    print(f"Belge manifesti yazıldı: {m_path.resolve()}")
    print(f"Belge parçaları yazıldı: {c_path.resolve()}")

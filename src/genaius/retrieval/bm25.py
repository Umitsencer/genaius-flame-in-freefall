"""Çevrimdışı, deterministik Okapi BM25 belge erişim ve sıralama katmanı."""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .documents import DocumentChunk

BM25_K1 = 1.5
BM25_B = 0.75

BM25_SCORE_DISCLAIMER = (
    "BM25 sözcük sıralama skorudur; bilimsel doğruluk veya yangın güvenliği olasılığı değildir."
)

BILINGUAL_SCOPE_NOTE = (
    "Türkçe-İngilizce köprülemesi yalnızca küçük, denetlenebilir alan terimi alias tablosuyla yapılır; "
    "genel Türkçe dil anlama veya çapraz-dil anlamsal arama sağlamaz. Tablo satırı sorguları "
    "(ör. 'Nomex testlerini bul') Paket B sayısal/tablo katmanının işidir."
)

VALID_INVESTIGATION_IDS = frozenset({"PSI-25", "PSI-69"})

# Denetlenebilir alan terimi aliasları: kaynak pasaj metni değiştirilmez, yalnızca sorgu genişletmesinde kullanılır.
DOMAIN_TERM_ALIASES: dict[str, tuple[str, ...]] = {
    "yanma hizi": ("burning", "rate", "mm2", "s"),
    "birimi": ("mm2", "unit", "units", "mole", "fraction"),
    "birim": ("mm2", "unit", "mole", "fraction"),
    "tanimi": ("definition", "average", "constant", "linear", "fit"),
    "tanim": ("definition", "average", "constant", "linear", "fit"),
    "sonme capi": ("visible", "flame", "extinction", "diameter"),
    "sonme": ("extinction", "extinguished"),
    "damlacik capi": ("droplet", "diameter"),
    "damlacik": ("droplet",),
    "baslangic": ("initial", "ambient"),
    "bilesimi": ("composition", "mole", "fraction"),
    "bilesim": ("composition", "mole", "fraction"),
    "karbondioksit": ("co2", "carbon", "dioxide"),
    "aralik disi": ("over", "range", "or", "1000", "ppm"),
    "ust sinir": ("over", "range", "1000", "ppm"),
    "kalibrasyonu": ("calibrated", "calibration", "fan", "voltage"),
    "kalibrasyon": ("calibrated", "calibration"),
    "gecikmesi": ("response", "time", "slow", "min", "minute"),
    "gecikme": ("response", "time", "slow", "min", "minute"),
    "tepki suresi": ("response", "time", "1", "min", "minute"),
    "kisitlayici": ("restrictor", "restrictors"),
    "akis": ("flow", "velocity", "duct"),
    "hiz": ("velocity", "speed", "airspeed"),
    "oksijen": ("oxygen", "o2"),
    "karbonmonoksit": ("co", "csa", "cp"),
    "radyometre": ("radiometer", "gain", "uncalibrated"),
    "basinc": ("pressure", "ambient", "mmhg", "atm"),
}

_SUBSCRIPT_MAP = str.maketrans("₀₁₂₃₄₅₆₇₈₉²", "01234567892")
_TR_FOLD_MAP = str.maketrans(
    {
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "İ": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }
)
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:_[a-z0-9]+)*")


class RetrievalValidationError(ValueError):
    """Boş sorgu, geçersiz top_k veya geçersiz çalışma filtresi hatası."""


@dataclass(frozen=True)
class RetrievalHit:
    """Kaynak konumu ve ham pasajı korunmuş tek BM25 erişim sonucu."""

    rank: int
    chunk_id: str
    score: float
    matched_terms: tuple[str, ...]
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
    extraction_warnings: tuple[str, ...]
    score_disclaimer: str = BM25_SCORE_DISCLAIMER
    passive_data_only: bool = True

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu sözlük gösterimi döndürür."""
        return {
            "rank": self.rank,
            "chunk_id": self.chunk_id,
            "score": self.score,
            "matched_terms": list(self.matched_terms),
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
            "score_disclaimer": self.score_disclaimer,
            "passive_data_only": self.passive_data_only,
        }


@dataclass(frozen=True)
class SearchResult:
    """BM25 arama çıktısı; uygulanan filtre ve alias genişletmelerini açıkça taşır."""

    query: str
    investigation_id: str | None
    top_k: int
    total_hits_returned: int
    hits: tuple[RetrievalHit, ...]
    query_tokens: tuple[str, ...]
    applied_query_expansions: tuple[dict[str, Any], ...]
    bilingual_scope_note: str = BILINGUAL_SCOPE_NOTE
    bm25_params: dict[str, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON uyumlu sözlük gösterimi döndürür."""
        return {
            "query": self.query,
            "investigation_id": self.investigation_id,
            "top_k": self.top_k,
            "total_hits_returned": self.total_hits_returned,
            "query_tokens": list(self.query_tokens),
            "applied_query_expansions": [dict(x) for x in self.applied_query_expansions],
            "bilingual_scope_note": self.bilingual_scope_note,
            "bm25_params": dict(self.bm25_params or {}),
            "hits": [hit.to_dict() for hit in self.hits],
        }


def tokenize_text(text: str) -> list[str]:
    """Bilimsel birim/alt-simge normalizasyonu ile deterministik BM25 tokenleştirici."""
    normalized = text.translate(_SUBSCRIPT_MAP).lower().translate(_TR_FOLD_MAP)
    # mm2/s veya O2/N2 ifadelerini hem tek hem ayrık eşlenebilir parçalara bölmek için / temizlenir
    normalized = normalized.replace("/", " ").replace("-", " ").replace("—", " ").replace("–", " ")
    return _TOKEN_RE.findall(normalized)


def expand_query_with_aliases(query: str) -> tuple[list[str], list[dict[str, Any]]]:
    """Küçük denetlenebilir alan aliaslarıyla sorgu terimlerini genişletir; metadata izini döndürür."""
    base_tokens = tokenize_text(query)
    if not base_tokens:
        return [], []

    joined_norm = " ".join(base_tokens)
    expansions: list[dict[str, Any]] = []
    expanded_tokens = list(base_tokens)
    seen_aliases: set[str] = set()

    for phrase, targets in DOMAIN_TERM_ALIASES.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", joined_norm):
            expansions.append({"matched_phrase": phrase, "added_terms": list(targets)})
            for tgt in targets:
                if tgt not in seen_aliases:
                    seen_aliases.add(tgt)
                    expanded_tokens.append(tgt)

    return expanded_tokens, expansions


class BM25Index:
    """Okapi BM25 indeksi.

    Formül:
      IDF(t) = ln((N - df(t) + 0.5) / (df(t) + 0.5) + 1.0)
      score(D, Q) = sum_{t in Q} IDF(t) * ((tf(t, D) * (k1 + 1)) / (tf(t, D) + k1 * (1 - b + b * (|D| / avgdl))))
    Eşitlik bozma kuralı:
      1. Yuvarlanmış BM25 skoru (-round(score, 12)) artan (yani yüksek skor önce),
      2. document_id artan,
      3. chunk_ordinal artan,
      4. chunk_id artan.
    """

    def __init__(
        self,
        chunks: Sequence[DocumentChunk],
        *,
        k1: float = BM25_K1,
        b: float = BM25_B,
    ) -> None:
        if k1 <= 0 or not math.isfinite(k1):
            raise RetrievalValidationError(f"BM25 k1 > 0 ve sonlu olmalıdır; alınan: {k1!r}")
        if b < 0 or b > 1 or not math.isfinite(b):
            raise RetrievalValidationError(f"BM25 b [0, 1] aralığında olmalıdır; alınan: {b!r}")

        self.k1 = float(k1)
        self.b = float(b)
        self._chunks: tuple[DocumentChunk, ...] = tuple(chunks)
        self._doc_count = len(self._chunks)
        self._doc_term_freqs: list[Counter[str]] = []
        self._doc_lengths: list[int] = []
        self._postings: dict[str, list[int]] = {}
        df_counts: Counter[str] = Counter()

        for doc_idx, chunk in enumerate(self._chunks):
            indexable = f"{chunk.section_number or ''} {chunk.section_title}\n{chunk.source_text}"
            tokens = tokenize_text(indexable)
            tf = Counter(tokens)
            self._doc_term_freqs.append(tf)
            self._doc_lengths.append(len(tokens))
            for term in tf:
                df_counts[term] += 1
                self._postings.setdefault(term, []).append(doc_idx)

        self._avgdl = (sum(self._doc_lengths) / self._doc_count) if self._doc_count > 0 else 0.0
        self._idf: dict[str, float] = {
            term: math.log(((self._doc_count - df + 0.5) / (df + 0.5)) + 1.0)
            for term, df in df_counts.items()
        }

    @property
    def chunks(self) -> tuple[DocumentChunk, ...]:
        """İndekslenen değiştirilemez belge parçalarını döndürür."""
        return self._chunks

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        investigation_id: str | None = None,
        use_bilingual_aliases: bool = True,
    ) -> SearchResult:
        """Deterministik BM25 sıralaması ile ilgili belge parçalarını döndürür."""
        if not isinstance(query, str) or not query.strip():
            raise RetrievalValidationError("Sorgu metni boş olamaz.")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0:
            raise RetrievalValidationError(f"top_k pozitif bir tam sayı olmalıdır; alınan: {top_k!r}")
        if investigation_id is not None and investigation_id not in VALID_INVESTIGATION_IDS:
            raise RetrievalValidationError(
                f"Geçersiz investigation_id: {investigation_id!r}. İzin verilenler: {sorted(VALID_INVESTIGATION_IDS)}"
            )

        if use_bilingual_aliases:
            query_terms, expansions = expand_query_with_aliases(query)
        else:
            query_terms, expansions = tokenize_text(query), []

        if not query_terms:
            raise RetrievalValidationError("Sorguda indekslenebilir hiçbir kelime/sembol bulunamadı.")

        # Tekrarlı sorgu terimlerini benzersiz tutup deterministik sırayı koru
        unique_query_terms = list(dict.fromkeys(query_terms))
        if self._doc_count == 0 or self._avgdl <= 0.0:
            return SearchResult(
                query=query,
                investigation_id=investigation_id,
                top_k=top_k,
                total_hits_returned=0,
                hits=(),
                query_tokens=tuple(unique_query_terms),
                applied_query_expansions=tuple(expansions),
                bm25_params={"k1": self.k1, "b": self.b},
            )

        candidate_indices: set[int] = set()
        for term in unique_query_terms:
            for idx in self._postings.get(term, ()):
                if investigation_id is not None and self._chunks[idx].investigation_id != investigation_id:
                    continue
                candidate_indices.add(idx)

        scored: list[tuple[float, DocumentChunk, tuple[str, ...]]] = []
        for idx in candidate_indices:
            tf_map = self._doc_term_freqs[idx]
            dl = self._doc_lengths[idx]
            if dl == 0:
                continue
            score = 0.0
            matched_terms: list[str] = []
            norm_len = 1.0 - self.b + self.b * (dl / self._avgdl)
            for term in unique_query_terms:
                tf = tf_map.get(term, 0)
                if tf <= 0:
                    continue
                idf = self._idf.get(term, 0.0)
                tf_part = (tf * (self.k1 + 1.0)) / (tf + self.k1 * norm_len)
                term_score = idf * tf_part
                if term_score > 0.0:
                    score += term_score
                    matched_terms.append(term)
            if score > 0.0 and matched_terms:
                scored.append((score, self._chunks[idx], tuple(matched_terms)))

        # Deterministik sıralama ve eşitlik bozma kuralı
        scored.sort(
            key=lambda item: (
                -round(item[0], 12),
                item[1].document_id,
                item[1].chunk_ordinal,
                item[1].chunk_id,
            )
        )

        selected = scored[:top_k]
        hits = tuple(
            RetrievalHit(
                rank=rank_idx,
                chunk_id=chunk.chunk_id,
                score=round(score, 8),
                matched_terms=matched_terms,
                document_id=chunk.document_id,
                investigation_id=chunk.investigation_id,
                section_number=chunk.section_number,
                section_title=chunk.section_title,
                section_path=chunk.section_path,
                source_text=chunk.source_text,
                pdf_page_start=chunk.pdf_page_start,
                pdf_page_end=chunk.pdf_page_end,
                printed_page_start=chunk.printed_page_start,
                printed_page_end=chunk.printed_page_end,
                printed_pages=chunk.printed_pages,
                paragraph_index_start=chunk.paragraph_index_start,
                paragraph_index_end=chunk.paragraph_index_end,
                source_url=chunk.source_url,
                source_relpath=chunk.source_relpath,
                source_sha256=chunk.source_sha256,
                extraction_warnings=chunk.extraction_warnings,
            )
            for rank_idx, (score, chunk, matched_terms) in enumerate(selected, 1)
        )

        return SearchResult(
            query=query,
            investigation_id=investigation_id,
            top_k=top_k,
            total_hits_returned=len(hits),
            hits=hits,
            query_tokens=tuple(unique_query_terms),
            applied_query_expansions=tuple(expansions),
            bm25_params={"k1": self.k1, "b": self.b},
        )


def build_bm25_index(
    chunks: Sequence[DocumentChunk],
    *,
    k1: float = BM25_K1,
    b: float = BM25_B,
) -> BM25Index:
    """Belge parçalarından BM25 indeksini kurar."""
    return BM25Index(chunks, k1=k1, b=b)

"""Paket C: Kaynak izli belge çıkarımı, manifest üretimi ve çevrimdışı BM25 arama katmanı."""

from __future__ import annotations

_DOCUMENTS_EXPORTS = {
    "DOCUMENT_SPECS",
    "DocumentChunk",
    "DocumentManifestEntry",
    "DocumentSpec",
    "RetrievalDocumentError",
    "extract_document_chunks",
    "generate_retrieval_artifacts",
    "load_retrieval_corpus",
}

_BM25_EXPORTS = {
    "BILINGUAL_SCOPE_NOTE",
    "BM25Index",
    "BM25_B",
    "BM25_K1",
    "BM25_SCORE_DISCLAIMER",
    "DOMAIN_TERM_ALIASES",
    "RetrievalHit",
    "RetrievalValidationError",
    "SearchResult",
    "build_bm25_index",
    "expand_query_with_aliases",
    "tokenize_text",
}


def __getattr__(name: str):
    if name in _DOCUMENTS_EXPORTS:
        from . import documents

        return getattr(documents, name)
    if name in _BM25_EXPORTS:
        from . import bm25

        return getattr(bm25, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = sorted(_DOCUMENTS_EXPORTS | _BM25_EXPORTS)

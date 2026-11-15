"""Verified NASA PSI Combustion Science research catalog and explainable search layer.

Combines official NASA PSI portal metadata (`psi_24_source_manifest.json`), local
suitability review records (`PSI_24_KARSILASTIRMA.csv`), audited CFI feasibility
findings (`CFI_ANALIZ_FIZIBILITESI.md`), and the active core registry (`DATASET_SPECS`).

Strict separation & boundary guarantees:
1. Support tiers (`catalogued`, `reviewed`, `queryable_in_core`) are explicit and distinct.
   `queryable_in_core` is derived strictly from `DATASET_SPECS` (`PSI-25`, `PSI-69`).
2. `PSI-39` (CFI) and `PSI-101` (SAME-R) are never marked `queryable_in_core`.
   `PSI-39` carries `"reviewed / descriptive extension proposed"` and avoids copying stale
   CSV claims superseded by `CFI_ANALIZ_FIZIBILITESI.md`.
3. Search ranking uses deterministic field matching (`deterministic_field_match_v1`),
   not Okapi BM25 and not semantic embeddings. Score means textual catalog match only,
   never scientific importance, novelty, data cleanliness, or fire-safety risk.
4. A–E evaluation classes reflect local engineering/readiness review only, never a
   numerical risk, importance, or quality score.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .data.contracts import DATASET_SPECS
from .retrieval.bm25 import tokenize_text

DEFAULT_MANIFEST_RELPATH = "data/processed/psi_24_source_manifest.json"
DEFAULT_COMPARISON_CSV_RELPATH = "docs/arastirma/space_apps_2026/PSI_24_KARSILASTIRMA.csv"
DEFAULT_CFI_FEASIBILITY_RELPATH = "docs/arastirma/space_apps_2026/CFI_ANALIZ_FIZIBILITESI.md"

EXPECTED_COMBUSTION_CATALOG_COUNT = 24
_PSI_ID_RE = re.compile(r"^PSI-([1-9]\d*)$")
_PSI_IN_TEXT_RE = re.compile(r"\bpsi[-\s]*([1-9]\d*)\b")

CORE_INVESTIGATION_IDS: frozenset[str] = frozenset(DATASET_SPECS.keys())

RANKING_ALGORITHM = "deterministic_field_match_v1"

RANKING_RULES_SUMMARY = (
    "Deterministic field-weighted lexical ranking (not BM25): "
    "exact psi_id match (+100.0), exact normalized acronym match (+80.0), "
    "distinct query-term coverage across entry (+25.0 exact, +18.75 plural/singular variant), "
    "plus field-level token overlap (title=+12.0, acronym_token=+10.0, sub_research_area=+6.0, "
    "flight_program=+4.0, project_type=+3.0, doi=+3.0; plural/singular 0.75x). "
    "Ties break deterministically by descending rounded score, ascending numeric PSI-ID, "
    "and ascending psi_id string."
)

CATALOG_LANGUAGE_SCOPE = (
    "English queries against verified portal catalog fields (psi_id, acronym, title, "
    "sub_research_area, project_type, flight_program, doi) are the supported initial scope; "
    "multilingual or semantic catalog search is not supported."
)

RELEVANCE_DISCLAIMER = (
    "Score reflects deterministic textual field matching on verified catalog metadata only; "
    "it does NOT measure scientific importance, novelty, data readiness, or fire-safety risk."
)

DECISION_DISCLAIMER = (
    "Evaluation class (A–E) records local engineering eligibility review only; "
    "it is not a fire-safety risk, scientific significance, or quality score."
)

TITLE_PROVENANCE_NOTE = (
    "Words in a portal title or research sub-area are not evidence that a specific physical "
    "variable was quantitatively measured or usable across experimental runs."
)

# Conservative English plural <-> singular pairs relevant to catalog titles/areas.
# Kept explicit and small so unverified stemming artifacts cannot invent false matches.
_SAFE_PLURAL_PAIRS: tuple[tuple[str, str], ...] = (
    ("flame", "flames"),
    ("droplet", "droplets"),
    ("fuel", "fuels"),
    ("gas", "gases"),
    ("experiment", "experiments"),
    ("investigation", "investigations"),
    ("aerosol", "aerosols"),
    ("model", "models"),
    ("transition", "transitions"),
    ("dataset", "datasets"),
    ("set", "sets"),
)

_EQUIV_VARIANTS: dict[str, tuple[str, ...]] = {}
for _sing, _plur in _SAFE_PLURAL_PAIRS:
    _EQUIV_VARIANTS.setdefault(_sing, (_plur,))
    _EQUIV_VARIANTS.setdefault(_plur, (_sing,))

_FIELD_WEIGHTS: dict[str, float] = {
    "title": 12.0,
    "acronym": 10.0,
    "sub_research_area": 6.0,
    "flight_program": 4.0,
    "project_type": 3.0,
    "doi": 3.0,
}

_SEARCHABLE_TEXT_FIELDS: tuple[str, ...] = (
    "title",
    "acronym",
    "sub_research_area",
    "project_type",
    "flight_program",
    "doi",
)

_CANONICAL_FIELD_ORDER: tuple[str, ...] = (
    "psi_id",
    "acronym",
    "title",
    "sub_research_area",
    "project_type",
    "flight_program",
    "doi",
)


class CatalogError(ValueError):
    """Base error for research catalog loading, validation, and search."""


class CatalogLoadError(CatalogError):
    """Raised when catalog sources are missing, malformed, duplicated, or inconsistent."""


class CatalogValidationError(CatalogError):
    """Raised when catalog search or filter arguments are invalid."""


@dataclass(frozen=True)
class CatalogProvenance:
    """File paths, SHA-256 checksums, and record keys backing a catalog entry."""

    manifest_relpath: str
    manifest_sha256: str
    manifest_record_key: str
    comparison_csv_relpath: str
    comparison_csv_sha256: str
    comparison_csv_row: int
    comparison_csv_key: str
    extra_review_relpath: str | None = None
    extra_review_sha256: str | None = None
    extra_review_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "manifest_relpath": self.manifest_relpath,
            "manifest_sha256": self.manifest_sha256,
            "manifest_record_key": self.manifest_record_key,
            "comparison_csv_relpath": self.comparison_csv_relpath,
            "comparison_csv_sha256": self.comparison_csv_sha256,
            "comparison_csv_row": self.comparison_csv_row,
            "comparison_csv_key": self.comparison_csv_key,
            "extra_review_relpath": self.extra_review_relpath,
            "extra_review_sha256": self.extra_review_sha256,
            "extra_review_key": self.extra_review_key,
        }


@dataclass(frozen=True)
class CatalogSupportStatus:
    """Explicit separation between catalog presence, local review, and active core support."""

    catalogued: bool
    reviewed: bool
    queryable_in_core: bool
    support_tier: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalogued": self.catalogued,
            "reviewed": self.reviewed,
            "queryable_in_core": self.queryable_in_core,
            "support_tier": self.support_tier,
        }


@dataclass(frozen=True)
class CatalogEntry:
    """Single verified NASA PSI Combustion Science catalog card."""

    psi_id: str
    title: str
    acronym: str | None
    research_area: str | None
    sub_research_area: str | None
    project_type: str | None
    flight_program: str | None
    license: str | None
    doi: str | None
    catalog_url: str | None
    metadata_api_url: str | None
    version: int | None
    catalog_generated_utc: str | None
    publication_count: int
    remote_total_files: int | None
    local_file_count: int
    evaluation_decision_code: str
    evaluation_decision_label: str
    evaluation_scope_status: str
    evaluation_summary: str
    limitations: str
    support: CatalogSupportStatus
    provenance: CatalogProvenance
    source_discrepancies: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "psi_id": self.psi_id,
            "title": self.title,
            "acronym": self.acronym,
            "research_area": self.research_area,
            "sub_research_area": self.sub_research_area,
            "project_type": self.project_type,
            "flight_program": self.flight_program,
            "license": self.license,
            "doi": self.doi,
            "catalog_url": self.catalog_url,
            "metadata_api_url": self.metadata_api_url,
            "version": self.version,
            "catalog_generated_utc": self.catalog_generated_utc,
            "publication_count": self.publication_count,
            "remote_total_files": self.remote_total_files,
            "local_file_count": self.local_file_count,
            "evaluation_decision_code": self.evaluation_decision_code,
            "evaluation_decision_label": self.evaluation_decision_label,
            "evaluation_scope_status": self.evaluation_scope_status,
            "evaluation_summary": self.evaluation_summary,
            "limitations": self.limitations,
            "support": self.support.to_dict(),
            "provenance": self.provenance.to_dict(),
            "source_discrepancies": list(self.source_discrepancies),
            "decision_disclaimer": DECISION_DISCLAIMER,
            "title_provenance_note": TITLE_PROVENANCE_NOTE,
        }


@dataclass(frozen=True)
class ResearchCatalog:
    """Loaded and verified NASA PSI Combustion Science catalog."""

    entries: tuple[CatalogEntry, ...]
    manifest_generated_utc: str | None
    manifest_scope: str | None
    source_search_url: str | None
    core_investigation_ids: tuple[str, ...]
    source_hashes: dict[str, str]

    def get(self, psi_id: str) -> CatalogEntry | None:
        normalized = _normalize_psi_id_query(psi_id) or psi_id.strip().upper()
        for entry in self.entries:
            if entry.psi_id == normalized:
                return entry
        return None

    def available_filters(self) -> dict[str, Any]:
        return {
            "project_types": sorted({e.project_type for e in self.entries if e.project_type}),
            "sub_research_areas": sorted({e.sub_research_area for e in self.entries if e.sub_research_area}),
            "core_investigation_ids": list(self.core_investigation_ids),
            "support_tiers": sorted({e.support.support_tier for e in self.entries}),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_studies": len(self.entries),
            "manifest_generated_utc": self.manifest_generated_utc,
            "manifest_scope": self.manifest_scope,
            "source_search_url": self.source_search_url,
            "core_investigation_ids": list(self.core_investigation_ids),
            "source_hashes": dict(self.source_hashes),
            "decision_disclaimer": DECISION_DISCLAIMER,
            "title_provenance_note": TITLE_PROVENANCE_NOTE,
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class CatalogSearchHit:
    """Single explainable catalog search match."""

    rank: int
    entry: CatalogEntry
    score: float
    matched_fields: tuple[str, ...]
    matched_terms: tuple[str, ...]
    field_matches: dict[str, tuple[str, ...]]
    ranking_reason: str
    score_disclaimer: str = RELEVANCE_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "psi_id": self.entry.psi_id,
            "score": self.score,
            "matched_fields": list(self.matched_fields),
            "matched_terms": list(self.matched_terms),
            "field_matches": {k: list(v) for k, v in self.field_matches.items()},
            "ranking_reason": self.ranking_reason,
            "score_disclaimer": self.score_disclaimer,
            "entry": self.entry.to_dict(),
        }


@dataclass(frozen=True)
class CatalogSearchResult:
    """Catalog search/filter output with explicit matching rules and disclaimers."""

    status: str
    query: str | None
    filters: dict[str, Any]
    total_catalog_studies: int
    total_matches: int
    hits: tuple[CatalogSearchHit, ...]
    ranking_algorithm: str = RANKING_ALGORITHM
    ranking_rules: str = RANKING_RULES_SUMMARY
    language_scope: str = CATALOG_LANGUAGE_SCOPE
    score_disclaimer: str = RELEVANCE_DISCLAIMER

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "query": self.query,
            "filters": dict(self.filters),
            "ranking_algorithm": self.ranking_algorithm,
            "ranking_rules": self.ranking_rules,
            "language_scope": self.language_scope,
            "score_disclaimer": self.score_disclaimer,
            "total_catalog_studies": self.total_catalog_studies,
            "total_matches": self.total_matches,
            "hits": [hit.to_dict() for hit in self.hits],
        }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relpath_str(path: Path, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _clean_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise CatalogLoadError(f"Expected string or null field, got {type(value).__name__}.")
    stripped = value.strip()
    return stripped if stripped else None


def _psi_numeric_id(psi_id: str) -> int:
    match = _PSI_ID_RE.match(psi_id)
    if not match:
        raise CatalogLoadError(f"Invalid PSI-ID format: {psi_id!r}. Expected 'PSI-<positive integer>'.")
    return int(match.group(1))


def _normalize_compact_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _normalize_psi_id_query(text: str) -> str | None:
    compact = re.sub(r"[\s_-]+", "", text.strip().lower())
    match = re.fullmatch(r"psi([1-9]\d*)", compact)
    if not match:
        return None
    return f"PSI-{match.group(1)}"


def _acronym_variants(acronym: str) -> tuple[str, ...]:
    parts = [p.strip() for p in acronym.split("/") if p.strip()]
    variants = [_normalize_compact_key(acronym)]
    for part in parts:
        norm = _normalize_compact_key(part)
        if norm and norm not in variants:
            variants.append(norm)
    return tuple(variants)


def _derive_support_tier(psi_id: str, core_ids: frozenset[str], reviewed: bool) -> tuple[bool, str]:
    if psi_id in core_ids:
        return True, "queryable_in_core"
    if psi_id == "PSI-39":
        return False, "reviewed / descriptive extension proposed"
    if reviewed:
        return False, "reviewed"
    return False, "catalogued"


def _derive_scope_status(psi_id: str, decision_code: str, core_ids: frozenset[str]) -> str:
    if psi_id in core_ids:
        return "core_active"
    if psi_id == "PSI-39":
        return "reviewed / descriptive extension proposed"
    mapping = {
        "B": "reviewed / verification_or_transform_required",
        "C": "reviewed / literature_or_reference_only",
        "D": "reviewed / deferred_not_for_v1",
        "E": "reviewed / insufficient_access",
    }
    return mapping.get(decision_code, "reviewed")


def _extract_decision_code(decision_label: str, psi_id: str) -> str:
    match = re.match(r"^\s*([A-E])\b", decision_label)
    if not match:
        raise CatalogLoadError(f"Unrecognized evaluation decision label for {psi_id}: {decision_label!r}")
    return match.group(1)


def _parse_cfi_feasibility_summary(cfi_text: str) -> tuple[str, str, str]:
    """Extract verified PSI-39 status from CFI_ANALIZ_FIZIBILITESI.md without stale claims."""
    if "ERTELE" not in cfi_text or "Farnesane" not in cfi_text:
        raise CatalogLoadError(
            "CFI_ANALIZ_FIZIBILITESI.md does not contain expected audited decision markers (ERTELE / Farnesane)."
        )
    summary = (
        "Audited in CFI_ANALIZ_FIZIBILITESI.md (Task 036-037): 144 candidate records "
        "(from 146 Completed Analysis?=Yes after dropping unignited 1212/1235) covering "
        "C12H26 and 75/25, 60/40 C12H26/iso-dodecane blends; predictive modeling is ERTELE (deferred) "
        "and CFI is proposed only as a separate Phase-2 descriptive module outside PSI-25 + PSI-69 core."
    )
    limitations = (
        "Portal CSV provides only 87 metadata rows. Jan 2021 workbook contains 227 rows with "
        "81 Completed Analysis?=No (including all 44 Farnesane workbook rows, though one remote "
        "Analyzed Data PDF FLEX-1393 exists unexamined locally), 48 raw_zero/interpretation_unresolved "
        "Dext,cool entries, 20 missing kcool values among 144 candidates, meaning_unverified Extrap CF?, "
        "severe Fiber x Pressure confounding at 3-5 atm, and 9 reused-droplet records."
    )
    discrepancy = (
        "PSI_24_KARSILASTIRMA.csv (Task 034) is superseded for PSI-39 by CFI_ANALIZ_FIZIBILITESI.md "
        "(Task 036-037): stale CSV wording claiming completed Farnesane workbook measurements and "
        "MVP-priority 1 status was excluded; CFI modeling is ERTELE and outside active DATASET_SPECS."
    )
    return summary, limitations, discrepancy


def _load_manifest(manifest_path: Path) -> tuple[dict[str, Any], dict[str, tuple[int, dict[str, Any]]], str]:
    if not manifest_path.is_file():
        raise CatalogLoadError(f"Manifest file not found: {manifest_path}")
    try:
        raw_text = manifest_path.read_text(encoding="utf-8")
        payload = json.loads(raw_text)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CatalogLoadError(f"Failed to read/parse manifest JSON {manifest_path}: {exc}") from exc

    if not isinstance(payload, dict) or not isinstance(payload.get("studies"), list):
        raise CatalogLoadError(f"Malformed manifest structure in {manifest_path}: expected object with 'studies' list.")

    studies = payload["studies"]
    declared_count = payload.get("study_count")
    if declared_count is not None and declared_count != len(studies):
        raise CatalogLoadError(
            f"Manifest study_count mismatch in {manifest_path}: declared {declared_count}, actual {len(studies)}."
        )

    by_id: dict[str, tuple[int, dict[str, Any]]] = {}
    for idx, study in enumerate(studies):
        if not isinstance(study, dict):
            raise CatalogLoadError(f"Manifest studies[{idx}] must be an object.")
        raw_id = study.get("psi_id")
        if not isinstance(raw_id, str) or not raw_id.strip():
            raise CatalogLoadError(f"Missing or invalid psi_id at manifest studies[{idx}].")
        psi_id = raw_id.strip()
        _psi_numeric_id(psi_id)
        if psi_id in by_id:
            raise CatalogLoadError(f"Duplicate psi_id {psi_id!r} in manifest {manifest_path}.")
        by_id[psi_id] = (idx, study)

    return payload, by_id, _sha256_file(manifest_path)


def _load_comparison_csv(csv_path: Path) -> tuple[dict[str, tuple[int, dict[str, str]]], str]:
    if not csv_path.is_file():
        raise CatalogLoadError(f"Comparison CSV not found: {csv_path}")
    try:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            required_cols = {"PSI-ID", "başlık", "tür", "kalite sınırı", "kullanım önerisi", "karar", "gerekçe"}
            fieldnames = set(reader.fieldnames or ())
            missing_cols = sorted(required_cols - fieldnames)
            if missing_cols:
                raise CatalogLoadError(f"Comparison CSV {csv_path} missing columns: {missing_cols}")

            by_id: dict[str, tuple[int, dict[str, str]]] = {}
            for row_num, row in enumerate(reader, start=2):
                raw_id = (row.get("PSI-ID") or "").strip()
                if not raw_id:
                    raise CatalogLoadError(f"Empty PSI-ID in {csv_path} at line {row_num}.")
                _psi_numeric_id(raw_id)
                if raw_id in by_id:
                    raise CatalogLoadError(f"Duplicate PSI-ID {raw_id!r} in {csv_path} at line {row_num}.")
                by_id[raw_id] = (row_num, row)
    except (UnicodeDecodeError, csv.Error) as exc:
        raise CatalogLoadError(f"Failed to read comparison CSV {csv_path}: {exc}") from exc

    return by_id, _sha256_file(csv_path)


def load_research_catalog(
    repo_root: Path | str = ".",
    *,
    manifest_relpath: str = DEFAULT_MANIFEST_RELPATH,
    comparison_csv_relpath: str = DEFAULT_COMPARISON_CSV_RELPATH,
    cfi_feasibility_relpath: str | None = DEFAULT_CFI_FEASIBILITY_RELPATH,
    expected_count: int | None = EXPECTED_COMBUSTION_CATALOG_COUNT,
    core_investigation_ids: Iterable[str] | None = None,
) -> ResearchCatalog:
    """Load, join on PSI-ID, validate, and return the NASA PSI Combustion catalog."""
    root = Path(repo_root)
    manifest_path = root / manifest_relpath
    csv_path = root / comparison_csv_relpath

    manifest_payload, manifest_by_id, manifest_sha = _load_manifest(manifest_path)
    csv_by_id, csv_sha = _load_comparison_csv(csv_path)

    manifest_ids = set(manifest_by_id)
    csv_ids = set(csv_by_id)
    if manifest_ids != csv_ids:
        only_manifest = sorted(manifest_ids - csv_ids)
        only_csv = sorted(csv_ids - manifest_ids)
        raise CatalogLoadError(
            "PSI-ID mismatch between manifest and comparison CSV: "
            f"only_in_manifest={only_manifest}, only_in_csv={only_csv}."
        )

    if expected_count is not None and len(manifest_by_id) != expected_count:
        raise CatalogLoadError(
            f"Expected {expected_count} unique PSI investigations, found {len(manifest_by_id)}."
        )

    active_core_ids = frozenset(DATASET_SPECS.keys()) if core_investigation_ids is None else frozenset(core_investigation_ids)
    for core_id in active_core_ids:
        if core_id not in manifest_ids:
            raise CatalogLoadError(f"Active core investigation {core_id!r} missing from catalog manifest.")

    cfi_summary_tuple: tuple[str, str, str] | None = None
    cfi_sha: str | None = None
    cfi_resolved_rel: str | None = None
    if cfi_feasibility_relpath is not None:
        cfi_path = root / cfi_feasibility_relpath
        if cfi_path.is_file():
            try:
                cfi_text = cfi_path.read_text(encoding="utf-8")
            except UnicodeDecodeError as exc:
                raise CatalogLoadError(f"Failed to read {cfi_path} as UTF-8: {exc}") from exc
            cfi_summary_tuple = _parse_cfi_feasibility_summary(cfi_text)
            cfi_sha = _sha256_file(cfi_path)
            cfi_resolved_rel = _relpath_str(cfi_path, root)
        elif "PSI-39" in manifest_ids:
            raise CatalogLoadError(f"Required audited feasibility file for PSI-39 missing: {cfi_path}")

    manifest_rel = _relpath_str(manifest_path, root)
    csv_rel = _relpath_str(csv_path, root)
    manifest_generated_utc = _clean_optional_str(manifest_payload.get("generated_utc"))

    entries: list[CatalogEntry] = []
    for psi_id in sorted(manifest_ids, key=_psi_numeric_id):
        _, study = manifest_by_id[psi_id]
        csv_row_num, csv_row = csv_by_id[psi_id]

        title = _clean_optional_str(study.get("title"))
        if not title:
            raise CatalogLoadError(f"Missing catalog title for {psi_id}.")

        acronym = _clean_optional_str(study.get("acronym"))
        research_area = _clean_optional_str(study.get("research_area"))
        sub_research_area = _clean_optional_str(study.get("sub_research_area"))
        project_type = _clean_optional_str(study.get("project_type"))
        flight_program = _clean_optional_str(study.get("flight_program"))
        license_val = _clean_optional_str(study.get("license"))
        doi = _clean_optional_str(study.get("doi"))
        catalog_url = _clean_optional_str(study.get("catalog_url"))
        metadata_api_url = _clean_optional_str(study.get("metadata_api_url"))

        raw_version = study.get("version")
        if raw_version is not None and (isinstance(raw_version, bool) or not isinstance(raw_version, int)):
            raise CatalogLoadError(f"Invalid manifest version for {psi_id}: {raw_version!r}")

        remote_summary = study.get("remote_summary")
        remote_total_files: int | None = None
        if isinstance(remote_summary, dict) and isinstance(remote_summary.get("total_files"), int):
            remote_total_files = remote_summary["total_files"]

        pub_count = study.get("publication_count")
        if not isinstance(pub_count, int) or isinstance(pub_count, bool):
            pub_count = len(study.get("publications", []) or [])

        local_files = study.get("local_files")
        local_file_count = len(local_files) if isinstance(local_files, list) else 0

        decision_label = (csv_row.get("karar") or "").strip()
        decision_code = _extract_decision_code(decision_label, psi_id)

        queryable_in_core, support_tier = _derive_support_tier(psi_id, active_core_ids, reviewed=True)
        if psi_id == "PSI-39" and queryable_in_core:
            raise CatalogLoadError("PSI-39 (CFI) cannot be marked queryable_in_core.")
        if psi_id == "PSI-101" and queryable_in_core:
            raise CatalogLoadError("PSI-101 (SAME-R) cannot be marked queryable_in_core.")

        scope_status = _derive_scope_status(psi_id, decision_code, active_core_ids)

        discrepancies: list[str] = []
        if project_type and "Microgravity" in project_type and "Microgravity" not in (csv_row.get("tür") or ""):
            discrepancies.append(f"project_type mismatch: manifest={project_type!r} vs csv={csv_row.get('tür')!r}")
        if project_type and "Ground" in project_type and "Ground" not in (csv_row.get("tür") or ""):
            discrepancies.append(f"project_type mismatch: manifest={project_type!r} vs csv={csv_row.get('tür')!r}")
        if "Cygnus" in (csv_row.get("tür") or "") and "Cygnus" not in (flight_program or ""):
            discrepancies.append(
                f"flight_program mismatch: manifest={flight_program!r} vs comparison_csv={csv_row.get('tür')!r}"
            )

        extra_rel: str | None = None
        extra_sha: str | None = None
        extra_key: str | None = None
        if psi_id == "PSI-39" and cfi_summary_tuple is not None:
            evaluation_summary, limitations, cfi_discrepancy = cfi_summary_tuple
            discrepancies.append(cfi_discrepancy)
            extra_rel = cfi_resolved_rel
            extra_sha = cfi_sha
            extra_key = "PSI-39 (Task 036-037 audit)"
        else:
            limitations = (csv_row.get("kalite sınırı") or "").strip() or "Not documented."
            usage = (csv_row.get("kullanım önerisi") or "").strip()
            rationale = (csv_row.get("gerekçe") or "").strip()
            evaluation_summary = f"{usage} — {rationale}".strip(" —") if (usage or rationale) else decision_label

        provenance = CatalogProvenance(
            manifest_relpath=manifest_rel,
            manifest_sha256=manifest_sha,
            manifest_record_key=f"studies[psi_id={psi_id}]",
            comparison_csv_relpath=csv_rel,
            comparison_csv_sha256=csv_sha,
            comparison_csv_row=csv_row_num,
            comparison_csv_key=f"PSI-ID={psi_id}",
            extra_review_relpath=extra_rel,
            extra_review_sha256=extra_sha,
            extra_review_key=extra_key,
        )

        entries.append(
            CatalogEntry(
                psi_id=psi_id,
                title=title,
                acronym=acronym,
                research_area=research_area,
                sub_research_area=sub_research_area,
                project_type=project_type,
                flight_program=flight_program,
                license=license_val,
                doi=doi,
                catalog_url=catalog_url,
                metadata_api_url=metadata_api_url,
                version=raw_version,
                catalog_generated_utc=manifest_generated_utc,
                publication_count=pub_count,
                remote_total_files=remote_total_files,
                local_file_count=local_file_count,
                evaluation_decision_code=decision_code,
                evaluation_decision_label=decision_label,
                evaluation_scope_status=scope_status,
                evaluation_summary=evaluation_summary,
                limitations=limitations,
                support=CatalogSupportStatus(
                    catalogued=True,
                    reviewed=True,
                    queryable_in_core=queryable_in_core,
                    support_tier=support_tier,
                ),
                provenance=provenance,
                source_discrepancies=tuple(discrepancies),
            )
        )

    source_hashes = {
        manifest_rel: manifest_sha,
        csv_rel: csv_sha,
    }
    if cfi_resolved_rel and cfi_sha:
        source_hashes[cfi_resolved_rel] = cfi_sha

    return ResearchCatalog(
        entries=tuple(entries),
        manifest_generated_utc=manifest_generated_utc,
        manifest_scope=_clean_optional_str(manifest_payload.get("scope")),
        source_search_url=_clean_optional_str(manifest_payload.get("source_search_url")),
        core_investigation_ids=tuple(sorted(active_core_ids, key=_psi_numeric_id)),
        source_hashes=source_hashes,
    )


def _passes_filters(
    entry: CatalogEntry,
    *,
    project_type: str | None,
    sub_research_area: str | None,
    queryable_in_core: bool | None,
) -> bool:
    if project_type is not None:
        if not entry.project_type or entry.project_type.lower() != project_type.strip().lower():
            return False
    if sub_research_area is not None:
        if not entry.sub_research_area or entry.sub_research_area.lower() != sub_research_area.strip().lower():
            return False
    if queryable_in_core is not None and entry.support.queryable_in_core != queryable_in_core:
        return False
    return True


def _extract_explicit_psi_ids(query: str) -> set[str]:
    return {f"PSI-{m.group(1)}" for m in _PSI_IN_TEXT_RE.finditer(query.lower())}


def _score_entry_text(
    entry: CatalogEntry,
    *,
    raw_query: str,
    query_tokens: Sequence[str],
    explicit_psi_ids: set[str],
) -> tuple[float, dict[str, tuple[str, ...]], str] | None:
    """Compute explainable lexical match score and provenance of matched fields/terms."""
    norm_query = _normalize_compact_key(raw_query)
    score = 0.0
    field_matches: dict[str, tuple[str, ...]] = {}
    reason_parts: list[str] = []

    # 1. Exact PSI-ID match (never match bare 'psi' prefix across unrelated PSI-* entries)
    exact_psi_query = _normalize_psi_id_query(raw_query)
    if entry.psi_id == exact_psi_query or entry.psi_id in explicit_psi_ids:
        score += 100.0
        matched_id_tok = entry.psi_id.lower()
        field_matches["psi_id"] = (matched_id_tok,)
        reason_parts.append(f"exact psi_id match ('{matched_id_tok}', +100.0)")

    # 2. Exact normalized acronym match (distinguishes FLEX vs FLEX-2, SAME vs SAME-R)
    exact_acronym_matched = False
    if entry.acronym:
        variants = _acronym_variants(entry.acronym)
        if norm_query in variants:
            exact_acronym_matched = True
            score += 80.0
            field_matches["acronym"] = (norm_query,)
            reason_parts.append(f"exact acronym match ('{norm_query}', +80.0)")

    # Filter out bare 'psi' when the user wrote an explicit PSI-ID reference such as "PSI-69"
    numeric_id_parts = {pid.split("-")[1] for pid in explicit_psi_ids}
    filtered_tokens: list[str] = []
    for tok in query_tokens:
        if explicit_psi_ids and (tok == "psi" or tok in numeric_id_parts):
            continue
        if tok not in filtered_tokens:
            filtered_tokens.append(tok)

    # 3. Token matches across verified catalog metadata fields
    query_token_match_kind: dict[str, str] = {}
    for field_name in _SEARCHABLE_TEXT_FIELDS:
        if field_name == "acronym" and exact_acronym_matched:
            continue
        raw_val = getattr(entry, field_name)
        if not raw_val:
            continue
        field_tokens = tokenize_text(raw_val)
        if not field_tokens:
            continue
        field_token_set = set(field_tokens)
        weight = _FIELD_WEIGHTS[field_name]

        matched_for_field: list[str] = []
        variant_notes: list[str] = []
        field_score = 0.0
        for qtok in filtered_tokens:
            if qtok in field_token_set:
                if qtok not in matched_for_field:
                    matched_for_field.append(qtok)
                query_token_match_kind[qtok] = "exact"
                field_score += weight
            else:
                for alt in _EQUIV_VARIANTS.get(qtok, ()):
                    if alt in field_token_set:
                        if alt not in matched_for_field:
                            matched_for_field.append(alt)
                        if query_token_match_kind.get(qtok) != "exact":
                            query_token_match_kind[qtok] = "variant"
                        variant_notes.append(f"{qtok}->{alt}")
                        field_score += weight * 0.75
                        break

        if matched_for_field:
            score += field_score
            field_matches[field_name] = tuple(matched_for_field)
            note_suffix = f" [plural/singular: {', '.join(variant_notes)}]" if variant_notes else ""
            reason_parts.append(
                f"{field_name} matched {matched_for_field}{note_suffix} (+{round(field_score, 2)})"
            )

    if query_token_match_kind:
        coverage_bonus = sum(
            25.0 if kind == "exact" else 18.75 for kind in query_token_match_kind.values()
        )
        score += coverage_bonus
        reason_parts.append(
            f"distinct query-term coverage {len(query_token_match_kind)}/{len(filtered_tokens)} (+{round(coverage_bonus, 2)})"
        )

    if score <= 0.0 or not field_matches:
        return None

    ordered_fields = {f: field_matches[f] for f in _CANONICAL_FIELD_ORDER if f in field_matches}
    reason = (
        f"{'; '.join(reason_parts)} [total textual match score={round(score, 2)}; "
        "not a scientific importance or safety rating]."
    )
    return round(score, 4), ordered_fields, reason


def search_catalog(
    catalog: ResearchCatalog,
    query: str | None = None,
    *,
    project_type: str | None = None,
    sub_research_area: str | None = None,
    queryable_in_core: bool | None = None,
    top_k: int | None = None,
) -> CatalogSearchResult:
    """Search and filter the verified NASA PSI research catalog with explainable ranking."""
    if top_k is not None and (isinstance(top_k, bool) or not isinstance(top_k, int) or top_k <= 0):
        raise CatalogValidationError(f"top_k must be a positive integer when provided; got {top_k!r}.")
    if queryable_in_core is not None and not isinstance(queryable_in_core, bool):
        raise CatalogValidationError(f"queryable_in_core must be a boolean or None; got {queryable_in_core!r}.")
    for filter_name, filter_val in (("project_type", project_type), ("sub_research_area", sub_research_area)):
        if filter_val is not None and (not isinstance(filter_val, str) or not filter_val.strip()):
            raise CatalogValidationError(f"{filter_name} must be a non-empty string when provided.")

    cleaned_query: str | None = None
    query_tokens: list[str] = []
    explicit_psi_ids: set[str] = set()
    if query is not None:
        if not isinstance(query, str) or not query.strip():
            raise CatalogValidationError("Query string cannot be empty; pass query=None to browse with filters.")
        cleaned_query = query.strip()
        query_tokens = tokenize_text(cleaned_query)
        if not query_tokens:
            raise CatalogValidationError("Query contains no indexable alphanumeric terms.")
        explicit_psi_ids = _extract_explicit_psi_ids(cleaned_query)

    applied_filters = {
        "project_type": project_type.strip() if project_type else None,
        "sub_research_area": sub_research_area.strip() if sub_research_area else None,
        "queryable_in_core": queryable_in_core,
        "top_k": top_k,
    }

    candidates = [
        entry
        for entry in catalog.entries
        if _passes_filters(
            entry,
            project_type=project_type,
            sub_research_area=sub_research_area,
            queryable_in_core=queryable_in_core,
        )
    ]

    scored_items: list[tuple[float, CatalogEntry, dict[str, tuple[str, ...]], str]] = []
    if cleaned_query is None:
        for entry in candidates:
            scored_items.append(
                (
                    0.0,
                    entry,
                    {},
                    "Listed by active catalog filters without a keyword query (sorted deterministically by numeric PSI-ID).",
                )
            )
    else:
        for entry in candidates:
            scored = _score_entry_text(
                entry,
                raw_query=cleaned_query,
                query_tokens=query_tokens,
                explicit_psi_ids=explicit_psi_ids,
            )
            if scored is not None:
                score, field_matches, reason = scored
                scored_items.append((score, entry, field_matches, reason))

    if not scored_items:
        return CatalogSearchResult(
            status="NO_MATCH",
            query=cleaned_query,
            filters=applied_filters,
            total_catalog_studies=len(catalog.entries),
            total_matches=0,
            hits=(),
        )

    scored_items.sort(
        key=lambda item: (
            -round(item[0], 9),
            _psi_numeric_id(item[1].psi_id),
            item[1].psi_id,
        )
    )

    selected = scored_items[:top_k] if top_k is not None else scored_items
    hits: list[CatalogSearchHit] = []
    for rank_idx, (score, entry, field_matches, reason) in enumerate(selected, start=1):
        ordered_terms: list[str] = []
        for fname in _CANONICAL_FIELD_ORDER:
            for term in field_matches.get(fname, ()):
                if term not in ordered_terms:
                    ordered_terms.append(term)
        hits.append(
            CatalogSearchHit(
                rank=rank_idx,
                entry=entry,
                score=score,
                matched_fields=tuple(field_matches.keys()),
                matched_terms=tuple(ordered_terms),
                field_matches=field_matches,
                ranking_reason=reason,
            )
        )

    return CatalogSearchResult(
        status="OK",
        query=cleaned_query,
        filters=applied_filters,
        total_catalog_studies=len(catalog.entries),
        total_matches=len(scored_items),
        hits=tuple(hits),
    )

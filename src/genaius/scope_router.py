"""Deterministic scope router for /api/evidence and /api/answer (`scope='auto'`).

Separated NASA corpora are never pooled: PSI-25/PSI-69 Core, SAFFIRE IV–VI case study,
PSI-99 SAFFIRE-II cards and out-of-scope PSI-39/CFI. Ambiguous or cross-study questions get a
deterministic clarification/abstention instead of a silent Core fallback.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from .schemas.requests import CORE_ONLY_FIELDS, EvidenceRequestIn

_SAFFIRE_CASE_EXPLICIT_RE = re.compile(
    r"\b(?:saffire[\s\-–—]*(?:iv|v|vi|4|5|6)(?:[\s\-–—]*(?:1|2|3|4))?|"
    r"iv-1|v-[234]|vi-[234]|what did the fire do to the air|saffire\s*case)\b",
    re.IGNORECASE,
)
_SAFFIRE_CASE_CYGNUS_CONTEXT_RE = re.compile(
    r"\bsaffire\b.*\b(?:cygnus|fortenberry|smac|smoke\s+detector|calorimetr|pmma|ffd|344|cabin\s+air|co2|co\b|flow)\b|"
    r"\b(?:cygnus|fortenberry|ffd|344\s*s)\b.*\bsaffire\b",
    re.IGNORECASE,
)
_SAFFIRE_II_EXPLICIT_RE = re.compile(r"\b(?:saffire[\s\-–—]*(?:ii|2)|psi[\s\-–—]*99)\b", re.IGNORECASE)
_SAFFIRE_ANY_RE = re.compile(r"\bsaffire\b", re.IGNORECASE)
_BASS_CORE_RE = re.compile(r"\b(?:bass[\s\-–—]*(?:ii|2)|psi[\s\-–—]*25)\b", re.IGNORECASE)
_FLEX_CORE_RE = re.compile(r"\b(?:flex|flame extinguishment|psi[\s\-–—]*69)\b", re.IGNORECASE)
_CFI_OUT_RE = re.compile(r"\b(?:psi[\s\-–—]*39|cool flame investigation|\bcfi\b)\b", re.IGNORECASE)
_POOLING_VERBS_RE = re.compile(
    r"\b(?:pool|combine|merge|joint(?:ly)?|unify|all\s+(?:datasets|experiments|studies|tests)|birleştir|havuzla)\b",
    re.IGNORECASE,
)

# Positive domain vocabulary: context does not manufacture relevance for free text.
# This conservative lexical gate is not a semantic classifier: unknown wording asks
# for clarification instead of silently supplying the active prediction's numbers.
_DOMAIN_QUESTION_RE = re.compile(
    r"\b(?:psi[\s-]*\d+|nasa|ntrs|bass|flex|saffire|same(?:-r|-2)?|cfi|sofie|acme"
    r"|vi-[234]|iv-1|v-[234]|microgravity|combust\w*|flam\w*|burn\w*|droplet\w*"
    r"|extinct\w*|oxygen|o2|co|co2|nomex|pmma|kapton|teflon|pyrell|sibal|methanol|heptane"
    r"|decane|dodecane|smok\w*|aerosol\w*|ignit\w*|flammab\w*|calorim\w*"
    r"|pressure|ventilation|buoyancy|diffusion|radiometer|soot|suppression|detector\w*"
    r"|material\w*|fuel\w*|geometry|calibrat\w*|sensor\w*"
    r"|astronaut\w*|spacecraft|cygnus|space\s+(?:station|fire)|cool\s+flame"
    r"|carbon\s+(?:monoxide|dioxide)|heat\s+(?:release|flux)|co\s+(?:change|concentration|produce\w*)"
    r"|ridge|shapley|logit\w*|brier|roc|rmse|model\s+(?:estimate|predict\w*|results?|score)"
    r"|yangin\w*|yanma\w*|alev\w*|oksijen\w*|basinc\w*|damla\w*|sonme\w*|duman\w*"
    r"|mikrocekim\w*|mikrogravite\w*|uzay\w*|havalandirma\w*|tutus\w*|sondur\w*"
    r"|metanol\w*|heptan\w*|karbonmonoksit\w*|karbondioksit\w*|malzeme\w*|yakit\w*"
    r"|yanici\w*|geometri\w*|kalibrasyon\w*|sensor\w*)\b"
)
_CONTEXT_FOLLOWUP_RE = re.compile(
    r"(?:explain\s+(?:this|these|the)\s+(?:model\s+)?(?:results?|prediction|estimate|condition|score|numbers?)"
    r"|explain\s+(?:this|these)|why|why\s+(?:is\s+that|so)|what\s+does\s+(?:this|that)\s+mean"
    r"|bu\s+(?:sonuclari|sonucu|kosulu|tahmini|degerleri|sayilari)\s+acikla"
    r"|bunu\s+acikla|neden|bu\s+ne\s+demek)[.!?]*"
)


def _question_has_domain_support(req: EvidenceRequestIn) -> bool:
    query = (req.query or "").strip()
    if not query:
        return True  # Preserve explicit structured table/prediction API operations.
    folded = unicodedata.normalize("NFKD", query.lower().replace("ı", "i"))
    folded = " ".join("".join(c for c in folded if not unicodedata.combining(c)).split())
    if _DOMAIN_QUESTION_RE.search(folded):
        return True
    context_available = bool(req.flex_condition or req.numeric_filters or req.compare_record_pks)
    return bool(context_available and _CONTEXT_FOLLOWUP_RE.fullmatch(folded))

_DEFAULT_SCOPE_OPTIONS: tuple[dict[str, str], ...] = (
    {"scope": "saffire_case", "label": "SAFFIRE IV–VI Case Study", "action": "requery"},
    {"scope": "core", "label": "Core (PSI-25 + PSI-69)", "action": "requery"},
    {"scope": "psi99_cards", "label": "PSI-99 SAFFIRE-II Cards", "href": "data.html#s-saffire", "action": "link"},
)


def resolve_scope(
    req: EvidenceRequestIn,
) -> tuple[EvidenceRequestIn, dict[str, Any], dict[str, Any] | None]:
    """Deterministically resolve `scope='auto'` without pooling or bypassing core study isolation."""
    raw_scope = req.scope
    effective_requested = raw_scope or "core"

    if not _question_has_domain_support(req):
        explanation = (
            "This question could not be linked to the supported NASA combustion experiments. "
            "An active page or FLEX condition is not evidence that the question is relevant. "
            "Please name the experiment, material, measurement or result you want explained. "
            "No prediction, source citation or LLM answer was generated."
        )
        return req, {
            "requested_scope": effective_requested,
            "resolved_scope": "out_of_domain",
            "auto_routed": False,
            "reason": "The question has no recognized supported research topic or explicit contextual follow-up.",
            "scope_options": [],
        }, {
            "reason_code": "OUT_OF_DOMAIN_QUERY",
            "summary": "Please ask a NASA combustion research question or clarify the result you mean.",
            "explanation": explanation,
            "limitation": "Ask about NASA material tests, flame behavior, smoke detection or the active FLEX estimate.",
            "ui_label": "OUTSIDE NASA EVIDENCE SCOPE",
            "query": req.query or "",
        }

    if raw_scope != "auto":
        return req, {
            "requested_scope": effective_requested,
            "resolved_scope": effective_requested,
            "auto_routed": False,
            "reason": f"Explicit scope '{effective_requested}' selected.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }, None

    query = req.query or ""
    inv = req.investigation_id
    has_flex_cond = req.flex_condition is not None

    has_saffire_case = bool(_SAFFIRE_CASE_EXPLICIT_RE.search(query) or _SAFFIRE_CASE_CYGNUS_CONTEXT_RE.search(query))
    has_saffire_ii = bool(_SAFFIRE_II_EXPLICIT_RE.search(query))
    has_saffire_any = bool(has_saffire_case or has_saffire_ii or _SAFFIRE_ANY_RE.search(query))
    has_bass = bool(_BASS_CORE_RE.search(query))
    has_flex = bool(_FLEX_CORE_RE.search(query))
    has_cfi = bool(_CFI_OUT_RE.search(query) or inv == "PSI-39")

    # 1. Cross-study pooling across separated NASA studies is never silently merged.
    distinct_families = int(has_saffire_any) + int(has_bass) + int(has_flex) + int(has_cfi)
    pooling_requested = bool(_POOLING_VERBS_RE.search(query))
    if (has_saffire_any and (has_bass or has_flex or has_cfi)) or (
        pooling_requested and (distinct_families >= 2 or "all" in query.lower())
    ):
        explanation = (
            "Cross-study pooling is disabled: PSI-25 (BASS-II solid samples), PSI-69 (FLEX liquid droplets), "
            "PSI-99 (SAFFIRE-II 9 reference cards), and SAFFIRE IV–VI (7 spacecraft cabin-air tests) "
            "measure different hardware, geometries, and outcomes and are never merged into one denominator. "
            "Select one scope below to inspect verified records within its own boundary."
        )
        routing = {
            "requested_scope": "auto",
            "resolved_scope": "clarification",
            "auto_routed": False,
            "reason": "Multi-study pooling across separated NASA scopes is not permitted.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }
        return req, routing, {
            "reason_code": "CROSS_STUDY_POOLING_NOT_SUPPORTED",
            "summary": "Cross-study pooling withheld (CROSS_STUDY_POOLING_NOT_SUPPORTED).",
            "explanation": explanation,
            "limitation": "Run separate questions per NASA study (Core PSI-25/PSI-69 vs SAFFIRE IV–VI vs PSI-99 cards on Data Explorer).",
            "ui_label": "SEPARATE CORPORA — NOT POOLED",
            "query": query,
        }

    # 2. Out-of-scope PSI-39 / CFI still routes through core's strict V12 guardrail.
    if has_cfi:
        return req.model_copy(update={"scope": "core"}), {
            "requested_scope": "auto",
            "resolved_scope": "core",
            "auto_routed": True,
            "reason": "Matched out-of-scope study identifier (PSI-39 / CFI); enforced core V12 boundary.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }, None

    # 3. Unambiguous SAFFIRE IV–VI flight/test reference -> SAFFIRE IV–VI Case Study.
    if has_saffire_case and not has_saffire_ii:
        cleared = {name: EvidenceRequestIn.model_fields[name].get_default(call_default_factory=True)
                   for name in CORE_ONLY_FIELDS}
        return req.model_copy(update={**cleared, "scope": "saffire_case"}), {
            "requested_scope": "auto",
            "resolved_scope": "saffire_case",
            "auto_routed": True,
            "reason": "Matched explicit SAFFIRE IV–VI flight/test identifier in Auto mode.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }, None

    # 4. Explicit PSI-99 / SAFFIRE-II OR ambiguous bare "Saffire" -> clarify without silent core fallback or pooling.
    if has_saffire_ii and not has_saffire_case:
        explanation = (
            "SAFFIRE-II (PSI-99) is stored as a separate 9-test microgravity reference inventory on Data Explorer "
            "(data.html#s-saffire) and is not pooled into Core Q&A (PSI-25 + PSI-69). "
            "If you meant spacecraft cabin fire air chemistry and smoke detection (IV-1 through VI-4), switch to SAFFIRE IV–VI Case Study."
        )
        routing = {
            "requested_scope": "auto",
            "resolved_scope": "clarification",
            "auto_routed": False,
            "reason": "PSI-99 (SAFFIRE-II) reference cards are kept separate from Core Q&A and SAFFIRE IV–VI Case Study.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }
        return req, routing, {
            "reason_code": "SCOPE_CLARIFICATION_REQUIRED",
            "summary": "Scope selection required (PSI-99 SAFFIRE-II vs SAFFIRE IV–VI).",
            "explanation": explanation,
            "limitation": "Open Data Explorer (#s-saffire) for the 9 PSI-99 reference cards, or select SAFFIRE IV–VI Case Study for VI-3/IV–VI Q&A.",
            "ui_label": "SCOPE CLARIFICATION — SEPARATE CORPORA",
            "query": query,
        }

    if has_saffire_any:
        explanation = (
            "Ambiguous 'Saffire' query: GeNAIus hosts two unpooled Saffire sections — "
            "(1) SAFFIRE IV–VI Case Study (7 documented spacecraft tests IV-1 through VI-4 with cabin gas/detector Q&A), and "
            "(2) PSI-99 SAFFIRE-II (9 read-only reference cards on data.html#s-saffire). "
            "Choose the intended scope below instead of falling back to Core (PSI-25 + PSI-69)."
        )
        routing = {
            "requested_scope": "auto",
            "resolved_scope": "clarification",
            "auto_routed": False,
            "reason": "Bare 'Saffire' could refer to SAFFIRE IV–VI Case Study or PSI-99 SAFFIRE-II reference cards.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }
        return req, routing, {
            "reason_code": "SCOPE_CLARIFICATION_REQUIRED",
            "summary": "Scope selection required for 'Saffire' query (SCOPE_CLARIFICATION_REQUIRED).",
            "explanation": explanation,
            "limitation": "Select SAFFIRE IV–VI Case Study to query flight tests IV-1..VI-4, or open data.html#s-saffire for PSI-99 cards.",
            "ui_label": "SCOPE CLARIFICATION — NOT QUERIED IN CORE",
            "query": query,
        }

    # 5. Active FLEX condition without conflicting study -> flex_prediction.
    if has_flex_cond:
        return req.model_copy(update={"scope": "flex_prediction"}), {
            "requested_scope": "auto",
            "resolved_scope": "flex_prediction",
            "auto_routed": True,
            "reason": "Active FLEX Predictor condition attached to context.",
            "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
        }, None

    # 6. Default: Core search (PSI-25 + PSI-69), preserving active page context filters.
    return req.model_copy(update={"scope": "core"}), {
        "requested_scope": "auto",
        "resolved_scope": "core",
        "auto_routed": True,
        "reason": "Routed to Core verified corpus (PSI-25 BASS-II + PSI-69 FLEX).",
        "scope_options": list(_DEFAULT_SCOPE_OPTIONS),
    }, None

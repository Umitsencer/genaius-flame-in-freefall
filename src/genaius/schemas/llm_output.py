"""Canonical LLM answer model: one source for the validator, the provider JSON schema and the prompt.

`LLMAnswer` checks *shape* only (types, required keys, counts, lengths). Citation membership
in the current evidence bundle and numerical faithfulness are domain checks performed in
`genaius.answering.validation` and `genaius.numerical_audit`; Pydantic never verifies that an
answer is scientifically correct.
"""
from __future__ import annotations

import copy
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

MAX_SUMMARY_CHARS = 1200
MAX_FINDINGS_COUNT = 12
MAX_FINDING_TEXT_CHARS = 1000
MAX_CITATIONS_PER_FINDING = 25
MAX_LIMITATIONS_COUNT = 12
MAX_LIMITATION_CHARS = 500
RECOMMENDED_FINDINGS_COUNT = 4

_STRICT = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False, frozen=True)


def _bounded_text(max_chars: int) -> Any:
    # Length is measured after stripping, exactly as the stored answer text.
    return Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=max_chars)]


class LLMFinding(BaseModel):
    model_config = _STRICT

    text: _bounded_text(MAX_FINDING_TEXT_CHARS)
    citation_ids: Annotated[list[str], Field(max_length=MAX_CITATIONS_PER_FINDING)]


class LLMAnswer(BaseModel):
    model_config = _STRICT

    summary: _bounded_text(MAX_SUMMARY_CHARS)
    findings: Annotated[list[LLMFinding], Field(min_length=1, max_length=MAX_FINDINGS_COUNT)]
    # Optional for the validator (providers without structured outputs may omit it);
    # the provider schema below still asks for it explicitly.
    limitations: Annotated[list[_bounded_text(MAX_LIMITATION_CHARS)], Field(max_length=MAX_LIMITATIONS_COUNT)] = []


ALLOWED_ANSWER_ROOT_KEYS: tuple[str, ...] = tuple(LLMAnswer.model_fields)
ALLOWED_FINDING_KEYS: tuple[str, ...] = tuple(LLMFinding.model_fields)

# Keywords many structured-output providers reject; limits are still enforced by `LLMAnswer`
# and stated in the prompt, both derived from the same constants above.
_PROVIDER_UNSUPPORTED_KEYWORDS = frozenset({"title", "default", "minLength", "maxLength", "minItems", "maxItems"})


def _strip_keywords(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_keywords(v) for k, v in node.items() if k not in _PROVIDER_UNSUPPORTED_KEYWORDS}
    if isinstance(node, list):
        return [_strip_keywords(v) for v in node]
    return node


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            return _inline_refs(copy.deepcopy(defs[node["$ref"].rsplit("/", 1)[-1]]), defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def _require_all_properties(node: Any) -> Any:
    # OpenAI-style strict structured outputs require every property to be listed as required.
    if isinstance(node, dict):
        out = {k: _require_all_properties(v) for k, v in node.items()}
        if out.get("type") == "object" and "properties" in out:
            out["required"] = list(out["properties"])
            out["additionalProperties"] = False
        return out
    if isinstance(node, list):
        return [_require_all_properties(v) for v in node]
    return node


def provider_json_schema() -> dict[str, Any]:
    """`response_format.json_schema` payload generated from `LLMAnswer`."""
    raw = LLMAnswer.model_json_schema()
    schema = _require_all_properties(_strip_keywords(_inline_refs(raw, raw.get("$defs", {}))))
    return {"name": "grounded_psi_answer", "strict": True, "schema": schema}


def prompt_contract_lines(*, has_citations: bool) -> list[str]:
    """Human-readable output contract for the system prompt (same limits as the model)."""
    return [
        f"- Allowed root keys ONLY (additionalProperties=false): {list(ALLOWED_ANSWER_ROOT_KEYS)}",
        f"- summary (required): non-empty plain string, 1..{MAX_SUMMARY_CHARS} chars (keep concise: 1-2 sentences directly answering USER_QUESTION).",
        f"- findings (required): non-empty JSON array of 1..{MAX_FINDINGS_COUNT} objects (prefer <= {RECOMMENDED_FINDINGS_COUNT} concise findings). Each finding object may contain ONLY {list(ALLOWED_FINDING_KEYS)}:",
        f"  * text (required): non-empty string, 1..{MAX_FINDING_TEXT_CHARS} chars.",
        (
            f"  * citation_ids (required): non-empty array of 1..{MAX_CITATIONS_PER_FINDING} exact strings copied verbatim from allowed_citation_ids (never empty, never raw titles/NTRS numbers)."
            if has_citations
            else "  * citation_ids (required): JSON array [] (no citable items exist in this summary-only bundle)."
        ),
        f"- limitations (always include; may be []): JSON array of 0..{MAX_LIMITATIONS_COUNT} plain strings (NOT objects), each 1..{MAX_LIMITATION_CHARS} chars (keep 1-2 concise limits relevant to USER_QUESTION).",
    ]

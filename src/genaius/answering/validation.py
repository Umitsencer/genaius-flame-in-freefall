"""LLM adapter output validation: Pydantic shape check + domain citation allowlist.

Shape (types, required/unknown keys, counts, lengths) comes from the canonical
`genaius.schemas.llm_output.LLMAnswer` model. Citation membership in the *current* bundle is a
domain rule checked here. Neither proves semantic faithfulness or zero hallucination.
Diagnostics carry codes, JSON paths and sizes only — never raw model text or prompt content.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import ValidationError

from ..schemas.llm_output import ALLOWED_ANSWER_ROOT_KEYS, ALLOWED_FINDING_KEYS, LLMAnswer
from .models import (
    OUT_DIAG_DISALLOWED_CITATION,
    OUT_DIAG_EMPTY_CITATIONS,
    OUT_DIAG_INVALID_JSON,
    OUT_DIAG_LIMIT_EXCEEDED,
    OUT_DIAG_MISSING_FIELD,
    OUT_DIAG_UNEXPECTED_KEY,
    OUT_DIAG_WRONG_TYPE,
    AdapterOutputValidationError,
    AnswerFinding,
)

_FIELD_ORDER = {
    **{name: i for i, name in enumerate(ALLOWED_ANSWER_ROOT_KEYS)},
    **{name: i for i, name in enumerate(ALLOWED_FINDING_KEYS)},
}
_CONTAINER_ERRORS = {"extra_forbidden": 0, "missing": 1}


def _safe_observed_token(value: Any, *, max_len: int = 48) -> str:
    """Format a bounded, secret-safe identifier or type preview for diagnostics."""
    txt = str(value or "")
    txt = re.sub(r"(sk-or-[A-Za-z0-9_\-]+|Bearer\s+[A-Za-z0-9._\-]+)", "[REDACTED]", txt, flags=re.IGNORECASE)
    if len(txt) > max_len:
        return txt[:max_len] + "..."
    return txt


def _reject_nonfinite_constant(token: str) -> Any:
    raise AdapterOutputValidationError(
        f"Non-finite JSON constant is not allowed: {token!r}",
        diagnosis_code=OUT_DIAG_INVALID_JSON,
        field_path="$",
        expected="finite JSON number",
        observed=_safe_observed_token(token),
    )


def _strip_single_json_fence(raw_text: str) -> str:
    stripped = raw_text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if len(lines) < 3:
        return stripped
    opening = lines[0].strip().lower()
    closing = lines[-1].strip()
    if opening not in {"```", "```json"} or closing != "```":
        return stripped
    return "\n".join(lines[1:-1]).strip()


def _json_path(loc: Sequence[str | int]) -> str:
    return "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}" for p in loc)


def _sort_key(err: Mapping[str, Any]) -> tuple[Any, ...]:
    # Report the first error in document order; unknown/missing keys of a container come
    # before errors inside that container (same precedence as the former hand-written checks).
    loc = tuple(err["loc"])
    rank = _CONTAINER_ERRORS.get(err["type"])
    container = loc[:-1] if rank is not None else loc
    ordinal = tuple(p if isinstance(p, int) else _FIELD_ORDER.get(p, 99) for p in container)
    return (ordinal, rank if rank is not None else 2)


def _to_diagnostic(err: Mapping[str, Any]) -> AdapterOutputValidationError:
    loc = tuple(err["loc"])
    kind = err["type"]
    path = _json_path(loc)
    if kind == "extra_forbidden":
        container = _json_path(loc[:-1])
        allowed = ALLOWED_ANSWER_ROOT_KEYS if len(loc) == 1 else ALLOWED_FINDING_KEYS
        return AdapterOutputValidationError(
            f"Unexpected key in adapter output at {container}.",
            diagnosis_code=OUT_DIAG_UNEXPECTED_KEY,
            field_path=container,
            expected=f"keys subset of {list(allowed)}",
            observed="unexpected key",
        )
    if kind == "missing":
        return AdapterOutputValidationError(
            f"Missing required field {path}.",
            diagnosis_code=OUT_DIAG_MISSING_FIELD,
            field_path=path,
            expected=f"present key '{loc[-1]}'",
            observed="missing key",
        )
    ctx = err.get("ctx") or {}
    if kind in {"string_too_short", "string_too_long", "too_short", "too_long"}:
        lo = ctx.get("min_length", 0)
        hi = ctx.get("max_length", "")
        unit = "chars" if kind.startswith("string_") else "items"
        return AdapterOutputValidationError(
            f"{path} must be {lo}..{hi} {unit}.",
            diagnosis_code=OUT_DIAG_LIMIT_EXCEEDED,
            field_path=path,
            expected=f"{lo}..{hi} {unit}",
            observed=f"{ctx.get('actual_length', 'out-of-range')} {unit}",
        )
    expected = {"string_type": "string", "list_type": "list", "model_type": "object",
                "model_attributes_type": "object"}.get(kind, kind)
    return AdapterOutputValidationError(
        f"{path} has the wrong type (expected {expected}).",
        diagnosis_code=OUT_DIAG_WRONG_TYPE,
        field_path=path,
        expected=expected,
        observed="wrong type",
    )


def _parse_raw(raw_output: str | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(raw_output, str):
        stripped = _strip_single_json_fence(raw_output)
        if not stripped:
            raise AdapterOutputValidationError(
                "Adapter returned an empty response string.",
                diagnosis_code=OUT_DIAG_INVALID_JSON,
                field_path="$",
                expected="non-empty JSON object string",
                observed="0 chars",
            )
        try:
            parsed = json.loads(stripped, parse_constant=_reject_nonfinite_constant)
        except json.JSONDecodeError as exc:
            raise AdapterOutputValidationError(
                f"Adapter response is not valid JSON (line {exc.lineno}, col {exc.colno}).",
                diagnosis_code=OUT_DIAG_INVALID_JSON,
                field_path="$",
                expected="valid JSON object",
                observed=f"JSONDecodeError at line {exc.lineno} col {exc.colno}",
            ) from exc
    elif isinstance(raw_output, Mapping):
        parsed = dict(raw_output)
    else:
        raise AdapterOutputValidationError(
            f"Adapter output must be a JSON string or mapping (got {type(raw_output).__name__}).",
            diagnosis_code=OUT_DIAG_WRONG_TYPE,
            field_path="$",
            expected="JSON string or object mapping",
            observed=type(raw_output).__name__,
        )
    if not isinstance(parsed, dict):
        raise AdapterOutputValidationError(
            f"Adapter JSON root must be an object (got {type(parsed).__name__}).",
            diagnosis_code=OUT_DIAG_WRONG_TYPE,
            field_path="$",
            expected="object",
            observed=type(parsed).__name__,
        )
    return parsed


def validate_llm_adapter_output(
    raw_output: str | Mapping[str, Any],
    *,
    allowed_citation_ids: Sequence[str],
) -> tuple[str, tuple[AnswerFinding, ...], tuple[str, ...]]:
    """Validate adapter output against `LLMAnswer` and the bundle's allowed citation IDs."""
    parsed = _parse_raw(raw_output)
    try:
        answer = LLMAnswer.model_validate(parsed)
    except ValidationError as exc:
        first = min(exc.errors(include_input=False, include_url=False), key=_sort_key)
        raise _to_diagnostic(first) from None

    allowed_set = set(allowed_citation_ids)
    require_cits = bool(allowed_set)
    findings: list[AnswerFinding] = []
    for idx, item in enumerate(answer.findings):
        item_path = f"$.findings[{idx}].citation_ids"
        if require_cits and not item.citation_ids:
            raise AdapterOutputValidationError(
                f"{item_path} must include at least one allowed citation_id.",
                diagnosis_code=OUT_DIAG_EMPTY_CITATIONS,
                field_path=item_path,
                expected=">= 1 citation_id from allowed_citation_ids",
                observed="0 items",
            )
        clean_cids: list[str] = []
        for cidx, cid in enumerate(item.citation_ids):
            cit_path = f"{item_path}[{cidx}]"
            if not cid.strip():
                raise AdapterOutputValidationError(
                    f"{cit_path} must not be empty.",
                    diagnosis_code=OUT_DIAG_EMPTY_CITATIONS,
                    field_path=cit_path,
                    expected="non-empty citation_id string",
                    observed="empty string",
                )
            if cid not in allowed_set:
                raise AdapterOutputValidationError(
                    f"{cit_path} is not in allowed_citation_ids ({len(cid)} chars)",
                    diagnosis_code=OUT_DIAG_DISALLOWED_CITATION,
                    field_path=cit_path,
                    expected=f"member of allowed_citation_ids ({len(allowed_set)} ids)",
                    observed=f"unlisted citation_id ({len(cid)} chars)",
                )
            if cid not in clean_cids:
                clean_cids.append(cid)
        findings.append(AnswerFinding(text=item.text, citation_ids=tuple(clean_cids)))
    return answer.summary, tuple(findings), tuple(answer.limitations)

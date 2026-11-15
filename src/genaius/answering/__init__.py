"""Grounded answer synthesis with a strictly bounded, provider-agnostic LLM adapter.

Reuses `EvidenceBundle.to_llm_payload()` without duplicating table calculations or BM25
retrieval. Deterministic evidence-backed answers work offline (`answer_mode="deterministic"`);
an injected `GroundedLLMAdapter` gets bounded input, Pydantic-validated structured output,
citation-allowlist and numerical checks, and a safe deterministic fallback.

Modules: `models` (types/errors), `deterministic` (evidence-only composition),
`adapter_input` (bounded payload), `validation` (output checks), `pipeline` (orchestration).
Structural/citation validation does NOT verify semantic correctness or prove zero hallucination.
"""

from ..schemas.llm_output import (
    ALLOWED_ANSWER_ROOT_KEYS,
    ALLOWED_FINDING_KEYS,
    MAX_CITATIONS_PER_FINDING,
    MAX_FINDING_TEXT_CHARS,
    MAX_FINDINGS_COUNT,
    MAX_LIMITATION_CHARS,
    MAX_LIMITATIONS_COUNT,
    MAX_SUMMARY_CHARS,
    RECOMMENDED_FINDINGS_COUNT,
)
from .adapter_input import (
    DEFAULT_MAX_ADAPTER_PASSAGE_CHARS,
    DEFAULT_MAX_ADAPTER_PASSAGES,
    DEFAULT_MAX_ADAPTER_PAYLOAD_CHARS,
    DEFAULT_MAX_ADAPTER_TABLE_ROWS,
    SYSTEM_GENERATION_RULES,
    build_bounded_adapter_input,
)
from .models import (
    OUT_DIAG_DISALLOWED_CITATION,
    OUT_DIAG_EMPTY_CITATIONS,
    OUT_DIAG_INVALID_JSON,
    OUT_DIAG_LIMIT_EXCEEDED,
    OUT_DIAG_MISSING_FIELD,
    OUT_DIAG_UNEXPECTED_KEY,
    OUT_DIAG_WRONG_TYPE,
    AdapterInputBudgetError,
    AdapterOutputValidationError,
    AdapterPromptInput,
    AnswerFinding,
    GroundedAnswer,
    GroundedLLMAdapter,
    SourceReference,
)
from .pipeline import generate_grounded_answer
from .validation import validate_llm_adapter_output

__all__ = [
    "ALLOWED_ANSWER_ROOT_KEYS",
    "ALLOWED_FINDING_KEYS",
    "AdapterInputBudgetError",
    "AdapterOutputValidationError",
    "AdapterPromptInput",
    "AnswerFinding",
    "DEFAULT_MAX_ADAPTER_PASSAGES",
    "DEFAULT_MAX_ADAPTER_PASSAGE_CHARS",
    "DEFAULT_MAX_ADAPTER_PAYLOAD_CHARS",
    "DEFAULT_MAX_ADAPTER_TABLE_ROWS",
    "GroundedAnswer",
    "GroundedLLMAdapter",
    "MAX_CITATIONS_PER_FINDING",
    "MAX_FINDINGS_COUNT",
    "MAX_FINDING_TEXT_CHARS",
    "MAX_LIMITATIONS_COUNT",
    "MAX_LIMITATION_CHARS",
    "MAX_SUMMARY_CHARS",
    "OUT_DIAG_DISALLOWED_CITATION",
    "OUT_DIAG_EMPTY_CITATIONS",
    "OUT_DIAG_INVALID_JSON",
    "OUT_DIAG_LIMIT_EXCEEDED",
    "OUT_DIAG_MISSING_FIELD",
    "OUT_DIAG_UNEXPECTED_KEY",
    "OUT_DIAG_WRONG_TYPE",
    "RECOMMENDED_FINDINGS_COUNT",
    "SYSTEM_GENERATION_RULES",
    "SourceReference",
    "build_bounded_adapter_input",
    "generate_grounded_answer",
    "validate_llm_adapter_output",
]

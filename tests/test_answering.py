"""Tests for the grounded answering layer and provider-agnostic LLM adapter boundary.

All adapters used in this file are synthetic test doubles verifying schema,
citation, bounds, and fallback contracts; passing these tests is NOT an
evaluation of external LLM scientific accuracy or model quality.
"""

from __future__ import annotations

import json
import unittest
from unittest import mock
from pathlib import Path

from genaius.answering import (
    AdapterInputBudgetError,
    AdapterOutputValidationError,
    AdapterPromptInput,
    MAX_FINDINGS_COUNT,
    MAX_SUMMARY_CHARS,
    OUT_DIAG_DISALLOWED_CITATION,
    OUT_DIAG_EMPTY_CITATIONS,
    OUT_DIAG_INVALID_JSON,
    OUT_DIAG_LIMIT_EXCEEDED,
    OUT_DIAG_MISSING_FIELD,
    OUT_DIAG_UNEXPECTED_KEY,
    OUT_DIAG_WRONG_TYPE,
    build_bounded_adapter_input,
    generate_grounded_answer,
    validate_llm_adapter_output,
)
from genaius.data.contracts import (
    DATASET_SPECS,
    ExperimentRecord,
    POSITION_DEFINITION,
    SourceLocation,
    TypedMeasurement,
)
from genaius.data.loader import parse_measurement_value
from genaius.data.query import NumericRangeFilter
from genaius.retrieval.bm25 import build_bm25_index
from genaius.service import EvidenceRequest, EvidenceService, load_processed_chunks

REPO_ROOT = Path(__file__).resolve().parents[1]


def _make_record(
    *,
    investigation_id: str,
    test_id: str,
    csv_index: int,
    fuel_raw: str,
    raw_values: dict[str, str],
    flex_identifier: str | None = None,
    test_end: str | None = None,
) -> ExperimentRecord:
    spec = DATASET_SPECS[investigation_id]
    contracts = {fc.field_name: fc for fc in spec.field_contracts}
    measurements = {
        fname: parse_measurement_value(raw_values.get(fname, ""), contract)
        for fname, contract in contracts.items()
    }
    norm_fields: dict[str, object] = {
        "fuel_raw": fuel_raw,
        "fuel_norm": " ".join(fuel_raw.split()),
    }
    if test_end is not None:
        norm_fields["test_end"] = test_end
    return ExperimentRecord(
        record_pk=f"{investigation_id}:{test_id}",
        investigation_id=investigation_id,
        test_id=test_id,
        sample_id=None,
        flex_identifier=flex_identifier,
        source=SourceLocation(
            source_relpath=spec.relative_path,
            source_sha256="c" * 64,
            encoding=spec.encoding,
            csv_record_index=csv_index,
            physical_line_start=csv_index + 1,
            physical_line_end=csv_index + 1,
            position_definition=POSITION_DEFINITION,
        ),
        raw_fields={"Fuel": fuel_raw, **raw_values},
        normalized_fields=norm_fields,
        measurements=measurements,
        quality_flags=(),
    )


class _RecordingAdapter:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.inputs: list[AdapterPromptInput] = []

    def generate(self, adapter_input: AdapterPromptInput):
        self.inputs.append(adapter_input)
        if self.exc is not None:
            raise self.exc
        if callable(self.response):
            return self.response(adapter_input)
        return self.response


class GroundedAnsweringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.chunks = load_processed_chunks(REPO_ROOT)
        cls.bm25_index = build_bm25_index(cls.chunks)
        cls.records = (
            _make_record(
                investigation_id="PSI-69",
                test_id="10",
                csv_index=10,
                fuel_raw="Methanol",
                flex_identifier="193F001",
                test_end="Extinction",
                raw_values={
                    "ambient_pressure_kpa": "2319",
                    "burning_rate_mm2_s": "0.37",
                },
            ),
            _make_record(
                investigation_id="PSI-69",
                test_id="11",
                csv_index=11,
                fuel_raw="Methanol",
                flex_identifier="193F002",
                test_end="Extinction",
                raw_values={
                    "ambient_pressure_kpa": "2318",
                    "burning_rate_mm2_s": "0.40",
                },
            ),
            _make_record(
                investigation_id="PSI-69",
                test_id="12",
                csv_index=12,
                fuel_raw="Heptane",
                flex_identifier="193F003",
                test_end="Disruption",
                raw_values={
                    "ambient_pressure_kpa": "2320",
                    "burning_rate_mm2_s": "",
                },
            ),
        )
        cls.service = EvidenceService(records=cls.records, bm25_index=cls.bm25_index)

    def test_deterministic_combined_summary_preserves_units_and_subset_counts(self) -> None:
        bundle = self.service.query(
            EvidenceRequest(
                query="PSI-69 burning rate high pressure",
                numeric_filters=(
                    NumericRangeFilter(field_name="ambient_pressure_kpa", unit="mmHg", min_value=2200.0),
                ),
                summarize_field_name="burning_rate_mm2_s",
                summarize_unit="mm²/s",
                compare_record_pks=("PSI-69:10", "PSI-69:11"),
                max_table_citations=1,
                top_k=2,
            )
        )
        answer = generate_grounded_answer(bundle)
        self.assertEqual(answer.status, "OK")
        self.assertEqual(answer.answer_mode, "deterministic")
        self.assertFalse(answer.llm_used)
        self.assertEqual(answer.evidence_overview["table_total_runs"], 3)
        self.assertEqual(answer.evidence_overview["table_shown_runs"], 2)
        self.assertIn("0.385", answer.summary)
        self.assertIn("mm²/s", answer.summary)
        self.assertTrue(any("2 of 3" in item.text for item in answer.findings))
        self.assertTrue(any("missing=1" in item.text for item in answer.findings))
        self.assertTrue(any("first 2 of 3 matching runs" in lim for lim in answer.limitations))
        self.assertTrue(all(cid in answer.citation_ids for f in answer.findings for cid in f.citation_ids))
        doc_sources = [s for s in answer.sources if s.source_type == "document_chunk"]
        self.assertTrue(doc_sources and all(s.source_url and s.source_url.startswith("https://") for s in doc_sources))

    def test_deterministic_document_fallback_presents_excerpts_without_synthesized_claim(self) -> None:
        bundle = self.service.query(
            EvidenceRequest(
                query="How does FLEX identify cool flames in NASA TP?",
                investigation_id="PSI-69",
                top_k=2,
            )
        )
        answer = generate_grounded_answer(bundle)
        self.assertEqual(answer.status, "OK")
        self.assertEqual(answer.answer_mode, "deterministic")
        self.assertFalse(answer.llm_used)
        self.assertEqual(answer.evidence_overview["table_total_runs"], 0)
        self.assertEqual(len(answer.findings), 2)
        for item in answer.findings:
            self.assertIn("Related source passage", item.text)
            self.assertEqual(len(item.citation_ids), 1)
            self.assertTrue(item.citation_ids[0].startswith("DOC:"))
        self.assertTrue(any("excerpts rather than verified scientific answers" in lim for lim in answer.limitations))

    def test_corpus_unavailable_flags_gap_without_hallucinating_text(self) -> None:
        table_only = EvidenceService(records=self.records, bm25_index=None)
        bundle = table_only.query(
            EvidenceRequest(query="burning rate", investigation_id="PSI-69", fuel="Methanol")
        )
        answer = generate_grounded_answer(bundle)
        self.assertEqual(answer.status, "OK")
        self.assertEqual(answer.answer_mode, "deterministic")
        self.assertFalse(answer.llm_used)
        self.assertTrue(any(w.startswith("corpus_unavailable:") for w in answer.warnings))
        self.assertTrue(any("not filled from model memory" in lim for lim in answer.limitations))

    def test_bounded_adapter_input_enforces_limits_and_records_truncation(self) -> None:
        bundle = self.service.query(
            EvidenceRequest(
                query="How does FLEX identify cool flames in NASA TP?",
                investigation_id="PSI-69",
                fuel="Methanol",
                top_k=3,
            )
        )
        adapter_input = build_bounded_adapter_input(
            bundle,
            max_table_rows=1,
            max_passages=2,
            max_chars_per_passage=80,
            max_payload_chars=2400,
        )
        self.assertTrue(adapter_input.truncated)
        self.assertTrue(adapter_input.truncation_notes)
        self.assertEqual(adapter_input.user_query, "How does FLEX identify cool flames in NASA TP?")
        self.assertIn("untrusted data", " ".join(adapter_input.system_rules))
        serialized = json.dumps(adapter_input.to_dict(), ensure_ascii=False, allow_nan=False)
        self.assertNotIn("OPENAI_API_KEY", serialized)
        self.assertLessEqual(len(adapter_input.evidence_payload["document_passages"]), 2)

    def test_valid_synthetic_adapter_produces_llm_mode_and_validates_citations(self) -> None:
        bundle = self.service.query(
            EvidenceRequest(
                query="How does FLEX identify cool flames in NASA TP?",
                investigation_id="PSI-69",
                top_k=2,
            )
        )

        def _valid_reply(inp: AdapterPromptInput) -> str:
            return json.dumps(
                {
                    "summary": "Two FLEX report excerpts discuss cool-flame observations in NASA/TP-2015-216046.",
                    "findings": [
                        {
                            "text": "Test FLEX-129 and Test FLEX-130 captions describe post-extinction cool-flame remarks.",
                            "citation_ids": [inp.allowed_citation_ids[0]],
                        }
                    ],
                    "limitations": ["Passage captions describe specific runs rather than an automatic classifier."],
                }
            )

        adapter = _RecordingAdapter(response=_valid_reply)
        answer = generate_grounded_answer(bundle, llm_adapter=adapter)
        self.assertEqual(len(adapter.inputs), 1)
        self.assertEqual(answer.status, "OK")
        self.assertEqual(answer.answer_mode, "llm")
        self.assertTrue(answer.llm_used)
        self.assertEqual(len(answer.findings), 1)
        self.assertEqual(answer.findings[0].citation_ids, (adapter.inputs[0].allowed_citation_ids[0],))

    def test_unknown_citation_malformed_output_and_exception_trigger_safe_fallback(self) -> None:
        bundle = self.service.query(
            EvidenceRequest(
                query="How does FLEX identify cool flames in NASA TP?",
                investigation_id="PSI-69",
                top_k=2,
            )
        )
        allowed = [c.citation_id for c in bundle.citations]

        # Direct validator checks: unknown citation, invalid JSON, NaN, extra root key
        with self.assertRaises(AdapterOutputValidationError):
            validate_llm_adapter_output(
                json.dumps(
                    {
                        "summary": "Claim",
                        "findings": [{"text": "Invented citation", "citation_ids": ["DOC:FAKE:0000"]}],
                        "limitations": [],
                    }
                ),
                allowed_citation_ids=allowed,
            )
        for bad_raw in ("", "{bad json", '{"summary":"x","findings":[{"text":"y","citation_ids":[]}]}', '{"summary":NaN}'):
            with self.assertRaises(AdapterOutputValidationError):
                validate_llm_adapter_output(bad_raw, allowed_citation_ids=allowed)

        # Fallback preserves deterministic output and hides secrets/exception strings
        for bad_adapter in (
            _RecordingAdapter(
                response=json.dumps(
                    {
                        "summary": "Claim",
                        "findings": [{"text": "Bad cite", "citation_ids": ["TBL:FAKE:999"]}],
                    }
                )
            ),
            _RecordingAdapter(response="{not valid json"),
            _RecordingAdapter(exc=RuntimeError("SECRET_TOKEN_XYZ system_rules_leak")),
        ):
            fallback = generate_grounded_answer(bundle, llm_adapter=bad_adapter)
            self.assertEqual(fallback.status, "OK")
            self.assertEqual(fallback.answer_mode, "deterministic_fallback")
            self.assertFalse(fallback.llm_used)
            self.assertTrue(any(w.startswith("llm_fallback:") for w in fallback.warnings))
            joined = " ".join([fallback.summary, *fallback.limitations, *fallback.warnings])
            self.assertNotIn("SECRET_TOKEN_XYZ", joined)
            self.assertNotIn("system_rules_leak", joined)

    def test_abstained_and_no_evidence_never_invoke_adapter(self) -> None:
        adapter = _RecordingAdapter(
            response='{"summary":"should never run","findings":[{"text":"x","citation_ids":[]}]}'
        )
        v10_bundle = self.service.query(
            EvidenceRequest(
                query="Classify droplets with d_ext < 1 mm as cool flames",
                investigation_id="PSI-69",
            )
        )
        empty_bundle = self.service.query(
            EvidenceRequest(query="xyznonexistenttoken98765", fuel="NoSuchFuel")
        )

        v10_ans = generate_grounded_answer(v10_bundle, llm_adapter=adapter)
        empty_ans = generate_grounded_answer(empty_bundle, llm_adapter=adapter)

        self.assertEqual(len(adapter.inputs), 0)
        self.assertEqual(v10_ans.status, "ABSTAINED")
        self.assertEqual(v10_ans.answer_mode, "deterministic")
        self.assertFalse(v10_ans.llm_used)
        self.assertEqual(v10_ans.findings, ())
        self.assertEqual(empty_ans.status, "NO_EVIDENCE")
        self.assertEqual(empty_ans.answer_mode, "deterministic")
        self.assertFalse(empty_ans.llm_used)

    def test_bounded_payload_syncs_allowed_citations_and_falls_back_on_impossible_budget(self) -> None:
        rec1 = _make_record(
            investigation_id="PSI-69",
            test_id="10",
            csv_index=10,
            fuel_raw="n-Decane",
            raw_values={"burning_rate_mm2_s": "0.41"},
        )
        rec2 = _make_record(
            investigation_id="PSI-69",
            test_id="11",
            csv_index=11,
            fuel_raw="n-Decane",
            raw_values={"burning_rate_mm2_s": "0.44"},
        )
        svc = EvidenceService(
            records=(rec1, rec2),
            bm25_index=self.bm25_index,
        )
        bundle = svc.query(
            EvidenceRequest(
                query="n-Decane cool flame",
                investigation_id="PSI-69",
                fuel="n-Decane",
                run_table_query=True,
                top_k=2,
            )
        )
        bounded = build_bounded_adapter_input(bundle, max_payload_chars=1800)
        self.assertLessEqual(
            len(json.dumps(bounded.evidence_payload, ensure_ascii=True, separators=(",", ":"))),
            1800,
        )
        kept_row_pks = {
            row["record_pk"]
            for row in (bounded.evidence_payload.get("table_summary") or {}).get("matched_rows", [])
        }
        kept_chunks = {p["chunk_id"] for p in bounded.evidence_payload.get("document_passages", [])}
        expected_allowed = {f"TBL:{pk}" for pk in kept_row_pks} | {f"DOC:{cid}" for cid in kept_chunks}
        self.assertTrue(set(bounded.allowed_citation_ids).issubset(expected_allowed))
        self.assertEqual(set(bounded.allowed_citation_ids), expected_allowed)

        # If a cropped citation ID is echoed by an LLM, validation must reject it.
        cropped = {c.citation_id for c in bundle.citations} - set(bounded.allowed_citation_ids)
        if cropped:
            bad_cite = next(iter(cropped))
            with self.assertRaises(AdapterOutputValidationError):
                validate_llm_adapter_output(
                    json.dumps(
                        {
                            "summary": "Uses cropped citation.",
                            "findings": [{"text": "Claim", "citation_ids": [bad_cite]}],
                            "limitations": [],
                        }
                    ),
                    allowed_citation_ids=bounded.allowed_citation_ids,
                )

        # An impossibly small payload budget raises AdapterInputBudgetError directly,
        # and generate_grounded_answer must catch it cleanly as deterministic_fallback.
        with self.assertRaises(AdapterInputBudgetError):
            build_bounded_adapter_input(bundle, max_payload_chars=40)

        adapter = _RecordingAdapter(response='{"summary":"never","findings":[]}')
        with mock.patch(
            "genaius.answering.pipeline.build_bounded_adapter_input",
            side_effect=AdapterInputBudgetError("Payload exceeds tiny test cap."),
        ):
            fallback = generate_grounded_answer(bundle, llm_adapter=adapter)
        self.assertEqual(len(adapter.inputs), 0)
        self.assertEqual(fallback.status, "OK")
        self.assertEqual(fallback.answer_mode, "deterministic_fallback")
        self.assertFalse(fallback.llm_used)
        self.assertTrue(any(w.startswith("llm_fallback:") for w in fallback.warnings))

    def test_fenced_json_block_is_parsed_strictly_while_prose_is_rejected(self) -> None:
        bundle = self.service.query(
            EvidenceRequest(query="Heptane cool flame", investigation_id="PSI-69", top_k=2)
        )
        allowed = [c.citation_id for c in bundle.citations]
        doc_cid = next(c for c in allowed if c.startswith("DOC:"))
        fenced = (
            "```json\n"
            + json.dumps(
                {
                    "summary": "Cool flame behavior is reported in the retrieved passage.",
                    "findings": [{"text": "Retrieved FLEX passage discusses extinction.", "citation_ids": [doc_cid]}],
                    "limitations": ["Single excerpt check."],
                }
            )
            + "\n```"
        )
        summary, findings, _ = validate_llm_adapter_output(fenced, allowed_citation_ids=allowed)
        self.assertIn("Cool flame", summary)
        self.assertEqual(findings[0].citation_ids, (doc_cid,))

        with self.assertRaises(AdapterOutputValidationError):
            validate_llm_adapter_output(f"Here is JSON:\n{fenced}", allowed_citation_ids=allowed)

    def test_abstention_avoids_duplicate_explanation_in_limitations(self) -> None:
        v12_bundle = self.service.query(
            EvidenceRequest(query="What happened in Saffire VI-3?", scope="core")
        )
        ans = generate_grounded_answer(v12_bundle)
        self.assertEqual(ans.status, "ABSTAINED")
        exp = ans.abstention["explanation"]
        self.assertNotIn(exp, ans.summary)
        self.assertNotIn(exp, ans.limitations)

    def test_typed_validation_diagnosis_codes_and_concise_vi3_fallback(self) -> None:
        from genaius.saffire_case import build_saffire_case_evidence_bundle, load_saffire_case_dataset

        saffire_bundle = build_saffire_case_evidence_bundle(
            EvidenceRequest(query="What happened in Saffire VI-3?", scope="saffire_case"),
            dataset=load_saffire_case_dataset(),
        )
        allowed = [c.citation_id for c in saffire_bundle.citations]
        cite0 = allowed[0]

        cases = [
            ("not valid json {", OUT_DIAG_INVALID_JSON, "$"),
            (json.dumps(["array-root"]), OUT_DIAG_WRONG_TYPE, "$"),
            (
                json.dumps({"summary": "ok", "findings": [], "extra_field": 1}),
                OUT_DIAG_UNEXPECTED_KEY,
                "$",
            ),
            (
                json.dumps({"summary": "ok"}),
                OUT_DIAG_MISSING_FIELD,
                "$.findings",
            ),
            (
                json.dumps(
                    {
                        "summary": "x" * (MAX_SUMMARY_CHARS + 5),
                        "findings": [{"text": "t", "citation_ids": [cite0]}],
                    }
                ),
                OUT_DIAG_LIMIT_EXCEEDED,
                "$.summary",
            ),
            (
                json.dumps(
                    {
                        "summary": "ok",
                        "findings": [{"text": "Finding without citation", "citation_ids": []}],
                    }
                ),
                OUT_DIAG_EMPTY_CITATIONS,
                "$.findings[0].citation_ids",
            ),
            (
                json.dumps(
                    {
                        "summary": "ok",
                        "findings": [{"text": "Bad cite", "citation_ids": ["DOC:FAKE_SECRET_PROMPT_LEAK"]}],
                    }
                ),
                OUT_DIAG_DISALLOWED_CITATION,
                "$.findings[0].citation_ids[0]",
            ),
            (
                json.dumps(
                    {
                        "summary": "ok",
                        "findings": [{"text": "t", "citation_ids": [cite0]} for _ in range(MAX_FINDINGS_COUNT + 1)],
                    }
                ),
                OUT_DIAG_LIMIT_EXCEEDED,
                "$.findings",
            ),
        ]
        for raw, expected_code, expected_path in cases:
            with self.subTest(expected_code=expected_code, expected_path=expected_path):
                with self.assertRaises(AdapterOutputValidationError) as ctx:
                    validate_llm_adapter_output(raw, allowed_citation_ids=allowed)
                exc = ctx.exception
                self.assertEqual(exc.diagnosis_code, expected_code)
                self.assertEqual(exc.field_path, expected_path)
                diag_dict = exc.to_dict()
                self.assertEqual(diag_dict["diagnosis_code"], expected_code)
                self.assertTrue(diag_dict["expected"])

        bad_adapter = _RecordingAdapter(
            response=json.dumps(
                {
                    "summary": "Short VI-3 summary.",
                    "findings": [{"text": "Bad cite", "citation_ids": ["CASE-TBL:NONEXISTENT"]}],
                    "limitations": [],
                }
            )
        )
        fb = generate_grounded_answer(saffire_bundle, llm_adapter=bad_adapter)
        self.assertEqual(fb.answer_mode, "deterministic_fallback")
        self.assertEqual(fb.failure_reason, "OUTPUT_VALIDATION_FAILED")
        self.assertFalse(fb.llm_used)
        self.assertLessEqual(len(fb.findings), 4)
        self.assertIsNotNone(fb.validation_diagnostics)
        self.assertEqual(fb.validation_diagnostics["diagnosis_code"], OUT_DIAG_DISALLOWED_CITATION)
        self.assertNotIn("CASE-TBL:NONEXISTENT", json.dumps(fb.to_dict()))
        self.assertFalse(any("llm_fallback" in lim.lower() for lim in fb.limitations))
        self.assertTrue(any(w.startswith("llm_fallback:") for w in fb.warnings))
        self.assertIn("no LLM synthesis", fb.summary)


if __name__ == "__main__":
    unittest.main()

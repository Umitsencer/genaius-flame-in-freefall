"""Offline mocked unit tests for OpenRouterAdapter and .env configuration policy."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from genaius.answering import generate_grounded_answer
from genaius.data.contracts import DATASET_SPECS, ExperimentRecord, POSITION_DEFINITION, SourceLocation
from genaius.data.loader import parse_measurement_value
from genaius.openrouter import (
    DEFAULT_OPENROUTER_MODEL,
    OpenRouterAdapter,
    OpenRouterConfig,
    OpenRouterConfigError,
    OpenRouterHTTPError,
    OpenRouterModelUnavailableError,
    OpenRouterResponseError,
    OpenRouterSecurityError,
    OpenRouterTransportError,
    create_openrouter_adapter_from_env,
    inspect_openrouter_env_status,
    load_merged_env,
    parse_dotenv_file,
)
from genaius.retrieval.bm25 import build_bm25_index
from genaius.retrieval.documents import DocumentChunk
from genaius.service import EvidenceRequest, EvidenceService


def _sample_record() -> ExperimentRecord:
    spec = DATASET_SPECS["PSI-69"]
    contracts = {fc.field_name: fc for fc in spec.field_contracts}
    raw_values = {"droplet_initial_diameter_mm": "2.4", "burning_rate_mm2_s": "0.41"}
    measurements = {
        fname: parse_measurement_value(raw_values.get(fname, ""), contract)
        for fname, contract in contracts.items()
    }
    return ExperimentRecord(
        record_pk="PSI-69:2",
        investigation_id="PSI-69",
        test_id="2",
        sample_id=None,
        flex_identifier=None,
        source=SourceLocation(
            source_relpath=spec.relative_path,
            source_sha256="c" * 64,
            encoding=spec.encoding,
            csv_record_index=2,
            physical_line_start=3,
            physical_line_end=3,
            position_definition=POSITION_DEFINITION,
        ),
        raw_fields={"Fuel": "n-Decane", **raw_values},
        normalized_fields={"fuel_raw": "n-Decane", "fuel_norm": "n-Decane"},
        measurements=measurements,
        quality_flags=(),
    )


def _sample_bundle():
    chunk = DocumentChunk(
        chunk_id="FLEX_TP_2015:0001",
        chunk_ordinal=1,
        document_id="FLEX_TP_2015",
        investigation_id="PSI-69",
        section_number="1",
        section_title="Summary",
        section_path=("Summary",),
        source_text="n-Decane cool flame behavior documented in PSI-69 summary notes.",
        pdf_page_start=1,
        pdf_page_end=1,
        printed_page_start="1",
        printed_page_end="1",
        printed_pages=("1",),
        paragraph_index_start=0,
        paragraph_index_end=0,
        source_url="https://ntrs.nasa.gov/citations/20150023456",
        source_relpath="data/raw/nasa_docs/20150023456_flex_tp.pdf",
        source_sha256="d" * 64,
    )
    service = EvidenceService(
        records=(_sample_record(),),
        bm25_index=build_bm25_index([chunk]),
    )
    return service.query(
        EvidenceRequest(
            query="n-Decane cool flame",
            investigation_id="PSI-69",
            fuel="n-Decane",
            run_table_query=True,
        )
    )


class OpenRouterPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = _sample_bundle()
        self.secret = "sk-or-v1-test-only-never-leak-987654321"

    def test_valid_free_model_happy_path_and_request_contract(self) -> None:
        recorded_calls: list[dict] = []

        def fake_transport(method, url, headers, body, timeout):
            decoded_body = json.loads(body.decode("utf-8")) if body else None
            recorded_calls.append({"method": method, "url": url, "headers": headers, "body": decoded_body, "timeout": timeout})
            return (
                200,
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "n-Decane PSI-69 burning rate evidence was retrieved.",
                                        "findings": [
                                            {
                                                "text": "Burning rate was 0.41 mm^2/s at d0=2.4 mm.",
                                                "citation_ids": ["TBL:PSI-69:2"],
                                            }
                                        ],
                                        "limitations": ["No model extrapolation beyond tested conditions."],
                                    }
                                )
                            },
                        }
                    ]
                },
            )

        adapter = OpenRouterAdapter(
            OpenRouterConfig(api_key=self.secret, model=DEFAULT_OPENROUTER_MODEL),
            transport=fake_transport,
        )
        answer = generate_grounded_answer(self.bundle, llm_adapter=adapter)
        self.assertEqual(answer.status, "OK")
        self.assertEqual(answer.answer_mode, "llm")
        self.assertTrue(answer.llm_used)
        self.assertEqual(len(recorded_calls), 1)
        req = recorded_calls[0]
        self.assertEqual(req["url"], "https://openrouter.ai/api/v1/chat/completions")
        self.assertEqual(req["body"]["model"], DEFAULT_OPENROUTER_MODEL)
        self.assertEqual(req["body"]["max_tokens"], 1200)
        self.assertEqual(req["body"]["reasoning"], {"enabled": False})
        self.assertIs(req["body"]["stream"], False)
        self.assertEqual(req["body"]["response_format"], {"type": "json_object"})
        self.assertIn(self.secret, req["headers"]["Authorization"])
        self.assertNotIn(self.secret, repr(adapter.config))

    def test_catalog_parameter_detection_respects_supported_parameters(self) -> None:
        seen_urls: list[str] = []
        sent_formats: list[object] = []
        sent_reasonings: list[object] = []

        def fake_transport(method, url, headers, body, timeout):
            seen_urls.append(f"{method} {url}")
            if method == "GET" and url.endswith("/models"):
                return (
                    200,
                    {
                        "data": [
                            {
                                "id": DEFAULT_OPENROUTER_MODEL,
                                "pricing": {"prompt": "0", "completion": "0"},
                                "supported_parameters": ["response_format", "temperature"],
                            }
                        ]
                    },
                )
            decoded = json.loads(body.decode("utf-8"))
            sent_formats.append(decoded.get("response_format"))
            sent_reasonings.append(decoded.get("reasoning"))
            return (
                200,
                {
                    "choices": [
                        {
                            "finish_reason": "stop",
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "Verified.",
                                        "findings": [{"text": "Matched doc.", "citation_ids": ["DOC:FLEX_TP_2015:0001"]}],
                                        "limitations": [],
                                    }
                                )
                            },
                        }
                    ]
                },
            )

        adapter = OpenRouterAdapter(
            OpenRouterConfig(
                api_key=self.secret,
                verify_free_catalog=True,
                use_json_schema_if_supported=True,
            ),
            transport=fake_transport,
        )
        ans = generate_grounded_answer(self.bundle, llm_adapter=adapter)
        self.assertTrue(ans.llm_used)
        self.assertEqual(seen_urls[0], "GET https://openrouter.ai/api/v1/models")
        self.assertEqual(sent_formats[0], {"type": "json_object"})
        self.assertIsNone(sent_reasonings[0])

    def test_non_free_and_auto_and_http_urls_are_rejected(self) -> None:
        for bad_model in ("openrouter/auto", "openrouter/auto:free", "google/gemma-4-26b-a4b-it", "badformat"):
            with self.assertRaises(OpenRouterModelUnavailableError):
                OpenRouterConfig(api_key=self.secret, model=bad_model)
        with self.assertRaises(OpenRouterSecurityError):
            OpenRouterConfig(api_key=self.secret, base_url="http://openrouter.ai/api/v1")

        # Paid catalog entry check
        def paid_catalog(method, url, headers, body, timeout):
            return (
                200,
                {
                    "data": [
                        {
                            "id": DEFAULT_OPENROUTER_MODEL,
                            "pricing": {"prompt": "0.0001", "completion": "0.0002"},
                            "supported_parameters": ["response_format"],
                        }
                    ]
                },
            )

        adapter = OpenRouterAdapter(
            OpenRouterConfig(api_key=self.secret, verify_free_catalog=True),
            transport=paid_catalog,
        )
        fallback = generate_grounded_answer(self.bundle, llm_adapter=adapter)
        self.assertEqual(fallback.answer_mode, "deterministic_fallback")
        self.assertFalse(fallback.llm_used)

    def test_error_status_timeout_truncation_and_bad_citation_fallback_without_retry(self) -> None:
        scenarios = [
            ("401", OpenRouterHTTPError(401, f"Unauthorized {self.secret}")),
            ("402", OpenRouterHTTPError(402, "Payment Required")),
            ("403", OpenRouterHTTPError(403, "Forbidden")),
            ("429", OpenRouterHTTPError(429, "Rate limit")),
            ("500", OpenRouterHTTPError(500, "Server error")),
            ("timeout", OpenRouterTransportError("TimeoutError")),
            ("redirect", OpenRouterSecurityError("HTTP redirect blocked")),
        ]
        for label, exc in scenarios:
            calls = 0

            def failing_transport(method, url, headers, body, timeout, _exc=exc):
                nonlocal calls
                calls += 1
                raise _exc

            adapter = OpenRouterAdapter(OpenRouterConfig(api_key=self.secret), transport=failing_transport)
            result = generate_grounded_answer(self.bundle, llm_adapter=adapter)
            self.assertEqual(calls, 1, f"{label} must not retry")
            self.assertEqual(result.answer_mode, "deterministic_fallback")
            self.assertFalse(result.llm_used)
            joined = " ".join([result.summary, *result.limitations, *result.warnings])
            self.assertNotIn(self.secret, joined)

        # finish_reason=length and fabricated citation must both fall back safely
        for resp in (
            {"choices": [{"finish_reason": "length", "message": {"content": '{"summary":"cut'}}]},
            {
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "content": json.dumps(
                                {
                                    "summary": "Claim",
                                    "findings": [{"text": "Fabricated", "citation_ids": ["TBL:FAKE:999"]}],
                                    "limitations": [],
                                }
                            )
                        },
                    }
                ]
            },
        ):
            adapter = OpenRouterAdapter(
                OpenRouterConfig(api_key=self.secret),
                transport=lambda *_: (200, resp),
            )
            result = generate_grounded_answer(self.bundle, llm_adapter=adapter)
            self.assertEqual(result.answer_mode, "deterministic_fallback")
            self.assertFalse(result.llm_used)

    def test_redirect_handler_blocks_3xx(self) -> None:
        from genaius.openrouter import _default_urllib_transport

        with patch("urllib.request.OpenerDirector.open", side_effect=OpenRouterSecurityError("redirect")):
            with self.assertRaises(OpenRouterSecurityError):
                _default_urllib_transport("POST", "https://openrouter.ai/api/v1/chat/completions", {}, b"{}", 5.0)

    def test_default_transport_allows_large_catalog_while_bounding_completions(self) -> None:
        from genaius.openrouter import MAX_RESPONSE_BYTES, _default_urllib_transport

        large_catalog = json.dumps({"data": [{"id": "x:free", "pad": "a" * (MAX_RESPONSE_BYTES + 2000)}]}).encode("utf-8")

        class _FakeResp:
            def __init__(self, payload_bytes: bytes) -> None:
                self.status = 200
                self._payload = payload_bytes

            def read(self, n: int) -> bytes:
                return self._payload[:n]

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("urllib.request.OpenerDirector.open", return_value=_FakeResp(large_catalog)):
            status, payload = _default_urllib_transport("GET", "https://openrouter.ai/api/v1/models", {}, None, 5.0)
            self.assertEqual(status, 200)
            self.assertEqual(payload["data"][0]["id"], "x:free")
            with self.assertRaises(OpenRouterResponseError):
                _default_urllib_transport("POST", "https://openrouter.ai/api/v1/chat/completions", {}, b"{}", 5.0)

    def test_dotenv_safe_parsing_precedence_and_no_secret_leakage(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_file = root / ".env"
            env_file.write_text(
                "\n".join(
                    [
                        "# comment line",
                        "GENAIUS_LLM_ENABLED=true",
                        f'OPENROUTER_API_KEY="{self.secret}" # inline comment',
                        f"OPENROUTER_MODEL={DEFAULT_OPENROUTER_MODEL}",
                        "SHELL_INJECTION=$(whoami)",
                    ]
                ),
                encoding="utf-8",
            )
            parsed = parse_dotenv_file(env_file)
            self.assertEqual(parsed["OPENROUTER_API_KEY"], self.secret)
            self.assertEqual(parsed["SHELL_INJECTION"], "$(whoami)")

            # Existing process env wins over .env
            merged = load_merged_env(root, environ={"GENAIUS_LLM_ENABLED": "false"})
            self.assertEqual(merged["GENAIUS_LLM_ENABLED"], "false")
            self.assertIsNone(create_openrouter_adapter_from_env(root, environ={"GENAIUS_LLM_ENABLED": "false"}))
            status = inspect_openrouter_env_status(root, environ={"GENAIUS_LLM_ENABLED": "false"})
            self.assertFalse(status["enabled"])
            self.assertNotIn(self.secret, json.dumps(status))

            # Enabled via .env builds adapter cleanly without printing secret
            adapter = create_openrouter_adapter_from_env(root, environ={})
            self.assertIsNotNone(adapter)
            self.assertEqual(adapter.config.model, DEFAULT_OPENROUTER_MODEL)
            self.assertNotIn(self.secret, repr(adapter.config))

            # Absent API key degrades cleanly
            (root / ".env").unlink()
            self.assertIsNone(create_openrouter_adapter_from_env(root, environ={}))

            # Invalid key name in .env raises OpenRouterConfigError in strict mode
            (root / ".env").write_text("INVALID-KEY=123\n", encoding="utf-8")
            with self.assertRaises(OpenRouterConfigError):
                parse_dotenv_file(root / ".env")


class OpenRouterPromptContractTests(unittest.TestCase):
    def test_build_messages_encodes_answering_bounds_and_omits_unsupported_response_format(self) -> None:
        from genaius.answering import (
            AdapterPromptInput,
            MAX_CITATIONS_PER_FINDING,
            MAX_FINDINGS_COUNT,
            MAX_FINDING_TEXT_CHARS,
            MAX_LIMITATIONS_COUNT,
            MAX_LIMITATION_CHARS,
            MAX_SUMMARY_CHARS,
        )

        adapter = OpenRouterAdapter(
            OpenRouterConfig(
                api_key="or-test-key-000",
                model="nvidia/nemotron-3.5-super-vl:free",
                verify_free_catalog=False,
                use_json_schema_if_supported=False,
            )
        )
        prompt_in = AdapterPromptInput(
            user_query="What happened in Saffire VI-3?",
            evidence_payload={"case_payload": {"tests": [{"citation_id": "CASE-TBL:VI-3", "test_id": "VI-3"}]}},
            allowed_citation_ids=("CASE-TBL:VI-3", "CASE-DET:DET-A"),
            system_rules=("Cite exact IDs only.",),
            truncated=False,
            truncation_notes=(),
        )
        msgs = adapter._build_messages(prompt_in)
        system_msg = msgs[0]["content"]
        self.assertIn(str(MAX_SUMMARY_CHARS), system_msg)
        self.assertIn(str(MAX_FINDINGS_COUNT), system_msg)
        self.assertIn(str(MAX_FINDING_TEXT_CHARS), system_msg)
        self.assertIn(str(MAX_CITATIONS_PER_FINDING), system_msg)
        self.assertIn(str(MAX_LIMITATIONS_COUNT), system_msg)
        self.assertIn(str(MAX_LIMITATION_CHARS), system_msg)
        self.assertIn("citation_ids", system_msg)

        captured_payloads: list[dict] = []

        def transport(method: str, url: str, headers: dict, body: bytes | None, timeout_s: float):
            if method == "GET":
                return (
                    200,
                    {
                        "data": [
                            {
                                "id": "nvidia/nemotron-3.5-super-vl:free",
                                "pricing": {"prompt": "0", "completion": "0"},
                                "supported_parameters": ["temperature", "max_tokens"],
                            }
                        ]
                    },
                )
            captured_payloads.append(json.loads((body or b"{}").decode("utf-8")))
            return (
                200,
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "summary": "Saffire VI-3 recorded CO2 and CO increases.",
                                        "findings": [
                                            {
                                                "text": "Test VI-3 data recorded.",
                                                "citation_ids": ["CASE-TBL:VI-3"],
                                            }
                                        ],
                                        "limitations": [],
                                    }
                                )
                            }
                        }
                    ]
                },
            )

        schema_adapter = OpenRouterAdapter(
            OpenRouterConfig(
                api_key="or-test-key-000",
                model="nvidia/nemotron-3.5-super-vl:free",
                verify_free_catalog=True,
                use_json_schema_if_supported=True,
            ),
            transport=transport,
        )
        schema_adapter.generate(prompt_in)
        self.assertEqual(len(captured_payloads), 1)
        self.assertNotIn("response_format", captured_payloads[0])


if __name__ == "__main__":
    unittest.main()

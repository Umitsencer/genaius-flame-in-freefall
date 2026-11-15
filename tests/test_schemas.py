"""Pydantic şema sözleşmeleri (Görev 056): tek kaynak, gevşek coercion yok, girdi yankısı yok."""
import json
import unittest

from genaius.app_service import AppService  # noqa: F401  (import side effects must stay clean)
from genaius.openrouter import _JSON_SCHEMA_SPEC
from genaius.schemas import llm_output
from genaius.schemas.requests import (
    EvidenceRequestIn,
    FlexConditionIn,
    MaterialLabRequest,
    RequestValidationError,
    SearchRequest,
    parse_request,
)

# The exact provider schema that was hand-written in openrouter.py before Görev 056.
LEGACY_PROVIDER_SCHEMA = {
    "name": "grounded_psi_answer",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "findings", "limitations"],
        "properties": {
            "summary": {"type": "string"},
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["text", "citation_ids"],
                    "properties": {
                        "text": {"type": "string"},
                        "citation_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "limitations": {"type": "array", "items": {"type": "string"}},
        },
    },
}


class LlmOutputSchemaTests(unittest.TestCase):
    def test_provider_schema_is_generated_from_model_and_matches_legacy_contract(self):
        self.assertEqual(llm_output.provider_json_schema(), LEGACY_PROVIDER_SCHEMA)
        self.assertEqual(_JSON_SCHEMA_SPEC, LEGACY_PROVIDER_SCHEMA)

    def test_prompt_limits_come_from_the_same_constants_as_the_validator(self):
        text = "\n".join(llm_output.prompt_contract_lines(has_citations=True))
        for value in (llm_output.MAX_SUMMARY_CHARS, llm_output.MAX_FINDINGS_COUNT,
                      llm_output.MAX_FINDING_TEXT_CHARS, llm_output.MAX_CITATIONS_PER_FINDING,
                      llm_output.MAX_LIMITATIONS_COUNT, llm_output.MAX_LIMITATION_CHARS):
            self.assertIn(str(value), text)
        field = llm_output.LLMAnswer.model_fields["summary"]
        self.assertIn(llm_output.MAX_SUMMARY_CHARS, [getattr(m, "max_length", None) for m in field.metadata])

    def test_llm_answer_rejects_coercion(self):
        bad = {"summary": 5, "findings": [{"text": "t", "citation_ids": ["A"]}]}
        with self.assertRaises(Exception):
            llm_output.LLMAnswer.model_validate(bad)
        with self.assertRaises(Exception):
            llm_output.LLMAnswer.model_validate({"summary": "s", "findings": [{"text": "t", "citation_ids": "A"}]})


class RequestSchemaTests(unittest.TestCase):
    def _codes(self, model, payload):
        with self.assertRaises(RequestValidationError) as ctx:
            parse_request(model, payload)
        return ctx.exception

    def test_strict_types_no_coercion(self):
        self.assertEqual(self._codes(SearchRequest, {"limit": "5"}).errors[0]["code"], "WRONG_TYPE")
        self.assertEqual(self._codes(SearchRequest, {"limit": True}).errors[0]["code"], "WRONG_TYPE")
        self.assertEqual(self._codes(SearchRequest, {"limit": 5.0}).errors[0]["code"], "WRONG_TYPE")
        # Literal-style integers must not accept booleans (True == 1 in Python).
        self.assertEqual(self._codes(MaterialLabRequest, {"flow_restrictor": True}).errors[0]["code"], "WRONG_TYPE")
        self.assertEqual(self._codes(EvidenceRequestIn, {"use_bilingual_aliases": "yes"}).errors[0]["code"],
                         "WRONG_TYPE")

    def test_unknown_keys_missing_fields_and_bounds(self):
        self.assertEqual(self._codes(SearchRequest, {"bogus": 1}).errors[0],
                         {"code": "UNEXPECTED_FIELD", "field": "$.bogus"})
        exc = self._codes(FlexConditionIn, {"fuel": "Heptane"})
        self.assertIn({"code": "MISSING_FIELD", "field": "$.o2_mol_frac"}, exc.errors)
        flex = {"fuel": "Heptane", "o2_mol_frac": 1.2, "co2_mol_frac": 0, "he_mol_frac": 0,
                "pressure_atm": 1, "droplet_initial_diameter_mm": 3}
        self.assertEqual(self._codes(FlexConditionIn, flex).errors[0], {"code": "OUT_OF_RANGE", "field": "$.o2_mol_frac"})
        self.assertEqual(self._codes(FlexConditionIn, {**flex, "o2_mol_frac": float("nan")}).errors[0]["code"],
                         "NON_FINITE_NUMBER")

    def test_errors_never_echo_input(self):
        secret = "sk-or-v1-SHOULD-NOT-LEAK"
        exc = self._codes(SearchRequest, {"fuel": 3, "investigation_id": [secret]})
        self.assertNotIn(secret, str(exc))
        self.assertNotIn(secret, json.dumps(exc.errors))

    def test_numbers_keep_their_json_type(self):
        req = parse_request(SearchRequest, {"numeric_filters": [{"field_name": "f", "unit": "u", "min_value": 2200}]})
        self.assertIs(type(req.numeric_filters[0].min_value), int)


if __name__ == "__main__":
    unittest.main()

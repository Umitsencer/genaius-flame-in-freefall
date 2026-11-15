"""Shared fire-prevention evidence summary for the Data page and the chatbot.

Four topics — atmosphere, material, flow, detection & suppression — each with strictly
separated layers:

* ``computed``      values computed here from verified PSI-25 / PSI-69 table rows (with record ids);
* ``source_findings`` statements taken from the curated SAFFIRE IV–VI source table
                    (published NTRS documents), labelled with their source ids — not recomputed;
* ``not_in_sources`` what the selected sources do not contain (never filled in or estimated);
* ``engineering_interpretation`` clearly labelled team interpretation, limited to the tested range.

No risk or safety score is produced; microgravity results are not turned into Moon/Mars evidence.
Language models are not involved; an LLM may narrate this payload but is never its authority.
"""
from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence
from typing import Any

from .analytics import _classify_psi25_material, _parse_flow_restrictor
from .data.contracts import ExperimentRecord, MeasurementStatus
from .data.query import summarize_field

INTERPRETATION_LABEL = "Engineering interpretation (GeNAIus team, not a NASA finding)"
BOUNDARY = (
    "Descriptive evidence only: no fire-risk or safety score, no crew-safety verdict, and no transfer of "
    "ISS microgravity or uncrewed Cygnus results to Moon/Mars or Earth gravity."
)


def _range(records: Sequence[ExperimentRecord], inv: str, field: str, unit: str) -> dict[str, Any]:
    s = summarize_field(records, investigation_id=inv, field_name=field, unit=unit)
    return {
        "investigation_id": inv, "field": field, "unit": unit, "min": s.min_value, "max": s.max_value,
        "measured_runs": s.used_total_count, "excluded_by_status": {k: v for k, v in s.excluded_by_status.items() if v},
        "record_ids": list(s.used_record_pks),
    }


def _fmt_range(r: dict[str, Any]) -> str:
    return f"{r['min']:g}–{r['max']:g} {r['unit']} ({r['measured_runs']} runs with a measured value)"


def _case_sources(case_raw: dict[str, Any] | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    if not case_raw:
        return [], [], []
    atm, flow, det = [], [], []
    for rec in case_raw.get("condition_records", []):
        o2, p = rec.get("oxygen_mol_percent"), rec.get("ambient_pressure_kpa")
        if o2 is not None or p is not None:
            atm.append({"source": "SAFFIRE IV–VI case table (NTRS)", "test_id": rec["test_id"],
                        "text": f"{rec['test_id']} ({rec.get('flight_vehicle')}): O₂ {o2} mol %, {p} kPa, "
                                f"material {rec.get('material')} (uncrewed Cygnus test)."})
        if rec.get("initial_air_flow_cm_s") is not None:
            flow.append({"source": "SAFFIRE IV–VI case table (NTRS)", "test_id": rec["test_id"],
                         "text": f"{rec['test_id']}: initial air flow {rec['initial_air_flow_cm_s']} cm/s, "
                                 f"{rec.get('flow_direction') or 'direction not stated'}."})
    for d in case_raw.get("detection_evidence", []):
        det.append({"source": f"SAFFIRE/SAME source card {d['evidence_id']}", "test_id": None, "text": d["title"]})
    return atm, flow, det


def psi69_all(records: Sequence[ExperimentRecord]) -> list[ExperimentRecord]:
    return [r for r in records if r.investigation_id == "PSI-69"]


def build_prevention_summary(
    records: Sequence[ExperimentRecord], *, case_raw: dict[str, Any] | None = None
) -> dict[str, Any]:
    psi25 = [r for r in records if r.investigation_id == "PSI-25"]
    psi69 = [r for r in records if r.investigation_id == "PSI-69"]
    case_atm, case_flow, case_det = _case_sources(case_raw)

    o2_25 = _range(records, "PSI-25", "initial_o2_vol_pct", "% vol")
    o2_69 = _range(records, "PSI-69", "initial_o2_flex_mol_pct", "% mol")
    p_69 = _range(records, "PSI-69", "ambient_pressure_kpa", "atm")
    p_vals = [r.measurements["ambient_pressure_kpa"].parsed_value for r in psi69_all(records)
              if r.record_pk in set(p_69["record_ids"])]
    pos = [v / 760.0 for v in p_vals if v is not None and v > 0]  # parsed_value is the source mmHg
    p_pos = {"min": round(min(pos), 4), "max": round(max(pos), 4), "n": len(pos),
             "nonpositive": sum(1 for v in p_vals if v is not None and v <= 0)}

    families = Counter(_classify_psi25_material(r.normalized_fields["fuel_norm"]) for r in psi25)
    by_family: dict[str, dict[str, int]] = {}
    for (fam, shape), n in sorted(families.items()):
        by_family.setdefault(fam, {})[shape] = n
    final_co_status = Counter(
        (r.measurements["final_co_ppm"].status.value if "final_co_ppm" in r.measurements else "missing") for r in psi25
    )

    restrictors = Counter(_parse_flow_restrictor(r) for r in psi25)
    test_end = Counter(r.normalized_fields.get("test_end") or "missing" for r in psi69)

    def interp(text: str) -> dict[str, str]:
        return {"label": INTERPRETATION_LABEL, "text": text}

    topics = [
        {
            "topic": "atmosphere",
            "title": "Atmosphere (oxygen, pressure, diluent)",
            "computed": [
                {"text": f"BASS-II solid samples: initial O₂ {_fmt_range(o2_25)}.", "detail": o2_25},
                {"text": f"FLEX droplets: initial O₂ {_fmt_range(o2_69)}.", "detail": o2_69},
                {"text": (f"FLEX droplets: ambient pressure {p_pos['min']:g}–{p_pos['max']:g} atm over {p_pos['n']} runs"
                          + (f"; {p_pos['nonpositive']} run(s) record 0 or negative pressure, a known source-table anomaly, "
                             "and are excluded from this range" if p_pos['nonpositive'] else "") + "."),
                 "detail": {**p_69, "positive_range": p_pos}},
            ],
            "source_findings": case_atm,
            "not_in_sources": [
                f"Solid-sample tests above {o2_25['max']:g} % vol O₂ (e.g. proposed exploration atmospheres) — none in BASS-II.",
                "Any test at Moon, Mars or other partial gravity.",
            ],
            "engineering_interpretation": [interp(
                f"Conclusions from these solid-sample tests apply only within the tested initial O₂ range "
                f"({o2_25['min']:g}–{o2_25['max']:g} % vol); higher-O₂ cabin atmospheres need their own tests.")],
        },
        {
            "topic": "material",
            "title": "Materials",
            "computed": [
                {"text": "BASS-II runs by material family/shape: "
                         + "; ".join(f"{fam} ({', '.join(f'{k} {v}' for k, v in shapes.items())})" for fam, shapes in by_family.items())
                         + ".", "detail": by_family},
                {"text": "BASS-II final CO statuses: " + ", ".join(f"{k} {v}" for k, v in sorted(final_co_status.items()))
                         + " (NULL and over-range values are never treated as numbers).", "detail": dict(final_co_status)},
            ],
            "source_findings": [],
            "not_in_sources": [
                "A flammability acceptance result or ranking for any material (e.g. NASA-STD-6001 test outcomes).",
                "Gas production as mass; the table gives chamber concentrations (ppm, % vol) only.",
            ],
            "engineering_interpretation": [interp(
                "Material comparisons here are descriptive: runs differ in thickness, width, O₂ and flow, so they "
                "should not be read as a material safety order.")],
        },
        {
            "topic": "flow",
            "title": "Flow / ventilation",
            "computed": [
                {"text": "BASS-II flow-restrictor codes: " + ", ".join(
                    f"{'not recorded' if k is None else f'code {k}'}: {v}" for k, v in sorted(restrictors.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)))
                         + ". Fan and air-display readings are uncalibrated and are not converted to velocity.",
                 "detail": {str(k): v for k, v in restrictors.items()}},
            ],
            "source_findings": case_flow,
            "not_in_sources": ["Calibrated flow velocity for individual BASS-II runs."],
            "engineering_interpretation": [interp(
                "Flow settings are recorded as codes, so these data can show which settings were tested, not a "
                "velocity threshold for spread or extinction.")],
        },
        {
            "topic": "detection_suppression",
            "title": "Detection & suppression",
            "computed": [
                {"text": "FLEX droplet test outcomes (test end): " + ", ".join(f"{k} {v}" for k, v in sorted(test_end.items()))
                         + ". Extinction here is a droplet-flame outcome in a sealed chamber, not an extinguisher test.",
                 "detail": dict(test_end)},
            ],
            "source_findings": case_det,
            "not_in_sources": [
                "Performance of portable extinguishers or suppression agents on burning solids.",
                "Detector response in a crewed cabin; the SAFFIRE tests were uncrewed.",
            ],
            "engineering_interpretation": [interp(
                "The source cards report detector timing and particle-size effects for specific tests; they do not "
                "set a detector requirement on their own.")],
        },
    ]
    record_ids = sorted(set(o2_25["record_ids"]) | set(o2_69["record_ids"]) | set(p_69["record_ids"]))
    return {
        "status": "OK",
        "mode": "prevention_evidence_summary",
        "badge": "Computed from table records · source findings labelled separately",
        "boundary": BOUNDARY,
        "llm_used": False,
        "topics": topics,
        "computed_record_count": len(record_ids),
        "measurement_status_values": [s.value for s in MeasurementStatus],
    }


_PREVENTION_RE = re.compile(r"\b(?:prevent\w*|prevention|mitigat\w*|onle\w*)\b")


def is_prevention_question(folded: str) -> bool:
    return bool(_PREVENTION_RE.search(folded))


def prevention_answer(summary: dict[str, Any]) -> dict[str, Any]:
    """Chatbot view of the same summary (no recomputation, no LLM)."""
    findings = []
    for t in summary["topics"]:
        computed = " ".join(c["text"] for c in t["computed"])
        src = f" Source findings ({len(t['source_findings'])}) are listed separately on the Data page." if t["source_findings"] else ""
        missing = " Not in the selected sources: " + "; ".join(t["not_in_sources"]) + "."
        findings.append({"text": f"{t['title']} — computed: {computed}{src}{missing}", "citation_ids": []})
    return {
        "status": "OK",
        "answer_mode": "prevention_summary",
        "answer_badge": summary["badge"],
        "llm_used": False,
        "llm_calls": 0,
        "resolved_investigation_id": None,
        "summary": ("Prevention-related evidence, by topic, from the verified tables (computed) and the curated SAFFIRE "
                    "source cards (labelled). " + summary["boundary"]),
        "findings": findings,
        "limitations": [i["label"] + ": " + i["text"] for t in summary["topics"] for i in t["engineering_interpretation"]],
        "warnings": [],
        "disclaimers": [summary["boundary"]],
        "sources": [],
        "citation_ids": [],
        "prevention_summary": summary,
        "abstention": {"abstained": False, "reason_code": None, "explanation": None},
        "evidence_overview": {"table_total_runs": summary["computed_record_count"], "table_shown_runs": 0,
                              "document_hit_count": 0, "citation_count": 0},
        "coverage": None,
        "numerical_audit": {"checked": False, "status": "not_applicable",
                            "reason": "Values computed from table records; no generated text to audit.",
                            "violation_count": 0, "checked_claim_count": 0},
        "failure_reason": "NONE",
    }

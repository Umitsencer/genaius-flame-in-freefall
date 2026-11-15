"""Record a deterministic HTTP contract snapshot of the local GeNAIus server.

Used for Görev 056 before/after comparison. Starts the server through the public
`genaius.prototype.server.make_server` entry point on an ephemeral loopback port,
sends a fixed list of requests (happy paths, abstentions, 400/403/404/503 paths,
static-file and traversal probes) and writes one JSON file:

    python scripts/dev/api_contract_snapshot.py --out snapshot.json

No network access outside 127.0.0.1; no LLM adapter is configured.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from genaius.app_service import AppService  # noqa: E402
from genaius.prototype.server import make_server  # noqa: E402

J = {"Content-Type": "application/json"}
FLEX_OK = {
    "fuel": "Heptane", "o2_mol_frac": 0.2, "co2_mol_frac": 0.0, "he_mol_frac": 0.0,
    "pressure_atm": 1.0, "droplet_initial_diameter_mm": 3.0,
}

# (label, method, path, body, headers)
REQUESTS: list[tuple[str, str, str, object, dict]] = [
    ("schema", "GET", "/api/schema", None, {}),
    ("catalog_filters", "GET", "/api/catalog/filters", None, {}),
    ("cfi_schema", "GET", "/api/cfi/schema", None, {}),
    ("saffire_schema", "GET", "/api/saffire/schema", None, {}),
    ("saffire_case_schema", "GET", "/api/saffire/case/schema", None, {}),
    ("flex_predict_schema", "GET", "/api/flex/predict/schema", None, {}),
    ("flex_reconciliation", "GET", "/api/flex/reconciliation", None, {}),
    ("ai_use_doc", "GET", "/docs/AI_USE.md", None, {}),
    ("static_root", "GET", "/", None, {}),
    ("static_js", "GET", "/js/chat.js", None, {}),
    ("static_traversal", "GET", "/js/../../.env", None, {}),
    ("static_dotfile", "GET", "/js/.hidden", None, {}),
    ("static_backslash", "GET", "/js\\chat.js", None, {}),
    ("static_unknown_ext", "GET", "/js/chat.map", None, {}),
    ("get_unknown", "GET", "/api/nope", None, {}),
    ("search_psi25", "POST", "/api/search", {"investigation_id": "PSI-25"}, J),
    ("search_paged", "POST", "/api/search", {"investigation_id": "PSI-69", "limit": 3, "offset": 2}, J),
    ("search_filter", "POST", "/api/search", {"investigation_id": "PSI-69", "numeric_filters": [
        {"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}]}, J),
    ("search_bad_limit", "POST", "/api/search", {"limit": 0}, J),
    ("search_bool_limit", "POST", "/api/search", {"limit": True}, J),
    ("search_extra_key", "POST", "/api/search", {"bogus": 1}, J),
    ("search_not_object", "POST", "/api/search", [1, 2], J),
    ("detail_ok", "POST", "/api/detail", {"record_pk": "PSI-69:10"}, J),
    ("detail_unknown", "POST", "/api/detail", {"record_pk": "PSI-69:99999"}, J),
    ("compare_ok", "POST", "/api/compare", {"record_pks": ["PSI-69:10", "PSI-69:12"]}, J),
    ("compare_dup", "POST", "/api/compare", {"record_pks": ["PSI-69:10", "PSI-69:10"]}, J),
    ("documents_ok", "POST", "/api/documents", {"query": "extinction diameter heptane", "top_k": 3}, J),
    ("documents_empty", "POST", "/api/documents", {"query": "   "}, J),
    ("evidence_core", "POST", "/api/evidence", {"query": "What is the burning rate unit in PSI-69?", "top_k": 2}, J),
    ("evidence_filter", "POST", "/api/evidence", {"query": "PSI-69 burning rate high pressure", "numeric_filters": [
        {"field_name": "ambient_pressure_kpa", "unit": "mmHg", "min_value": 2200}]}, J),
    ("evidence_auto_pool", "POST", "/api/evidence", {"query": "combine BASS-II and FLEX results", "scope": "auto"}, J),
    ("evidence_auto_saffire", "POST", "/api/evidence", {"query": "Saffire VI-3 CO2 rise", "scope": "auto"}, J),
    ("evidence_bad_scope", "POST", "/api/evidence", {"query": "x", "scope": "everything"}, J),
    ("answer_core", "POST", "/api/answer", {"query": "n-decane burning rate PSI-69", "investigation_id": "PSI-69"}, J),
    ("answer_cfi_v12", "POST", "/api/answer", {"query": "PSI-39 cool flame results", "scope": "auto"}, J),
    ("answer_mars", "POST", "/api/answer", {"query": "How does Mars safety compare with ISS smoke rules?", "scope": "auto"}, J),
    ("answer_case", "POST", "/api/answer", {"query": "What did the fire do to the air in VI-3?", "scope": "saffire_case"}, J),
    ("answer_flex_scope", "POST", "/api/answer", {"query": "extinction chance", "scope": "flex_prediction",
                                                   "flex_condition": FLEX_OK}, J),
    ("catalog_search", "POST", "/api/catalog/search", {"query": "FLEX"}, J),
    ("catalog_core", "POST", "/api/catalog/search", {"queryable_in_core": True}, J),
    ("catalog_blank", "POST", "/api/catalog/search", {"query": "  "}, J),
    ("analytics", "POST", "/api/analytics", {"investigation_id": "PSI-69", "field_name": "burning_rate_mm2_s",
                                             "unit": "mm²/s"}, J),
    ("analytics_missing", "POST", "/api/analytics", {"investigation_id": "PSI-69"}, J),
    ("export_csv", "POST", "/api/export", {"investigation_id": "PSI-69", "field_name": "burning_rate_mm2_s",
                                          "unit": "mm²/s", "format": "csv"}, J),
    ("analytics_flex", "POST", "/api/analytics/flex", {"fuel": "Heptane", "target_o2_pct": 20.0}, J),
    ("analytics_flex_bad", "POST", "/api/analytics/flex", {"o2_min_pct": "x"}, J),
    ("analytics_materials", "POST", "/api/analytics/materials", {"target_o2_pct": 21.0, "window_pct": 3.0}, J),
    ("analytics_materials_fr", "POST", "/api/analytics/materials", {"flow_restrictor": 3}, J),
    ("cfi_analysis", "POST", "/api/cfi/analysis", {"pressure_atm": 1.0, "fiber": "Yes"}, J),
    ("cfi_bad_pressure", "POST", "/api/cfi/analysis", {"pressure_atm": 3.0, "fiber": "Yes"}, J),
    ("saffire_ref_all", "POST", "/api/saffire/reference", {}, J),
    ("saffire_ref_one", "POST", "/api/saffire/reference", {"sample_id": "2-1"}, J),
    ("saffire_ref_bad", "POST", "/api/saffire/reference", {"sample_id": "zz"}, J),
    ("case_ref", "POST", "/api/saffire/case", {"test_id": "vi-3"}, J),
    ("case_ref_bad", "POST", "/api/saffire/case", {"test_id": "VII-1"}, J),
    ("case_export_csv", "POST", "/api/saffire/case/export", {"format": "csv"}, J),
    ("flex_predict_ok", "POST", "/api/flex/predict", FLEX_OK, J),
    ("flex_predict_unsupported", "POST", "/api/flex/predict", {**FLEX_OK, "o2_mol_frac": 0.6}, J),
    ("flex_predict_nonfinite_text", "POST", "/api/flex/predict",
     '{"fuel":"Heptane","o2_mol_frac":NaN,"co2_mol_frac":0,"he_mol_frac":0,"pressure_atm":1,'
     '"droplet_initial_diameter_mm":3}', J),
    ("flex_predict_bool", "POST", "/api/flex/predict", {**FLEX_OK, "o2_mol_frac": True}, J),
    ("flex_predict_extra", "POST", "/api/flex/predict", {**FLEX_OK, "burn_time_s": 1}, J),
    ("flex_map", "POST", "/api/flex/predict/map", {"fuel": "Heptane", "pressure_atm": 1.0,
                                                   "droplet_initial_diameter_mm": 3.0}, J),
    ("flex_map_bad_steps", "POST", "/api/flex/predict/map", {"fuel": "Heptane", "pressure_atm": 1.0,
                                                             "droplet_initial_diameter_mm": 3.0, "o2_steps": 99}, J),
    ("flex_export_md", "POST", "/api/flex/predict/export", {**FLEX_OK, "format": "md"}, J),
    ("post_unknown", "POST", "/api/nope", {}, J),
    ("post_wrong_ctype", "POST", "/api/search", {}, {"Content-Type": "text/plain"}),
    ("post_empty_body", "POST", "/api/search", "", J),
    ("post_invalid_json", "POST", "/api/search", "{not json", J),
    ("post_too_large", "POST", "/api/documents", {"query": "x" * 40000}, J),
    ("post_bad_origin", "POST", "/api/search", {}, {**J, "Origin": "https://untrusted.invalid"}),
    ("post_bad_host", "POST", "/api/search", {}, {**J, "Host": "evil.example:80"}),
    ("get_bad_host", "GET", "/api/schema", None, {"Host": "evil.example"}),
]

KEPT_HEADERS = ("content-type", "cache-control", "x-content-type-options", "content-security-policy")


def _send(port: int, method: str, path: str, body: object, headers: dict) -> dict:
    if body is None:
        raw = None
    elif isinstance(body, str):
        raw = body.encode("utf-8")
    else:
        raw = json.dumps(body).encode("utf-8")
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=60)
    try:
        hdrs = dict(headers)
        conn.putrequest(method, path, skip_host="Host" in hdrs, skip_accept_encoding=True)
        for k, v in hdrs.items():
            conn.putheader(k, v)
        if raw is not None:
            conn.putheader("Content-Length", str(len(raw)))
        conn.endheaders(raw)
        resp = conn.getresponse()
        data = resp.read()
        got = {k.lower(): v for k, v in resp.getheaders()}
    finally:
        conn.close()
    out: dict = {"status": resp.status, "headers": {k: got.get(k) for k in KEPT_HEADERS}}
    if (got.get("content-type") or "").startswith("application/json"):
        out["json"] = json.loads(data)
    else:
        out["sha256"] = hashlib.sha256(data).hexdigest()
        out["bytes"] = len(data)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    server = make_server(AppService(ROOT), 0)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        snap = {label: _send(server.server_port, m, p, b, h) for label, m, p, b, h in REQUESTS}
    finally:
        server.shutdown()
        server.server_close()
        t.join(timeout=5)
    args.out.write_text(json.dumps(snap, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(json.dumps({k: v["status"] for k, v in snap.items()}))


if __name__ == "__main__":
    main()

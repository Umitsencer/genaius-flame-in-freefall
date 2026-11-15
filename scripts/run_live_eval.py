"""Optional bounded live OpenRouter `:free` evaluation runner (strict <=15 calls, 0 retries)."""

from __future__ import annotations

import json
from pathlib import Path
import sys
import time

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from genaius.app_service import AppService
from genaius.openrouter import create_openrouter_adapter_from_env, inspect_openrouter_env_status

EVAL_SPEC_PATH = REPO_ROOT / "tests" / "evaluation" / "eval_cases.json"
MAX_LIVE_CALLS = 15


def main() -> int:
    env_status = inspect_openrouter_env_status(REPO_ROOT)
    if not env_status.get("enabled"):
        print(
            json.dumps(
                {
                    "status": "BLOCKED",
                    "reason": env_status.get("reason"),
                    "model": env_status.get("model"),
                    "message": "No local OPENROUTER_API_KEY configured; skipping live completion calls.",
                },
                indent=2,
            )
        )
        return 2

    adapter = create_openrouter_adapter_from_env(REPO_ROOT, strict=True)
    if adapter is None:
        print(json.dumps({"status": "BLOCKED", "reason": "adapter_inactive"}, indent=2))
        return 2

    spec = json.loads(EVAL_SPEC_PATH.read_text(encoding="utf-8"))
    cases = spec["cases"]
    if len(cases) > MAX_LIVE_CALLS:
        raise RuntimeError(f"Evaluation suite exceeds hard live call cap {MAX_LIVE_CALLS}.")

    # Enforce free-catalog check; zero retries inside OpenRouterAdapter.
    service = AppService(REPO_ROOT, answer_adapter=adapter)
    results = []
    live_calls_attempted = 0
    for case in cases:
        t0 = time.monotonic()
        env = service.answer(dict(case["request"]))
        elapsed_ms = round((time.monotonic() - t0) * 1000.0, 1)
        data = env["data"]
        if data.get("llm_used") or data.get("answer_mode") == "deterministic_fallback":
            live_calls_attempted += 1
        sources = data.get("sources") or ()
        source_ids = [s.get("citation_id", "") for s in sources if isinstance(s, dict)]
        findings = data.get("findings") or ()
        finding_cits_valid = all(
            isinstance(f, dict)
            and all(cid in source_ids for cid in (f.get("citation_ids") or ()))
            for f in findings
        )
        missing_prefixes = [
            p for p in case.get("required_citation_prefixes", ())
            if not any(cid.startswith(p) for cid in source_ids)
        ]
        summary_text = str(data.get("summary") or "")
        combined_text = " ".join(
            [
                summary_text,
                *(str(f.get("text") or "") for f in findings if isinstance(f, dict)),
                *(str(x) for x in (data.get("limitations") or ())),
            ]
        )
        missing_substrings = [
            sub for sub in case.get("required_summary_substrings", ())
            if sub not in combined_text
        ]
        injection_clean = "DOC:FAKE:999" not in json.dumps(data, ensure_ascii=False)
        results.append(
            {
                "id": case["id"],
                "tier": case["tier"],
                "expected_status": case["expected_status"],
                "actual_status": env["status"],
                "answer_mode": data.get("answer_mode"),
                "llm_used": data.get("llm_used"),
                "abstention": data.get("abstention"),
                "source_count": len(sources),
                "findings_count": len(findings),
                "finding_citations_valid": finding_cits_valid,
                "missing_prefixes": missing_prefixes,
                "missing_substrings": missing_substrings,
                "injection_clean": injection_clean,
                "warning_count": len(data.get("warnings") or ()),
                "fallback_warnings": [
                    w for w in (data.get("warnings") or ())
                    if str(w).startswith("llm_fallback:")
                ],
                "summary": summary_text,
                "findings": findings,
                "limitations": data.get("limitations") or (),
                "elapsed_ms": elapsed_ms,
            }
        )

    print(
        json.dumps(
            {
                "status": "OK",
                "model": adapter.config.model,
                "max_tokens": adapter.config.max_tokens,
                "live_calls_attempted": live_calls_attempted,
                "cases": results,
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

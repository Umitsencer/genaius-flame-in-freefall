# Testing and delivery acceptance

## Automated checks

Download all 9 raw files before the full suite. Set `PYTHONPATH` to `src;tests` on Windows or `src:tests` on macOS/Linux.

```powershell
$env:PYTHONPATH = "src;tests"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node frontend/tests/lib.test.js
node frontend/tests/stats.test.js
```

Training tests need `requirements-train.txt`; otherwise they explicitly skip. No key is needed for deterministic, mocked-provider, unit or HTTP tests. Live model checks are separate and never establish general answer accuracy.

## Manual smoke test

| View | Action | Expected |
|---|---|---|
| Material Lab | Select PMMA, group by material and shape | Charts load; correlations are numeric or explicitly unavailable, never object-formatted `NaN` |
| Material Lab | Inspect evidence map | Labels, oxygen strips and medians align; narrow screens stack rows |
| Fire | Methanol, 21% O₂, 1 atm, 0 g | Table evidence and scenario result load |
| Scenario | Leave purpose empty | Optional empty input is accepted |
| Models | Select supported methanol preset | Ridge K and logistic score are labelled as estimates |
| Models | Select mixed CO₂+He preset | Unsupported conditions are blocked |
| Case | Open VI-3 story and timeline details | 637 s, 981 s and derived 344 s are distinct; 780 s burn duration is separate |
| Case | Inspect V-3/V-4 | Missing gas results remain missing |
| Data | Select 2–4 records | Side-by-side conditions and source locations |
| Assistant | Ask highest tested solid-material O₂ | Table-computed answer with record citations |
| Assistant | Ask an unrelated recipe | Out-of-scope response, no selected FLEX estimate attached |
| Navigation | Scroll down, then up; tab into menu | Menu hides/reappears and remains keyboard-accessible |

## Release validation record

Verified locally on **2026-11-15**, Windows / Python 3.11, in the clean public snapshot:

| Check | Actual result |
|---|---|
| Fresh virtual environment + hashed runtime install | Passed |
| `pip check` | No broken requirements |
| Full Python discovery | 223 cases discovered; 5 training-dependent cases skipped in the runtime-only environment. One documentation assertion failed initially; it was fixed and the affected full HTTP test passed on rerun. The other 217 runtime cases passed in discovery. |
| Training-dependent cases | All 5 passed separately against this snapshot using the existing scikit-learn/NumPy training environment (3 training compatibility + 2 group-protocol checks) |
| Offline subset | 25/25 passed in the fresh environment |
| Frontend | Both JS test files and syntax checks for all frontend JS passed |
| Release validator | UTF-8, JSON, HTML IDs/assets and local Markdown links passed |
| HTTP smoke checks | Four pages returned 200; table answer OK/no LLM, blank-purpose scenario OK/TESTED, FLEX prediction OK |
| Source inputs | Nine raw source hashes matched the previously validated copies; three PSI inputs were also re-downloaded live before the slow network transfer was interrupted |
| Public-file scan | No actual local API key, high-confidence credential pattern or personal workstation path detected; raw data/.env/venv excluded |

Across the discovery and targeted reruns, all 223 cases were covered successfully. A second complete discovery run was not performed after the documentation-only fix. This is not a claim that the first full run was entirely green.

GitHub CI runs the 25-test offline subset, frontend checks and release validator without NASA downloads or live LLM calls. Its actual remote result must be checked on GitHub.

## Remaining manual/platform checks

- Windows computer-use could not confidently identify the browser URL, so visual desktop/mobile acceptance is not complete. HTTP tests do not replace visual inspection.
- Fresh installation was tested on Windows. macOS/Linux commands are provided; their end-to-end installation was not locally executed.
- No live key is shipped. A live NVIDIA/OpenRouter answer was previously checked in the development worktree, not in this clean credential-free snapshot.
- No software license was selected on behalf of all contributors; see [NOTICE](../NOTICE.md).

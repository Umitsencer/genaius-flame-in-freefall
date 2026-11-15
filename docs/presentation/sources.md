# Presentation source and revision record

Verified against the public delivery snapshot on **2026-11-15**. English and Turkish versions each contain seven slides with equivalent claims. The Turkish deck retains English screenshots of the application. Screenshots were captured from the current local public application with Playwright/Chrome; only floating navigation/chat chrome was hidden for capture. Displayed data was not composited or fabricated.

| Slide | Evidence |
|---|---|
| 1 | User-supplied challenge-video transcript; README and catalog implementation. The original video was not independently reopened for this presentation. |
| 2 | PSI-25 records and manifests; `frontend/js/lab.js`, `stats.js`, `src/genaius/analytics.py`. Screenshot: Material Lab two-measure comparison. |
| 3 | `src/genaius/scenario_check.py`, `schemas/scenario.py`, `flex/training.py`, `data/processed/flex_acceptance_v2.json`; current scenario result and model cards. |
| 4 | `data/processed/saffire_case_reference.json`, `src/genaius/saffire_case.py`; NTRS [20240002981](https://ntrs.nasa.gov/citations/20240002981), p.5/Fig.7 and [20240007488](https://ntrs.nasa.gov/citations/20240007488), slides 16–19/21. Published source locators come from the audited case record; PDFs were not re-audited in this presentation-only task. |
| 5 | Core/catalog manifests, `catalog.py`, `data/loader.py`, `data/query.py`; current Data record table. |
| 6 | `retrieval/bm25.py`, `answering/`, `numerical_audit.py`, `openrouter.py`, `flex/training.py`, `frontend/js/stats.js`; no claim of embedding integration. |
| 7 | Demonstrated source workflow and application scope; no claim of certification, new physical discovery or competition result. |

## Corrections to the older deck

- Scenario tolerances are **±0.05 O₂ percentage points / ±0.01 atm**, not ±2 / ±0.1.
- Scenario sources are canonical PSI-25 and PSI-69 records kept separate; the old 262-row combined frontend fixture is not the active scenario source.
- The FLEX prediction panel is visible again. Ridge and logistic outputs are shown as estimates; they do not drive the animation.
- Case Study uses the new story layout. The 1 mg/m³ value is the authors' smoke-concentration criterion, not a demonstrated calibrated alarm setting.
- The 344-second derived interval and 780-second reported burn duration are separate from flow termination.
- Old notes about an uncorrected Spearman `NaN` and map-class mismatch are removed; those defects were corrected in the delivery snapshot.
- Public applications do not ship API credentials. The deck describes optional LLM capability instead of promising its activation on every machine.

## Files and reproduction

- `index.html`: seven-slide HTML presentation; no CDN dependency.
- `genaius-presentation-en.pdf`: English print rendering of `index.html`, 16:9.
- `index-tr.html` and `genaius-presentation-tr.pdf`: Turkish slide text with shared application screenshots, 16:9.
- `speaker-notes.md`: English script and Turkish cues, target 300 seconds; no spoken timing measurement claimed.
- `assets/`: actual delivery UI captures.
- `build.mjs`: optional authoring tool; install Playwright in the authoring environment and provide Chrome through `CHROME_PATH` if needed. `PLAYWRIGHT_MODULE` may point to an existing Playwright package directory. Application runtime dependencies remain unchanged.

Run the application, set `GENAIUS_DEMO_URL` if different from localhost:8783, then run `node docs/presentation/build.mjs --capture`. To regenerate both language PDFs without new screenshots, omit `--capture`. Rendering uses the browser's print engine; fonts use local Arial/Segoe UI/Georgia fallbacks.

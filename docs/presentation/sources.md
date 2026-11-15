# English presentation - evidence and revision record

Verified against local public-project files on **2026-11-15**. The English and Turkish decks now follow the same seven-slide story, numerical claims and evidence boundaries. The Turkish translation retains the real English application screenshots. No chart, measurement or screenshot value was fabricated.

## Guide and rubric

The user supplied an eight-page Turkish project-submission guide and the five judging criteria (Impact, Creativity, Validity, Relevance, Presentation). Relevant guide pages: 2-3 for public links and demo format, 4 for NASA data and references, 5 for AI disclosures, 6-7 for English-only slides, seven-slide maximum and team names. The guide was read locally; it was not independently authenticated as the live global policy. All five team names were explicitly confirmed.

## Claim-to-source record

| Slide | Evidence and limits |
|---|---|
| 1 | NASA NTRS 20240002981, public abstract; README project scope. Original SVG explains evidence types, not experimental physics. |
| 2 | `data/processed/psi_core_manifest.json`: 129 PSI-25 and 274 PSI-69 runs; `psi_24_source_manifest.json`: 24 studies; `docs/DATA_AND_MODELS.md`: source separation and 107 sample IDs. |
| 3 | Actual Material Lab capture; `frontend/js/lab.js`, `stats.js`, `src/genaius/analytics.py`, `data/query.py`: measurement filtering, comparison and record provenance. No user-impact metric is asserted. |
| 4 | Actual scenario capture; `src/genaius/scenario_check.py`: ±0.05 oxygen percentage points, ±0.01 atm; `analytics.py` and `frontend/js/fire.js`: independent nearby-FLEX search starting at ±2 points / ±0.1 atm, widening for sample count. GAP refers only to indexed sources. |
| 5 | `saffire_case_reference.json`; NTRS [20240002981](https://ntrs.nasa.gov/citations/20240002981), p.5/Fig.7, and [20240007488](https://ntrs.nasa.gov/citations/20240007488), slides 16-19/21. Source locators and timestamps are inherited from the audited case record; the original NASA PDFs were not re-audited in this deck task. |
| 6 | `docs/AI_USE.md`, `answering/`, `retrieval/bm25.py`, `openrouter.py`; `flex_acceptance_v2.json`: grouped atmosphere+pressure regression R² 0.7078 and classification false positives 32/82 at threshold 0.5. Recorded results, not newly run evaluation. |
| 7 | Implemented workflow supports intended researcher utility. Expert validation and user studies are proposed; no adoption, novelty-first, safety or time-saving claim. |

## Primary NASA resources

- [BASS-II experimental data and ReadMe](https://doi.org/10.60555/4qc4-de67)
- [FLEX experimental data](https://doi.org/10.60555/mbq8-0451)
- [BASS-II summary report](https://ntrs.nasa.gov/citations/20210011385)
- [FLEX detailed report](https://ntrs.nasa.gov/citations/20150023456)
- [Saffire VI report](https://ntrs.nasa.gov/citations/20240002981)
- [Saffire VI presentation](https://ntrs.nasa.gov/citations/20240007488)

Some NASA endpoints can fail in automated tools. This revision checks repository source records, not universal current URL availability.

## AI and visual provenance

AI coding assistants supported HTML/CSS/SVG design, wording and document preparation. Scientific claims were checked against the cited project artifacts. Visuals comprise original code-native SVG and actual application screenshots; no generated photographs, synthetic experimental data, external logo or copied third-party slide design is used. This disclosure does not certify overall competition eligibility.

## Reproduction

- `index.html` and `genaius-presentation-en.pdf`: revised seven-slide English story.
- `index-tr.html` and `genaius-presentation-tr.pdf`: synchronized Turkish translation, with shared English application screenshots.
- `plan.md`: narrative, criterion mapping and acceptance criteria.
- `speaker-notes.md`: English five-minute rehearsal script with Turkish cues.
- `build.mjs`: optional Playwright/Chrome authoring tool; runtime application dependencies are unchanged.
- `assets/`: actual application captures shared by both decks.

With Playwright available, run `node docs/presentation/build.mjs --lang=en` to rebuild only the English PDF. Set `PLAYWRIGHT_MODULE` and `CHROME_PATH` if required. Without a language argument, both PDFs are rebuilt. Use `--capture` only with the application running (default localhost:8783); it replaces screenshots. Fonts are local Arial/Segoe UI/Georgia fallbacks.

Before delivery, check seven-page count, English content, asset paths, controls, overflow and every rendered page. Confirm public access in a browser without login separately from the build.

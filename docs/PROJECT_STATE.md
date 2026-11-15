# Project state

Last verified: 2026-11-15.

## Jury presentation

The English jury deck (`docs/presentation/index.html`, `genaius-presentation-en.pdf`) was rebuilt around the supplied five judging criteria and submission guide: seven 16:9 slides, confirmed team names, NASA-data integration, a measured-data workflow, scenario coverage, VI-3 case evidence, methods/limits and intended impact. `plan.md` maps slides to criteria; `speaker-notes.md` contains a five-minute English rehearsal script with Turkish cues; `sources.md` records claim provenance and AI assistance. The earlier Turkish HTML/PDF is preserved as a separate narrative, not a synchronized translation. All seven revised English PDF pages were rendered and visually inspected; navigation, asset/encoding links and footer clearance were checked. No application code or model evaluation was changed or rerun. Scenario strict matching (±0.05 O₂ points / ±0.01 atm) is distinct from nearby-FLEX search (starting ±2 points / ±0.1 atm). This presentation check does not establish competition eligibility or safety certification.

## Objective

Deliver an independent NASA Space Apps Flame in Freefall research dashboard with traceable table evidence, report retrieval, scenario coverage and separate statistical FLEX estimates.

## Public snapshot

This repository is a clean source snapshot. It excludes private development history, personal paths, credentials, raw NASA downloads, virtual environments, caches and internal team/planning documents.

Canonical entry points: `README.md`, `docs/ARCHITECTURE.md`, `docs/DATA_AND_MODELS.md`, `docs/AI_USE.md` and `docs/TESTING.md`.

The four views are Material Lab, Fire Animation/Scenario/Models, SAFFIRE Case Study and Data. Optional external synthesis is configured locally; credentials are never part of the release.

## Verified delivery checks

Fresh Windows/Python 3.11 runtime installation passed. All 223 discovered cases were covered across the full discovery and targeted reruns (the initial documentation assertion was corrected; five optional training tests passed in a separate training environment). Both frontend test files, all JS syntax checks, public-file scan and release validator passed. Four pages and principal table/scenario/model endpoints were checked over localhost:8783. Exact qualifications are in `docs/TESTING.md`.

CI uses pinned official checkout/setup-python actions and an offline 25-case subset. Credentials, private Git history and raw downloads are excluded. Material Lab Spearman value formatting and evidence-map CSS alignment were corrected for this delivery.

## Remaining limits

The local server is not an authenticated Internet deployment. Results are not safety certifications. Browser visual acceptance and cross-platform installation coverage must be reported separately from automated tests. See the final release record in `docs/TESTING.md`.

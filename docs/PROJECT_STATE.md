# Project state

Last verified: 2026-11-15.

## Jury presentation

`docs/presentation/index.html` and `genaius-presentation.pdf` contain seven revised slides (Turkish slides, English five-minute speaker script). Current UI captures show Material Lab, canonical scenario matching, the restored FLEX model panel, the revised VI-3 story and Data records. Old tolerances, obsolete UI screenshots and operational-alarm wording were replaced. `sources.md` records the claim boundaries and reproduction method. The PDF has seven 16:9 pages; all pages were rendered and visually inspected. HTML navigation, print layout and local assets were checked with headless Chrome; this does not replace broader manual acceptance of the application.

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

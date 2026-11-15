# Architecture

The application uses a `src/` Python package and a static frontend. `AppService` connects HTTP handlers to domain services. Persistent inputs and model coefficients are files; request-time records live in memory.

| Layer | Canonical location | Responsibility |
|---|---|---|
| HTTP | `src/genaius/api/` | FastAPI/Uvicorn, Host/Origin checks, body bounds and allowlisted assets |
| Validation | `src/genaius/schemas/` | Strict Pydantic request and model-output contracts |
| Tables | `src/genaius/data/` | CSV parsing, units, statuses, source locations and filtered queries |
| Analytics | `analytics.py`, `scenario_check.py` | Same-study summaries and scenario coverage |
| Retrieval | `src/genaius/retrieval/` | PDF/DOCX extraction and Okapi BM25 (`k1=1.5`, `b=0.75`) |
| Answers | `src/genaius/answering/`, `table_answers.py` | Deterministic answers, bounded optional synthesis and output validation |
| Models | `src/genaius/flex/` | scikit-learn training; runtime JSON-coefficient inference and support gates |
| Separate studies | `cfi.py`, `saffire.py`, `saffire_case.py` | Isolated CFI, SAFFIRE-II and SAFFIRE IV–VI evidence |
| UI | `frontend/` | HTML/CSS/vanilla JS; SVG charts, Canvas animation and bilingual presentation |

## Key interfaces

- `/api/search`, `/api/detail`, `/api/compare`: typed core records.
- `/api/analytics/materials`, `/api/analytics/flex`: same-study analytics.
- `/api/scenario/check`, `/api/scenario/grid`, `/api/scenario/report`: deterministic evidence coverage.
- `/api/flex/predict`, `/api/flex/predict/map`, `/api/flex/predict/export`: model estimates and support.
- `/api/saffire/case`, `/api/saffire/reference`, `/api/cfi/analysis`: isolated study modules.
- `/api/documents`, `/api/catalog/search`: passage and metadata search.
- `/api/answer`: routed evidence answers; optional OpenRouter synthesis.

The server binds to `127.0.0.1`. It is a local prototype and has no deployment authentication or multi-user database. Do not expose it to the Internet without a separate deployment/security review.

## UI calculations

Python handles unit validation, paired measurements, core summaries, model inference and answer calculations. Some presentation statistics (quartiles and Spearman correlation) are computed in JavaScript from the selected records. Their predicates must remain consistent with backend exclusions. LLM arithmetic is never the authority for a numerical result.

## Dependency policy

`pyproject.toml` is canonical. `requirements.txt` and `requirements-train.txt` are hashed lockfiles. Runtime needs FastAPI, Uvicorn, Pydantic, pypdf and openpyxl. Training adds scikit-learn and NumPy. No frontend package installation or build pipeline is required.

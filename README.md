<div align="center">

<img src="frontend/assets/logo.jpg" width="100" alt="GeNAIus logo">

# GeNAIus · Flame in Freefall

**Explore NASA combustion experiments. Compare measured evidence. Trace every claim.**

![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)
![Backend](https://img.shields.io/badge/Backend-FastAPI-009688?logo=fastapi&logoColor=white)
![Models](https://img.shields.io/badge/Models-scikit--learn-F7931E?logo=scikitlearn&logoColor=white)
![Frontend](https://img.shields.io/badge/Frontend-JavaScript%20%C2%B7%20SVG%20%C2%B7%20Canvas-F7DF1E)
![Challenge](https://img.shields.io/badge/NASA%20Space%20Apps-Flame%20in%20Freefall-E8492C)

[Quick start](#quick-start) · [Architecture](docs/ARCHITECTURE.md) · [Data & models](docs/DATA_AND_MODELS.md) · [AI transparency](docs/AI_USE.md) · [Testing](docs/TESTING.md) · [Security](SECURITY.md)

</div>

---

## Presentation / Sunum

Both versions contain seven slides. / Her iki sürüm de yedi slayttır.

| Language / Dil | Slides / Slaytlar |
|---|---|
| **English** | **[Open PDF](docs/presentation/genaius-presentation-en.pdf)** · [Download PDF](https://github.com/Umitsencer/genaius-flame-in-freefall/raw/refs/heads/main/docs/presentation/genaius-presentation-en.pdf) |
| **Türkçe** | **[PDF'yi aç](docs/presentation/genaius-presentation-tr.pdf)** · [PDF'yi indir](https://github.com/Umitsencer/genaius-flame-in-freefall/raw/refs/heads/main/docs/presentation/genaius-presentation-tr.pdf) |

[Speaker notes / Konuşmacı notları](docs/presentation/speaker-notes.md). Editable HTML sources: [English](docs/presentation/index.html) · [Türkçe](docs/presentation/index-tr.html). Download an HTML source together with its `assets/` folder to present it locally; GitHub displays HTML as source code.

## Why GeNAIus?

NASA combustion research spans experimental tables, technical reports and different physical regimes. GeNAIus brings selected sources into a research workflow: find a study, inspect its actual conditions, compare measurements, identify coverage gaps and open the original evidence.

Built for the **NASA Space Apps Challenge — Flame in Freefall**, by **Team GeNAIus**, Kırklareli. This is an independent research prototype, not an official NASA product or a fire-safety certification tool.

## Four research views

| View | What you can do |
|---|---|
| **Material Lab** | Explore 129 PSI-25 BASS-II runs across 107 unique Sample # identifiers; filter materials and geometry; inspect paired gas changes, distributions and coverage. |
| **Fire Animation & Models** | View a conceptual FLEX droplet animation, check scenario coverage and inspect separate Ridge burning-rate and logistic extinction estimates. |
| **SAFFIRE Case Study** | Follow published VI-3 events, compare reported gas increases and inspect related SAME/aerosol evidence with explicit source limitations. |
| **Data & Sources** | Search a 24-study metadata catalog, inspect 403 core runs, compare records, search report passages and export traceable subsets. |

The evidence assistant routes table calculations, scenario checks and report questions to the appropriate source. Optional OpenRouter synthesis adds a model-written explanation; calculations and source selection remain explicit.

## Evidence before explanation

- **403 core runs:** PSI-25 BASS-II (129) and PSI-69 FLEX (274), analyzed within their respective studies.
- **Separate modules:** PSI-39 CFI and PSI-99 SAFFIRE-II are never pooled into core averages. SAFFIRE IV–VI is a published-report case study.
- **Traceable records:** raw values, normalized units, measurement statuses, test IDs, CSV locations and SHA-256 fingerprints.
- **Honest missingness:** missing, invalid, approximate and above-limit measurements remain distinct; missing does not become zero.
- **Scenario coverage:** `TESTED / PARTIAL / GAP` describe indexed evidence, not a safety ranking.
- **Bounded AI:** schema, citation and numerical checks; explicit deterministic fallback when an LLM response fails validation.

## Quick start

### Prerequisites

- Python **3.11+**; the lockfiles and local validation target Python 3.11.
- Git. Node.js is optional for frontend tests.
- Internet access for the initial official NASA source downloads. An LLM key is optional.

```bash
git clone https://github.com/Umitsencer/genaius-flame-in-freefall.git
cd genaius-flame-in-freefall
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements.txt
.\.venv\Scripts\python.exe scripts/download_raw_data.py
```

Start with the virtual environment's Python directly; activation and execution-policy changes are unnecessary:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m genaius.prototype.server --port 8765
```

### macOS / Linux

```bash
python3.11 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/python scripts/download_raw_data.py
PYTHONPATH=src .venv/bin/python -m genaius.prototype.server --port 8765
```

Open **http://127.0.0.1:8765/**. The entry page opens the data explorer. Stop the server with **Ctrl+C**. Launchers are also provided in `scripts/run_local.ps1` and `scripts/run_local.sh`.

The downloader retrieves **9 files** for the complete application. `--core-only` downloads 5 core files; CFI and SAFFIRE-II then remain unavailable. Raw files are downloaded locally and are not committed.

### Optional NVIDIA / OpenRouter answers

Copy `.env.example` to `.env` in this repository, insert your own `OPENROUTER_API_KEY`, then restart the server. Never commit or share `.env`.

```powershell
Copy-Item .env.example .env
```

The configured model ID is `nvidia/nemotron-3.5-super-vl:free`. Only explicitly named `:free` models are accepted. Availability and quota depend on the provider. Without a key, the app uses deterministic evidence answers. Table calculations and scenario checks use zero LLM calls even when a key is configured.

## Architecture

```text
Official NASA CSV / XLSX / PDF / DOCX
                 │
       typed records + source provenance
                 │
    ┌────────────┼────────────────────┐
    │            │                    │
table queries  BM25 passages     FLEX model inference
scenario check report evidence  pre-fitted JSON coefficients
    │            │                    │
    └────────────┼────────────────────┘
                 │
       optional bounded LLM explanation
       schema / citation / numerical checks
                 │
        FastAPI → HTML / CSS / JavaScript
```

No database server, embedding model or vector database is required. CSV/JSON files and in-memory Python records support the local research workflow. Graphics use SVG and Canvas. Some chart summaries are computed in JavaScript; typed filtering, model inference and answer calculations run in Python.

## Project structure

```text
genaius-flame-in-freefall/
├── src/genaius/
│   ├── api/          # FastAPI routes, local server and static allowlist
│   ├── schemas/      # Strict request and LLM output models
│   ├── data/         # Typed contracts, loading, quality and queries
│   ├── retrieval/    # Source extraction and deterministic BM25
│   ├── answering/    # Evidence answers, bounded prompts and validation
│   ├── flex/         # Dataset, training, inference and support gates
│   └── *.py          # Scenario, catalog, SAFFIRE and CFI domain services
├── frontend/         # Four research pages, shared JS/CSS and UI tests
├── data/processed/   # Model artifacts, source manifests and derived evidence
├── data/raw/         # Downloaded locally; ignored by Git
├── scripts/          # Download, launch, research and diagnostic commands
├── tests/            # Unit, integration, HTTP and evidence-boundary tests
├── docs/             # Architecture, data/model notes and delivery guide
├── pyproject.toml    # Canonical dependencies
└── requirements*.txt # Hashed runtime / training lockfiles
```

## Verification

See [testing and acceptance](docs/TESTING.md) for the actual release validation record and manual checks.

```powershell
$env:PYTHONPATH = "src;tests"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node frontend/tests/lib.test.js
node frontend/tests/stats.test.js
```

Full dataset tests require all 9 downloaded files. Training-specific tests additionally require `requirements-train.txt`; runtime inference does not import scikit-learn. Tests check contracts and known cases, not universal scientific or language-model correctness.

## Scientific limits

- Microgravity measurements do not establish Moon/Mars partial-gravity behavior.
- The animation is conceptual, not a measured replay or CFD simulation.
- FLEX predictions are statistical estimates within observed support, not physical laws or spacecraft fire-safety probabilities. The logistic score is uncalibrated and has material false positives; evaluation artifacts retain those errors.
- SAFFIRE gas increases are not a crew-exposure dose. The derived **344 s** interval is not a certified operational alarm latency.
- SHA-256 proves file identity, not scientific correctness. Numerical validation is not a guarantee of complete semantic truth.

## Sources & attribution

[NASA PSI](https://psi.nasa.gov/) · [FLEX report](https://ntrs.nasa.gov/citations/20150023456) · [BASS-II report](https://ntrs.nasa.gov/citations/20210011385) · [SAFFIRE VI report](https://ntrs.nasa.gov/citations/20240002981)

See [NOTICE.md](NOTICE.md) for dataset/report rights, third-party conditions and software licensing status. Public source availability does not imply NASA endorsement.

**Team GeNAIus** · NASA Space Apps, Kırklareli · [Repository maintainer](https://github.com/Umitsencer)

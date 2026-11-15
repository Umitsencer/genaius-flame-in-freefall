# GeNAIus Frontend (`frontend/`)

Static HTML/CSS/JS pages served by the Python GeNAIus HTTP server (`scripts/run_local.ps1`, default `http://127.0.0.1:8765/`). Opening `/`, `/api/*`, or `/docs/*` flows directly requires running the Python backend rather than a bare static server.

## Pages

- `index.html`: Minimal entry redirect to `data.html`.
- `material-lab.html`: Microgravity material screening (`PSI-25` BASS-II, `129` tests), coverage card, and gas comparison (`js/lab.js`, `js/lab-charts.js`, `js/stats.js`).
- `fire.html`: Conceptual droplet animation, deterministic Scenario Evidence Check, and a separate FLEX pre-test model panel (`js/flex-predictor-ui.js`, `css/flex-predictor.css`). The scenario panel reports table coverage; the model panel reports Ridge burning-rate estimates and uncalibrated logistic extinction scores with support gates, nearest measured runs and evaluation details.
- `case-saffire.html`: Isolated `SAFFIRE IV–VI` and `SAME` smoke/smoldering case viewer (`js/case-saffire.js`, `saffire_case.py`).
- `data.html`: Isolated study browser (`BASS-II`, `FLEX`, isolated `PSI-39 CFI`, isolated `PSI-99 SAFFIRE-II`), row citations/BibTeX, and source manifest (`js/data.js`).

The active frontend consists of these four research pages; there is no React/npm build step.

## Shared UI & Tests

- `js/api.js`: Fetch wrappers for `/api/schema`, `/api/search`, `/api/flex/*`, `/api/saffire/case`, `/api/coverage/evaluate`, and `/api/answer`.
- `js/chat.js`: Evidence assistant drawer supporting `auto`, `core`, `saffire_case`, and `flex_prediction` scopes, typed `validation_diagnostics` inside `<details class="gc-tech">`, one-click scope switching, and `Escape` focus restoration.
- `js/i18n.js` / `js/i18n-tr.js`: English/Turkish UI translator.

Run JavaScript unit checks:

```powershell
node frontend/tests/lib.test.js
node frontend/tests/stats.test.js
```

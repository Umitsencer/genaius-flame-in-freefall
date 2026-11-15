# Data and models

## Included and downloaded material

The release includes processed JSON artifacts and provenance records. `scripts/download_raw_data.py` retrieves the original NASA inputs into ignored `data/raw/`. NASA availability can affect initial setup; inspect downloader errors rather than treating an unavailable source as zero matching evidence.

| Study | Use | Boundary |
|---|---|---|
| PSI-25 BASS-II | 129 runs / 107 unique Sample # identifiers | Solid materials; `% vol` O₂; pressure is not a calibrated comparison field |
| PSI-69 FLEX | 274 CSV runs | Droplet fuels; `% mol` O₂; pressure, diameter and outcomes |
| PSI-39 CFI | 227 workbook records, 144 candidate analysis records | Separate descriptive module; zero cool-flame extinction diameters remain unresolved raw zeros |
| PSI-99 SAFFIRE-II | 9 physical sample cards | Six auxiliary rows are not extra physical samples |
| SAFFIRE IV–VI | Published conditions and gas results | Report-derived case data, not PSI raw measurement series |
| SAME/SAME-2 | Related smoke/detector findings | Separate evidence; not pooled with Cygnus gas measurements |

The 24-study catalog is broader than the numerical core. A catalog hit does not mean its full raw experiment is integrated.

## Source contracts

Records preserve source headers, raw values, units, measurement status, identity and SHA-256. `measured`, `missing`, `invalid`, `approximate`, `above_limit` and `meaning_unverified` are distinct. A gas change requires valid measured initial and final endpoints. Repeated Sample # identifiers are preserved as runs or explicitly summarized by sample median.

Scenario matching uses ±0.05 O₂ percentage points and ±0.01 atm within its recorded dimensions. `GAP` refers only to indexed sources; `PARTIAL` is used when pressure/gravity support differs or is unrecorded. These tolerances do not constitute experimental uncertainty estimates.

## FLEX training and inference

- Inputs: fuel indicator, O₂/CO₂/He fractions, pressure and initial droplet diameter.
- Feature maps: log pressure and fuel-interaction terms; 8 regression and 10 classification features.
- Training: `FunctionTransformer → StandardScaler → Ridge / LogisticRegression` in scikit-learn pipelines.
- Selected models: `ridge_phys8` (`alpha=2`) and `logit_phys10` (`C=0.5`).
- Comparators: Dummy, Decision Tree and Random Forest estimators.
- Evaluation: grouped condition splits with target-agnostic `GroupKFold`; MAE/RMSE/R² and classification ROC-AUC/Brier/confusion counts.
- Runtime: `flex_condition_models_v2_sklearn.json`, evaluated with saved coefficients and scaling; no runtime training.

See `data/processed/flex_acceptance_v2.json` and `flex_eval_report_v2_sklearn.json` for the recorded protocol and metrics. The uncalibrated extinction score has substantial false positives and is not a safety probability. Raw-feature Shapley bars remain disabled after the recorded validity audit. Outside support, return `NOT_SUPPORTED` rather than extrapolating.

Training reproduction (after all raw downloads):

```powershell
.\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-train.txt
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe scripts/research/compare_flex_sklearn.py --repo-root .
```

## Case study derivations

`pO₂ = pressure × O₂ mol% / 100`. The VI-3 interval `981 − 637 = 344 s` connects reported timestamps. The 1 mg/m³ value is the authors' selected smoke-concentration criterion, not a demonstrated calibrated ionization-detector alarm setting. Reported burn duration (780 s) is separate from flow termination at experiment clock 1420 s.

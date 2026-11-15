# PSI-39 CFI — audited feasibility reference

This reference is retained at its historical path because the research catalog records its provenance. CFI is integrated as a **separate descriptive module**, outside the 403-run PSI-25/PSI-69 core.

- Workbook: 227 unique experiment keys joined across five sheets by Flex Number; string key `1274A` is preserved.
- Completed analysis: 146 records. Excluding two unignited/failed-ignition records leaves **144 candidate analysis records**, not a declaration that all values are valid.
- Positive `Dext,cool`: 69; raw zeros: 48; missing: 25; literal NaN: 2, within the 144-record pool.
- `kcool`: 124 finite positive observations and 20 missing in the candidate pool.
- Raw zero extinction diameter remains `interpretation_unresolved`, not automatic complete combustion or a positive-diameter observation.
- Extrapolation and reignition flags are retained for sensitivity views; not silently deleted.
- Comparisons are stratified by pressure, fiber condition and fuel; uncertainty from FLEX cannot automatically be transferred to CFI.
- **Predictive modeling decision: ERTELE (deferred)**. Farnesane records do not have completed analysis in the audited table and are excluded from this candidate analysis pool.

Reproduce with `scripts/research/audit_cfi_eligibility.py`; inspect `data/processed/cfi_eligibility_audit.json` and the downloaded PSI-39 workbook. See [data/model notes](../../DATA_AND_MODELS.md) for active module boundaries. The workbook is downloaded separately; raw files are not included in Git.

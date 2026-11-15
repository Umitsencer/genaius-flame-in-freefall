"""PSI-69 FLEX condition predictor (pre-test inputs only, JSON-coefficient inference).

Modules: `common` (constants/errors), `dataset` (eligible training rows, support reference),
`model` (feature maps + JSON inference), `artifacts` (signed JSON load), `inference`
(validation, support gating, Shapley, condition map), `reports` (export, evidence bundle),
`training` (scikit-learn; optional `train` dependencies, never imported at runtime).
"""

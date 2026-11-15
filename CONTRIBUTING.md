# Contributing

1. Create a focused branch from `main`.
2. Keep source changes in `src/genaius`, UI changes in `frontend`, and tests in their existing locations.
3. Preserve NASA source identifiers, raw values, units, measurement statuses and provenance.
4. Run the applicable checks from [testing](docs/TESTING.md); explain unavailable checks.
5. Open a pull request with the user-visible change, evidence, test results and known limits.

Do not commit credentials, raw downloads, virtual environments, generated caches or local screenshots containing private information. New datasets require documented origin, usage conditions and scientific compatibility. Do not pool different experimental regimes or present coverage/model scores as spacecraft safety certification.

Research scripts and legacy artifacts are retained for reproducibility. An old artifact is not an active model merely because it exists. Check [data/model notes](docs/DATA_AND_MODELS.md) before changing training or activating a model.

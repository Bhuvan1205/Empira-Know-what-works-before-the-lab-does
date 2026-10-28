# Release v1.0, sealed 14 Oct 2026

**Scope:** Phases A–F complete, plus the Empira demo (FastAPI backend and Streamlit app in `app/`). Phase E is pipeline-complete and tested; it awaits ARMD-MGB data.

**Sealed artefacts:**
- `models/`: 33 files, checksums in `models/SHA256SUMS`;
- `data/predictions/final_{val,test}.parquet` (rebuilt locally, not tracked);
- reports 01–07;
- pipeline code, checksums in `release_code.sha256`.

**Release checks:** `python tests/run_tests.py` → 10/10 passed at sealing: checksums, leakage rules, feature exclusions, temporal split, exact reproduction of test predictions, manifest metrics, demo API behaviour, Phase C thresholds and the external schema check. App: `python -m pytest app/backend/tests` → 11/11.

**Reproduction:** both final components were retrained from scratch into a separate folder → identical predictions (max difference 0.0) and identical calibration.

**Do not change:** anything in `models/`, `src/predictor.py`, or the thresholds in `src/demo_api.py` (they must equal `reports/phaseC/decision_summary.json`; a test enforces this). The app builds on `src/demo_api.py`.

**Next:**
1. External validation when ARMD-MGB arrives: `python src/08_external_validate.py --raw data/armd_mgb --site mgb`.
2. Silent-mode evaluation on live orders.
3. Write-up (TRIPOD+AI).

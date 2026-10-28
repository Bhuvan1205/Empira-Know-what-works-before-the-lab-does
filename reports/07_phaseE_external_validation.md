# Phase E: external validation pipeline (ready; waiting for ARMD-MGB data)

Status 14 Oct 2026: **the pipeline is built and tested; the MGB data has not arrived** (`data/armd_mgb` is empty, pending PhysioNet credentialing).
Code: `src/08_external_validate.py`, fixture generator `tests/make_mgb_like_fixture.py`. Outputs: `reports/phaseE/<site>/`.

## When the data arrives: one command

1. Download ARMD-MGB from PhysioNet into `data\armd_mgb\` (CSV files in ARMD format).
2. Run:

```
python src/08_external_validate.py --raw data/armd_mgb --site mgb
```

3. Read `reports/phaseE/mgb/summary.json`, `metrics_by_antibiotic.csv` and `coverage.json`.

The model is **frozen**: no retraining and no refitting of the shipped calibration. The same leakage rules are applied (history ≥3 days, exposures ≥1 day).

## What it does

| Step | Detail | Output |
| --- | --- | --- |
| Schema check | Required: cohort and demographics tables. Optional: ward, ADI, nursing home, prior resistance, prior organisms, antibiotic exposure, procedures. Missing optional tables are left blank, not fatal. | `schema_check.json` |
| Feature build | Same code as Stanford (`02_build_features.py`) via `ARMD_RAW` / `ARMD_PROCESSED`. Antibiotic spellings harmonised (e.g. "Trimethoprim-Sulfamethoxazole", "PIPERACILLIN-TAZOBACTAM"). | `data/processed_external/<site>/` |
| Scoring | Frozen ensemble. Features absent at the site are set to "not recorded"; antibiotics outside the 28 are listed, not scored. | `coverage.json` |
| Metrics | Per antibiotic: AUROC with patient-bootstrap 95% CI, AUPRC, Brier, sensitivity at 90% specificity, calibration slope/intercept, observed vs predicted rate; by year. | `metrics_by_antibiotic.csv`, `metrics_by_year.csv`, `summary.json` |
| Sensitivity | Refit only the calibration on the site's earliest 30% of cultures; evaluate on the rest (model weights untouched). This shows whether local recalibration would be enough. | `local_recalibration_sensitivity.csv` |

## Tests run

| Test | Purpose | Result |
| --- | --- | --- |
| **Identity:** Stanford raw data through the external pipeline, years 2022–2024 | The rebuild-and-score path must reproduce the frozen test results | **Pass:** mean AUROC 0.7795, AUPRC 0.4543, Brier 0.0948, all identical to Phase A/B |
| **Regression:** rebuild Stanford features with the generalised builder | No change to the model's inputs | **Pass:** all 6 processed tables identical |
| **MGB-like fixture:** 4,000 Stanford patients with no ICU column, an extra urgent-care column, no ADI table, hyphenated/upper-case antibiotic names, plus fosfomycin | Pipeline survives MGB's known schema differences | **Pass:** 28 antibiotics scored including the renamed ones; 20 out-of-model antibiotics reported (fosfomycin, daptomycin, ceftazidime/avibactam…); missing ADI and ICU handled |

The fixture's AUROC (0.83) is not a performance estimate: those patients' earlier cultures were in the training data.

## Known MGB differences to watch

- Ward categories are inpatient / outpatient / ER / urgent care / day surgery, with no ICU flag, so the ICU feature will be blank.
- MGB adds MIC values and beta-lactamase fields. The frozen model doesn't use them, but they are a natural extension.
- If MGB file names differ from Stanford's, rename them to the names in `schema_check.json`. The check names anything it can't find.

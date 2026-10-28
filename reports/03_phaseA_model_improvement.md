# Phase A: model improvement

Run 14 Oct 2026. Code: `src/02_build_features.py labs_vitals`, `src/04b_organism_probs.py`, `src/04_experiments.py`.
Every choice below was made on the **2021 validation year only**; the 2022–2024 test set was not used for selection.

## Selected model

**Average of two LightGBM models:** one model per antibiotic plus one shared model across all 28 antibiotics. Antibiotics with ≥10,000 labels are modelled.

| | Validation 2021 | Test 2022–24 |
| --- | --- | --- |
| Mean AUROC, 28 antibiotics | 0.803 | **0.780** |
| Mean AUROC, top 10 antibiotics | 0.770 | 0.761 (baseline was 0.758) |
| Mean AUPRC / Brier, 28 antibiotics | — | 0.454 / 0.096 |
| Mean AUROC, new patients only | — | 0.748 |

Per-antibiotic test results: `reports/phaseA/final_metrics_by_antibiotic.csv`. Frozen components: `models/final_manifest.json`.

## Experiments (validation, mean over 28 antibiotics unless noted)

| Experiment | Val AUROC | Val AUPRC | Val Brier | Decision |
| --- | --- | --- | --- | --- |
| Per-antibiotic, no labs (top 10) | 0.7702 (top 10) | — | 0.0978 (top 10) | reference |
| Per-antibiotic + labs/vitals (top 10) | 0.7705 (top 10) | — | 0.0985 (top 10) | **Rejected:** no gain, and the lab window timing is unverified |
| Per-antibiotic, no labs (28) | 0.8022 | 0.4938 | 0.0931 | component |
| Shared, default (28) | 0.7974 | 0.4921 | 0.0921 | — |
| Shared, tuned: 127 leaves, min leaf 200 (28) | 0.7982 | 0.4951 | 0.0921 | component |
| Shared, tuned: lr 0.02 | +0.0006 global AUROC, still running at 1,100 rounds | — | — | Dropped: too slow on a 3 GB / 2-core machine for a negligible gain |
| Per-antibiotic + organism probabilities (28) | 0.8032 | 0.4955 | 0.0945 | **Rejected:** +0.001 AUROC, worse Brier, an extra model to maintain |
| **Average of per-antibiotic + shared tuned** | **0.8027** | **0.4992** | **0.0919** | **Selected** (best AUPRC and Brier, AUROC tied) |

## Notes

- **Weakest antibiotics** (test AUROC < 0.72): ampicillin/sulbactam 0.684, pip/tazo 0.706, tetracycline 0.711, ampicillin 0.715, nitrofurantoin 0.715.
- **Strongest:** amikacin 0.924, meropenem 0.921, linezolid 0.900. These are rare-resistance drugs, so AUPRC is the more honest measure for them (0.23–0.39).
- **Penicillin** falls from 0.911 (validation) to 0.757 (test). It is a small group (2,107 test rows) and the behaviour suggests a shift in who gets tested; this is checked in Phase B.
- Memory: the feature builder was rewritten to peak at 1.6 GB (was 3.6 GB), so the pipeline runs on a 4 GB laptop.

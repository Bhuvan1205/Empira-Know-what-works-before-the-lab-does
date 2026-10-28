# Data

No patient data is stored in this repository. Everything here is downloaded or rebuilt locally and is ignored by git.

| Folder | What goes there | How to get it |
| --- | --- | --- |
| `armd_stanford/` | The ARMD-Stanford CSV tables (`microbiology_cultures_cohort.csv`, `..._demographics.csv`, `..._ward_info.csv`, `..._microbial_resistance.csv`, `microbiology_culture_prior_infecting_organism.csv`, `..._antibiotic_class_exposure.csv`, `..._priorprocedures.csv`, `..._prior_med.csv`, `..._nursing_home_visits.csv`, `..._adi_scores.csv`, and the rest; about 4 GB) | Download from Dryad: https://doi.org/10.5061/dryad.jq2bvq8kp |
| `armd_mgb/` | ARMD-MGB (Mass General Brigham) in the same format, for external validation | PhysioNet, credentialed access |
| `processed/` | Leakage-safe features and labels (Parquet) | `python run_all.py --only features` |
| `predictions/` | Validation and test predictions, including the sealed `final_val.parquet` and `final_test.parquet` | `python run_all.py` (stages `final` onward) |
| `processed_external/` | Features for an external site | `python src/08_external_validate.py --raw data/armd_mgb --site mgb` |

The demo API needs `models/` and `processed/` at startup, and `predictions/final_test.parquet` for the real-case pages.

Paths can be overridden with `ARMD_RAW`, `ARMD_PROCESSED`, `ARMD_PRED`, `ARMD_MODELS` and `ARMD_REPORTS`.

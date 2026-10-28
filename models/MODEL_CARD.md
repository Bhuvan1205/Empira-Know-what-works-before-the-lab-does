# Model card: ARMD empiric antibiotic-resistance predictor, v1.0 (sealed 14 Oct 2026)

**Task.** At the moment a urine, blood or respiratory culture is ordered (organism unknown), predict, for each of 28 antibiotics, the probability that the culture will grow an organism resistant to that antibiotic. Label: Resistant vs Susceptible/Intermediate; worst result across organisms in the culture.

**Intended use.** Research and demonstration of AI-assisted empiric antibiotic selection and stewardship. **Not a medical device and not for clinical decisions.**

**Data.** ARMD-Stanford (Dryad, doi:10.5061/dryad.jq2bvq8kp): adult cultures at Stanford Health Care. Modelling set 2008–2024: 118,748 positive cultures with susceptibility results, 1.47M culture × antibiotic rows. Split by time: train 2008–2020 (1,013,479 rows), validation 2021 (140,359), test 2022–Jan 2024 (317,134).

**Inputs (90 features).** Specimen type, care setting (outpatient/ER/inpatient/ICU), age band, anonymised sex code, area deprivation index, nursing-home contact. The patient's earlier resistant results and prior organisms (≥3 days before the order), earlier antibiotic-class exposures and procedures (≥1 day), and the patient's own prior results for the target antibiotic.
**Excluded by design:** organism identity, labs/vitals (window undocumented), same-day medications (treatment leakage).

**Model.** Mean of (a) 28 per-antibiotic LightGBM models and (b) one shared LightGBM over all antibiotics (127 leaves, min leaf 200), followed by per-antibiotic logistic recalibration fitted on 2021. All choices were selected on 2021 validation only.

**Performance (test 2022–24).**
- Mean AUROC 0.780 (95% CI 0.772–0.787, patient bootstrap); 0.761 for the 10 most-tested antibiotics; 0.748 for patients new to the system.
- Mean AUPRC 0.454; mean Brier 0.095; median calibration ECE 0.012, slope 0.98.
- Per antibiotic: `reports/phaseA/final_metrics_by_antibiotic.csv`; CIs: `reports/phaseB/bootstrap_auroc_ci.csv`.

**Decision impact (retrospective, urine, n = 7,436).** At clinicians' error rate, second-line use falls from 23.3% to 7.7%. At clinicians' second-line use, mismatched therapy falls from 11.8% to 8.0% (`reports/05_phaseC_decision_analysis.md`).

**Known limitations.**
- Single health system. External validation (ARMD-MGB) is pending.
- Performance decays over time (AUROC 0.803 → 0.771 from 2021 to 2023): refit the calibration yearly and retrain every 1–2 years.
- Weaker for blood cultures (0.69), ER (0.71), age 85+ (0.72), and more deprived neighbourhoods (small groups).
- Penicillin testing became selective in 2022, so calibration is poor for penicillin (slope 0.62).
- A first-ever resistant infection with no history is hard to predict.
- The decision analysis ignores allergies, renal function, pregnancy and colonisation.

**Fairness.** Calibration-in-the-large is within ±1.3 points in every subgroup examined (specimen, setting, age, sex code, deprivation, new/returning patient). Deprivation contributes least to predictions (mean |SHAP| 0.04).

**Files.** `final_manifest.json` (components, metrics, versions), `final_calibration.json`, `per_ab_nolabs_all__*.txt` (28), `shared_t1.txt` + `_state_shared_t1.json`, `testing_frequency.json` (demo), `SHA256SUMS`. Experiment models that were not selected are not kept in the release; `python run_all.py --only experiments` rebuilds them into `models/experiments/`.

# ARMD-Stanford: per-antibiotic baselines

Run 12 Oct 2026. Code: `src/02_build_features.py` (parts `base`, `history`, `own_history`) and
`src/03_train_baseline.py agnostic|organism`. Metrics: `reports/baseline/*_metrics.csv`; importances: `*_feature_importance.csv`.

## Result

Predicting at culture order (organism unknown), LightGBM reaches **mean AUROC 0.758** across the 10 largest antibiotics on 2022–2024 data. That compares with 0.547 for the antibiogram baseline and 0.661 for a prior-resistance rule. Once the organism is known, the mean rises to **0.837** (antibiogram 0.702).

## Setup

- **Unit:** culture × antibiotic (organism-agnostic; the label is the worst result across organisms) or culture × organism × antibiotic (organism-known). Label = Resistant vs Susceptible/Intermediate.
- **Split:** temporal. Train 2008–2020, validate 2021 (early stopping only), test 2022–2024. "New patients" = test patients with no culture in the training period.
- **Model:** one LightGBM per antibiotic (lr 0.03, 31 leaves, early stopping on validation AUROC). No tuning yet.
- **Features (leakage rules from report 01):** demographics, ward, ordering mode, culture type, area deprivation index, nursing home; prior resistance and prior organisms (≥3 days before order); antibiotic class exposure and procedures (≥1 day); patient's own prior results for the target antibiotic rebuilt from the cohort table (≥3 days). Not used: labs and vitals (window unverified), same-day medications, organism (except in the organism-known variant).
- **Comparators** (fit on the training period): *antibiogram* = resistance rate by culture type (agnostic) or by organism (organism-known); *prior-R rule* = the same rate split by "patient had a resistant result to this antibiotic ≥3 days earlier".

## Organism-agnostic (at culture order)

| Antibiotic | Test n | Resistant % | AUROC | AUPRC | Sens @ 90% spec | Brier (antibiogram) | AUROC antibiogram | AUROC prior-R rule | AUROC new patients |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Meropenem | 18,556 | 0.6 | 0.906 | 0.352 | 0.82 | 0.005 (0.006) | 0.818 | 0.843 | 0.858 |
| Levofloxacin | 15,493 | 18.8 | 0.789 | 0.575 | 0.54 | 0.113 (0.154) | 0.525 | 0.687 | 0.747 |
| Ciprofloxacin | 19,078 | 19.0 | 0.777 | 0.566 | 0.51 | 0.116 (0.154) | 0.516 | 0.677 | 0.739 |
| Ceftriaxone | 17,691 | 11.0 | 0.764 | 0.454 | 0.48 | 0.077 (0.098) | 0.482 | 0.661 | 0.742 |
| Cefazolin | 16,714 | 20.5 | 0.754 | 0.538 | 0.46 | 0.130 (0.158) | 0.538 | 0.645 | 0.742 |
| TMP/SMX | 19,137 | 21.7 | 0.734 | 0.522 | 0.42 | 0.140 (0.171) | 0.520 | 0.630 | 0.705 |
| Gentamicin | 19,363 | 8.4 | 0.724 | 0.362 | 0.43 | 0.064 (0.077) | 0.515 | 0.644 | 0.676 |
| Nitrofurantoin | 16,553 | 12.7 | 0.713 | 0.344 | 0.35 | 0.098 (0.111) | 0.500 | 0.602 | 0.699 |
| Ampicillin | 16,878 | 52.8 | 0.711 | 0.746 | 0.38 | 0.213 (0.248) | 0.521 | 0.611 | 0.696 |
| Pip/Tazo | 17,749 | 2.9 | 0.705 | 0.140 | 0.40 | 0.027 (0.028) | 0.535 | 0.607 | 0.696 |
| **Mean** | | | **0.758** | **0.460** | **0.48** | **0.098 (0.121)** | **0.547** | **0.661** | |

## Organism-known (after identification)

| Antibiotic | AUROC | AUPRC | Sens @ 90% spec | AUROC antibiogram | AUROC new patients |
| --- | --- | --- | --- | --- | --- |
| Meropenem | 0.970 | 0.370 | 0.96 | 0.931 | 0.954 |
| Nitrofurantoin | 0.965 | 0.881 | 0.89 | 0.948 | 0.969 |
| Cefazolin | 0.857 | 0.765 | 0.68 | 0.736 | 0.844 |
| Levofloxacin | 0.839 | 0.636 | 0.59 | 0.648 | 0.814 |
| Ampicillin | 0.831 | 0.869 | 0.60 | 0.715 | 0.820 |
| Ciprofloxacin | 0.814 | 0.599 | 0.54 | 0.614 | 0.791 |
| Ceftriaxone | 0.783 | 0.461 | 0.49 | 0.560 | 0.764 |
| TMP/SMX | 0.779 | 0.552 | 0.44 | 0.620 | 0.757 |
| Gentamicin | 0.765 | 0.392 | 0.45 | 0.594 | 0.733 |
| Pip/Tazo | 0.762 | 0.149 | 0.49 | 0.655 | 0.757 |
| **Mean** | **0.837** | **0.568** | **0.61** | **0.702** | |

Nitrofurantoin and meropenem are high mainly because resistance is near-intrinsic to certain organisms (e.g. Proteus, Klebsiella for nitrofurantoin), which the antibiogram already captures.

## Findings

1. **Patient history drives the agnostic model.** Days since the patient's last resistant result to the same antibiotic is the top feature (15% of gain), followed by culture type and prior resistance to related drugs.
2. **The provided prior-resistance table covers only 26 of 55 antibiotics.** TMP/SMX, pip/tazo and amox/clav are missing. Rebuilding history from the cohort table raised TMP/SMX AUROC from 0.680 to 0.734 and pip/tazo from 0.690 to 0.705. Keep this step.
3. **New patients score 0.01–0.05 lower AUROC.** This is the honest number for first-time patients.
4. **Calibration:** Brier beats the antibiogram for every antibiotic. Reliability curves are not yet checked.

## Next steps (in order of expected gain)

1. Add labs/vitals as a sensitivity block (first_* values) and measure the gain.
2. One multi-task model across antibiotics (shared history, antibiotic as a feature), which helps rare antibiotics.
3. Calibration curves plus a decision analysis: how often a narrower drug is recommended and still covers the organism.
4. External validation on ARMD-MGB once PhysioNet access arrives.

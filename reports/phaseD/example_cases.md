# Worked example cases (2022-2024 test set)

Contributions are SHAP values in log-odds: positive pushes toward resistance, negative toward susceptibility.

## High predicted risk, resistant (correct)

- Antibiotic: **penicillin**, specimen: RESPIRATORY, ordered as: Outpatient
- Predicted resistance risk: **98.1%**; actual result: **Resistant**

| Factor | Value in this case | Contribution (log-odds) |
| --- | --- | --- |
| Last resistant result to this antibiotic | 117 days ago | +1.86 |
| Specimen | RESPIRATORY | +0.93 |
| Antibiotic | penicillin | +0.91 |
| Earlier resistance to this antibiotic (registry table) | 117 days ago | +0.85 |
| Number of earlier resistant results to this antibiotic | 27 | +0.85 |
| Earlier resistance to penicillin | 117 days ago | +0.80 |

## Low predicted risk, susceptible (correct)

- Antibiotic: **ciprofloxacin**, specimen: URINE, ordered as: Outpatient
- Predicted resistance risk: **2.3%**; actual result: **Susceptible/Intermediate**

| Factor | Value in this case | Contribution (log-odds) |
| --- | --- | --- |
| Last tested for this antibiotic | 16 days ago | -0.53 |
| Earlier infection with escherichia | 14 days ago | -0.39 |
| Antibiotic | ciprofloxacin | +0.21 |
| Age band (0 = 18-24 ... 8 = 90+) | 1 | -0.19 |
| Earlier exposure to fluoroquinolone | 1900 days ago | -0.18 |
| Earlier resistance to ciprofloxacin | none recorded | -0.16 |

## Low predicted risk but resistant (missed)

- Antibiotic: **ciprofloxacin**, specimen: URINE, ordered as: Outpatient
- Predicted resistance risk: **3.5%**; actual result: **Resistant**

| Factor | Value in this case | Contribution (log-odds) |
| --- | --- | --- |
| Last tested for this antibiotic | 219 days ago | -0.22 |
| Earlier exposure to macrolide lincosamide | 2454 days ago | -0.20 |
| Earlier infection with escherichia | 216 days ago | -0.19 |
| Earlier resistance to ciprofloxacin | none recorded | -0.17 |
| Antibiotic | ciprofloxacin | +0.15 |
| Last resistant result to this antibiotic | none recorded | -0.11 |

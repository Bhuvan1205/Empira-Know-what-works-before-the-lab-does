# ARMD-Stanford: data exploration and leakage audit

Run 12 Oct 2026 on `data/armd_stanford` (15 tables; comorbidity table not downloaded).
Code: `src/01_eda_leakage_audit.py` (parts `labels`, `audit`, `wide`, `merge`). Raw outputs: `reports/eda/`.

## Bottom line

- **Modelling set:** 1,601,980 labelled culture × organism × antibiotic pairs from 118,749 positive cultures and 67,008 patients. 16.6% are Resistant.
- **Leakage:** the feature tables are mostly built with a ≥1-day look-back. Three places still need rules: same-day medications (10.5% of medication rows), prior resistance results from 1–3 days before the order, and the lab/vitals windows, whose direction is undocumented.
- **Splits:** 82.6% of cultures come from patients with repeat cultures, so splits must be by patient. Resistance rates drop sharply in 2017, so the test set should be a later time period.

## 1. Cohort and labels

| Item | Value |
| --- | --- |
| Rows in cohort table | 2,241,050 (0 exact duplicates) |
| Patients / encounters / cultures | 283,715 / 574,584 / 751,075 |
| Dates (jittered) | Dec 1999 – Feb 2024; only ~2,000/yr before 2008, 13 in 2007 |
| Culture types | Urine 375,177 · Blood 291,365 · Respiratory 84,533 |
| Culture positive rate | 16.0% overall (blood 4.5%, respiratory 21.1%, urine 23.8%) |
| Susceptibility values | S 1,289,258 · R 265,071 · I 47,651 · Inconclusive 2,670 · Synergism 1,932 · Null 634,468 |
| Null susceptibility | 630,798 of 634,468 are negative cultures (no organism), so not a label |
| Labelled pairs (S/I/R) | 1,601,980 · 118,749 cultures · 67,008 patients |
| Resistant rate (R vs S+I) | 16.6% overall; blood 19.6%, respiratory 24.3%, urine 14.8% |
| Antibiotics with ≥10k labels | 28 of 55 |
| Top 10 organisms' share of labels | 86.9% (E. coli alone: 874,189 pairs, 61,347 cultures) |
| Organisms per positive culture | mean 1.12, max 7 |
| Same culture × organism × antibiotic with conflicting results | 7,742 keys (multiple isolates) |

Largest antibiotics (resistant rate): Ciprofloxacin 111k (18.5%), Gentamicin 105k (8.4%), Levofloxacin 104k (18.9%), TMP/SMX 103k (22.1%), Ampicillin 93k (48.3%), Nitrofurantoin 90k (11.0%), Pip/Tazo 86k (2.6%), Cefazolin 83k (19.7%), Ceftriaxone 71k (10.9%), Meropenem 70k (2.1%). Full list: `reports/eda/labels_by_antibiotic.csv`.

Clinically key pairs: E. coli – Ciprofloxacin 22.1%, – TMP/SMX 28.6%, – Ceftriaxone 12.1%, – Nitrofurantoin 1.7%; S. aureus – Oxacillin (MRSA) 11.2%, – Vancomycin 0%; K. pneumoniae – Meropenem 0.25%.

**Temporal drift.** Resistance in urine falls from 16.7% (2016) to 13.2% (2017) and respiratory from 25.3% to 20.1%, then stays flat. This looks like a change in testing panels or breakpoints, not biology. Models must be tested on later years.

## 2. Leakage audit

The prediction time is the culture order time. Nothing recorded after it may be a feature.

| Table | Rows | Cultures covered | Time column range (days before order) | Same-day (0 d) rows | Verdict |
| --- | --- | --- | --- | --- | --- |
| microbial_resistance (prior resistant results) | 2,161,648 | 22.2% | 1 – 5,773 | 0 | **Use with ≥3-day gap.** 2,584 rows are 1–3 days before the order, when that earlier culture may not have been reported yet. |
| prior_infecting_organism | 1,083,739 | 27.9% | 1 – 5,770 | 0 | Use with ≥3-day gap (same reason; 0.03% of rows fall within 1 day). |
| antibiotic_class_exposure | 5,402,486 | 64.5% | 1 – 5,748 | 0 | Safe (day 0 already excluded). |
| antibiotic_subtype_exposure | 5,402,486 | 64.5% | 1 – 5,748 | 0 | Safe; duplicates class table at finer grain, so use one. |
| prior_med | 9,823,458 | 76.6% | 0 – 5,748 | 1,034,527 (10.5%) | **Drop day-0 rows.** Day-0 rows are dominated by empiric IV antibiotics (pip/tazo, vancomycin, metronidazole) started at or after the order. This is treatment-indication leakage. |
| priorprocedures | 1,664,615 | 33.5% | 1 – 8,181 | 0 | Safe. |
| nursing_home_visits | 7,628 | 1.0% | 0 – 207 | 3,819 (50%) | Low risk (where the patient came from); keep, but rare. |
| labs (14-day window, Q25/median/Q75/first/last) | 1,408,677 | 65.6% | not given | — | **Unverified.** Window direction is undocumented, and there are ~2.9 rows per culture whose meaning is undocumented. Use `first_*` values only, or run a with/without sensitivity analysis. |
| vitals | 4,591,374 | 77.4% | not given | — | **Unverified**, same issue, ~7.9 rows per culture. |
| demographics, ward_info, adi_scores | 751,075 each | 100% | snapshot | — | Safe. |
| implied_susceptibility | 1,978,731 | — | — | — | **Label, not a feature.** Use only to fill or augment labels. |
| organism (in cohort) | — | — | known 24–48 h after order | — | **Not available at order time.** Use only in the "organism known" framing below. |

**Prior resistance is the strongest single signal.** With a prior resistant result to the same antibiotic (≥1 day before), the current isolate is resistant 46.1% of the time vs 13.5% without one. Getting its timing right matters more than any other choice.

## 3. Decisions to make before modelling

1. **Framing.** (a) Organism-agnostic: at order time, predict P(resistant | antibiotic, culture type, patient history), which is the true empiric decision. (b) Organism-known: at Gram stain or ID time (~24–48 h), add organism. Both are valid; (a) is the harder and more novel one.
2. **Label.** Resistant vs Susceptible, with Intermediate as non-susceptible in a sensitivity run. Resolve the 7,742 conflicts by taking the worst result (R > I > S).
3. **Scope.** Start with the ~10 antibiotics with ≥70k labels, or the urine + E. coli subset, which is the largest and cleanest.
4. **Splits.** Group by `anon_id`; train 2008–2020, validate 2021, test 2022–2024. Drop pre-2008 data (sparse, plus a 2007 gap).
5. **Feature rules.** prior_med: day ≥1. Prior resistance and prior organism: day ≥3. Labs/vitals: aggregate per culture and treat as a sensitivity block until the window direction is confirmed with the ARMD authors (fnateghi@stanford.edu).

## Open questions

- Are lab/vitals windows the 14 days *before* the order, or centred on it? Why are there multiple rows per culture?
- Is `resistant_time_to_culturetime` measured from the earlier culture's order or from its result?

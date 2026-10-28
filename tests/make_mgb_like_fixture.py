"""Build a small ARMD-format fixture that mimics known ARMD-MGB differences, to test the external pipeline
before the real data arrive.  Usage: python tests/make_mgb_like_fixture.py <out_dir> [n_patients]
Perturbations: no ICU flag + extra urgent-care ward column, no ADI table, antibiotic names spelled with
hyphens / upper case, and an antibiotic the model does not cover (fosfomycin)."""
import os, sys
import numpy as np
import pandas as pd

SRC = "data/armd_stanford"; OUT = sys.argv[1]; N = int(sys.argv[2]) if len(sys.argv) > 2 else 4000
os.makedirs(OUT, exist_ok=True)
c = pd.read_csv(f"{SRC}/microbiology_cultures_cohort.csv", dtype=str)
yr = c.order_time_jittered_utc.str[:4].astype(int)
pats = c[(yr >= 2021) & c.susceptibility.isin(["Resistant", "Susceptible"])].anon_id.drop_duplicates().sample(N, random_state=1)
keep = set(pats)
c = c[c.anon_id.isin(keep)].copy()
ren = {"Trimethoprim/Sulfamethoxazole": "Trimethoprim-Sulfamethoxazole", "Piperacillin/Tazobactam": "PIPERACILLIN-TAZOBACTAM"}
c["antibiotic"] = c.antibiotic.replace(ren)
fos = c[c.antibiotic == "Nitrofurantoin"].head(300).copy(); fos["antibiotic"] = "Fosfomycin"
pd.concat([c, fos]).to_csv(f"{OUT}/microbiology_cultures_cohort.csv", index=False)
for f in ["microbiology_cultures_demographics.csv", "microbiology_cultures_nursing_home_visits.csv",
          "microbiology_cultures_microbial_resistance.csv", "microbiology_culture_prior_infecting_organism.csv",
          "microbiology_cultures_antibiotic_class_exposure.csv", "microbiology_cultures_priorprocedures.csv",
          "microbiology_cultures_ward_info.csv"]:
    parts = [ch[ch.anon_id.isin(keep)] for ch in pd.read_csv(f"{SRC}/{f}", dtype=str, chunksize=1_000_000)]
    x = pd.concat(parts)
    if f == "microbiology_cultures_ward_info.csv":
        x = x.drop(columns=["hosp_ward_ICU"]); x["hosp_ward_UC"] = "0"
    if f == "microbiology_cultures_microbial_resistance.csv":
        x["antibiotic"] = x.antibiotic.str.upper()
    x.to_csv(f"{OUT}/{f}", index=False); print(f, len(x), flush=True)
print("fixture written to", OUT, "patients", N)

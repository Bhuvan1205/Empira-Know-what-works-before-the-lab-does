"""ARMD-Stanford: data exploration + leakage audit.

Usage (from the project root):
    python src/01_eda_leakage_audit.py labels
    python src/01_eda_leakage_audit.py audit
    python src/01_eda_leakage_audit.py wide
    python src/01_eda_leakage_audit.py merge
Each part fits in ~1-2 min and <2 GB RAM. Outputs go to reports/eda/.
"""
import json, os, sys
import numpy as np
import pandas as pd

D, O = "data/armd_stanford", "reports/eda"
NA = ["Null", "NULL", ""]
os.makedirs(O, exist_ok=True)


def save(name, obj):
    with open(f"{O}/_part_{name}.json", "w") as fh:
        json.dump(obj, fh, indent=2, default=str)


def culture_ids():
    return set(pd.read_csv(f"{D}/microbiology_cultures_cohort.csv", usecols=["order_proc_id_coded"]).order_proc_id_coded)


def labelled():
    c = pd.read_csv(f"{D}/microbiology_cultures_cohort.csv", na_values=["Null"], low_memory=False,
                    usecols=["anon_id", "order_proc_id_coded", "organism", "antibiotic", "susceptibility"])
    lab = c[c.susceptibility.isin(["Susceptible", "Resistant", "Intermediate"])].copy()
    lab["R"] = (lab.susceptibility == "Resistant").astype(int)
    return lab


# ---------------- part 1: cohort + labels ----------------
def part_labels():
    S = {}
    c = pd.read_csv(f"{D}/microbiology_cultures_cohort.csv", na_values=["Null"], low_memory=False)
    c["t"] = pd.to_datetime(c.order_time_jittered_utc, utc=True, errors="coerce")
    c["year"] = c.t.dt.year
    S["cohort_rows"] = len(c)
    S["patients"] = int(c.anon_id.nunique())
    S["cultures"] = int(c.order_proc_id_coded.nunique())
    S["encounters"] = int(c.pat_enc_csn_id_coded.nunique())
    S["date_range"] = [str(c.t.min()), str(c.t.max())]
    S["exact_duplicate_rows"] = int(c.duplicated().sum())

    cul = c.groupby("order_proc_id_coded").agg(anon_id=("anon_id", "first"), ctype=("culture_description", "first"),
                                               mode=("ordering_mode", "first"), pos=("was_positive", "max"),
                                               year=("year", "first"))
    S["culture_type_counts"] = cul.ctype.value_counts().astype(int).to_dict()
    S["culture_positive_rate"] = round(float(cul.pos.mean()), 4)
    S["culture_positive_rate_by_type"] = cul.groupby("ctype").pos.mean().round(4).to_dict()
    S["ordering_mode"] = cul["mode"].value_counts(dropna=False).astype(int).to_dict()
    S["cultures_by_year"] = cul.year.value_counts().sort_index().astype(int).to_dict()
    S["susceptibility_counts"] = c.susceptibility.value_counts(dropna=False).astype(int).to_dict()

    nul = c[c.susceptibility.isna()]
    S["null_susc_rows"] = len(nul)
    S["null_susc_negative_culture"] = int((nul.was_positive == 0).sum())
    S["null_susc_positive_culture"] = int((nul.was_positive == 1).sum())

    lab = c[c.susceptibility.isin(["Susceptible", "Resistant", "Intermediate"])].copy()
    lab["R"] = (lab.susceptibility == "Resistant").astype(int)
    lab["NS"] = lab.susceptibility.isin(["Resistant", "Intermediate"]).astype(int)
    S["labelled_pairs"] = len(lab)
    S["labelled_cultures"] = int(lab.order_proc_id_coded.nunique())
    S["labelled_patients"] = int(lab.anon_id.nunique())
    S["overall_resistant_rate"] = round(float(lab.R.mean()), 4)
    k = ["order_proc_id_coded", "organism", "antibiotic"]
    S["dup_label_keys"] = int(lab.duplicated(k).sum())
    S["conflicting_label_keys"] = int((lab.groupby(k).susceptibility.nunique() > 1).sum())
    S["organisms_per_labelled_culture"] = lab.groupby("order_proc_id_coded").organism.nunique().describe().round(2).to_dict()

    ab = lab.groupby("antibiotic").agg(n=("R", "size"), cultures=("order_proc_id_coded", "nunique"),
                                       resistant_rate=("R", "mean"), nonsusc_rate=("NS", "mean")).sort_values("n", ascending=False)
    ab.round(4).to_csv(f"{O}/labels_by_antibiotic.csv")
    org = lab.groupby("organism").agg(n=("R", "size"), cultures=("order_proc_id_coded", "nunique"),
                                      resistant_rate=("R", "mean")).sort_values("n", ascending=False)
    org.round(4).to_csv(f"{O}/labels_by_organism.csv")
    S["antibiotics_with_ge_10k_labels"] = int((ab.n >= 10000).sum())
    S["top10_organisms_share_of_labels"] = round(float(org.n.head(10).sum() / org.n.sum()), 4)
    lab = lab.merge(cul[["ctype"]], left_on="order_proc_id_coded", right_index=True)
    yr = lab.groupby(["year", "ctype"]).agg(n=("R", "size"), resistant_rate=("R", "mean")).reset_index()
    yr.round(4).to_csv(f"{O}/labels_by_year_culture.csv", index=False)
    S["resistant_rate_by_culture_type"] = lab.groupby("ctype").R.mean().round(4).to_dict()

    kp = lab.groupby(["organism", "antibiotic"]).agg(n=("R", "size"), resistant_rate=("R", "mean")).reset_index()
    kp.sort_values("n", ascending=False).head(60).round(4).to_csv(f"{O}/labels_top_organism_antibiotic_pairs.csv", index=False)
    key = [("ESCHERICHIA COLI", a) for a in ["Ciprofloxacin", "Ceftriaxone", "Trimethoprim/Sulfamethoxazole", "Nitrofurantoin", "Cefazolin", "Piperacillin/Tazobactam"]]
    key += [("STAPHYLOCOCCUS AUREUS", a) for a in ["Oxacillin", "Vancomycin", "Clindamycin"]]
    key += [("KLEBSIELLA PNEUMONIAE", a) for a in ["Ceftriaxone", "Ciprofloxacin", "Meropenem"]]
    S["key_pairs"] = kp.set_index(["organism", "antibiotic"]).reindex(key).dropna().reset_index().round(4).to_dict("records")

    pc = cul.groupby("anon_id").size()
    S["cultures_per_patient"] = {"median": float(pc.median()), "p90": float(pc.quantile(.9)), "max": int(pc.max()),
                                 "share_patients_with_repeat_cultures": round(float((pc > 1).mean()), 4),
                                 "share_cultures_from_repeat_patients": round(float(pc[pc > 1].sum() / pc.sum()), 4)}
    save("labels", S)


# ---------------- part 2: long event tables (time-relative features) ----------------
EVENT = {
    "microbiology_cultures_microbial_resistance.csv": "resistant_time_to_culturetime",
    "microbiology_culture_prior_infecting_organism.csv": "prior_infecting_organism_days_to_culutre",
    "microbiology_cultures_antibiotic_class_exposure.csv": "time_to_culturetime",
    "microbiology_cultures_antibiotic_subtype_exposure.csv": "medication_time_to_cultureTime",
    "microbiology_cultures_prior_med.csv": "medication_time_to_culturetime",
    "microbiology_cultures_priorprocedures.csv": "procedure_time_to_culturetime",
    "microbiology_cultures_nursing_home_visits.csv": "nursing_home_visit_culture",
}


def part_audit():
    ids = culture_ids()
    S = {"event_tables": []}
    for f, col in EVENT.items():
        n = nnull = neg = zero = le1 = 0; mn, mx = np.inf, -np.inf; ords = set(); samp = []
        for ch in pd.read_csv(f"{D}/{f}", usecols=["order_proc_id_coded", col], na_values=NA, chunksize=1_000_000):
            v = pd.to_numeric(ch[col], errors="coerce")
            n += len(ch); nnull += int(v.isna().sum()); neg += int((v < 0).sum())
            zero += int((v == 0).sum()); le1 += int((v <= 1).sum())
            mn, mx = min(mn, v.min()), max(mx, v.max()); ords.update(ch.order_proc_id_coded.unique())
            vv = v.dropna(); samp.append(vv.sample(min(len(vv), 20000), random_state=0))
        q = pd.concat(samp).quantile([.01, .05, .25, .5, .75, .95, .99]).round(1)
        S["event_tables"].append(dict(table=f, rows=n, time_col=col, null=nnull, min=float(mn), max=float(mx),
                                      negative_rows=neg, zero_day_rows=zero, zero_day_share=round(zero / n, 4),
                                      le1_day_share=round(le1 / n, 4), cultures_covered=len(ords & ids),
                                      coverage=round(len(ords & ids) / len(ids), 4),
                                      q01=q[.01], q05=q[.05], q50=q[.5], q95=q[.95], q99=q[.99]))

    # Does "prior resistance" at 0 days reproduce the CURRENT culture's label?
    lab = labelled()
    mr = pd.read_csv(f"{D}/microbiology_cultures_microbial_resistance.csv", na_values=NA,
                     usecols=["order_proc_id_coded", "organism", "antibiotic", "resistant_time_to_culturetime"])
    mr["antibiotic_l"] = mr.antibiotic.str.lower(); lab["antibiotic_l"] = lab.antibiotic.str.lower()
    for d in [0, 1, 2, 3, 7]:
        S[f"resistance_rows_le_{d}d"] = int((mr.resistant_time_to_culturetime <= d).sum())
    m = lab.merge(mr[mr.resistant_time_to_culturetime == 0][["order_proc_id_coded", "antibiotic_l"]].drop_duplicates(),
                  on=["order_proc_id_coded", "antibiotic_l"], how="left", indicator=True)
    hit = m["_merge"] == "both"
    S["label_pairs_with_0day_prior_resistance_same_antibiotic"] = int(hit.sum())
    S["resistant_rate_when_0day_flag"] = round(float(m.loc[hit, "R"].mean()), 4) if hit.any() else None
    S["resistant_rate_without_0day_flag"] = round(float(m.loc[~hit, "R"].mean()), 4)
    # same comparison with a >=1 day gap only (safe version)
    safe = mr[mr.resistant_time_to_culturetime >= 1][["order_proc_id_coded", "antibiotic_l"]].drop_duplicates()
    m2 = lab.merge(safe, on=["order_proc_id_coded", "antibiotic_l"], how="left", indicator=True)
    h2 = m2["_merge"] == "both"
    S["resistant_rate_when_prior_resistance_ge1d"] = round(float(m2.loc[h2, "R"].mean()), 4)
    S["resistant_rate_without_prior_resistance_ge1d"] = round(float(m2.loc[~h2, "R"].mean()), 4)
    save("audit", S)


# ---------------- part 3: wide snapshot tables ----------------
WIDE = ["microbiology_cultures_labs.csv", "microbiology_cultures_vitals.csv", "microbiology_cultures_demographics.csv",
        "microbiology_cultures_ward_info.csv", "microbiology_cultures_adi_scores.csv"]


def part_wide():
    ids = culture_ids()
    S = {"wide_tables": []}
    for f in WIDE:
        hdr = pd.read_csv(f"{D}/{f}", nrows=0).columns.tolist()
        n = 0; nulls = pd.Series(0, index=hdr); ords = set(); extra = {}
        for ch in pd.read_csv(f"{D}/{f}", na_values=NA, chunksize=400_000, low_memory=False, dtype=str):
            n += len(ch); nulls += ch.isna().sum(); ords.update(ch.order_proc_id_coded.unique())
            for col in ["Period_Day", "age", "gender"]:
                if col in ch:
                    extra.setdefault(col, []).append(ch[col].value_counts(dropna=False))
        nm = f.replace("microbiology_cultures_", "").replace(".csv", "")
        (nulls / n).round(4).rename("null_share").to_csv(f"{O}/missingness_{nm}.csv")
        ids_s = {int(x) for x in ords if str(x).isdigit()}
        rec = dict(table=f, rows=n, columns=len(hdr), cultures_covered=len(ids_s & ids),
                   coverage=round(len(ids_s & ids) / len(ids), 4), rows_per_culture=round(n / max(len(ids_s), 1), 3),
                   mean_null_share=round(float((nulls / n).mean()), 4))
        for k, v in extra.items():
            rec[k] = {str(a): int(b) for a, b in pd.concat(v).groupby(level=0, dropna=False).sum().items()}
        S["wide_tables"].append(rec)
        print("profiled", f, flush=True)
    save("wide", S)


def merge():
    S = {}
    for p in ["labels", "audit", "wide"]:
        S.update(json.load(open(f"{O}/_part_{p}.json")))
    pd.DataFrame(S["event_tables"] + S["wide_tables"]).to_csv(f"{O}/table_audit.csv", index=False)
    json.dump(S, open(f"{O}/summary.json", "w"), indent=2, default=str)
    print(json.dumps(S, indent=1, default=str))


if __name__ == "__main__":
    {"labels": part_labels, "audit": part_audit, "wide": part_wide, "merge": merge}[sys.argv[1]]()
    print("DONE", sys.argv[1])

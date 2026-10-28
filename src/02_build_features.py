"""Build leakage-safe features for ARMD-Stanford.

Usage (from project root):  python src/02_build_features.py base
                            python src/02_build_features.py history
                            python src/02_build_features.py own_history
                            python src/02_build_features.py labs_vitals
Prediction time = culture order time. Leakage rules (from reports/01_EDA_and_leakage_audit.md):
  - prior resistance / prior organism: only events >= 3 days before order
  - antibiotic exposure, procedures: >= 1 day (as provided)
  - prior_med: not used (antibiotic class exposure covers it, day 0 excluded)
  - labs / vitals: excluded from the main model (window direction undocumented)
  - organism: only in the organism-known variant
Outputs: data/processed/*.parquet
"""
import sys
import numpy as np
import pandas as pd

import os
D = os.environ.get("ARMD_RAW", "data/armd_stanford")          # raw ARMD-format folder
P = os.environ.get("ARMD_PROCESSED", "data/processed")        # output folder
MIN_YEAR = int(os.environ.get("ARMD_MIN_YEAR", 2008))
os.makedirs(P, exist_ok=True)
# spelling variants seen across sites -> Stanford names (lower-case)
AB_ALIASES = {"trimethoprim-sulfamethoxazole": "trimethoprim/sulfamethoxazole", "trimethoprim/sulfa": "trimethoprim/sulfamethoxazole",
              "sulfamethoxazole/trimethoprim": "trimethoprim/sulfamethoxazole", "tmp/smx": "trimethoprim/sulfamethoxazole",
              "piperacillin-tazobactam": "piperacillin/tazobactam", "piperacillin/tazobactam (zosyn)": "piperacillin/tazobactam",
              "amoxicillin-clavulanate": "amoxicillin/clavulanic acid", "amoxicillin/clavulanate": "amoxicillin/clavulanic acid",
              "ampicillin-sulbactam": "ampicillin/sulbactam", "nitrofurantoin macrocrystals": "nitrofurantoin",
              "oxacillin (cefoxitin screen)": "oxacillin"}
WARD_COLS = ["hosp_ward_IP", "hosp_ward_OP", "hosp_ward_ER", "hosp_ward_ICU"]


def exists(f):
    return os.path.exists(f"{D}/{f}")
NA = ["Null", "NULL", ""]
GAP_HISTORY = 3
WORST = {"Susceptible": 0, "Intermediate": 1, "Resistant": 2}


def norm_ab(s):
    s = s.astype(str).str.lower().str.strip()
    return s.replace(AB_ALIASES)


def base():
    c = pd.read_csv(f"{D}/microbiology_cultures_cohort.csv", na_values=["Null"], low_memory=False)
    c["t"] = pd.to_datetime(c.order_time_jittered_utc, utc=True)
    c = c[c.t.dt.year >= MIN_YEAR]
    lab = c[c.susceptibility.isin(WORST)].copy()
    lab["sev"] = lab.susceptibility.map(WORST)
    lab["ab"] = norm_ab(lab.antibiotic)

    # organism-agnostic label: worst result for this antibiotic across all organisms in the culture
    la = lab.groupby(["order_proc_id_coded", "ab"]).sev.max().reset_index()
    la["R"] = (la.sev == 2).astype("int8"); la["NS"] = (la.sev >= 1).astype("int8")
    la.drop(columns="sev").to_parquet(f"{P}/labels_agnostic.parquet", index=False)

    # organism-known label: worst result per culture x organism x antibiotic (resolves duplicate isolates)
    lo = lab.groupby(["order_proc_id_coded", "organism", "ab"]).sev.max().reset_index()
    lo["R"] = (lo.sev == 2).astype("int8"); lo["NS"] = (lo.sev >= 1).astype("int8")
    lo.drop(columns="sev").to_parquet(f"{P}/labels_organism.parquet", index=False)

    ids = la.order_proc_id_coded.unique()
    cul = (c[c.order_proc_id_coded.isin(ids)]
           .groupby("order_proc_id_coded")
           .agg(anon_id=("anon_id", "first"), t=("t", "first"), culture_type=("culture_description", "first"),
                ordering_mode=("ordering_mode", "first"))
           .reset_index())
    cul["year"] = cul.t.dt.year
    dem = pd.read_csv(f"{D}/microbiology_cultures_demographics.csv", na_values=NA,
                      usecols=["order_proc_id_coded", "age", "gender"])
    parts = [dem]
    if exists("microbiology_cultures_ward_info.csv"):
        ward = pd.read_csv(f"{D}/microbiology_cultures_ward_info.csv", na_values=NA)
        parts.append(ward[["order_proc_id_coded"] + [c for c in WARD_COLS if c in ward]])
    if exists("microbiology_cultures_adi_scores.csv"):
        parts.append(pd.read_csv(f"{D}/microbiology_cultures_adi_scores.csv", na_values=NA,
                                 usecols=["order_proc_id_coded", "adi_score", "adi_state_rank"]))
    for t in parts:
        cul = cul.merge(t.drop_duplicates("order_proc_id_coded"), on="order_proc_id_coded", how="left")
    for c in WARD_COLS + ["adi_score", "adi_state_rank"]:
        if c not in cul:
            cul[c] = np.nan; print("missing column (left blank):", c)
    if exists("microbiology_cultures_nursing_home_visits.csv"):
        nh = pd.read_csv(f"{D}/microbiology_cultures_nursing_home_visits.csv", na_values=NA,
                         usecols=["order_proc_id_coded"]).drop_duplicates().assign(nursing_home=1)
        cul = cul.merge(nh, on="order_proc_id_coded", how="left")
    else:
        cul["nursing_home"] = np.nan
    cul["nursing_home"] = cul.nursing_home.fillna(0).astype("int8")
    age_order = ["18-24 years", "25-34 years", "35-44 years", "45-54 years", "55-64 years",
                 "65-74 years", "75-84 years", "85-89 years", "above 90"]
    cul["age_ord"] = cul.age.map({a: i for i, a in enumerate(age_order)})
    cul["adi_score"] = pd.to_numeric(cul.adi_score, errors="coerce")
    cul["adi_state_rank"] = pd.to_numeric(cul.adi_state_rank, errors="coerce")
    cul.to_parquet(f"{P}/cultures.parquet", index=False)
    print("cultures", len(cul), "agnostic labels", len(la), "organism labels", len(lo))


def pivot_min_days(f, key, day, ids, min_day, top=None, prefix=""):
    """Per culture: min days since each category (only events >= min_day), plus count of events."""
    parts = []
    for ch in pd.read_csv(f"{D}/{f}", usecols=["order_proc_id_coded", key, day], na_values=NA, chunksize=1_000_000):
        ch = ch[ch.order_proc_id_coded.isin(ids) & (ch[day] >= min_day)]
        parts.append(ch.groupby(["order_proc_id_coded", key])[day].agg(["min", "size"]).reset_index())
    g = pd.concat(parts).groupby(["order_proc_id_coded", key]).agg({"min": "min", "size": "sum"}).reset_index()
    g[key] = g[key].astype(str).str.lower().str.strip()
    if key == "antibiotic":
        g[key] = g[key].replace(AB_ALIASES)
        g = g.groupby(["order_proc_id_coded", key], as_index=False).agg({"min": "min", "size": "sum"})
    if top is not None:
        keep = g[key].value_counts().head(top).index
    else:
        keep = g[key].unique()
    w = g[g[key].isin(keep)].pivot(index="order_proc_id_coded", columns=key, values="min")
    w.columns = [f"{prefix}{c}".replace(" ", "_").replace("/", "_") for c in w.columns]
    tot = g.groupby("order_proc_id_coded")["size"].sum().rename(f"{prefix}n_events")
    recent = g[g["min"] <= 90].groupby("order_proc_id_coded")[key].nunique().rename(f"{prefix}n_types_90d")
    return w.join(tot, how="outer").join(recent, how="left"), g


def history():
    cul = pd.read_parquet(f"{P}/cultures.parquet", columns=["order_proc_id_coded"])
    ids = set(cul.order_proc_id_coded)
    out = cul.set_index("order_proc_id_coded")
    specs = [("microbiology_cultures_microbial_resistance.csv", "antibiotic", "resistant_time_to_culturetime", GAP_HISTORY, 40, "priorR_"),
             ("microbiology_culture_prior_infecting_organism.csv", "prior_organism", "prior_infecting_organism_days_to_culutre", GAP_HISTORY, 25, "priorOrg_"),
             ("microbiology_cultures_antibiotic_class_exposure.csv", "antibiotic_class", "time_to_culturetime", 1, None, "abx_"),
             ("microbiology_cultures_priorprocedures.csv", "procedure_description", "procedure_time_to_culturetime", 1, None, "proc_")]
    for f, key, day, gap, top, pre in specs:
        if not exists(f):
            print("missing table (features left blank):", f); continue
        w, g = pivot_min_days(f, key, day, ids, gap, top=top, prefix=pre)
        if pre == "priorR_":
            g["antibiotic"] = norm_ab(g.antibiotic)
            g.rename(columns={"antibiotic": "ab", "min": "priorR_target_days", "size": "priorR_target_n"}) \
             .groupby(["order_proc_id_coded", "ab"], as_index=False).agg(priorR_target_days=("priorR_target_days", "min"),
                                                                        priorR_target_n=("priorR_target_n", "sum")) \
             .to_parquet(f"{P}/prior_resistance_long.parquet", index=False)
        out = out.join(w); print(f, w.shape, flush=True)
    if not os.path.exists(f"{P}/prior_resistance_long.parquet"):
        pd.DataFrame(columns=["order_proc_id_coded", "ab", "priorR_target_days", "priorR_target_n"]).astype(
            {"order_proc_id_coded": "int64", "ab": "str", "priorR_target_days": "float64", "priorR_target_n": "float64"}) \
            .to_parquet(f"{P}/prior_resistance_long.parquet", index=False)
    out.reset_index().to_parquet(f"{P}/history.parquet", index=False)
    print("history features", out.shape)


def own_history():
    """Target-specific history rebuilt from the cohort table itself (covers all 55 antibiotics;
    the provided microbial_resistance table covers only 26). For each culture x antibiotic:
    days since the patient's last Resistant and last tested result for that antibiotic, using only
    cultures ordered >= GAP_HISTORY days earlier."""
    c = pd.read_csv(f"{D}/microbiology_cultures_cohort.csv", na_values=["Null"], low_memory=False,
                    usecols=["anon_id", "order_proc_id_coded", "order_time_jittered_utc", "antibiotic", "susceptibility"])
    c = c[c.susceptibility.isin(WORST)]
    c["t"] = pd.to_datetime(c.order_time_jittered_utc, utc=True)
    c["ab"] = norm_ab(c.antibiotic)
    c["R"] = (c.susceptibility == "Resistant").astype("int8")
    ev = c.groupby(["anon_id", "ab", "order_proc_id_coded"]).agg(t=("t", "first"), R=("R", "max")).reset_index()
    tgt = ev[["anon_id", "ab", "order_proc_id_coded", "t"]].copy()
    gap = pd.Timedelta(days=GAP_HISTORY)
    out = tgt
    for name, src in [("own_lastR_days", ev[ev.R == 1]), ("own_lastTested_days", ev)]:
        e = src[["anon_id", "ab", "t"]].rename(columns={"t": "te"}).copy()
        e["t_avail"] = e.te + gap
        m = pd.merge_asof(tgt.sort_values("t"), e.sort_values("t_avail")[["anon_id", "ab", "t_avail", "te"]],
                          left_on="t", right_on="t_avail", by=["anon_id", "ab"], direction="backward",
                          allow_exact_matches=True)
        out = out.merge(m[["order_proc_id_coded", "ab"]].assign(**{name: (m.t - m.te).dt.days.values}),
                        on=["order_proc_id_coded", "ab"], how="left")
    # prior counts of resistant results to this antibiotic (>= gap)
    e = ev[ev.R == 1][["anon_id", "ab", "t"]].sort_values("t")
    e["k"] = e.groupby(["anon_id", "ab"]).cumcount() + 1
    e["t_avail"] = e.t + gap
    m = pd.merge_asof(tgt.sort_values("t"), e[["anon_id", "ab", "t_avail", "k"]].sort_values("t_avail"),
                      left_on="t", right_on="t_avail", by=["anon_id", "ab"], direction="backward")
    out = out.merge(m[["order_proc_id_coded", "ab", "k"]].rename(columns={"k": "own_nR"}),
                    on=["order_proc_id_coded", "ab"], how="left")
    out["own_nR"] = out.own_nR.fillna(0)
    out.drop(columns=["anon_id", "t"]).to_parquet(f"{P}/own_history_long.parquet", index=False)
    print("own history rows", len(out), "with prior R:", int(out.own_lastR_days.notna().sum()),
          "with prior test:", int(out.own_lastTested_days.notna().sum()))
    assert (out.own_lastR_days.dropna() >= GAP_HISTORY).all()


def labs_vitals():
    """Per-culture lab and vital-sign summaries (sensitivity block: the source window direction is
    undocumented). Multiple source rows per culture are averaged. Keeps median_*, first_* and last_*."""
    ids = set(pd.read_parquet(f"{P}/cultures.parquet", columns=["order_proc_id_coded"]).order_proc_id_coded)
    out = None
    for f, pre in [("microbiology_cultures_labs.csv", "lab_"), ("microbiology_cultures_vitals.csv", "vit_")]:
        hdr = pd.read_csv(f"{D}/{f}", nrows=0).columns
        cols = [c for c in hdr if c.startswith(("median_", "first_", "last_"))]
        sums, cnts = [], []
        for ch in pd.read_csv(f"{D}/{f}", usecols=["order_proc_id_coded"] + cols, na_values=NA,
                              chunksize=1_000_000, dtype={c: "float32" for c in cols}):
            ch = ch[ch.order_proc_id_coded.isin(ids)]
            g = ch.groupby("order_proc_id_coded")[cols]
            sums.append(g.sum(min_count=1)); cnts.append(g.count())
        s_ = pd.concat(sums).groupby(level=0).sum(min_count=1)
        c_ = pd.concat(cnts).groupby(level=0).sum()
        m = (s_ / c_.replace(0, np.nan)).astype("float32")
        m.columns = [pre + c for c in m.columns]
        out = m if out is None else out.join(m, how="outer")
        print(f, m.shape, flush=True)
    out.reset_index().to_parquet(f"{P}/labs_vitals.parquet", index=False)
    print("labs_vitals", out.shape, "coverage", round(len(out) / len(ids), 3))


if __name__ == "__main__":
    {"base": base, "history": history, "own_history": own_history, "labs_vitals": labs_vitals}[sys.argv[1]]()

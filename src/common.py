"""Shared configuration, feature assembly and metrics for the ARMD resistance project."""
import os, re, json
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.environ.get("ARMD_PROCESSED", os.path.join(ROOT, "data", "processed"))
MODELS = os.environ.get("ARMD_MODELS", os.path.join(ROOT, "models"))
REPORTS = os.environ.get("ARMD_REPORTS", os.path.join(ROOT, "reports"))
PRED = os.environ.get("ARMD_PRED", os.path.join(ROOT, "data", "predictions"))
SEED = 7
TRAIN_END, VAL_YEAR, TEST_START = 2020, 2021, 2022
MIN_LABELS = 10_000          # antibiotics with at least this many labels are modelled
CATS = ["culture_type", "ordering_mode", "gender", "ab_cat", "organism_grp"]
ID_COLS = ["order_proc_id_coded", "anon_id", "t", "year", "age", "ab", "organism", "R", "NS"]


def clean(cols):
    return [re.sub(r"[^0-9a-zA-Z_]", "_", c) for c in cols]


def load_cultures(labs=False, orgprob=False):
    cul = pd.read_parquet(f"{P}/cultures.parquet").merge(
        pd.read_parquet(f"{P}/history.parquet"), on="order_proc_id_coded", how="left")
    if labs:
        cul = cul.merge(pd.read_parquet(f"{P}/labs_vitals.parquet"), on="order_proc_id_coded", how="left")
    if orgprob:
        cul = cul.merge(pd.read_parquet(f"{P}/organism_probs.parquet"), on="order_proc_id_coded", how="left")
    cul.columns = clean(cul.columns)
    for c in cul.columns:
        if c in ("order_proc_id_coded",):
            continue
        if pd.api.types.is_float_dtype(cul[c]) or pd.api.types.is_integer_dtype(cul[c]):
            cul[c] = cul[c].astype("float32")
    cul["year"] = cul["year"].astype("int16")
    for c in ["culture_type", "ordering_mode", "gender", "age"]:
        cul[c] = cul[c].astype("category")
    return cul


def model_antibiotics(mode="agnostic"):
    lab = pd.read_parquet(f"{P}/labels_{mode}.parquet", columns=["ab"])
    vc = lab.ab.value_counts()
    return vc[vc >= MIN_LABELS].index.tolist()


def build_frame(mode="agnostic", labs=False, abs_=None, cul=None, orgprob=False):
    """One row per labelled culture x antibiotic (agnostic) or culture x organism x antibiotic.
    Returns (frame, feature_list). Target-specific history is joined per antibiotic."""
    lab = pd.read_parquet(f"{P}/labels_{mode}.parquet")
    abs_ = abs_ or model_antibiotics(mode)
    lab = lab[lab.ab.isin(abs_)].copy()
    abcat = pd.CategoricalDtype(sorted(abs_))
    lab["ab"] = lab.ab.astype(abcat)
    if mode == "organism":
        top_org = lab.organism.value_counts().head(30).index
        lab["organism_grp"] = lab.organism.where(lab.organism.isin(top_org), "OTHER")
    cul = load_cultures(labs, orgprob) if cul is None else cul
    pr = pd.read_parquet(f"{P}/prior_resistance_long.parquet",
                         columns=["order_proc_id_coded", "ab", "priorR_target_days", "priorR_target_n"])
    own = pd.read_parquet(f"{P}/own_history_long.parquet")
    pr = pr[pr.ab.isin(abs_)].copy(); own = own[own.ab.isin(abs_)].copy()
    for t in (pr, own):
        t["ab"] = t.ab.astype(abcat)
        for c in t.columns:
            if c not in ("order_proc_id_coded", "ab"):
                t[c] = t[c].astype("float32")
    lab = lab.merge(pr, on=["order_proc_id_coded", "ab"], how="left")
    lab = lab.merge(own, on=["order_proc_id_coded", "ab"], how="left")
    del pr, own
    lab["R"] = lab.R.astype("int8"); lab["NS"] = lab.NS.astype("int8")
    lab["ab_cat"] = lab.ab
    if "organism_grp" in lab:
        lab["organism_grp"] = lab.organism_grp.astype("category")
    # index lookup instead of merge: far lower peak memory on a 3-4 GB machine
    pos = pd.Index(cul.order_proc_id_coded).get_indexer(lab.order_proc_id_coded)
    keep = pos >= 0
    lab = lab.loc[keep].reset_index(drop=True); pos = pos[keep]
    num = [c for c in cul.columns if c != "order_proc_id_coded" and pd.api.types.is_float_dtype(cul[c])]
    d = pd.DataFrame(cul[num].to_numpy(np.float32)[pos], columns=num, copy=False)
    for c in cul.columns:
        if c not in num and c != "order_proc_id_coded":
            d[c] = cul[c].iloc[pos].to_numpy() if not isinstance(cul[c].dtype, pd.CategoricalDtype) \
                else pd.Categorical.from_codes(cul[c].cat.codes.to_numpy()[pos], dtype=cul[c].dtype)
    for c in lab.columns:
        d[c] = lab[c].to_numpy() if not isinstance(lab[c].dtype, pd.CategoricalDtype) else lab[c].array
    del lab
    feats = [c for c in d.columns if c not in ID_COLS]
    return d, feats


def split(d):
    return d[d.year <= TRAIN_END], d[d.year == VAL_YEAR], d[d.year >= TEST_START]


def sens_at_spec(y, p, spec=0.9):
    neg = np.sort(p[y == 0]); thr = neg[int(np.ceil(spec * len(neg))) - 1]
    return float((p[y == 1] > thr).mean())


def metrics(y, p):
    y = np.asarray(y); p = np.asarray(p, dtype=float)
    return dict(n=int(len(y)), prevalence=round(float(y.mean()), 4), auroc=round(roc_auc_score(y, p), 4),
                auprc=round(average_precision_score(y, p), 4), brier=round(brier_score_loss(y, p), 4),
                sens_at_90spec=round(sens_at_spec(y, p), 4))


def save_json(obj, path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        json.dump(obj, fh, indent=2, default=str)

"""Phase B: evaluation of the frozen final model on the 2022-2024 test set.
  - patient-clustered bootstrap 95% CIs (resampling patients, not rows)
  - calibration: reliability bins, ECE, calibration intercept/slope, curves (PNG)
  - subgroups: culture type, ward, ordering mode, age, sex code, deprivation (ADI), new vs returning patients
  - temporal drift: by year, and the 2017 change in testing practice
Usage: python src/05_evaluate.py [bootstrap|calibration|subgroups|drift|all]
Outputs: reports/phaseB/
"""
import sys, os
import numpy as np
import pandas as pd
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

O = os.path.join(C.REPORTS, "phaseB")
PRED = C.PRED
B = int(os.environ.get("ARMD_BOOT", 1000))
TOP10 = ["ciprofloxacin", "gentamicin", "trimethoprim/sulfamethoxazole", "levofloxacin", "ampicillin",
         "nitrofurantoin", "piperacillin/tazobactam", "cefazolin", "ceftriaxone", "meropenem"]


def load_test():
    te = pd.read_parquet(f"{PRED}/final_test.parquet")
    cul = pd.read_parquet(f"{C.P}/cultures.parquet")
    tr_pat = set(cul[cul.year <= C.TRAIN_END].anon_id)
    keep = ["order_proc_id_coded", "ordering_mode", "age", "gender", "adi_score",
            "hosp_ward_IP", "hosp_ward_OP", "hosp_ward_ER", "hosp_ward_ICU"]
    te = te.merge(cul[keep], on="order_proc_id_coded", how="left")
    te["new_patient"] = ~te.anon_id.isin(tr_pat)
    return te


def bootstrap(te):
    rng = np.random.default_rng(C.SEED)
    pats = te.anon_id.unique(); pidx = pd.Index(pats)
    te = te.assign(pi=pidx.get_indexer(te.anon_id))
    abs_ = sorted(te.ab.unique())
    groups = {ab: te[te.ab == ab] for ab in abs_}
    point = {ab: roc_auc_score(g.R, g.p) for ab, g in groups.items()}
    boots = np.zeros((B, len(abs_)))
    for b in range(B):
        w = rng.multinomial(len(pats), np.full(len(pats), 1 / len(pats))).astype(float)
        for j, ab in enumerate(abs_):
            g = groups[ab]; sw = w[g.pi.values]
            m = sw > 0
            boots[b, j] = roc_auc_score(g.R.values[m], g.p.values[m], sample_weight=sw[m]) if g.R.values[m].min() != g.R.values[m].max() else np.nan
    lo, hi = np.nanpercentile(boots, 2.5, axis=0), np.nanpercentile(boots, 97.5, axis=0)
    res = pd.DataFrame(dict(antibiotic=abs_, auroc=[point[a] for a in abs_], ci_low=lo, ci_high=hi)).round(4)
    mean_all, mean_t10 = np.nanmean(boots, axis=1), np.nanmean(boots[:, [abs_.index(a) for a in TOP10]], axis=1)
    summ = dict(bootstrap_reps=B, unit="patient",
                mean_auroc_all=round(float(np.mean(list(point.values()))), 4),
                mean_auroc_all_ci=[round(float(np.percentile(mean_all, q)), 4) for q in (2.5, 97.5)],
                mean_auroc_top10=round(float(np.mean([point[a] for a in TOP10])), 4),
                mean_auroc_top10_ci=[round(float(np.percentile(mean_t10, q)), 4) for q in (2.5, 97.5)])
    res.to_csv(f"{O}/bootstrap_auroc_ci.csv", index=False); C.save_json(summ, f"{O}/bootstrap_summary.json")
    print(summ)


def calib_stats(y, p):
    p = np.clip(p, 1e-6, 1 - 1e-6); lg = np.log(p / (1 - p)).reshape(-1, 1)
    lr = LogisticRegression(C=1e6, max_iter=1000).fit(lg, y)
    bins = pd.qcut(p, 10, duplicates="drop")
    tab = pd.DataFrame(dict(y=y, p=p, b=bins)).groupby("b", observed=True).agg(pred=("p", "mean"), obs=("y", "mean"), n=("y", "size"))
    ece = float((tab.n * (tab.pred - tab.obs).abs()).sum() / tab.n.sum())
    return dict(slope=round(float(lr.coef_[0][0]), 3), intercept=round(float(lr.intercept_[0]), 3), ece=round(ece, 4),
                mean_pred=round(float(p.mean()), 4), observed=round(float(np.mean(y)), 4)), tab


def calibration(te):
    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    rows = []
    fig, axes = plt.subplots(2, 5, figsize=(17, 7), sharex=False)
    for ab in sorted(te.ab.unique()):
        g = te[te.ab == ab]; st, tab = calib_stats(g.R.values, g.p.values); st["antibiotic"] = ab; rows.append(st)
        if ab in TOP10:
            ax = axes.flat[TOP10.index(ab)]
            mx = max(tab.pred.max(), tab.obs.max()) * 1.05
            ax.plot([0, mx], [0, mx], ls="--", lw=1, color="#888")
            ax.plot(tab.pred, tab.obs, marker="o", lw=1.5, color="#2a6fb0")
            ax.set_title(f"{ab}\nslope {st['slope']}, ECE {st['ece']}", fontsize=9)
            ax.set_xlabel("predicted", fontsize=8); ax.set_ylabel("observed", fontsize=8); ax.tick_params(labelsize=7)
    fig.suptitle("Calibration on 2022–2024 test set (deciles of predicted risk)", fontsize=11)
    fig.tight_layout(); fig.savefig(f"{O}/calibration_top10.png", dpi=130); plt.close(fig)
    r = pd.DataFrame(rows)[["antibiotic", "observed", "mean_pred", "intercept", "slope", "ece"]]
    r.to_csv(f"{O}/calibration_by_antibiotic.csv", index=False)
    print(r.to_string(index=False)); print("median ECE", r.ece.median(), "median slope", r.slope.median())


def mean_auroc(df, min_pos=20):
    vals, n = [], 0
    for ab, g in df.groupby("ab", observed=True):
        if g.R.sum() >= min_pos and (g.R == 0).sum() >= min_pos:
            vals.append(roc_auc_score(g.R, g.p)); n += 1
    return (round(float(np.mean(vals)), 4) if vals else None), n


def subgroups(te):
    te = te.copy()
    te["ward"] = np.select([te.hosp_ward_ICU == 1, te.hosp_ward_ER == 1, te.hosp_ward_IP == 1, te.hosp_ward_OP == 1],
                           ["ICU", "ER", "Inpatient", "Outpatient"], "Unknown")
    te["age_band"] = te.age.astype(str).map(lambda a: "18-44" if a in ("18-24 years", "25-34 years", "35-44 years")
                                             else "45-64" if a in ("45-54 years", "55-64 years")
                                             else "65-84" if a in ("65-74 years", "75-84 years") else "85+" if a != "nan" else "Unknown")
    te["sex_code"] = te.gender.astype(str)
    # ADI national percentile (1 = least deprived, 100 = most); fixed bands because the score is heavily tied
    te["adi_quintile"] = pd.cut(te.adi_score, [0, 20, 40, 60, 80, 100],
                                labels=["1-20 least deprived", "21-40", "41-60", "61-80", "81-100 most deprived"]).astype(str)
    te["patient_type"] = np.where(te.new_patient, "New patient", "Returning patient")
    rows = []
    for col in ["culture_type", "ward", "ordering_mode", "age_band", "sex_code", "adi_quintile", "patient_type"]:
        for lvl, g in te.groupby(col, observed=True):
            ma, n = mean_auroc(g)
            rows.append(dict(attribute=col, group=str(lvl), rows=len(g), cultures=g.order_proc_id_coded.nunique(),
                             resistant_rate=round(g.R.mean(), 4), mean_pred=round(g.p.mean(), 4),
                             obs_minus_pred=round(g.R.mean() - g.p.mean(), 4), mean_auroc=ma, n_antibiotics=n))
    r = pd.DataFrame(rows); r.to_csv(f"{O}/subgroups.csv", index=False); print(r.to_string(index=False))


def drift():
    va = pd.read_parquet(f"{PRED}/final_val.parquet"); te = pd.read_parquet(f"{PRED}/final_test.parquet")
    d = pd.concat([va, te])
    rows = []
    for y, g in d.groupby("year"):
        ma, n = mean_auroc(g)
        rows.append(dict(year=int(y), rows=len(g), resistant_rate=round(g.R.mean(), 4), mean_pred=round(g.p.mean(), 4),
                         mean_auroc=ma, n_antibiotics=n))
    r = pd.DataFrame(rows); r.to_csv(f"{O}/drift_by_year.csv", index=False); print(r.to_string(index=False))
    # testing practice over time: antibiotics tested per positive culture, by year (all years)
    lab = pd.read_parquet(f"{C.P}/labels_agnostic.parquet")
    cul = pd.read_parquet(f"{C.P}/cultures.parquet", columns=["order_proc_id_coded", "year"])
    x = lab.merge(cul, on="order_proc_id_coded")
    tp = x.groupby("year").agg(cultures=("order_proc_id_coded", "nunique"), labels=("R", "size"), resistant_rate=("R", "mean"))
    tp["antibiotics_per_culture"] = (tp.labels / tp.cultures).round(2)
    # same-panel check: resistance among a fixed set of antibiotics tested in every year
    fixed = ["ciprofloxacin", "trimethoprim/sulfamethoxazole", "nitrofurantoin", "cefazolin", "gentamicin"]
    tp["resistant_rate_fixed_panel"] = x[x.ab.isin(fixed)].groupby("year").R.mean()
    tp = tp.round(4); tp.to_csv(f"{O}/testing_practice_by_year.csv"); print(tp.to_string())
    pen = x[x.ab == "penicillin"].groupby("year").agg(n=("R", "size"), resistant_rate=("R", "mean")).round(3)
    pen.to_csv(f"{O}/penicillin_by_year.csv"); print("penicillin\n", pen.tail(8).to_string())


if __name__ == "__main__":
    os.makedirs(O, exist_ok=True)
    what = sys.argv[1] if len(sys.argv) > 1 else "all"
    te = load_test() if what in ("bootstrap", "calibration", "subgroups", "all") else None
    if what in ("bootstrap", "all"): bootstrap(te)
    if what in ("calibration", "all"): calibration(te)
    if what in ("subgroups", "all"): subgroups(te)
    if what in ("drift", "all"): drift()

"""Phase E: external validation of the FROZEN model on another ARMD-format site (e.g. ARMD-MGB).

Usage (from project root):
  python src/08_external_validate.py --raw data/armd_mgb --site mgb [--years 2008-2030] [--boot 1000]
Steps: (1) schema check of the raw folder, (2) feature build with the same leakage rules into
data/processed_external/<site>/, (3) score with the frozen model (no refitting), (4) metrics: per-antibiotic
AUROC/AUPRC/Brier with patient-bootstrap CIs, calibration (ECE, slope), by year, plus a sensitivity analysis
where only the calibration is refit on the site's earliest 30% of cultures (model weights untouched).
Outputs: reports/phaseE/<site>/
"""
import argparse, os, sys, subprocess, json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REQUIRED = {
    "microbiology_cultures_cohort.csv": ["anon_id", "pat_enc_csn_id_coded", "order_proc_id_coded", "order_time_jittered_utc",
                                         "ordering_mode", "culture_description", "was_positive", "organism", "antibiotic", "susceptibility"],
    "microbiology_cultures_demographics.csv": ["order_proc_id_coded", "age", "gender"],
}
OPTIONAL = {
    "microbiology_cultures_ward_info.csv": ["order_proc_id_coded"],
    "microbiology_cultures_adi_scores.csv": ["order_proc_id_coded", "adi_score", "adi_state_rank"],
    "microbiology_cultures_nursing_home_visits.csv": ["order_proc_id_coded"],
    "microbiology_cultures_microbial_resistance.csv": ["order_proc_id_coded", "antibiotic", "resistant_time_to_culturetime"],
    "microbiology_culture_prior_infecting_organism.csv": ["order_proc_id_coded", "prior_organism", "prior_infecting_organism_days_to_culutre"],
    "microbiology_cultures_antibiotic_class_exposure.csv": ["order_proc_id_coded", "antibiotic_class", "time_to_culturetime"],
    "microbiology_cultures_priorprocedures.csv": ["order_proc_id_coded", "procedure_description", "procedure_time_to_culturetime"],
}


def schema_check(raw):
    rep = {"required": {}, "optional": {}, "ok": True}
    for group, spec in [("required", REQUIRED), ("optional", OPTIONAL)]:
        for f, cols in spec.items():
            path = os.path.join(raw, f)
            if not os.path.exists(path):
                rep[group][f] = "MISSING"
                if group == "required": rep["ok"] = False
                continue
            hdr = list(pd.read_csv(path, nrows=0).columns)
            miss = [c for c in cols if c not in hdr]
            rep[group][f] = "ok" if not miss else f"missing columns {miss}"
            if miss and group == "required": rep["ok"] = False
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", required=True); ap.add_argument("--site", required=True)
    ap.add_argument("--years", default=None); ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--skip-build", action="store_true"); ap.add_argument("--min-year", default="2008")
    a = ap.parse_args()
    raw = os.path.abspath(a.raw); proc = os.path.join(ROOT, "data", "processed_external", a.site)
    out = os.path.join(ROOT, "reports", "phaseE", a.site); os.makedirs(out, exist_ok=True)

    rep = schema_check(raw); json.dump(rep, open(f"{out}/schema_check.json", "w"), indent=2)
    print("schema:", json.dumps(rep))
    if not rep["ok"]:
        sys.exit("Required files/columns missing; see schema_check.json")

    env = dict(os.environ, ARMD_RAW=raw, ARMD_PROCESSED=proc, ARMD_MIN_YEAR=a.min_year)
    if not a.skip_build:
        for part in ["base", "history", "own_history"]:
            r = subprocess.run([sys.executable, os.path.join(ROOT, "src", "02_build_features.py"), part], env=env,
                               cwd=ROOT, capture_output=True, text=True)
            print(r.stdout.strip()[-600:])
            if r.returncode: sys.exit(r.stderr[-2000:])

    os.environ["ARMD_PROCESSED"] = proc
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import common as C
    from predictor import ResistancePredictor
    from sklearn.metrics import roc_auc_score
    from sklearn.linear_model import LogisticRegression
    rp = ResistancePredictor()
    labs_ab = pd.read_parquet(f"{proc}/labels_agnostic.parquet", columns=["ab"]).ab.value_counts()
    usable = [ab for ab in rp.antibiotics if ab in labs_ab.index]
    unmatched = labs_ab[~labs_ab.index.isin(rp.antibiotics)]
    d, _ = C.build_frame("agnostic", abs_=usable)
    if a.years:
        y0, y1 = map(int, a.years.split("-")); d = d[(d.year >= y0) & (d.year <= y1)]
    d = d.reset_index(drop=True)
    d["p"] = rp.predict(d)
    C.save_json(dict(site=a.site, rows=len(d), cultures=int(d.order_proc_id_coded.nunique()), patients=int(d.anon_id.nunique()),
                     years=[int(d.year.min()), int(d.year.max())], antibiotics_scored=usable,
                     antibiotics_not_in_model=unmatched.head(30).to_dict(), features_missing_at_site=rp.last_missing_features),
                f"{out}/coverage.json")

    # per-antibiotic metrics + patient bootstrap
    rng = np.random.default_rng(C.SEED); pats = d.anon_id.unique(); pi = pd.Index(pats).get_indexer(d.anon_id)
    W = rng.multinomial(len(pats), np.full(len(pats), 1 / len(pats)), size=a.boot).astype(np.float32) if a.boot else None
    rows = []
    for ab, g in d.groupby("ab", observed=True):
        if g.R.sum() < 10 or (g.R == 0).sum() < 10: continue
        r = {"antibiotic": ab}; r.update(C.metrics(g.R.values, g.p.values))
        if W is not None:
            idx = pi[g.index.values]; bs = []
            for b in range(a.boot):
                sw = W[b, idx]; m = sw > 0; yb = g.R.values[m]
                if yb.min() != yb.max(): bs.append(roc_auc_score(yb, g.p.values[m], sample_weight=sw[m]))
            r["auroc_ci_low"], r["auroc_ci_high"] = np.percentile(bs, [2.5, 97.5]).round(4)
        pc = np.clip(g.p.values, 1e-6, 1 - 1e-6); lg = np.log(pc / (1 - pc)).reshape(-1, 1)
        lr = LogisticRegression(C=1e6, max_iter=1000).fit(lg, g.R.values)
        r["cal_slope"], r["cal_intercept"] = round(float(lr.coef_[0][0]), 3), round(float(lr.intercept_[0]), 3)
        r["observed"], r["mean_pred"] = round(float(g.R.mean()), 4), round(float(g.p.mean()), 4)
        rows.append(r)
    m = pd.DataFrame(rows).sort_values("n", ascending=False); m.to_csv(f"{out}/metrics_by_antibiotic.csv", index=False)

    # by year
    yr = []
    for y, g in d.groupby("year"):
        vals = [roc_auc_score(x.R, x.p) for _, x in g.groupby("ab", observed=True) if x.R.sum() >= 20 and (x.R == 0).sum() >= 20]
        yr.append(dict(year=int(y), rows=len(g), resistant_rate=round(g.R.mean(), 4), mean_pred=round(g.p.mean(), 4),
                       mean_auroc=round(float(np.mean(vals)), 4) if vals else None, n_antibiotics=len(vals)))
    pd.DataFrame(yr).to_csv(f"{out}/metrics_by_year.csv", index=False)

    # sensitivity: refit only the per-antibiotic calibration on the earliest 30% of cultures, evaluate on the rest
    cut = d.drop_duplicates("order_proc_id_coded").t.quantile(0.3)
    early, late = d[d.t <= cut], d[d.t > cut].copy()
    late["p_local"] = late.p
    for ab, g in early.groupby("ab", observed=True):
        if g.R.nunique() < 2: continue
        pc = np.clip(g.p.values, 1e-6, 1 - 1e-6); lr = LogisticRegression(C=1e6, max_iter=1000).fit(np.log(pc / (1 - pc)).reshape(-1, 1), g.R)
        mk = late.ab == ab; pl = np.clip(late.loc[mk, "p"].values, 1e-6, 1 - 1e-6)
        late.loc[mk, "p_local"] = lr.predict_proba(np.log(pl / (1 - pl)).reshape(-1, 1))[:, 1]
    rc = []
    for ab, g in late.groupby("ab", observed=True):
        if g.R.sum() < 10 or (g.R == 0).sum() < 10: continue
        rc.append(dict(antibiotic=ab, n=len(g), brier_frozen=round(C.metrics(g.R, g.p)["brier"], 4),
                       brier_local_recal=round(C.metrics(g.R, g.p_local)["brier"], 4),
                       observed=round(g.R.mean(), 4), pred_frozen=round(g.p.mean(), 4), pred_local=round(g.p_local.mean(), 4)))
    pd.DataFrame(rc).to_csv(f"{out}/local_recalibration_sensitivity.csv", index=False)

    summ = dict(site=a.site, rows=len(d), antibiotics=len(m), mean_auroc=round(m.auroc.mean(), 4),
                mean_auprc=round(m.auprc.mean(), 4), mean_brier=round(m.brier.mean(), 4),
                median_cal_slope=round(m.cal_slope.median(), 3),
                mean_brier_late_frozen=round(pd.DataFrame(rc).brier_frozen.mean(), 4) if rc else None,
                mean_brier_late_local_recal=round(pd.DataFrame(rc).brier_local_recal.mean(), 4) if rc else None)
    C.save_json(summ, f"{out}/summary.json"); print(json.dumps(summ))


if __name__ == "__main__":
    main()

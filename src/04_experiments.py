"""Phase A experiments. Model selection uses the 2021 validation year ONLY; test (2022-24) is reported.

Usage (from project root):
  python src/04_experiments.py per_ab  nolabs|labs|orgprob [top10|all]   # one LightGBM per antibiotic
  python src/04_experiments.py shared  <name> nolabs|labs [k=v ...]
        # one model for all 28 antibiotics; time-boxed + resumable: re-run the same command until it prints FINISHED
  python src/04_experiments.py finalize   # freeze the selected model (see FINAL_COMPONENTS)
  python src/04_experiments.py compare <name> <name> ...   # validation-only comparison + ensemble
Outputs: reports/phaseA/exp_<name>.csv, models/<name>.txt, data/predictions/<name>_{val,test}.parquet
"""
import sys, os, time, json
import numpy as np
import pandas as pd
import lightgbm as lgb
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

TOP10 = ["ciprofloxacin", "gentamicin", "trimethoprim/sulfamethoxazole", "levofloxacin", "ampicillin",
         "nitrofurantoin", "piperacillin/tazobactam", "cefazolin", "ceftriaxone", "meropenem"]
BASE_PARAMS = dict(objective="binary", learning_rate=0.05, num_leaves=63, min_data_in_leaf=100,
                   feature_fraction=0.7, bagging_fraction=0.7, bagging_freq=1, lambda_l2=1.0,
                   max_bin=63, metric="auc", seed=C.SEED, verbose=-1, num_threads=2)
OUT = os.path.join(C.REPORTS, "phaseA")
FINAL_COMPONENTS = ["per_ab_nolabs_all", "shared_t1"]     # selected on 2021 validation (see reports/03)
PRED = C.PRED


def per_ab_metrics(df, pcol, abs_):
    rows = []
    for ab in abs_:
        s = df[df.ab == ab]
        if s.R.sum() < 10:
            continue
        r = {"antibiotic": ab}; r.update(C.metrics(s.R.values, s[pcol].values)); rows.append(r)
    return pd.DataFrame(rows)


def summarise(name, va, te):
    mv = per_ab_metrics(va, "p", TOP10).add_prefix("val_").rename(columns={"val_antibiotic": "antibiotic"})
    mt = per_ab_metrics(te, "p", TOP10).add_prefix("test_").rename(columns={"test_antibiotic": "antibiotic"})
    m = mv.merge(mt, on="antibiotic")
    m.to_csv(f"{OUT}/exp_{name}.csv", index=False)
    allab = per_ab_metrics(te, "p", sorted(te.ab.unique()))
    allab.to_csv(f"{OUT}/exp_{name}_all_antibiotics_test.csv", index=False)
    res = dict(name=name, val_mean_auroc_top10=round(m.val_auroc.mean(), 4), test_mean_auroc_top10=round(m.test_auroc.mean(), 4),
               val_mean_brier_top10=round(m.val_brier.mean(), 4), test_mean_brier_top10=round(m.test_brier.mean(), 4),
               test_mean_auroc_all=round(allab.auroc.mean(), 4), n_antibiotics_all=len(allab))
    C.save_json(res, f"{OUT}/exp_{name}_summary.json")
    print(json.dumps(res))


def per_ab(fset, scope="top10"):
    """fset: nolabs | labs | orgprob"""
    name = f"per_ab_{fset}" + ("_all" if scope == "all" else "")
    abs_ = TOP10 if scope == "top10" else C.model_antibiotics()
    d, feats = C.build_frame("agnostic", labs=(fset == "labs"), abs_=abs_, orgprob=(fset == "orgprob"))
    feats = [f for f in feats if f != "ab_cat"]
    tr, va, te = C.split(d)
    va = va.copy(); te = te.copy(); va["p"] = np.nan; te["p"] = np.nan
    for ab in abs_:
        a, b = tr[tr.ab == ab], va[va.ab == ab]
        dtr = lgb.Dataset(a[feats], a.R); dva = lgb.Dataset(b[feats], b.R, reference=dtr)
        prm = dict(BASE_PARAMS, num_leaves=31, learning_rate=0.03, min_data_in_leaf=50, max_bin=255)
        m = lgb.train(prm, dtr, 3000, valid_sets=[dva], callbacks=[lgb.early_stopping(100, verbose=False)])
        va.loc[va.ab == ab, "p"] = m.predict(b[feats], num_iteration=m.best_iteration)
        te.loc[te.ab == ab, "p"] = m.predict(te.loc[te.ab == ab, feats], num_iteration=m.best_iteration)
        mdir = C.MODELS if name in FINAL_COMPONENTS else os.path.join(C.MODELS, "experiments")
        os.makedirs(mdir, exist_ok=True)
        m.save_model(f"{mdir}/{name}__{ab.replace('/', '_')}.txt", num_iteration=m.best_iteration)
        print(ab, m.best_iteration, flush=True)
    keep = ["order_proc_id_coded", "anon_id", "ab", "year", "culture_type", "R", "p"]
    va[keep].to_parquet(f"{PRED}/{name}_val.parquet", index=False)
    te[keep].to_parquet(f"{PRED}/{name}_test.parquet", index=False)
    summarise(name, va, te)


def shared(name, labs, overrides, budget=float(os.environ.get("ARMD_BUDGET", 1e9))):
    """budget = seconds per call (only needed on machines that cannot run long jobs)."""
    t0 = time.time()
    params = dict(BASE_PARAMS); params.update(overrides)
    mdir = C.MODELS if name in FINAL_COMPONENTS else os.path.join(C.MODELS, "experiments")
    os.makedirs(mdir, exist_ok=True)
    mfile, sfile = f"{mdir}/{name}.txt", f"{mdir}/_state_{name}.json"
    st = json.load(open(sfile)) if os.path.exists(sfile) else dict(iters=0, best_iter=0, best_auc=0.0, done=False,
                                                                     params=params, labs=labs)
    d, feats = C.build_frame("agnostic", labs=labs)
    tr, va, te = C.split(d); del d
    if not st["done"]:
        dtr = lgb.Dataset(tr[feats], tr.R, free_raw_data=True)
        dva = lgb.Dataset(va[feats], va.R, reference=dtr)
        state = {"stop": False}

        def cb(env):
            it = st["iters"] + env.iteration - env.begin_iteration + 1
            auc = env.evaluation_result_list[0][2]
            if auc > st["best_auc"] + 1e-5:
                st["best_auc"], st["best_iter"] = auc, it
            if it - st["best_iter"] >= 100 or it >= 4000:
                st["done"] = True; raise lgb.callback.EarlyStopException(env.iteration, env.evaluation_result_list)
            if time.time() - t0 > budget:
                raise lgb.callback.EarlyStopException(env.iteration, env.evaluation_result_list)
        init = mfile if st["iters"] > 0 else None
        before = st["iters"]
        b = lgb.train(params, dtr, 4000, valid_sets=[dva], init_model=init, callbacks=[cb])
        st["iters"] = b.current_iteration()
        b.save_model(mfile)
        C.save_json(st, sfile)
        print(f"{name}: trained {st['iters'] - before} rounds this call, total {st['iters']}, best {st['best_iter']} "
              f"val AUROC(all rows) {st['best_auc']:.4f}, done={st['done']}, {time.time() - t0:.0f}s", flush=True)
        if not st["done"]:
            print("CONTINUE"); return
    b = lgb.Booster(model_file=mfile)
    va = va.copy(); te = te.copy()
    va["p"] = b.predict(va[feats], num_iteration=st["best_iter"])
    te["p"] = b.predict(te[feats], num_iteration=st["best_iter"])
    keep = ["order_proc_id_coded", "anon_id", "ab", "year", "culture_type", "R", "p"]
    va[keep].to_parquet(f"{PRED}/{name}_val.parquet", index=False)
    te[keep].to_parquet(f"{PRED}/{name}_test.parquet", index=False)
    summarise(name, va, te)
    print("FINISHED")


def compare(names):
    """Validation-only comparison over all 28 antibiotics, plus the average of the listed models."""
    vals = {n: pd.read_parquet(f"{PRED}/{n}_val.parquet") for n in names}
    key = ["order_proc_id_coded", "ab"]
    base = vals[names[0]][key + ["R", "year", "anon_id", "culture_type"]].copy()
    for n in names:
        base = base.merge(vals[n][key + ["p"]].rename(columns={"p": n}), on=key)
    base["ensemble"] = base[names].mean(axis=1)
    rows = []
    for n in names + ["ensemble"]:
        m = per_ab_metrics(base, n, sorted(base.ab.unique()))
        rows.append(dict(model=n, val_mean_auroc_all=round(m.auroc.mean(), 4), val_mean_auprc_all=round(m.auprc.mean(), 4),
                         val_mean_brier_all=round(m.brier.mean(), 4),
                         val_mean_auroc_top10=round(m[m.antibiotic.isin(TOP10)].auroc.mean(), 4)))
    r = pd.DataFrame(rows); r.to_csv(f"{OUT}/compare_validation.csv", index=False); print(r.to_string(index=False))


def _versions():
    import platform, sklearn
    return dict(python=platform.python_version(), lightgbm=lgb.__version__, pandas=pd.__version__, numpy=np.__version__,
                scikit_learn=sklearn.__version__)


def finalize():
    """Freeze the selected model (chosen on 2021 validation): mean of per-antibiotic and shared LightGBM."""
    key = ["order_proc_id_coded", "ab"]
    out = {}
    for split_ in ["val", "test"]:
        parts = [pd.read_parquet(f"{PRED}/{n}_{split_}.parquet") for n in FINAL_COMPONENTS]
        f = parts[0].drop(columns="p").copy()
        for n, prt in zip(FINAL_COMPONENTS, parts):
            f = f.merge(prt[key + ["p"]].rename(columns={"p": n}), on=key)
        f["p_raw"] = f[FINAL_COMPONENTS].mean(axis=1)
        out[split_] = f
    # per-antibiotic logistic recalibration on logit(p), fitted on the 2021 validation year only
    from sklearn.linear_model import LogisticRegression
    cal = {}
    for ab, g in out["val"].groupby("ab", observed=True):
        x = np.log(np.clip(g.p_raw, 1e-6, 1 - 1e-6) / (1 - np.clip(g.p_raw, 1e-6, 1 - 1e-6))).values.reshape(-1, 1)
        lr = LogisticRegression(C=1e6, max_iter=1000).fit(x, g.R)
        cal[str(ab)] = dict(a=float(lr.intercept_[0]), b=float(lr.coef_[0][0]))
    C.save_json(cal, f"{C.MODELS}/final_calibration.json")
    for split_, f in out.items():
        lg = np.log(np.clip(f.p_raw, 1e-6, 1 - 1e-6) / (1 - np.clip(f.p_raw, 1e-6, 1 - 1e-6)))
        a = f.ab.astype(str).map({k: v["a"] for k, v in cal.items()}); b = f.ab.astype(str).map({k: v["b"] for k, v in cal.items()})
        f["p"] = 1 / (1 + np.exp(-(a + b * lg)))
        f.to_parquet(f"{PRED}/final_{split_}.parquet", index=False)
    tr_pat = set(pd.read_parquet(f"{C.P}/cultures.parquet", columns=["anon_id", "year"]).query("year <= @C.TRAIN_END").anon_id)
    te = out["test"]; te["new_patient"] = ~te.anon_id.isin(tr_pat)
    rows = []
    for ab in sorted(te.ab.unique()):
        s = te[te.ab == ab]; v = out["val"][out["val"].ab == ab]
        r = {"antibiotic": ab}
        r.update({f"val_{k}": x for k, x in C.metrics(v.R, v.p).items()})
        r.update({f"test_{k}": x for k, x in C.metrics(s.R, s.p).items()})
        sn = s[s.new_patient]
        r["test_newpat_auroc"] = C.metrics(sn.R, sn.p)["auroc"] if sn.R.nunique() > 1 else None
        rows.append(r)
    m = pd.DataFrame(rows).sort_values("test_n", ascending=False)
    m.to_csv(f"{OUT}/final_metrics_by_antibiotic.csv", index=False)
    man = dict(components=FINAL_COMPONENTS, combine="mean of probabilities, then per-antibiotic logistic recalibration (fit on 2021 validation)", selected_on="2021 validation",
               antibiotics=sorted(te.ab.unique()),
               states={n: json.load(open(f"{C.MODELS}/_state_{n}.json")) for n in FINAL_COMPONENTS if n.startswith("shared")},
               versions=_versions(),
               val_mean_auroc=round(m.val_auroc.mean(), 4), test_mean_auroc=round(m.test_auroc.mean(), 4),
               test_mean_auroc_top10=round(m[m.antibiotic.isin(TOP10)].test_auroc.mean(), 4),
               test_mean_auprc=round(m.test_auprc.mean(), 4), test_mean_brier=round(m.test_brier.mean(), 4),
               test_mean_newpat_auroc=round(m.test_newpat_auroc.mean(), 4))
    C.save_json(man, f"{C.MODELS}/final_manifest.json")
    print(json.dumps({k: v for k, v in man.items() if k not in ("states", "antibiotics")}))


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True); os.makedirs(PRED, exist_ok=True); os.makedirs(C.MODELS, exist_ok=True)
    if sys.argv[1] == "finalize":
        finalize()
    elif sys.argv[1] == "compare":
        compare(sys.argv[2:])
    elif sys.argv[1] == "per_ab":
        per_ab(sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "top10")
    else:
        ov = {}
        for kv in sys.argv[4:]:
            k, v = kv.split("="); ov[k] = float(v) if "." in v else int(v)
        shared(sys.argv[2], sys.argv[3] == "labs", ov)

"""Per-antibiotic LightGBM baselines for ARMD-Stanford.

Usage (from project root):  python src/03_train_baseline.py agnostic   # predict at culture order
                            python src/03_train_baseline.py organism   # organism already identified
Split: temporal. Train 2008-2020, validate 2021 (early stopping), test 2022-2024.
Test metrics are also reported on 'new patients' (no culture in the training period).
Outputs: reports/baseline/<mode>_metrics.csv, <mode>_feature_importance.csv
"""
import os, sys, json
import numpy as np
import pandas as pd
import lightgbm as lgb
from sklearn.metrics import roc_auc_score, average_precision_score, brier_score_loss

P, O = "data/processed", "reports/baseline"
os.makedirs(O, exist_ok=True)
MODE = sys.argv[1]
N_AB = 10
SEED = 7

cul = pd.read_parquet(f"{P}/cultures.parquet")
hist = pd.read_parquet(f"{P}/history.parquet")
cul = cul.merge(hist, on="order_proc_id_coded", how="left")
import re
cul.columns = [re.sub(r"[^0-9a-zA-Z_]", "_", c) for c in cul.columns]
for col in ["culture_type", "ordering_mode", "gender"]:
    cul[col] = cul[col].astype("category")
plong = pd.read_parquet(f"{P}/prior_resistance_long.parquet")
own = pd.read_parquet(f"{P}/own_history_long.parquet")

if MODE == "agnostic":
    lab = pd.read_parquet(f"{P}/labels_agnostic.parquet")
else:
    lab = pd.read_parquet(f"{P}/labels_organism.parquet")
    top_org = lab.organism.value_counts().head(30).index
    lab["organism_grp"] = lab.organism.where(lab.organism.isin(top_org), "OTHER")

drop = {"order_proc_id_coded", "anon_id", "t", "year", "age"}
base_feats = [c for c in cul.columns if c not in drop]


def sens_at_spec(y, p, spec=0.9):
    neg = np.sort(p[y == 0]); thr = neg[int(np.ceil(spec * len(neg))) - 1]
    return float((p[y == 1] > thr).mean())


def metrics(y, p):
    return dict(n=len(y), prevalence=round(float(y.mean()), 4), auroc=round(roc_auc_score(y, p), 4),
                auprc=round(average_precision_score(y, p), 4), brier=round(brier_score_loss(y, p), 4),
                sens_at_90spec=round(sens_at_spec(y, p), 4))


top_abs = lab.ab.value_counts().head(N_AB).index.tolist()
rows, imps = [], []
for ab in top_abs:
    d = lab[lab.ab == ab].merge(cul, on="order_proc_id_coded")
    pr = plong[plong.ab == ab][["order_proc_id_coded", "priorR_target_days", "priorR_target_n"]]
    d = d.merge(pr, on="order_proc_id_coded", how="left")
    d = d.merge(own[own.ab == ab].drop(columns="ab"), on="order_proc_id_coded", how="left")
    feats = base_feats + ["priorR_target_days", "priorR_target_n", "own_lastR_days", "own_lastTested_days", "own_nR"]
    if MODE == "organism":
        d["organism_grp"] = d.organism_grp.astype("category")
        feats = feats + ["organism_grp"]
    tr, va, te = d[d.year <= 2020], d[d.year == 2021], d[d.year >= 2022]
    if te.R.sum() < 20 or tr.R.sum() < 50:
        print("skip", ab); continue
    m = lgb.LGBMClassifier(n_estimators=2000, learning_rate=0.03, num_leaves=31, min_child_samples=50,
                           subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0,
                           random_state=SEED, verbose=-1)
    m.fit(tr[feats], tr.R, eval_set=[(va[feats], va.R)], eval_metric="auc",
          callbacks=[lgb.early_stopping(100, verbose=False)])
    p = m.predict_proba(te[feats])[:, 1]
    y = te.R.values

    # comparators, all fit on the training period only
    #  antibiogram: resistance rate by culture type (organism-agnostic) or by organism (organism-known)
    key = "organism_grp" if MODE == "organism" else "culture_type"
    rate = tr.groupby(key, observed=True).R.mean()
    p_abg = te[key].map(rate).astype(float).fillna(tr.R.mean()).values
    #  rule: prior resistance to this antibiotic (>=3 d) -> high risk, else antibiogram
    #  (as a probability: training-period resistance rate per antibiogram group x prior-resistance flag)
    trf = tr.assign(prior=tr.own_lastR_days.notna()); tef = te.assign(prior=te.own_lastR_days.notna())
    rr = trf.groupby([key, "prior"], observed=True).R.mean()
    p_rule = pd.Series(list(zip(tef[key], tef.prior))).map(rr).astype(float).fillna(tr.R.mean()).values

    new = ~te.anon_id.isin(set(tr.anon_id))
    r = dict(antibiotic=ab, n_train=len(tr), n_test=len(te), best_iter=m.best_iteration_)
    for name, pp in [("lgbm", p), ("antibiogram", p_abg), ("priorR_rule", p_rule)]:
        for k, v in metrics(y, pp).items():
            r[f"{name}_{k}"] = v
    nm = metrics(y[new.values], p[new.values])
    r.update({f"lgbm_newpat_{k}": v for k, v in nm.items()})
    rows.append(r)
    imp = pd.Series(m.booster_.feature_importance("gain"), index=feats)
    imps.append((imp / imp.sum()).rename(ab))
    print(f"{ab:32s} test n={len(te):6d} prev={y.mean():.3f}  LGBM AUROC={r['lgbm_auroc']:.3f}  "
          f"antibiogram={r['antibiogram_auroc']:.3f}  priorR rule={r['priorR_rule_auroc']:.3f}  "
          f"new-pat AUROC={nm['auroc']:.3f}", flush=True)

res = pd.DataFrame(rows)
res.to_csv(f"{O}/{MODE}_metrics.csv", index=False)
fi = pd.concat(imps, axis=1)
fi["mean"] = fi.mean(axis=1)
fi.sort_values("mean", ascending=False).round(4).to_csv(f"{O}/{MODE}_feature_importance.csv")
print("\nmean AUROC  lgbm=%.3f antibiogram=%.3f rule=%.3f" % (res.lgbm_auroc.mean(), res.antibiogram_auroc.mean(),
                                                            res.priorR_rule_auroc.mean()))
print(fi.sort_values("mean", ascending=False)["mean"].head(12).round(3).to_string())

"""Phase D: explainability of the frozen model (TreeSHAP via LightGBM pred_contrib).
Outputs (reports/phaseD/): global importance by feature and by family, per-antibiotic top features,
dependence of risk on 'days since last resistant result', and worked example cases.
Usage: python src/07_explain.py"""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C
from predictor import ResistancePredictor, family, describe

O = os.path.join(C.REPORTS, "phaseD")
TOP10 = ["ciprofloxacin", "gentamicin", "trimethoprim/sulfamethoxazole", "levofloxacin", "ampicillin",
         "nitrofurantoin", "piperacillin/tazobactam", "cefazolin", "ceftriaxone", "meropenem"]


def main():
    os.makedirs(O, exist_ok=True)
    rp = ResistancePredictor()
    d, _ = C.build_frame("agnostic"); _, _, te = C.split(d); del d
    s = te.sample(min(10000, len(te)), random_state=C.SEED).copy()
    s["p"] = rp.predict(s)
    e = rp.explain(s); feats = [c for c in e.columns if c != "bias"]
    imp = e[feats].abs().mean().sort_values(ascending=False)
    fam = imp.groupby(imp.index.map(family)).sum().sort_values(ascending=False)
    imp_df = pd.DataFrame(dict(mean_abs_shap=imp.round(4), family=imp.index.map(family),
                               description=[describe(f, np.nan).split(":")[0] for f in imp.index]))
    imp_df.to_csv(f"{O}/global_importance_features.csv"); fam.round(4).rename("mean_abs_shap").to_csv(f"{O}/global_importance_families.csv")

    rows = []
    for ab in TOP10:
        m = (s.ab.astype(str) == ab).values
        t = e.loc[m, feats].abs().mean().sort_values(ascending=False).head(5)
        rows.append(dict(antibiotic=ab, n=int(m.sum()), **{f"top{i+1}": f"{describe(k, np.nan).split(':')[0]} ({v:.3f})" for i, (k, v) in enumerate(t.items())}))
    pd.DataFrame(rows).to_csv(f"{O}/top_features_by_antibiotic.csv", index=False)

    # dependence: days since last resistant result to the same antibiotic
    x = s.own_lastR_days; c = e.own_lastR_days
    bins = pd.cut(x, [0, 30, 90, 180, 365, 730, 1825, 10000], labels=["3-30", "31-90", "91-180", "181-365", "1-2 y", "2-5 y", ">5 y"])
    dep = pd.DataFrame(dict(bin=bins, shap=c, R=s.R)).groupby("bin", observed=True).agg(n=("R", "size"), mean_shap_logodds=("shap", "mean"), resistant_rate=("R", "mean"))
    none = dict(n=int(x.isna().sum()), mean_shap_logodds=float(c[x.isna()].mean()), resistant_rate=float(s.R[x.isna()].mean()))
    dep.loc["never resistant"] = none
    dep.round(3).to_csv(f"{O}/dependence_last_resistant_days.csv")

    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(1, 2, figsize=(13, 5), gridspec_kw=dict(width_ratios=[1, 1.15]))
    ff = fam[::-1]; ax[0].barh(ff.index, ff.values, color="#2a6fb0"); ax[0].set_xlabel("mean |SHAP| (log-odds)")
    ax[0].set_title("What drives predictions (feature families)", fontsize=10); ax[0].tick_params(labelsize=8)
    ii = imp.head(15)[::-1]
    ax[1].barh([describe(k, np.nan).split(":")[0][:55] for k in ii.index], ii.values, color="#5b8fc7")
    ax[1].set_xlabel("mean |SHAP| (log-odds)"); ax[1].set_title("Top 15 individual features", fontsize=10); ax[1].tick_params(labelsize=7)
    fig.tight_layout(); fig.savefig(f"{O}/global_importance.png", dpi=140); plt.close(fig)

    # worked cases: highest-risk true positive, lowest-risk true negative, confident miss (false negative)
    s["base_p"] = 1 / (1 + np.exp(-e["bias"]))
    cases = {"High predicted risk, resistant (correct)": s[(s.R == 1)].p.idxmax(),
             "Low predicted risk, susceptible (correct)": s[(s.R == 0) & (s.ab.astype(str) == "ciprofloxacin")].p.idxmin(),
             "Low predicted risk but resistant (missed)": s[(s.R == 1) & (s.ab.astype(str) == "ciprofloxacin")].p.idxmin()}
    lines = ["# Worked example cases (2022-2024 test set)\n",
             "Contributions are SHAP values in log-odds: positive pushes toward resistance, negative toward susceptibility.\n"]
    for title, i in cases.items():
        r = s.loc[i]; ce = e.loc[i, feats].sort_values(key=np.abs, ascending=False).head(6)
        lines.append(f"## {title}\n")
        lines.append(f"- Antibiotic: **{r.ab}**, specimen: {r.culture_type}, ordered as: {r.ordering_mode}")
        lines.append(f"- Predicted resistance risk: **{r.p:.1%}**; actual result: **{'Resistant' if r.R == 1 else 'Susceptible/Intermediate'}**\n")
        lines.append("| Factor | Value in this case | Contribution (log-odds) |\n| --- | --- | --- |")
        for f, v in ce.items():
            dsc = describe(f, r[f]); name, val = (dsc.split(": ", 1) + [""])[:2]
            lines.append(f"| {name} | {val} | {v:+.2f} |")
        lines.append("")
    open(f"{O}/example_cases.md", "w").write("\n".join(lines))
    print(fam.round(3).to_string()); print(imp.head(12).round(3).to_string()); print(dep.round(3).to_string())


if __name__ == "__main__":
    main()

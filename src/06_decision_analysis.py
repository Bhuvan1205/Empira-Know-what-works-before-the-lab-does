"""Phase C: clinical decision analysis for empiric therapy of urine cultures.
Constraint: nitrofurantoin is not offered for inpatient cultures (policy and antibiogram alike).

Policy: give the narrowest antibiotic (ordered list below) whose predicted resistance risk <= threshold.
Clinician: the systemic candidate antibiotic recorded on the day of the culture order (prior_med, day 0).
Cohort: urine cultures with results for ALL candidate antibiotics and exactly one clinician candidate drug.
Threshold chosen on 2021 validation (match clinician's inappropriate-therapy rate); reported on 2022-24 test.
Outcomes: inappropriate therapy = organism resistant (or intermediate, sensitivity) to the drug given;
          use of second-line / broad drugs.
Usage: python src/06_decision_analysis.py
"""
import sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as C

O = os.path.join(C.REPORTS, "phaseC")
PRED = C.PRED
# narrow -> broad (AWaRe Access first, then Watch, then broad Watch/Reserve-like)
CANDIDATES = ["nitrofurantoin", "trimethoprim/sulfamethoxazole", "cefazolin", "ciprofloxacin", "ceftriaxone",
              "piperacillin/tazobactam", "meropenem"]
TIER = {"nitrofurantoin": "first-line", "trimethoprim/sulfamethoxazole": "first-line", "cefazolin": "first-line",
        "ciprofloxacin": "second-line", "ceftriaxone": "second-line",
        "piperacillin/tazobactam": "broad", "meropenem": "broad"}
# clinician drug -> antibiotic whose susceptibility result is used as its surrogate
MED_MAP = {"Nitrofurantoin": "nitrofurantoin", "Macrobid": "nitrofurantoin", "Nitrofurantoin Macrocrystal": "nitrofurantoin",
           "Sulfamethoxazole-Trimethoprim": "trimethoprim/sulfamethoxazole", "Bactrim Ds": "trimethoprim/sulfamethoxazole",
           "Bactrim": "trimethoprim/sulfamethoxazole",
           "Cephalexin": "cefazolin", "Keflex": "cefazolin", "Cefadroxil": "cefazolin", "Cefazolin": "cefazolin",
           "Cefazolin In Dextrose": "cefazolin",
           "Ciprofloxacin Hcl": "ciprofloxacin", "Ciprofloxacin In": "ciprofloxacin", "Cipro": "ciprofloxacin",
           "Levofloxacin": "ciprofloxacin", "Levofloxacin In": "ciprofloxacin", "Ofloxacin": "ciprofloxacin",
           "Ceftriaxone": "ceftriaxone", "Cefpodoxime": "ceftriaxone", "Cefdinir": "ceftriaxone",
           "Piperacillin-Tazobactam-Dextrs": "piperacillin/tazobactam", "Piperacillin-Tazobactam": "piperacillin/tazobactam",
           "Meropenem": "meropenem", "Meropenem-Sodium Chloride": "meropenem"}


def cohort(split_):
    pr = pd.read_parquet(f"{PRED}/final_{split_}.parquet")
    pr = pr[(pr.culture_type == "URINE") & pr.ab.isin(CANDIDATES)]
    lab = pd.read_parquet(f"{C.P}/labels_agnostic.parquet")
    pr = pr.merge(lab[["order_proc_id_coded", "ab", "NS"]], on=["order_proc_id_coded", "ab"])
    P = pr.pivot(index="order_proc_id_coded", columns="ab", values="p")
    R = pr.pivot(index="order_proc_id_coded", columns="ab", values="R")
    NS = pr.pivot(index="order_proc_id_coded", columns="ab", values="NS")
    full = P.dropna(subset=CANDIDATES).index
    meds = pd.read_parquet(f"{C.P}/sameday_meds_2021plus.parquet")
    meds["drug"] = meds.medication_name.map(MED_MAP)
    meds = meds.dropna(subset=["drug"]).drop_duplicates(["order_proc_id_coded", "drug"])
    one = meds.groupby("order_proc_id_coded").drug.nunique()
    clin = meds[meds.order_proc_id_coded.isin(one[one == 1].index)].drop_duplicates("order_proc_id_coded") \
        .set_index("order_proc_id_coded").drug
    ids = full.intersection(clin.index)
    cul = pd.read_parquet(f"{C.P}/cultures.parquet").set_index("order_proc_id_coded")
    stats = dict(urine_cultures=int(pr.order_proc_id_coded.nunique()), all_candidates_tested=len(full),
                 with_one_clinician_candidate=len(ids))
    return P.loc[ids, CANDIDATES], R.loc[ids, CANDIDATES], NS.loc[ids, CANDIDATES], clin.loc[ids], cul.loc[ids], stats


def allowed_mask(cul):
    """Clinical constraint: nitrofurantoin only for non-inpatient urine cultures (cystitis); it does not reach
    therapeutic levels for pyelonephritis/bacteraemia, which dominate inpatient urine cultures."""
    A = np.ones((len(cul), len(CANDIDATES)), dtype=bool)
    A[(cul.ordering_mode == "Inpatient").values, CANDIDATES.index("nitrofurantoin")] = False
    return A


def policy(Pm, thr, A):
    """index of first allowed candidate with p <= thr; if none, the lowest-risk allowed candidate"""
    ok = (Pm <= thr) & A
    Pa = np.where(A, Pm, np.inf)
    return np.where(ok.any(1), ok.argmax(1), Pa.argmin(1))


def outcomes(choice_idx, Rm, NSm):
    rows = np.arange(len(choice_idx))
    tiers = np.array([TIER[c] for c in CANDIDATES])[choice_idx]
    return dict(n=len(choice_idx), inappropriate_R=float(Rm[rows, choice_idx].mean()),
                inappropriate_NS=float(NSm[rows, choice_idx].mean()),
                second_line_or_broad=float((tiers != "first-line").mean()), broad=float((tiers == "broad").mean()))


def evaluate(split_):
    P, R, NS, clin, cul, stats = cohort(split_)
    Pm, Rm, NSm = P.values, R.values, NS.values
    cidx = clin.map({c: i for i, c in enumerate(CANDIDATES)}).values
    res = {"clinician": outcomes(cidx, Rm, NSm)}
    # antibiogram policy: same rule but with training-period resistance rates for urine (identical for everyone)
    return P, Pm, Rm, NSm, cidx, cul, stats, res


def main():
    os.makedirs(O, exist_ok=True)
    tr_rates = None
    out = {}
    # threshold selection on validation
    _, Pv, Rv, NSv, cv, culv, sv, resv = evaluate("val")
    Av = allowed_mask(culv)
    grid = np.round(np.arange(0.02, 0.61, 0.01), 2)
    curve_v = pd.DataFrame([dict(threshold=t, **outcomes(policy(Pv, t, Av), Rv, NSv)) for t in grid])
    clin_v = resv["clinician"]
    feas = curve_v[curve_v.inappropriate_R <= clin_v["inappropriate_R"]]
    t_match_inapp = float(feas.sort_values("second_line_or_broad").threshold.iloc[0])
    feas2 = curve_v[curve_v.second_line_or_broad <= clin_v["second_line_or_broad"]]
    t_match_2nd = float(feas2.sort_values("inappropriate_R").threshold.iloc[0])
    # test
    Pt_df, Pt, Rt, NSt, ct, cult, st, rest = evaluate("test")
    At = allowed_mask(cult)
    curve_t = pd.DataFrame([dict(threshold=t, **outcomes(policy(Pt, t, At), Rt, NSt)) for t in grid])
    # antibiogram baseline: training-period (<=2020) urine resistance rates -> same choice for everyone
    lab = pd.read_parquet(f"{C.P}/labels_agnostic.parquet")
    cu = pd.read_parquet(f"{C.P}/cultures.parquet", columns=["order_proc_id_coded", "year", "culture_type"])
    x = lab.merge(cu, on="order_proc_id_coded"); x = x[(x.year <= C.TRAIN_END) & (x.culture_type == "URINE") & x.ab.isin(CANDIDATES)]
    abg = x.groupby("ab").R.mean().reindex(CANDIDATES)
    abg_rows = []
    Pabg = np.tile(abg.values, (len(Pt), 1))
    for t in grid:
        ch = policy(Pabg, t, At)
        drugs = "+".join(sorted(set(np.array(CANDIDATES)[ch])))
        abg_rows.append(dict(threshold=t, **outcomes(ch, Rt, NSt), drug=drugs))
    abg_curve = pd.DataFrame(abg_rows)

    def at(t):
        return outcomes(policy(Pt, t, At), Rt, NSt)
    summary = dict(cohort_val=sv, cohort_test=st, clinician_val=clin_v, clinician_test=rest["clinician"],
                   threshold_match_inappropriate=t_match_inapp, policy_test_at_match_inappropriate=at(t_match_inapp),
                   threshold_match_second_line=t_match_2nd, policy_test_at_match_second_line=at(t_match_2nd),
                   antibiogram_urine_rates_train=abg.round(4).to_dict())
    clin_mix = pd.Series(np.array(CANDIDATES)[ct]).value_counts(normalize=True).round(3).to_dict()
    pol_mix = pd.Series(np.array(CANDIDATES)[policy(Pt, t_match_inapp, At)]).value_counts(normalize=True).round(3).to_dict()
    pol_mix2 = pd.Series(np.array(CANDIDATES)[policy(Pt, t_match_2nd, At)]).value_counts(normalize=True).round(3).to_dict()
    summary["clinician_drug_mix_test"] = clin_mix; summary["policy_drug_mix_test_at_match_inappropriate"] = pol_mix
    summary["policy_drug_mix_test_at_match_second_line"] = pol_mix2
    summary["clinician_inpatient_nitrofurantoin_share_test"] = round(float(((cult.ordering_mode == "Inpatient").values & (ct == 0)).sum() / max((cult.ordering_mode == "Inpatient").sum(), 1)), 4)
    # outpatient subgroup (closest to uncomplicated cystitis)
    op = (cult.ordering_mode == "Outpatient").values
    summary["outpatient_test"] = dict(n=int(op.sum()), clinician=outcomes(ct[op], Rt[op], NSt[op]),
                                      policy_match_inappropriate=outcomes(policy(Pt[op], t_match_inapp, At[op]), Rt[op], NSt[op]),
                                      policy_match_second_line=outcomes(policy(Pt[op], t_match_2nd, At[op]), Rt[op], NSt[op]))
    # bootstrap CIs for paired differences (policy - clinician) at both operating points (resample cultures)
    rng = np.random.default_rng(C.SEED); rows = np.arange(len(Pt))
    tierarr = np.array([TIER[c] for c in CANDIDATES])
    ic, nc, tc = Rt[rows, ct], NSt[rows, ct], tierarr[ct] != "first-line"
    B = rng.integers(0, len(rows), (2000, len(rows)))
    for name, t in [("match_inappropriate", t_match_inapp), ("match_second_line", t_match_2nd)]:
        pidx = policy(Pt, t, At); ip, np_, tp = Rt[rows, pidx], NSt[rows, pidx], tierarr[pidx] != "first-line"
        res_ = {}
        for lbl, a, b_ in [("inappropriate_R", ip, ic), ("inappropriate_NS", np_, nc), ("second_line_or_broad", tp, tc)]:
            dd = a[B].mean(1) - b_[B].mean(1)
            res_[lbl] = [round(float(a.mean() - b_.mean()), 4), round(float(np.percentile(dd, 2.5)), 4), round(float(np.percentile(dd, 97.5)), 4)]
        summary[f"diff_policy_minus_clinician_{name}"] = res_
    C.save_json(summary, f"{O}/decision_summary.json")
    curve_t.to_csv(f"{O}/policy_curve_test.csv", index=False); curve_v.to_csv(f"{O}/policy_curve_val.csv", index=False)
    abg_curve.to_csv(f"{O}/antibiogram_curve_test.csv", index=False)

    import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.plot(curve_t.second_line_or_broad * 100, curve_t.inappropriate_R * 100, color="#2a6fb0", lw=2, label="Model-guided policy (threshold sweep)")
    a2 = abg_curve.drop_duplicates("drug")
    ax.scatter(a2.second_line_or_broad * 100, a2.inappropriate_R * 100, color="#999", zorder=3, label="Antibiogram (one drug per setting: outpatient / inpatient)")
    for _, r in a2.iterrows():
        ax.annotate(r.drug.split("/")[0], (r.second_line_or_broad * 100, r.inappropriate_R * 100), fontsize=7, xytext=(4, 2), textcoords="offset points", color="#666")
    c = rest["clinician"]; ax.scatter([c["second_line_or_broad"] * 100], [c["inappropriate_R"] * 100], color="#c0392b", s=70, zorder=4, label="Clinicians (actual)")
    for t, mk, lbl in [(t_match_inapp, "D", "same error rate as clinicians"), (t_match_2nd, "s", "same 2nd-line use as clinicians")]:
        m = at(t); ax.scatter([m["second_line_or_broad"] * 100], [m["inappropriate_R"] * 100], color="#2a6fb0", s=70, marker=mk, zorder=4,
                              label=f"Policy at threshold {t} ({lbl}; set on 2021)")
    ax.set_xlabel("Second-line or broad-spectrum use (%)"); ax.set_ylabel("Inappropriate therapy: organism resistant (%)")
    ax.set_title(f"Empiric therapy for urine cultures, 2022–2024 test (n={len(Pt):,})", fontsize=10)
    ax.legend(fontsize=8); ax.grid(alpha=.3); fig.tight_layout(); fig.savefig(f"{O}/policy_vs_clinician.png", dpi=140)
    import json; print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()

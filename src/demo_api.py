"""Demo-facing API on top of the frozen model.  Everything the demo needs, nothing it must re-derive.

    from demo_api import AMRDemoAPI
    api = AMRDemoAPI()
    out = api.score({                                   # a hypothetical patient, simple inputs
        "culture_type": "URINE", "setting": "Outpatient", "age_band": "65-74 years", "sex_code": 0,
        "prior_resistance": [{"antibiotic": "ciprofloxacin", "days_ago": 120}],
        "prior_antibiotics": [{"class": "fluoroquinolone", "days_ago": 30}],
    })
    out = api.score_test_culture(order_proc_id)         # a real 2022-24 test culture, with true results
    api.example_cases()                                 # a few interesting test cultures for the demo

Returns a dict: per-antibiotic risk table (calibrated probability, risk band, top reasons), and for urine
cultures the narrowest-safe recommendation from the Phase C policy. Inputs that would break the model's
leakage rules (history < 3 days before the culture, exposures < 1 day) are ignored with a warning.
Not a medical device; for research demonstration only.
"""
import os, json
import numpy as np
import pandas as pd
import common as C
from predictor import ResistancePredictor, describe

AGE_BANDS = ["18-24 years", "25-34 years", "35-44 years", "45-54 years", "55-64 years", "65-74 years",
             "75-84 years", "85-89 years", "above 90"]
SETTINGS = {  # setting -> (ordering_mode, IP, OP, ER, ICU), as coded in ARMD-Stanford
    "Outpatient": ("Outpatient", 0, 1, 0, 0), "ER": ("Inpatient", 1, 0, 1, 0),
    "Inpatient": ("Inpatient", 1, 0, 0, 0), "ICU": ("Inpatient", 1, 0, 0, 1)}
URINE_POLICY = dict(candidates=["nitrofurantoin", "trimethoprim/sulfamethoxazole", "cefazolin", "ciprofloxacin",
                                "ceftriaxone", "piperacillin/tazobactam", "meropenem"],
                    tiers={"nitrofurantoin": "first-line", "trimethoprim/sulfamethoxazole": "first-line", "cefazolin": "first-line",
                           "ciprofloxacin": "second-line", "ceftriaxone": "second-line",
                           "piperacillin/tazobactam": "broad", "meropenem": "broad"},
                    thresholds={"balanced (same 2nd-line use as clinicians, fewer mismatches)": 0.15,
                                "stewardship (same mismatch rate as clinicians, far less 2nd-line use)": 0.20},
                    default_threshold=0.15,
                    note="Validated retrospectively on 2022-24 urine cultures (reports/05). Nitrofurantoin not offered for inpatient/ER/ICU cultures.")
GAP_HISTORY, GAP_EXPOSURE = 3, 1


def risk_band(p):
    return "high" if p >= 0.30 else "moderate" if p >= 0.10 else "low"


class AMRDemoAPI:
    def __init__(self):
        self.rp = ResistancePredictor()
        self.antibiotics = self.rp.antibiotics
        f = self.rp.shared_feats
        self.priorR_cols = [c for c in f if c.startswith("priorR_") and c not in ("priorR_n_events", "priorR_n_types_90d", "priorR_target_days", "priorR_target_n")]
        self.org_cols = [c for c in f if c.startswith("priorOrg_") and not c.startswith("priorOrg_n_")]
        self.abx_cols = [c for c in f if c.startswith("abx_") and not c.startswith("abx_n_")]
        self.proc_cols = [c for c in f if c.startswith("proc_") and not c.startswith("proc_n_")]
        self.registry_abs = sorted(pd.read_parquet(f"{C.P}/prior_resistance_long.parquet", columns=["ab"]).ab.unique())
        self.cats = dict(zip(["culture_type", "ordering_mode", "gender", "ab_cat"], self.rp.shared.pandas_categorical))
        self.test_freq = self._testing_frequency()

    @staticmethod
    def _testing_frequency():
        """Share of positive training-period cultures of each specimen type in which each antibiotic was tested."""
        f = f"{C.MODELS}/testing_frequency.json"
        if os.path.exists(f):
            return {tuple(k.split("|")): v for k, v in json.load(open(f)).items()}
        lab = pd.read_parquet(f"{C.P}/labels_agnostic.parquet", columns=["order_proc_id_coded", "ab"])
        cul = pd.read_parquet(f"{C.P}/cultures.parquet", columns=["order_proc_id_coded", "year", "culture_type"])
        x = lab.merge(cul, on="order_proc_id_coded"); x = x[x.year <= C.TRAIN_END]
        n = x.groupby("culture_type").order_proc_id_coded.nunique()
        fr = (x.groupby(["culture_type", "ab"]).order_proc_id_coded.nunique() / n.reindex(x.groupby(["culture_type", "ab"]).size().index.get_level_values(0)).values).round(4)
        out = {f"{a}|{b}": float(v) for (a, b), v in fr.items()}
        C.save_json(out, f)
        return {tuple(k.split("|")): v for k, v in out.items()}

    # ---------- schema for UIs ----------
    def schema(self):
        return dict(culture_types=self.cats["culture_type"], settings=list(SETTINGS), age_bands=AGE_BANDS, sex_codes=[0, 1],
                    antibiotics=self.antibiotics,
                    prior_resistance_antibiotics=sorted(set(self.antibiotics) | set(self.registry_abs)),
                    prior_organisms=[c[len("priorOrg_"):] for c in self.org_cols],
                    prior_antibiotic_classes=[c[len("abx_"):] for c in self.abx_cols],
                    procedures=[c[len("proc_"):] for c in self.proc_cols],
                    urine_policy=URINE_POLICY, gaps_days=dict(history=GAP_HISTORY, exposure=GAP_EXPOSURE))

    # ---------- feature construction from simple inputs ----------
    @staticmethod
    def _events(items, key, min_gap, warn, label):
        out = []
        for it in items or []:
            d = float(it["days_ago"])
            if d < min_gap:
                warn.append(f"Ignored {label} '{it[key]}' {d:.0f} day(s) before the culture (model uses >= {min_gap} days).")
                continue
            out.append((str(it[key]).lower().strip(), d))
        return out

    @staticmethod
    def _block(events, cols, prefix, row):
        if not events:
            return
        for name, d in events:
            c = prefix + name.replace(" ", "_").replace("/", "_")
            if c in cols:
                row[c] = d if np.isnan(row.get(c, np.nan)) else min(row[c], d)
        row[prefix + "n_events"] = float(len(events))
        recent = {n for n, d in events if d <= 90}
        row[prefix + "n_types_90d"] = float(len(recent)) if recent else np.nan

    def build_rows(self, patient):
        warn = []
        ct = patient.get("culture_type", "URINE").upper()
        if ct not in self.cats["culture_type"]:
            raise ValueError(f"culture_type must be one of {self.cats['culture_type']}")
        setting = patient.get("setting", "Outpatient")
        mode, ip, op, er, icu = SETTINGS[setting]
        age = patient.get("age_band", "55-64 years")
        base = {f: np.nan for f in self.rp.shared_feats}
        base.update(hosp_ward_IP=ip, hosp_ward_OP=op, hosp_ward_ER=er, hosp_ward_ICU=icu,
                    adi_score=patient.get("adi_score", np.nan), adi_state_rank=np.nan,
                    nursing_home=1.0 if patient.get("nursing_home") else 0.0, age_ord=float(AGE_BANDS.index(age)))
        res = self._events(patient.get("prior_resistance"), "antibiotic", GAP_HISTORY, warn, "resistance")
        tested = self._events(patient.get("prior_tested"), "antibiotic", GAP_HISTORY, warn, "test")
        orgs = self._events(patient.get("prior_organisms"), "organism", GAP_HISTORY, warn, "organism")
        abx = self._events(patient.get("prior_antibiotics"), "class", GAP_EXPOSURE, warn, "antibiotic exposure")
        procs = self._events(patient.get("procedures"), "procedure", GAP_EXPOSURE, warn, "procedure")
        self._block([e for e in res if e[0] in self.registry_abs], self.priorR_cols, "priorR_", base)
        self._block(orgs, self.org_cols, "priorOrg_", base)
        self._block(abx, self.abx_cols, "abx_", base)
        self._block(procs, self.proc_cols, "proc_", base)
        rows = []
        for ab in self.antibiotics:
            r = dict(base)
            rd = [d for n, d in res if n == ab]; td = [d for n, d in tested if n == ab]
            r["own_lastR_days"] = min(rd) if rd else np.nan
            r["own_nR"] = float(len(rd))
            r["own_lastTested_days"] = min(rd + td) if (rd or td) else np.nan
            if ab in self.registry_abs and rd:
                r["priorR_target_days"], r["priorR_target_n"] = min(rd), float(len(rd))
            r.update(culture_type=ct, ordering_mode=mode, gender=float(patient.get("sex_code", 0)), ab=ab, ab_cat=ab)
            rows.append(r)
        d = pd.DataFrame(rows)
        for c in ["culture_type", "ordering_mode", "gender", "ab_cat"]:
            d[c] = pd.Categorical(d[c], categories=self.cats[c])
        num = [c for c in self.rp.shared_feats if c not in ("culture_type", "ordering_mode", "gender", "ab_cat")]
        d[num] = d[num].astype("float32")
        return d, warn, setting

    # ---------- scoring ----------
    def _result(self, d, warn, setting, culture_type, truth=None, top_k=4, threshold=None):
        p = self.rp.predict(d); e = self.rp.explain(d)
        feats = [c for c in e.columns if c != "bias"]
        table = []
        for i in range(len(d)):
            ab = str(d.ab.iloc[i]); ce = e.iloc[i][feats]
            ce = ce[(ce.abs() > 0.02) & (~ce.index.isin(["ab_cat"]))].sort_values(key=np.abs, ascending=False).head(top_k)
            reasons = [dict(factor=describe(f, d[f].iloc[i]), effect=("raises risk" if v > 0 else "lowers risk"), log_odds=round(float(v), 3))
                       for f, v in ce.items()]
            freq = self.test_freq.get((str(culture_type), ab), 0.0)
            row = dict(antibiotic=ab, risk=round(float(p[i]), 4), band=risk_band(p[i]), reasons=reasons,
                       routinely_tested=bool(freq >= 0.05), tested_share_for_specimen=freq)
            if truth is not None:
                row["actual"] = truth.get(ab)
            table.append(row)
        table.sort(key=lambda r: (not r["routinely_tested"], r["risk"]))   # routine drugs first, then rarely-tested ones
        rare = [r["antibiotic"] for r in table if not r["routinely_tested"]]
        if rare:
            warn = warn + [f"Rarely tested on {culture_type.lower()} specimens (<5% of cultures), so interpret with caution: " + ", ".join(rare)]
        out = dict(culture_type=culture_type, setting=setting, warnings=warn, antibiotics=table,
                   disclaimer="Research prototype. Not for clinical use.")
        if culture_type == "URINE":
            out["recommendation"] = self.recommend_urine(p, d, setting, threshold)
        else:
            out["recommendation"] = dict(available=False, note="The narrowest-safe policy was validated for urine cultures only; ranked risks are shown instead.")
        return out

    def recommend_urine(self, p, d, setting, threshold=None):
        t = URINE_POLICY["default_threshold"] if threshold is None else float(threshold)
        risk = dict(zip(d.ab.astype(str), p))
        allowed = [c for c in URINE_POLICY["candidates"] if not (c == "nitrofurantoin" and setting != "Outpatient")]
        options = [dict(antibiotic=c, risk=round(float(risk[c]), 4), tier=URINE_POLICY["tiers"][c]) for c in allowed if c in risk]
        choice = next((o for o in options if o["risk"] <= t), min(options, key=lambda o: o["risk"]))
        return dict(available=True, threshold=t, choice=choice["antibiotic"], choice_risk=choice["risk"], tier=choice["tier"],
                    considered=options, rule=f"Narrowest candidate with predicted resistance <= {t:.0%}; if none, the lowest-risk candidate.",
                    note=URINE_POLICY["note"])

    def score(self, patient, threshold=None):
        d, warn, setting = self.build_rows(patient)
        return self._result(d, warn, setting, d.culture_type.iloc[0], threshold=threshold)

    def _test_frame(self):
        if not hasattr(self, "_te"):
            d, _ = C.build_frame("agnostic"); self._te = d[d.year >= C.TEST_START].reset_index(drop=True)
        return self._te

    def score_test_culture(self, order_proc_id, threshold=None):
        te = self._test_frame()
        d = te[te.order_proc_id_coded == int(order_proc_id)].reset_index(drop=True)
        if d.empty:
            raise KeyError(f"{order_proc_id} is not a 2022-24 test culture")
        truth = {str(a): ("Resistant" if r == 1 else "Susceptible/Intermediate") for a, r in zip(d.ab, d.R)}
        hw = d.iloc[0]
        setting = "ICU" if hw.hosp_ward_ICU == 1 else "ER" if hw.hosp_ward_ER == 1 else "Inpatient" if hw.ordering_mode == "Inpatient" else "Outpatient"
        out = self._result(d, [], setting, str(hw.culture_type), truth=truth, threshold=threshold)
        out.update(order_proc_id=int(order_proc_id), year=int(hw.year), age_band=str(hw.age), tested_antibiotics=len(d))
        return out

    def example_cases(self, n_each=2, seed=C.SEED):
        """Real test cultures that make good demo material: urine with prior resistance, urine with no history,
        blood culture, and one where the model missed resistance."""
        pred = pd.read_parquet(f"{C.PRED}/final_test.parquet")
        own = pd.read_parquet(f"{C.P}/own_history_long.parquet")
        x = pred.merge(own, on=["order_proc_id_coded", "ab"], how="left")
        g = x.groupby("order_proc_id_coded").agg(ct=("culture_type", "first"), n=("ab", "size"), anyR=("own_lastR_days", lambda s: s.notna().any()),
                                                 R=("R", "sum"))
        rng = np.random.default_rng(seed)
        pick = lambda q: [int(i) for i in rng.choice(q.index.values, size=min(n_each, len(q)), replace=False)]
        miss = x[(x.R == 1) & (x.p < 0.05) & (x.culture_type == "URINE")].order_proc_id_coded.unique()
        return {"urine_with_prior_resistance": pick(g[(g.ct == "URINE") & g.anyR & (g.n >= 12)]),
                "urine_no_history": pick(g[(g.ct == "URINE") & ~g.anyR & (g.n >= 12)]),
                "blood_culture": pick(g[(g.ct == "BLOOD") & (g.n >= 8)]),
                "missed_resistance_example": [int(i) for i in rng.choice(miss, size=min(n_each, len(miss)), replace=False)]}

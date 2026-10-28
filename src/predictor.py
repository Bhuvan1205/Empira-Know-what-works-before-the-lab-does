"""Frozen resistance predictor: loads the final ensemble, scores rows and explains them.

    from predictor import ResistancePredictor
    rp = ResistancePredictor()            # loads models/ (final_manifest.json)
    p = rp.predict(frame)                 # frame = common.build_frame(...) rows (one per culture x antibiotic)
    contrib = rp.explain(frame)           # per-feature contributions in log-odds (SHAP, TreeSHAP)

Ensemble = mean of the per-antibiotic and shared LightGBM probabilities, then per-antibiotic logistic
recalibration. Explanations average the two models' TreeSHAP log-odds values and scale them by the
calibration slope; this is an approximation of the ensemble (exact for each component model).
"""
import os, json, re
import numpy as np
import pandas as pd
import lightgbm as lgb
import common as C


def _logit(p):
    p = np.clip(p, 1e-6, 1 - 1e-6); return np.log(p / (1 - p))


class ResistancePredictor:
    def __init__(self, models_dir=None):
        md = models_dir or C.MODELS
        self.manifest = json.load(open(f"{md}/final_manifest.json"))
        self.cal = json.load(open(f"{md}/final_calibration.json"))
        self.antibiotics = self.manifest["antibiotics"]
        self.per_ab = {ab: lgb.Booster(model_file=f"{md}/per_ab_nolabs_all__{ab.replace('/', '_')}.txt") for ab in self.antibiotics}
        st = self.manifest["states"]["shared_t1"]
        self.shared = lgb.Booster(model_file=f"{md}/shared_t1.txt")
        self.shared_iter = int(st["best_iter"])
        self.shared_feats = self.shared.feature_name()
        self.per_ab_feats = {ab: b.feature_name() for ab, b in self.per_ab.items()}

    def prepare(self, d):
        """Make a frame from another site scoreable: add any missing model features as blank (NaN, which
        LightGBM treats as 'not recorded') and coerce categorical features to category dtype."""
        d = d.copy()
        need = set(self.shared_feats).union(*[set(v) for v in self.per_ab_feats.values()])
        missing = sorted(need - set(d.columns))
        for f in missing:
            d[f] = pd.Series(np.nan, index=d.index, dtype="float32")
        for c in ["ab_cat", "culture_type", "ordering_mode", "gender"]:
            if c in d and not isinstance(d[c].dtype, pd.CategoricalDtype):
                d[c] = d[c].astype("category")
        self.last_missing_features = missing
        return d

    def _components(self, d):
        d = self.prepare(d)
        p1 = np.full(len(d), np.nan); ab = d.ab.astype(str).values
        for a in np.unique(ab):
            m = ab == a
            p1[m] = self.per_ab[a].predict(d.loc[m, self.per_ab_feats[a]])
        p2 = self.shared.predict(d[self.shared_feats], num_iteration=self.shared_iter)
        return p1, p2

    def predict(self, d, return_raw=False):
        p1, p2 = self._components(d)
        raw = (p1 + p2) / 2
        ab = d.ab.astype(str)
        a = ab.map({k: v["a"] for k, v in self.cal.items()}).values
        b = ab.map({k: v["b"] for k, v in self.cal.items()}).values
        p = 1 / (1 + np.exp(-(a + b * _logit(raw))))
        return (p, raw) if return_raw else p

    def explain(self, d):
        """DataFrame of contributions (log-odds, calibrated scale) for the union of features, plus 'bias'."""
        d = self.prepare(d)
        feats = self.shared_feats
        out = np.zeros((len(d), len(feats) + 1))
        cs = self.shared.predict(d[feats], num_iteration=self.shared_iter, pred_contrib=True)
        out += cs / 2
        ab = d.ab.astype(str).values
        idx = {f: i for i, f in enumerate(feats)}
        for a in np.unique(ab):
            m = np.where(ab == a)[0]
            fa = self.per_ab_feats[a]
            ca = self.per_ab[a].predict(d.iloc[m][fa], pred_contrib=True)
            cols = [idx[f] for f in fa] + [len(feats)]
            out[np.ix_(m, cols)] += ca / 2
        slope = d.ab.astype(str).map({k: v["b"] for k, v in self.cal.items()}).values[:, None]
        return pd.DataFrame(out * slope, columns=feats + ["bias"], index=d.index)


FAMILY_RULES = [
    (r"^own_|^priorR_target", "Patient's prior resistance to THIS antibiotic"),
    (r"^priorR_", "Patient's prior resistance to other antibiotics"),
    (r"^priorOrg_", "Patient's prior organisms"),
    (r"^abx_", "Prior antibiotic exposure"),
    (r"^proc_", "Prior procedures / devices"),
    (r"^culture_type$|^ab_cat$", "Specimen type / antibiotic"),
    (r"^hosp_ward|^ordering_mode$|^nursing_home$", "Care setting"),
    (r"^age_ord$|^gender$", "Age / sex"),
    (r"^adi_", "Neighbourhood deprivation (ADI)"),
]


def family(f):
    for pat, name in FAMILY_RULES:
        if re.search(pat, f):
            return name
    return "Other"


def describe(f, v):
    """Plain-language description of a feature value (used in case explanations and the demo)."""
    if pd.isna(v):
        v_txt = "none recorded"
    elif isinstance(v, (float, np.floating)):
        v_txt = f"{v:.0f}"
    else:
        v_txt = str(v)
    m = re.match(r"^own_lastR_days$", f)
    if m: return f"Last resistant result to this antibiotic: {v_txt if pd.isna(v) else v_txt + ' days ago'}"
    if f == "own_lastTested_days": return f"Last tested for this antibiotic: {v_txt if pd.isna(v) else v_txt + ' days ago'}"
    if f == "own_nR": return f"Number of earlier resistant results to this antibiotic: {v_txt}"
    if f == "priorR_target_days": return f"Earlier resistance to this antibiotic (registry table): {v_txt if pd.isna(v) else v_txt + ' days ago'}"
    if f == "priorR_target_n": return f"Earlier resistant results (registry table): {v_txt}"
    for pre, txt in [("priorR_", "Earlier resistance to "), ("priorOrg_", "Earlier infection with "), ("abx_", "Earlier exposure to "),
                     ("proc_", "Earlier procedure: ")]:
        if f.startswith(pre) and f not in (pre + "n_events", pre + "n_types_90d"):
            name = f[len(pre):].replace("_", " ")
            return f"{txt}{name}: {v_txt if pd.isna(v) else v_txt + ' days ago'}"
    flags = {"hosp_ward_ICU": "ICU", "hosp_ward_ER": "Emergency department", "hosp_ward_IP": "Inpatient ward",
             "hosp_ward_OP": "Outpatient", "nursing_home": "Nursing-home contact"}
    if f in flags:
        return f"{flags[f]}: {'yes' if (not pd.isna(v) and float(v) == 1) else 'no'}"
    nice = {"culture_type": "Specimen", "ab_cat": "Antibiotic", "ordering_mode": "Ordered as", "nursing_home": "Nursing-home contact",
            "age_ord": "Age band (0 = 18-24 ... 8 = 90+)", "gender": "Sex code", "adi_score": "ADI percentile", "adi_state_rank": "ADI state decile",
            "hosp_ward_ICU": "ICU", "hosp_ward_ER": "Emergency dept", "hosp_ward_IP": "Inpatient ward", "hosp_ward_OP": "Outpatient",
            "priorR_n_events": "Earlier resistant results (all drugs)", "priorR_n_types_90d": "Drugs with resistance in last 90 days",
            "priorOrg_n_events": "Earlier positive cultures", "priorOrg_n_types_90d": "Organisms in last 90 days",
            "abx_n_events": "Earlier antibiotic courses", "abx_n_types_90d": "Antibiotic classes in last 90 days",
            "proc_n_events": "Earlier procedures", "proc_n_types_90d": "Procedure types in last 90 days"}
    return f"{nice.get(f, f)}: {v_txt}"

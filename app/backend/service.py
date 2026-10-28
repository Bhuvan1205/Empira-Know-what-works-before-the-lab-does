"""Glue between the API and the sealed model (src/demo_api.py, src/predictor.py). No model logic lives here."""
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(ROOT, "src"))
import common as C  # noqa: E402
from demo_api import AMRDemoAPI, URINE_POLICY  # noqa: E402

from . import wording as W  # noqa: E402

DISCLAIMER = ("Research prototype built on past data from one US hospital. It does not replace lab results "
              "or clinical judgement and must not be used to treat patients.")
MODES = {"balanced": 0.15, "stewardship": 0.20}
assert sorted(MODES.values()) == sorted(URINE_POLICY["thresholds"].values()), "thresholds must match the sealed policy"


class Service:
    def __init__(self):
        self.api = AMRDemoAPI()
        self.rp = self.api.rp
        self.manifest = json.load(open(os.path.join(C.MODELS, "final_manifest.json")))
        self._cases = None

    # ------------------------------------------------------------------ options
    def options(self):
        s = self.api.schema()
        hist_abs = [a for a in s["prior_resistance_antibiotics"] if a in W.DRUGS]
        return {
            "specimens": [{"value": k, "label": v} for k, v in W.SPECIMENS.items()],
            "settings": [{"value": k, "label": v} for k, v in W.SETTINGS.items()],
            "age_groups": [{"value": k, "label": v} for k, v in W.AGE_GROUPS.items()],
            "when": [{"value": k, "label": v[0]} for k, v in W.WHEN.items()],
            "antibiotics": sorted([{"value": a, "label": W.drug(a)} for a in hist_abs], key=lambda x: x["label"]),
            "germs": sorted([{"value": g, "label": W.GERMS.get(g, g)} for g in s["prior_organisms"]], key=lambda x: x["label"]),
            "antibiotic_families": sorted([{"value": f, "label": W.cap(W.FAMILIES.get(f, f))} for f in s["prior_antibiotic_classes"]],
                                          key=lambda x: x["label"]),
            "devices": [{"value": d, "label": W.DEVICES.get(d, d)} for d in s["procedures"]],
            "choice_modes": [{"value": "balanced", "label": "Fewer wrong first choices"},
                             {"value": "stewardship", "label": "Fewer broad-spectrum antibiotics"}],
        }

    # ------------------------------------------------------------------ scoring
    def _to_demo_patient(self, p):
        days = lambda w: W.WHEN[w][1]
        return {"culture_type": p.specimen, "setting": p.setting, "age_band": p.age_group, "sex_code": 0,
                "nursing_home": p.nursing_home,
                "prior_resistance": [{"antibiotic": r.antibiotic, "days_ago": days(r.when)} for r in p.past_resistance],
                "prior_organisms": [{"organism": g.germ, "days_ago": days(g.when)} for g in p.past_germs],
                "prior_antibiotics": [{"class": a.family, "days_ago": days(a.when)} for a in p.recent_antibiotics],
                "procedures": [{"procedure": d.device, "days_ago": days(d.when)} for d in p.devices]}

    def _results(self, d, specimen, setting, mode, truth=None):
        prob = self.rp.predict(d)
        contrib = self.rp.explain(d)
        feats = [c for c in contrib.columns if c != "bias"]
        out = []
        for i in range(len(d)):
            ab = str(d.ab.iloc[i]); row = d.iloc[i]
            ce = contrib.iloc[i][feats]
            ce = ce[ce.abs() >= 0.05].sort_values(key=np.abs, ascending=False)
            reasons, seen = [], set()
            for f, v in ce.items():
                txt = W.reason(f, row[f] if f in d.columns else np.nan, ab, row)
                if txt and txt not in seen:
                    seen.add(txt)
                    reasons.append({"text": txt, "direction": "raises" if v > 0 else "lowers", "strength": round(float(abs(v)), 3)})
                if len(reasons) == 3:
                    break
            p = float(prob[i]); key, label = W.verdict(p)
            freq = self.api.test_freq.get((specimen, ab), 0.0)
            res = {"antibiotic": ab, "name": W.drug(ab), "chance_resistant": round(p, 4), "chance_text": W.chance_text(p),
                   "verdict": key, "verdict_label": label, "commonly_tested": bool(freq >= 0.05), "reasons": reasons}
            if truth is not None:
                res["lab_result"] = "Resistant" if truth[ab] == 1 else "Worked"
            out.append(res)
        out.sort(key=lambda r: (not r["commonly_tested"], r["chance_resistant"]))
        rec = self._recommend(prob, d, specimen, setting, mode, truth)
        return out, rec

    def _recommend(self, prob, d, specimen, setting, mode, truth):
        if specimen != "URINE":
            return {"available": False, "summary": "A single suggested first choice is only available for urine samples, "
                    "where it was tested against what doctors actually prescribed. The list below shows each antibiotic's chance of not working."}
        r = self.api.recommend_urine(prob, d, setting, MODES[mode])
        risk = dict(zip(d.ab.astype(str), prob))
        options = [{"antibiotic": o["antibiotic"], "name": W.drug(o["antibiotic"]), "chance_resistant": o["risk"],
                    "chance_text": W.chance_text(o["risk"]), "spectrum": W.TIERS[o["tier"]]} for o in r["considered"]]
        ab = r["choice"]; p = float(risk[ab])
        within = p <= r["threshold"]
        summary = (f"The narrowest antibiotic with a low chance of resistance: about {W.chance_text(p)} "
                   "similar patients had a germ resistant to it." if within else
                   f"Every usual option has a high chance of resistance, so this is the one with the lowest chance ({W.chance_text(p)}). "
                   "Consider waiting for lab results or seeking specialist advice.")
        if setting != "Outpatient":
            summary += " Nitrofurantoin is not offered because it does not treat kidney or blood infections."
        out = {"available": True, "antibiotic": ab, "name": W.drug(ab), "chance_resistant": round(p, 4),
               "chance_text": W.chance_text(p), "spectrum": W.TIERS[r["tier"]], "summary": summary, "options": options}
        if truth is not None and ab in truth:
            out["lab_result"] = "Resistant" if truth[ab] == 1 else "Worked"
        return out

    def predict(self, patient):
        d, warn, setting = self.api.build_rows(self._to_demo_patient(patient))
        results, rec = self._results(d, patient.specimen, setting, patient.choice_mode)
        notes = [w.replace("(model uses >= 3 days)", "").strip() for w in warn if not w.startswith("Rarely tested")]
        rare = [r["name"] for r in results if not r["commonly_tested"]]
        if rare:
            notes.append(f"{len(rare)} antibiotics are rarely tested on {W.SPECIMENS[patient.specimen].lower()} samples, "
                         "so their estimates are less reliable. They are listed separately.")
        return {"specimen": patient.specimen, "setting": setting, "recommendation": rec, "antibiotics": results,
                "notes": notes, "disclaimer": DISCLAIMER}

    # ------------------------------------------------------------------ real past cases
    def _case_catalogue(self):
        if self._cases is not None:
            return self._cases
        ex = self.api.example_cases(n_each=2)
        te = self.api._test_frame()
        meta = te.drop_duplicates("order_proc_id_coded").set_index("order_proc_id_coded")
        picks = [
            (ex["urine_with_prior_resistance"][0], "Urine infection, resistant germs before",
             "A clinic patient whose earlier urine germs were resistant to some antibiotics."),
            (ex["urine_with_prior_resistance"][1], "Urine infection, repeat visits",
             "Another patient with a history of resistant urine infections."),
            (ex["urine_no_history"][0], "Urine infection, first visit",
             "No earlier cultures on record: the model falls back on what is typical for urine samples."),
            (ex["blood_culture"][0], "Blood infection",
             "A blood sample. Shows each antibiotic's chance of not working (no single suggestion for blood)."),
            (ex["missed_resistance_example"][0], "A case the model got wrong",
             "The model rated an antibiotic low-risk, but the lab found resistance. No model is right every time."),
        ]
        cats = []
        for cid, title, desc in picks:
            m = meta.loc[cid]
            setting = "ICU" if m.hosp_ward_ICU == 1 else "ER" if m.hosp_ward_ER == 1 else "Inpatient" if m.ordering_mode == "Inpatient" else "Outpatient"
            desc = f"{desc} {W.SPECIMENS[str(m.culture_type)]} sample, {W.SETTINGS[setting].lower()}, age {W.AGE_GROUPS.get(str(m.age), '?')}."
            cats.append({"case_id": int(cid), "title": title, "description": desc})
        self._cases = cats
        return cats

    def cases(self):
        return self._case_catalogue()

    def _patient_summary(self, row, setting):
        out = [f"{W.SPECIMENS[str(row.culture_type)]} sample", W.SETTINGS[setting], f"Age {W.AGE_GROUPS.get(str(row.age), 'unknown')}"]
        res = sorted([(W.drug(c[len('priorR_'):]), row[c]) for c in self.api.priorR_cols if not pd.isna(row[c])], key=lambda x: x[1])
        if res:
            out.append("Earlier resistance: " + ", ".join(f"{n.split(' (')[0]} ({W.ago(v)})" for n, v in res[:4]) + (" and more" if len(res) > 4 else ""))
        else:
            out.append("No earlier resistant germs on record")
        germs = sorted([(W.GERMS.get(c[len('priorOrg_'):], c), row[c]) for c in self.api.org_cols if not pd.isna(row[c])], key=lambda x: x[1])
        if germs:
            out.append("Earlier germs: " + ", ".join(f"{g} ({W.ago(v)})" for g, v in germs[:3]))
        abx = sorted([(W.FAMILIES.get(c[len('abx_'):], c).split(' (')[0], row[c]) for c in self.api.abx_cols
                      if not pd.isna(row[c]) and row[c] <= 365], key=lambda x: x[1])
        if abx:
            out.append("Antibiotics in the past year: " + ", ".join(f"{a} ({W.ago(v)})" for a, v in abx[:3]))
        dev = [W.DEVICES.get(c[len('proc_'):], c) for c in self.api.proc_cols if not pd.isna(row[c]) and row[c] <= 90]
        if dev:
            out.append("In the last 3 months: " + ", ".join(dev).lower())
        return out

    def case(self, case_id, mode="balanced"):
        cat = {c["case_id"]: c for c in self._case_catalogue()}
        te = self.api._test_frame()
        d = te[te.order_proc_id_coded == int(case_id)].reset_index(drop=True)
        if d.empty:
            raise KeyError(case_id)
        row = d.iloc[0]
        setting = "ICU" if row.hosp_ward_ICU == 1 else "ER" if row.hosp_ward_ER == 1 else "Inpatient" if row.ordering_mode == "Inpatient" else "Outpatient"
        truth = {str(a): int(r) for a, r in zip(d.ab, d.R)}
        results, rec = self._results(d, str(row.culture_type), setting, mode, truth)
        good = [r for r in results if r["verdict"] == "likely_works"]; bad = [r for r in results if r["verdict"] == "likely_resistant"]
        gw, br = sum(r['lab_result'] == 'Worked' for r in good), sum(r['lab_result'] == 'Resistant' for r in bad)
        agree = f"Of {W.plural(len(good), 'antibiotic', 'antibiotics')} rated likely to work, {gw} worked in the lab."
        if bad:
            agree += f" Of {len(bad)} rated likely resistant, {br} {'was' if br == 1 else 'were'} resistant."
        c = cat.get(int(case_id), {"title": f"Case {case_id}", "description": ""})
        return {"case_id": int(case_id), "title": c["title"], "year": int(row.year), "patient": self._patient_summary(row, setting),
                "specimen": str(row.culture_type), "setting": setting, "recommendation": rec, "antibiotics": results,
                "notes": ["Only antibiotics the lab actually tested are shown."], "agreement": agree, "disclaimer": DISCLAIMER}

    # ------------------------------------------------------------------ about
    def model_info(self):
        dec = json.load(open(os.path.join(ROOT, "reports", "phaseC", "decision_summary.json")))
        boot = json.load(open(os.path.join(ROOT, "reports", "phaseB", "bootstrap_summary.json")))
        cl, bal, stw = dec["clinician_test"], dec["policy_test_at_match_second_line"], dec["policy_test_at_match_inappropriate"]
        pct = lambda x: f"{x * 100:.1f}%"
        return {
            "what_it_does": "Estimates, for 28 antibiotics, the chance that the germ in a new urine, blood or airway sample will be resistant, "
                            "before lab results are back (usually 2-3 days).",
            "trained_on": "About 88,000 positive cultures from adults at Stanford Health Care, 2008-2020. Tested on 2022-2024 cultures it had never seen.",
            "accuracy": f"When comparing a resistant and a non-resistant case, it ranks the resistant one higher about "
                        f"{round(boot['mean_auroc_all'] * 100)}% of the time (AUROC {boot['mean_auroc_all']:.2f}; 95% CI "
                        f"{boot['mean_auroc_all_ci'][0]:.2f}-{boot['mean_auroc_all_ci'][1]:.2f}). The usual hospital antibiogram scores about 55%.",
            "impact": [
                {"label": "Doctors' actual first choice", "wrong_choice": pct(cl["inappropriate_R"]), "broad_use": pct(cl["second_line_or_broad"])},
                {"label": "Tool: fewer wrong first choices", "wrong_choice": pct(bal["inappropriate_R"]), "broad_use": pct(bal["second_line_or_broad"])},
                {"label": "Tool: fewer broad-spectrum drugs", "wrong_choice": pct(stw["inappropriate_R"]), "broad_use": pct(stw["second_line_or_broad"])},
            ],
            "impact_note": f"Urine cultures from 2022-2024 (n = {dec['cohort_test']['with_one_clinician_candidate']:,}) where we know what doctors gave. "
                           "\"Wrong first choice\" means the germ turned out to be resistant to the drug given.",
            "uses": ["Earlier resistant results and how long ago", "Germs found before", "Recent antibiotic courses",
                     "Catheters, lines and other devices", "Type of sample, where the patient is seen, and age"],
            "does_not_use": ["Today's lab results", "The germ in this sample (not known yet)", "Names or identifiers"],
            "limits": ["Built from one US hospital; needs checking elsewhere", "Weaker for blood samples, emergency patients and people over 85",
                       "Cannot foresee a first-ever resistant infection", "Does not know about allergies, kidney function or pregnancy"],
            "version": "v1.0 (sealed 14 Oct 2026)",
            "test_mean_auroc": self.manifest["test_mean_auroc"],
        }

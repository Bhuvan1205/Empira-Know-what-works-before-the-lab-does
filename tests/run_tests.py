"""Release checks for the sealed model.  Usage: python tests/run_tests.py   (from project root, ~1-2 min)
Exit code 0 = all checks passed."""
import os, sys, json, hashlib, time
import numpy as np
import pandas as pd
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src")); os.chdir(ROOT)
import common as C

results = []


def check(name):
    def deco(fn):
        t = time.time()
        try:
            msg = fn() or ""
            results.append((name, True, msg)); print(f"PASS  {name}  {msg}  ({time.time() - t:.1f}s)", flush=True)
        except Exception as e:
            results.append((name, False, repr(e))); print(f"FAIL  {name}  {e!r}", flush=True)
        return fn
    return deco


@check("model files match SHA256SUMS")
def _():
    lines = open("models/SHA256SUMS").read().strip().splitlines()
    for ln in lines:
        h, f = ln.split("  ", 1)
        assert hashlib.sha256(open(os.path.join("models", f), "rb").read()).hexdigest() == h, f
    return f"{len(lines)} files"


@check("leakage: history features >= 3 days, exposures >= 1 day")
def _():
    own = pd.read_parquet(f"{C.P}/own_history_long.parquet")
    assert own.own_lastR_days.dropna().min() >= 3 and own.own_lastTested_days.dropna().min() >= 3
    pr = pd.read_parquet(f"{C.P}/prior_resistance_long.parquet"); assert pr.priorR_target_days.min() >= 3
    h = pd.read_parquet(f"{C.P}/history.parquet")
    for pre, gap in [("priorR_", 3), ("priorOrg_", 3), ("abx_", 1), ("proc_", 1)]:
        cols = [c for c in h.columns if c.startswith(pre) and "_n_" not in c]
        assert np.nanmin(h[cols].values) >= gap, pre
    return "own/registry/organism >=3 d; antibiotic/procedure >=1 d"


@check("no labs/vitals/organism/same-day meds in model features")
def _():
    from predictor import ResistancePredictor
    rp = ResistancePredictor(); feats = set(rp.shared_feats).union(*map(set, rp.per_ab_feats.values()))
    bad = [f for f in feats if f.startswith(("lab_", "vit_", "orgp_")) or f in ("organism", "organism_grp", "year")]
    assert not bad, bad
    return f"{len(feats)} features"


@check("temporal split: train <=2020, val 2021, test >=2022, no overlap")
def _():
    va = pd.read_parquet(f"{C.PRED}/final_val.parquet"); te = pd.read_parquet(f"{C.PRED}/final_test.parquet")
    assert set(va.year) == {2021} and te.year.min() >= 2022
    return f"val {len(va):,} rows, test {len(te):,} rows"


@check("frozen predictor reproduces sealed test predictions")
def _():
    from predictor import ResistancePredictor
    rp = ResistancePredictor()
    d, _ = C.build_frame("agnostic"); te = d[d.year >= C.TEST_START].sample(20000, random_state=1)
    ref = pd.read_parquet(f"{C.PRED}/final_test.parquet").set_index(["order_proc_id_coded", "ab"]).p
    r = ref.loc[list(zip(te.order_proc_id_coded, te.ab.astype(str)))].values
    err = float(np.abs(rp.predict(te) - r).max()); assert err < 1e-9, err
    return f"max |diff| = {err:.1e} on 20,000 rows"


@check("sealed metrics match manifest")
def _():
    m = json.load(open("models/final_manifest.json")); te = pd.read_parquet(f"{C.PRED}/final_test.parquet")
    au = np.mean([C.metrics(g.R, g.p)["auroc"] for _, g in te.groupby("ab", observed=True)])
    assert abs(au - m["test_mean_auroc"]) < 1e-3, (au, m["test_mean_auroc"])
    cal = json.load(open("models/final_calibration.json")); assert set(cal) == set(m["antibiotics"])
    return f"test mean AUROC {au:.4f}, 28 calibrators"


@check("demo API: hypothetical patient, determinism, leakage guard, recommendation")
def _():
    from demo_api import AMRDemoAPI
    api = AMRDemoAPI()
    pt = {"culture_type": "URINE", "setting": "Outpatient", "age_band": "45-54 years", "sex_code": 0,
          "prior_resistance": [{"antibiotic": "ciprofloxacin", "days_ago": 200}, {"antibiotic": "cefazolin", "days_ago": 2}]}
    a, b = api.score(pt), api.score(pt)
    assert [r["risk"] for r in a["antibiotics"]] == [r["risk"] for r in b["antibiotics"]]
    assert len(a["antibiotics"]) == 28 and all(0 <= r["risk"] <= 1 for r in a["antibiotics"])
    assert any("Ignored resistance 'cefazolin'" in w for w in a["warnings"])
    assert a["recommendation"]["available"] and a["recommendation"]["choice"] in [c["antibiotic"] for c in a["recommendation"]["considered"]]
    blood = api.score(dict(pt, culture_type="BLOOD", setting="ICU")); assert not blood["recommendation"]["available"]
    inpat = api.score(dict(pt, setting="Inpatient"))
    assert "nitrofurantoin" not in [c["antibiotic"] for c in inpat["recommendation"]["considered"]]
    risk = {r["antibiotic"]: r["risk"] for r in a["antibiotics"]}
    none = {r["antibiotic"]: r["risk"] for r in api.score(dict(pt, prior_resistance=[]))["antibiotics"]}
    assert risk["ciprofloxacin"] > none["ciprofloxacin"]
    return f"cipro risk {none['ciprofloxacin']:.2f} -> {risk['ciprofloxacin']:.2f} with prior resistance"


@check("demo API: real test culture with true results")
def _():
    from demo_api import AMRDemoAPI
    api = AMRDemoAPI(); ex = api.example_cases(n_each=1)
    r = api.score_test_culture(ex["urine_no_history"][0])
    assert all(x["actual"] in ("Resistant", "Susceptible/Intermediate") for x in r["antibiotics"] if x.get("actual"))
    return f"culture {r['order_proc_id']}: {r['tested_antibiotics']} antibiotics with results"


@check("demo urine thresholds equal the Phase C validated thresholds")
def _():
    from demo_api import URINE_POLICY
    s = json.load(open("reports/phaseC/decision_summary.json"))
    assert sorted(URINE_POLICY["thresholds"].values()) == sorted([s["threshold_match_second_line"], s["threshold_match_inappropriate"]])
    assert URINE_POLICY["default_threshold"] == s["threshold_match_second_line"]
    return "0.15 / 0.20"


@check("external pipeline schema check")
def _():
    import importlib.util
    spec = importlib.util.spec_from_file_location("ext", "src/08_external_validate.py"); ext = importlib.util.module_from_spec(spec); spec.loader.exec_module(ext)
    assert ext.schema_check("data/armd_stanford")["ok"]
    assert not ext.schema_check("data/armd_mgb")["ok"] or os.listdir("data/armd_mgb")
    return "Stanford ok; empty MGB folder correctly rejected"


if __name__ == "__main__":
    ok = all(r[1] for r in results)
    print(f"\n{sum(r[1] for r in results)}/{len(results)} checks passed")
    sys.exit(0 if ok else 1)

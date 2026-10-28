"""API tests. Run from the project root:  python -m pytest app/backend/tests -q"""
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.backend.main import app

URINE = {"specimen": "URINE", "setting": "Outpatient", "age_group": "65-74 years",
         "past_resistance": [{"antibiotic": "ciprofloxacin", "when": "3_12_months"}]}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/api/health"); assert r.status_code == 200 and r.json()["antibiotics"] == 28


def test_options_complete(client):
    o = client.get("/api/options").json()
    assert {x["value"] for x in o["specimens"]} == {"URINE", "BLOOD", "RESPIRATORY"}
    assert len(o["age_groups"]) == 9 and len(o["when"]) == 5 and len(o["devices"]) == 6


def test_predict_shape_and_ranges(client):
    j = client.post("/api/predict", json=URINE).json()
    assert len(j["antibiotics"]) == 28
    assert all(0 <= a["chance_resistant"] <= 1 for a in j["antibiotics"])
    assert j["recommendation"]["available"] and j["recommendation"]["antibiotic"] in {o["antibiotic"] for o in j["recommendation"]["options"]}
    assert j["disclaimer"]


def test_history_raises_risk(client):
    base = client.post("/api/predict", json=dict(URINE, past_resistance=[])).json()
    hist = client.post("/api/predict", json=URINE).json()
    get = lambda j: {a["antibiotic"]: a["chance_resistant"] for a in j["antibiotics"]}["ciprofloxacin"]
    assert get(hist) > get(base) * 2


def test_matches_sealed_predictor(client):
    """API probabilities must equal the sealed model's for the same inputs."""
    from app.backend.main import svc
    s = svc()
    d, _, _ = s.api.build_rows({"culture_type": "URINE", "setting": "Outpatient", "age_band": "65-74 years", "sex_code": 0,
                                "prior_resistance": [{"antibiotic": "ciprofloxacin", "days_ago": 180}]})
    ref = dict(zip(d.ab.astype(str), s.rp.predict(d)))
    j = client.post("/api/predict", json=URINE).json()
    assert max(abs(a["chance_resistant"] - ref[a["antibiotic"]]) for a in j["antibiotics"]) < 1e-4


def test_no_nitrofurantoin_for_inpatients(client):
    j = client.post("/api/predict", json=dict(URINE, setting="Inpatient")).json()
    assert "nitrofurantoin" not in {o["antibiotic"] for o in j["recommendation"]["options"]}


def test_blood_has_no_single_suggestion(client):
    j = client.post("/api/predict", json=dict(URINE, specimen="BLOOD")).json()
    assert not j["recommendation"]["available"]


def test_validation_errors(client):
    assert client.post("/api/predict", json=dict(URINE, age_group="12")).status_code == 422
    assert client.post("/api/predict", json=dict(URINE, specimen="CSF")).status_code == 422
    assert client.post("/api/predict", json=dict(URINE, past_resistance=[{"antibiotic": "xyz"}])).status_code == 422


def test_cases_have_lab_results(client):
    cs = client.get("/api/cases").json(); assert len(cs) >= 4
    k = client.get(f"/api/cases/{cs[0]['case_id']}").json()
    assert all(a["lab_result"] in ("Resistant", "Worked") for a in k["antibiotics"]) and k["patient"]
    assert client.get("/api/cases/1").status_code == 404


def test_case_probabilities_match_sealed_test_predictions(client):
    import os
    from app.backend.service import ROOT
    ref = pd.read_parquet(os.path.join(ROOT, "data", "predictions", "final_test.parquet"))
    cid = client.get("/api/cases").json()[0]["case_id"]
    k = client.get(f"/api/cases/{cid}").json()
    r = ref[ref.order_proc_id_coded == cid].set_index("ab").p
    assert max(abs(a["chance_resistant"] - r[a["antibiotic"]]) for a in k["antibiotics"]) < 1e-4


def test_model_info(client):
    m = client.get("/api/model").json(); assert len(m["impact"]) == 3 and abs(m["test_mean_auroc"] - 0.7795) < 1e-3

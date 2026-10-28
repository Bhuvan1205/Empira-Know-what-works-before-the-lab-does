"""Empira API (FastAPI): antibiotic guidance before the lab is back.

Run from the project root:
    uvicorn app.backend.main:app --port 8000
Interactive docs: http://localhost:8000/docs
"""
import logging
import time
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware

from . import wording as W
from .schemas import CaseOut, CaseSummary, PatientIn, PredictionOut
from .service import Service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("empira")

@asynccontextmanager
async def lifespan(_app):
    svc()          # load the model once at startup
    yield


app = FastAPI(
    lifespan=lifespan,
    title="Empira API",
    version="1.0.0",
    description="Empira estimates, before lab results are back, the chance that the germ in a urine, blood or airway sample "
                "is resistant to each of 28 antibiotics, and suggests a narrow first choice for urine samples. "
                "Research prototype built on ARMD-Stanford; not for clinical use.",
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])
_service = None


def svc() -> Service:
    global _service
    if _service is None:
        t = time.time(); _service = Service(); log.info("model loaded in %.1fs", time.time() - t)
    return _service


@app.middleware("http")
async def _timing(request: Request, call_next):
    t = time.time(); resp = await call_next(request)
    log.info("%s %s -> %s in %.0f ms", request.method, request.url.path, resp.status_code, (time.time() - t) * 1000)
    return resp


@app.get("/api/health", tags=["service"])
def health():
    """Liveness check: is the model loaded?"""
    s = svc()
    return {"status": "ok", "model_version": "1.0", "antibiotics": len(s.rp.antibiotics)}


@app.get("/api/options", tags=["form"])
def options():
    """Everything a form needs: sample types, settings, age groups, antibiotics, germs, antibiotic families, devices."""
    return svc().options()


@app.post("/api/predict", response_model=PredictionOut, tags=["predict"])
def predict(patient: PatientIn):
    """Score a patient described with simple inputs. Returns each antibiotic's chance of resistance with reasons,
    and, for urine samples, a suggested first choice."""
    s = svc()
    if patient.age_group not in W.AGE_GROUPS:
        raise HTTPException(422, f"age_group must be one of {list(W.AGE_GROUPS)}")
    opts = s.options()
    for field, items, key, valid in [("past_resistance", patient.past_resistance, "antibiotic", {o["value"] for o in opts["antibiotics"]}),
                                     ("past_germs", patient.past_germs, "germ", {o["value"] for o in opts["germs"]}),
                                     ("recent_antibiotics", patient.recent_antibiotics, "family", {o["value"] for o in opts["antibiotic_families"]}),
                                     ("devices", patient.devices, "device", {o["value"] for o in opts["devices"]})]:
        bad = [getattr(i, key) for i in items if getattr(i, key) not in valid]
        if bad:
            raise HTTPException(422, f"Unknown {key} in {field}: {bad}. See /api/options.")
    return s.predict(patient)


@app.get("/api/cases", response_model=List[CaseSummary], tags=["real cases"])
def cases():
    """Real cultures from 2022-2024 (never used in training) that are useful to explore."""
    return svc().cases()


@app.get("/api/cases/{case_id}", response_model=CaseOut, tags=["real cases"])
def case(case_id: int, choice_mode: str = Query("balanced", pattern="^(balanced|stewardship)$")):
    """Score a real past culture and show the lab's actual results next to the model's estimates."""
    try:
        return svc().case(case_id, choice_mode)
    except KeyError:
        raise HTTPException(404, f"Case {case_id} is not one of the 2022-2024 test cultures")


@app.get("/api/model", tags=["service"])
def model_info():
    """Plain-language summary of what the model does, how well it works, and its limits."""
    return svc().model_info()

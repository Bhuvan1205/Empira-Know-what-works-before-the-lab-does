"""Request / response models for the Empira API."""
from typing import List, Literal, Optional
from pydantic import BaseModel, Field

When = Literal["last_month", "1_3_months", "3_12_months", "1_2_years", "over_2_years"]


class PastResistance(BaseModel):
    antibiotic: str = Field(..., examples=["ciprofloxacin"], description="Antibiotic a germ from this patient was resistant to")
    when: When = Field("3_12_months", description="How long before this sample")


class PastGerm(BaseModel):
    germ: str = Field(..., examples=["escherichia"])
    when: When = "3_12_months"


class RecentAntibiotic(BaseModel):
    family: str = Field(..., examples=["fluoroquinolone"])
    when: When = "1_3_months"


class Device(BaseModel):
    device: str = Field(..., examples=["urethral_catheter"])
    when: When = "last_month"


class PatientIn(BaseModel):
    specimen: Literal["URINE", "BLOOD", "RESPIRATORY"] = "URINE"
    setting: Literal["Outpatient", "ER", "Inpatient", "ICU"] = "Outpatient"
    age_group: str = Field("55-64 years", examples=["65-74 years"])
    past_resistance: List[PastResistance] = []
    past_germs: List[PastGerm] = []
    recent_antibiotics: List[RecentAntibiotic] = []
    devices: List[Device] = []
    nursing_home: bool = False
    choice_mode: Literal["balanced", "stewardship"] = Field(
        "balanced", description="balanced = fewer wrong first choices; stewardship = fewer broad-spectrum drugs")

    model_config = {"json_schema_extra": {"examples": [{
        "specimen": "URINE", "setting": "Outpatient", "age_group": "65-74 years",
        "past_resistance": [{"antibiotic": "ciprofloxacin", "when": "3_12_months"}],
        "recent_antibiotics": [{"family": "fluoroquinolone", "when": "1_3_months"}]}]}}


class Reason(BaseModel):
    text: str
    direction: Literal["raises", "lowers"]
    strength: float


class AntibioticResult(BaseModel):
    antibiotic: str
    name: str
    chance_resistant: float
    chance_text: str
    verdict: Literal["likely_works", "uncertain", "likely_resistant"]
    verdict_label: str
    commonly_tested: bool
    reasons: List[Reason]
    lab_result: Optional[Literal["Resistant", "Worked"]] = None


class Option(BaseModel):
    antibiotic: str
    name: str
    chance_resistant: float
    chance_text: str
    spectrum: str


class Recommendation(BaseModel):
    available: bool
    antibiotic: Optional[str] = None
    name: Optional[str] = None
    chance_resistant: Optional[float] = None
    chance_text: Optional[str] = None
    spectrum: Optional[str] = None
    summary: str
    options: List[Option] = []
    lab_result: Optional[Literal["Resistant", "Worked"]] = None


class PredictionOut(BaseModel):
    specimen: str
    setting: str
    recommendation: Recommendation
    antibiotics: List[AntibioticResult]
    notes: List[str]
    disclaimer: str


class CaseSummary(BaseModel):
    case_id: int
    title: str
    description: str


class CaseOut(PredictionOut):
    case_id: int
    title: str
    patient: List[str]
    year: int
    agreement: str

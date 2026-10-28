"""Plain-language wording for the demo: drug and germ names people recognise, time phrases,
verdicts, and one-sentence reasons built from the model's SHAP contributions."""
import math

DRUGS = {
    "amikacin": "Amikacin",
    "amoxicillin/clavulanic acid": "Amoxicillin-clavulanate (Augmentin)",
    "ampicillin": "Ampicillin",
    "ampicillin/sulbactam": "Ampicillin-sulbactam (Unasyn)",
    "aztreonam": "Aztreonam",
    "cefazolin": "Cefazolin / cephalexin (Keflex)",
    "cefepime": "Cefepime",
    "cefoxitin": "Cefoxitin",
    "ceftazidime": "Ceftazidime",
    "ceftriaxone": "Ceftriaxone",
    "ciprofloxacin": "Ciprofloxacin (Cipro)",
    "clindamycin": "Clindamycin",
    "ertapenem": "Ertapenem",
    "erythromycin": "Erythromycin",
    "gentamicin": "Gentamicin",
    "imipenem": "Imipenem",
    "levofloxacin": "Levofloxacin",
    "linezolid": "Linezolid",
    "meropenem": "Meropenem",
    "moxifloxacin": "Moxifloxacin",
    "nitrofurantoin": "Nitrofurantoin (Macrobid)",
    "oxacillin": "Oxacillin (tests for MRSA)",
    "penicillin": "Penicillin",
    "piperacillin/tazobactam": "Piperacillin-tazobactam (Zosyn)",
    "tetracycline": "Tetracycline / doxycycline",
    "tobramycin": "Tobramycin",
    "trimethoprim/sulfamethoxazole": "Trimethoprim-sulfamethoxazole (Bactrim)",
    "vancomycin": "Vancomycin",
    # only seen in history inputs
    "cefpodoxime": "Cefpodoxime", "clarithromycin": "Clarithromycin", "colistin": "Colistin",
    "metronidazole": "Metronidazole", "minocycline": "Minocycline", "rifampin": "Rifampin",
}

GERMS = {
    "escherichia": "E. coli", "klebsiella": "Klebsiella", "proteus": "Proteus", "enterococcus": "Enterococcus",
    "pseudomonas": "Pseudomonas", "staphylococcus": "Staph aureus", "cons": "Coagulase-negative staph",
    "streptococcus": "Streptococcus", "enterobacter": "Enterobacter", "citrobacter": "Citrobacter",
    "serratia": "Serratia", "morganella": "Morganella", "providencia": "Providencia",
    "acinetobacter": "Acinetobacter", "stenotrophomonas": "Stenotrophomonas", "candida": "Candida (yeast)",
}

FAMILIES = {  # written to sit mid-sentence; the UI capitalises the first letter for labels
    "beta_lactam": "penicillins or cephalosporins", "fluoroquinolone": "fluoroquinolones (e.g. Cipro, levofloxacin)",
    "folate_synthesis_inhibitor": "trimethoprim", "sulfonamide": "sulfa drugs (e.g. Bactrim)",
    "combination_antibiotic": "combination antibiotics (e.g. Augmentin, Zosyn)",
    "nitrofuran": "nitrofurantoin", "aminoglycoside": "aminoglycosides (e.g. gentamicin)",
    "glycopeptide": "vancomycin", "macrolide_lincosamide": "macrolides or clindamycin",
    "tetracycline": "tetracyclines (e.g. doxycycline)", "nitroimidazole": "metronidazole",
    "oxazolidinone": "linezolid", "monobactam": "aztreonam", "polymyxin__lipopeptide": "colistin or daptomycin",
    "fosfomycin": "fosfomycin", "urinary_antiseptic": "urinary antiseptics (e.g. methenamine)",
    "ansamycin": "rifamycins", "antitubercular": "TB drugs",
}


def cap(t):
    return t[:1].upper() + t[1:]


def plural(n, one, many):
    n = int(n)
    return f"{n} {one if n == 1 else many}"


DEVICES = {
    "urethral_catheter": "Urinary catheter", "cvc": "Central line", "mechvent": "Breathing machine (ventilator)",
    "dialysis": "Dialysis", "surgical_procedure": "Surgery", "parenteral_nutrition": "IV nutrition",
}

SPECIMENS = {"URINE": "Urine", "BLOOD": "Blood", "RESPIRATORY": "Sputum / airway"}
SETTINGS = {"Outpatient": "Clinic (outpatient)", "ER": "Emergency department", "Inpatient": "Hospital ward", "ICU": "Intensive care (ICU)"}
AGE_GROUPS = {"18-24 years": "18-24", "25-34 years": "25-34", "35-44 years": "35-44", "45-54 years": "45-54",
              "55-64 years": "55-64", "65-74 years": "65-74", "75-84 years": "75-84", "85-89 years": "85-89", "above 90": "90 or older"}
AGE_LIST = list(AGE_GROUPS)

# "when" choices offered in the UI -> representative days before the culture
WHEN = {"last_month": ("In the last month", 14), "1_3_months": ("1-3 months ago", 60), "3_12_months": ("3-12 months ago", 180),
        "1_2_years": ("1-2 years ago", 540), "over_2_years": ("More than 2 years ago", 1100)}

TIERS = {"first-line": "Narrow-spectrum, a usual first choice", "second-line": "Broader-spectrum",
         "broad": "Very broad, usually kept in reserve"}

LIKELY_WORKS, LIKELY_FAILS = 0.10, 0.30


def drug(ab):
    return DRUGS.get(ab, ab.capitalize())


def verdict(p):
    if p < LIKELY_WORKS:
        return "likely_works", "Likely to work"
    if p < LIKELY_FAILS:
        return "uncertain", "Uncertain"
    return "likely_resistant", "Likely resistant"


def chance_text(p):
    n = max(1, round(p * 100)) if p >= 0.005 else 0
    return "under 1 in 100" if n == 0 else f"{n} in 100"


def ago(days):
    d = float(days)
    if d < 45:
        return f"{int(round(d))} days ago"
    if d < 365:
        return f"about {int(round(d / 30))} months ago"
    y = d / 365
    return "about a year ago" if y < 1.5 else f"about {int(round(y))} years ago"


def _missing(v):
    if v is None:
        return True
    try:
        return math.isnan(float(v))
    except (TypeError, ValueError):
        return False


def reason(feature, value, ab, row):
    """One plain sentence for a feature's contribution, or None to hide it (anonymised or uninformative)."""
    f, v, name = feature, value, drug(ab)
    if f in ("gender", "ab_cat", "adi_state_rank"):
        return None
    if f in ("own_lastR_days", "priorR_target_days") or f == f"priorR_{ab}":
        return f"A germ from this patient was resistant to {name} {ago(v)}" if not _missing(v) else f"No earlier resistance to {name} on record"
    if f == "own_lastTested_days":
        if _missing(v):
            return f"No earlier lab result for {name}"
        if _missing(row.get("own_lastR_days")):
            return f"Tested against {name} {ago(v)} and it worked"
        return f"Last tested against {name} {ago(v)}"
    if f == "own_nR":
        if _missing(v) or v <= 0:
            return None
        return f"Resistant to {name} once before" if int(v) == 1 else f"Resistant to {name} {int(v)} times before"
    if f == "priorR_target_n":
        return None
    if f.startswith("priorR_n_"):
        if f == "priorR_n_events":
            return "No earlier resistant germs on record" if _missing(v) else plural(v, "earlier resistant lab result", "earlier resistant lab results")
        return None if _missing(v) else f"Resistance to {plural(v, 'antibiotic', 'different antibiotics')} in the last 3 months"
    if f.startswith("priorR_"):
        other = drug(f[len("priorR_"):])
        return f"Earlier resistance to {other} ({ago(v)})" if not _missing(v) else f"No earlier resistance to {other}"
    if f == "priorOrg_n_events":
        return "No earlier positive cultures" if _missing(v) else plural(v, "earlier positive culture", "earlier positive cultures")
    if f == "priorOrg_n_types_90d":
        return None if _missing(v) else f"{plural(v, 'germ', 'different germs')} found in the last 3 months"
    if f.startswith("priorOrg_"):
        g = GERMS.get(f[len("priorOrg_"):], f[len("priorOrg_"):].capitalize())
        return f"Earlier {g} infection ({ago(v)})" if not _missing(v) else f"No earlier {g} infections"
    if f == "abx_n_events":
        return "No earlier antibiotic courses on record" if _missing(v) else plural(v, "earlier antibiotic course", "earlier antibiotic courses")
    if f == "abx_n_types_90d":
        return None if _missing(v) else f"{plural(v, 'kind of antibiotic', 'kinds of antibiotics')} in the last 3 months"
    if f.startswith("abx_"):
        fam = FAMILIES.get(f[len("abx_"):], f[len("abx_"):].replace("_", " "))
        return f"Took {fam} {ago(v)}" if not _missing(v) else f"No recent {fam.split(' (')[0]}"
    if f == "proc_n_events":
        return None if _missing(v) else plural(v, "earlier procedure or device", "earlier procedures or devices")
    if f == "proc_n_types_90d":
        return None if _missing(v) else f"{plural(v, 'kind of procedure', 'kinds of procedures')} in the last 3 months"
    if f.startswith("proc_"):
        dv = DEVICES.get(f[len("proc_"):], f[len("proc_"):].replace("_", " "))
        return f"{dv} {ago(v)}" if not _missing(v) else f"No {dv.lower()} on record"
    if f == "culture_type":
        return f"{SPECIMENS.get(str(v), str(v))} sample"
    if f == "ordering_mode":
        return "Hospital order" if str(v) == "Inpatient" else "Clinic order"
    if f == "age_ord":
        return None if _missing(v) else f"Age group {AGE_GROUPS[AGE_LIST[int(v)]]}"
    flags = {"hosp_ward_ICU": ("In intensive care", "Not in intensive care"),
             "hosp_ward_ER": ("Seen in the emergency department", "Not in the emergency department"),
             "hosp_ward_IP": ("On a hospital ward", "Not on a hospital ward"),
             "hosp_ward_OP": ("Seen in clinic", "Not a clinic visit"),
             "nursing_home": ("Recent nursing-home stay", "No nursing-home stay")}
    if f in flags:
        return flags[f][0] if (not _missing(v) and float(v) == 1) else flags[f][1]
    if f == "adi_score":
        return None if _missing(v) else "Neighbourhood deprivation score"
    return None

# Empira: antibiotic guidance before the lab is back

![Empira](frontend/static/brand/empira-logo-light.png)

Empira is a FastAPI backend and a Streamlit app built on the sealed v1.0 model (`models/`, `src/predictor.py`, `src/demo_api.py`).
The model itself is untouched; the app only calls it.

![Results screen](../docs/screenshots/03_results.png)

The name comes from *empiric therapy*: choosing an antibiotic before the lab has identified the germ. Brand files: `frontend/static/brand/`. The brand board (`empira-brand-board.png`) shows the logo, sizes and palette.

## Run it

From the project folder:

```
pip install -r requirements.txt -r app/requirements.txt
```

Then either:
- Windows: double-click `app\run_demo.bat`
- Mac/Linux: run `./app/run_demo.sh`

Or start the two parts yourself:

```
python -m uvicorn app.backend.main:app --port 8000      # the API, from the project folder
cd app/frontend && python -m streamlit run streamlit_app.py   # the app
```

Then open:
- the app at http://localhost:8501
- the API docs at http://localhost:8000/docs

Needed from the project:
- `models/`
- `data/processed/` (cultures, history, labels_agnostic, own_history_long, prior_resistance_long)
- `data/predictions/final_test.parquet` (for the real cases)
- `reports/phaseB/bootstrap_summary.json`
- `reports/phaseC/decision_summary.json`

## What the app does

A dark bar across the top holds the logo and three page buttons; on phones the buttons fold into a menu button. A one-line disclaimer sits at the foot of each page. The screens show no technical details; the API is documented separately at `http://localhost:8000/docs`.

| Page | For |
| --- | --- |
| **Check a patient** | Three steps: the sample (type, where the patient is seen, age group), their history (earlier resistant germs, germs found before, antibiotics taken, catheters and lines; all optional), then check. You get each antibiotic's chance of resistance ("11 in 100"), grouped as likely to work / uncertain / likely resistant, shown as cards. Button groups filter the cards (Works / Uncertain / Resistant / Rarely tested) and each card has a **Why?** button with the top three reasons. For urine you also get a suggested first choice (the narrowest antibiotic with a low enough chance of resistance) and a **Compare urine options** button. Answers are kept while you visit other pages. |
| **Real cases** | Five real 2022–2024 cultures the model never saw, with the lab's actual results next to each estimate. One is a case the model got wrong. |
| **How it works** | Key numbers, how it decides, the urine replay against doctors' choices, what it looks at and its limits. |

## Files

```
app/backend/            FastAPI service (main.py, service.py, schemas.py, wording.py, tests/)
app/frontend/
  streamlit_app.py      entry point: logo and top navigation
  ui.py                 shared styles, API calls and result components
  views/                check.py, cases.py, about.py
  static/               Lexend font (SIL OFL) and brand/ (logo SVG and PNG files, favicon, brand board)
  .streamlit/config.toml  theme taken from the logo palette
docs/screenshots/       screenshots and a walkthrough video of the running app (repo root)
```

## API

| Method | Path | Returns |
| --- | --- | --- |
| GET | `/api/health` | Model loaded, number of antibiotics |
| GET | `/api/options` | Everything a form needs (sample types, settings, age groups, antibiotics, germs, antibiotic families, devices, "when" choices) |
| POST | `/api/predict` | Chance of resistance for 28 antibiotics with reasons, plus a suggested first choice for urine |
| GET | `/api/cases` | The real example cases |
| GET | `/api/cases/{case_id}` | Model estimates next to the lab's actual results |
| GET | `/api/model` | Plain-language accuracy, impact and limits |

Example:

```
curl -X POST http://localhost:8000/api/predict -H "Content-Type: application/json" -d "{\"specimen\":\"URINE\",\"setting\":\"Outpatient\",\"age_group\":\"65-74 years\",\"past_resistance\":[{\"antibiotic\":\"ciprofloxacin\",\"when\":\"3_12_months\"}]}"
```

Input rules:
- `when` is one of `last_month`, `1_3_months`, `3_12_months`, `1_2_years`, `over_2_years`.
- `choice_mode` is `balanced` (threshold 0.15) or `stewardship` (0.20). These are the two thresholds validated in report 05; a test fails if they ever drift.
- Unknown values return a 422 that names the field.

## Tests

```
python -m pytest app/backend/tests -q        # 11 tests
```

They check that:
- the API's probabilities equal the sealed model's, for both form input and real test cultures;
- prior resistance raises risk;
- nitrofurantoin is never offered to inpatients;
- blood samples get no single suggestion;
- bad input is rejected.

## Design notes

- **Wording is for non-specialists:** "11 in 100" instead of probabilities, and brand names next to generic names. Reasons are written as sentences ("A germ from this patient was resistant to Ciprofloxacin about 6 months ago").
- **Verdict bands:** under 10 in 100 = likely to work, 10–30 = uncertain, over 30 = likely resistant.
- **Rarely tested drugs** (tested in under 5% of cultures of that sample type) are listed separately as less reliable.
- **Typeface:** Lexend, designed for readability, bundled under the SIL Open Font License (`frontend/static/OFL.txt`) so it works offline.
- **Palette:** neutral colours from the logo: slate `#2B3437`, deep sage `#34433F`, sage `#4F6660`, mist `#8C9A92`, stone `#9C9486`, halo `#D7DFD9`, fog `#F4F5F3`. Verdict colours are muted to match: `#5E7F67`, `#A3874F`, `#9E5A5A`.

Research prototype. Not for clinical use.

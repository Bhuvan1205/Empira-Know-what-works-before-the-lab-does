import json

import streamlit as st

import ui

OPT, LBL = ui.options()
WHEN_KEYS = [o["value"] for o in OPT["when"]]
DEFAULTS = {"f_specimen": "URINE", "f_setting": "Outpatient", "f_age": "55-64 years", "f_nh": False, "f_mode": "balanced"}
EXAMPLE = {"f_specimen": "URINE", "f_setting": "Outpatient", "f_age": "65-74 years",
           "f_res": ["ciprofloxacin", "trimethoprim/sulfamethoxazole"], "f_germs": ["escherichia"], "f_abx": ["fluoroquinolone"],
           "f_dev": [], "f_nh": False, "w_res_ciprofloxacin": "3_12_months", "w_res_trimethoprim/sulfamethoxazole": "1_3_months",
           "w_germs_escherichia": "3_12_months", "w_abx_fluoroquinolone": "1_3_months"}
for k, v in DEFAULTS.items():
    st.session_state.setdefault(k, v)


def load_example():
    st.session_state.update(EXAMPLE); st.session_state.pop("result", None)


def clear_form():
    for k in list(st.session_state):
        if k.startswith(("f_", "w_", "grp_")) or k == "result":
            del st.session_state[k]
    st.session_state.update(DEFAULTS)


def keep(key, fallback):
    """Button groups can be switched off by clicking the active button; keep the last real choice."""
    if st.session_state.get(key) is None:
        st.session_state[key] = fallback


def history_picker(label, options_key, state_key, placeholder):
    chosen = st.multiselect(label, options=list(LBL[options_key]), format_func=lambda v: LBL[options_key][v],
                            key=f"f_{state_key}", placeholder=placeholder)
    out = []
    for v in chosen:
        k = f"w_{state_key}_{v}"
        st.session_state.setdefault(k, "3_12_months")
        c1, c2 = st.columns([1.15, 1])
        c1.markdown(f'<div class="picked">{ui.esc(LBL[options_key][v])}</div>', unsafe_allow_html=True)
        c2.selectbox("When", WHEN_KEYS, format_func=lambda w: LBL["when"][w], key=k, label_visibility="collapsed")
        out.append((v, st.session_state[k]))
    if chosen:
        st.markdown('<div style="height:.6rem"></div>', unsafe_allow_html=True)
    return out


ui.header("Check a patient", "Lab results take 2 to 3 days. Until then, see which antibiotics are likely to work for this patient.")

left, right = st.columns([5, 7], gap="large")
with left:
    b1, b2 = st.columns(2)
    b1.button("Try an example", on_click=load_example, use_container_width=True, icon=":material/person:")
    b2.button("Start over", on_click=clear_form, use_container_width=True, icon=":material/restart_alt:")

    ui.step(1, "The sample")
    keep("f_specimen", "URINE"); keep("f_setting", "Outpatient")
    specimen = st.segmented_control("Sample sent to the lab", list(LBL["specimens"]), format_func=lambda v: LBL["specimens"][v],
                                    key="f_specimen") or "URINE"
    setting = st.segmented_control("Where the patient is seen", list(LBL["settings"]),
                                   format_func=lambda v: {"Outpatient": "Clinic", "ER": "Emergency", "Inpatient": "Ward", "ICU": "ICU"}[v],
                                   key="f_setting") or "Outpatient"
    age = st.select_slider("Age group", list(LBL["age_groups"]), format_func=lambda v: LBL["age_groups"][v], key="f_age")

    ui.step(2, "Their history")
    st.caption("Optional. Add anything from at least a few days before this sample.")
    res = history_picker("Resistant to before", "antibiotics", "res", "Choose antibiotics")
    germs = history_picker("Germs found before", "germs", "germs", "Choose germs")
    abx = history_picker("Antibiotics taken", "antibiotic_families", "abx", "Choose antibiotics")
    dev = history_picker("Catheters, lines or procedures", "devices", "dev", "Choose devices or procedures")
    nh = st.toggle("Recent nursing-home stay", key="f_nh")

    ui.step(3, "Check")
    mode = "balanced"
    if specimen == "URINE":
        keep("f_mode", "balanced")
        mode = st.segmented_control("For the suggested first choice, prefer", ["balanced", "stewardship"],
                                    format_func=lambda v: {"balanced": "Fewer wrong choices", "stewardship": "Narrower antibiotics"}[v],
                                    key="f_mode") or "balanced"
    payload = {"specimen": specimen, "setting": setting, "age_group": age, "nursing_home": nh, "choice_mode": mode,
               "past_resistance": [{"antibiotic": v, "when": w} for v, w in res],
               "past_germs": [{"germ": v, "when": w} for v, w in germs],
               "recent_antibiotics": [{"family": v, "when": w} for v, w in abx],
               "devices": [{"device": v, "when": w} for v, w in dev]}
    if st.button("Check antibiotics", type="primary", use_container_width=True, icon=":material/search:"):
        try:
            with st.spinner("Checking 28 antibiotics..."):
                st.session_state["result"] = (json.dumps(payload, sort_keys=True), ui.post("/api/predict", payload))
        except ValueError:
            st.error("Some details could not be used. Check the form and try again.")
        except Exception:
            ui.unavailable()

with right:
    if "result" not in st.session_state:
        st.markdown('<div class="empty"><img src="app/static/brand/empira-mark.svg" alt=""><br>'
                    'Describe the sample and the patient\'s history, then press <b>Check antibiotics</b>.'
                    '<br><br>Short on time? Press <b>Try an example</b>.</div>', unsafe_allow_html=True)
    else:
        sent, r = st.session_state["result"]
        if sent != json.dumps(payload, sort_keys=True):
            st.warning("Details changed. Press Check antibiotics to update.", icon=":material/refresh:")
        st.subheader(f'Results for a {LBL["specimens"][r["specimen"]].lower()} sample')
        ui.rec_card(r["recommendation"], key="check")
        ui.result_groups(r["antibiotics"], key="check")

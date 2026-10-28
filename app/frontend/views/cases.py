import streamlit as st

import ui

ui.header("Real cases", "Real cultures from 2022 to 2024 that Empira never saw while it was being built. "
          "Compare its estimates with what the lab found.")

try:
    cases = ui.get("/api/cases")
except Exception:
    ui.unavailable()
titles = {c["case_id"]: c["title"] for c in cases}
st.session_state.setdefault("case_pick", list(titles)[0])
if st.session_state.get("case_pick") is None:
    st.session_state["case_pick"] = list(titles)[0]
cid = st.segmented_control("Choose a case", list(titles), format_func=lambda i: titles[i], key="case_pick") or list(titles)[0]

case = ui.get(f"/api/cases/{cid}")
good = [a for a in case["antibiotics"] if a["verdict"] == "likely_works"]
bad = [a for a in case["antibiotics"] if a["verdict"] == "likely_resistant"]

c1, c2 = st.columns([5, 7], gap="large")
with c1:
    with st.container(border=True, key="box_cases_1"):
        st.markdown("**The patient**")
        st.markdown('<ul class="facts">' + "".join(f"<li>{ui.esc(p)}</li>" for p in case["patient"]) + "</ul>",
                    unsafe_allow_html=True)
    with st.container(border=True, key="box_cases_2"):
        st.markdown("**How Empira did**")
        m1, m2 = st.columns(2)
        m1.metric("Likely to work", f'{sum(a["lab_result"] == "Worked" for a in good)} of {len(good)}',
                  help="Of the antibiotics Empira rated likely to work, how many worked in the lab")
        m2.metric("Likely resistant", f'{sum(a["lab_result"] == "Resistant" for a in bad)} of {len(bad)}',
                  help="Of the antibiotics Empira rated likely resistant, how many were resistant in the lab")
with c2:
    ui.rec_card(case["recommendation"], key="case", show_lab=True)
    ui.result_groups(case["antibiotics"], key=f"case_{cid}", show_lab=True)

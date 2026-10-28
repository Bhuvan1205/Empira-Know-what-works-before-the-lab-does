import streamlit as st

import ui

try:
    info = ui.get("/api/model")
except Exception:
    ui.unavailable()
doc, bal, stw = info["impact"]

ui.header("How it works", "Empira estimates which antibiotics are likely to work for a urine, blood or airway sample, "
          "days before the lab result is back.")

m1, m2, m3 = st.columns(3)
for n, (col, label, value, note) in enumerate([(m1, "Antibiotics checked", "28", "for every sample"),
                                (m2, "Past cultures learned from", "88,000", "Stanford Health Care, 2008-2020"),
                                (m3, "Wrong first choices, urine", bal["wrong_choice"], f'doctors: {doc["wrong_choice"]}')]):
    with col.container(border=True, key=f"box_metric_{n}"):
        st.metric(label, value)
        st.caption(note)

a1, a2 = st.columns([6, 5], gap="large")
with a1:
    st.subheader("How it decides")
    st.markdown("1. You describe the sample and the patient's past infections and treatment.\n"
                "2. Empira compares this with past cultures and estimates each antibiotic's chance of resistance.\n"
                "3. For urine it suggests the narrowest antibiotic with a low enough chance. Narrow antibiotics "
                "cause less resistance in the long run.")
    st.subheader("Does it help?")
    rows = "".join(f'<tr class="{"tool" if i else ""}"><td>{ui.esc(r["label"])}</td><td>{ui.esc(r["wrong_choice"])}</td>'
                   f'<td>{ui.esc(r["broad_use"])}</td></tr>' for i, r in enumerate(info["impact"]))
    st.markdown(f'<table class="impact"><tr><th>Urine cultures, 2022-2024</th><th>Germ resistant to the drug</th>'
                f'<th>Broader antibiotics</th></tr>{rows}</table>', unsafe_allow_html=True)
    st.caption("Compared with the antibiotic doctors actually gave on the day.")
with a2:
    with st.container(border=True, key="box_about_1"):
        st.markdown("**What it looks at**")
        st.markdown("\n".join(f"- {u}" for u in info["uses"]))
    with st.container(border=True, key="box_about_2"):
        st.markdown("**Limits**")
        st.markdown("\n".join(f"- {u}" for u in info["limits"]))

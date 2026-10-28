"""Empira: antibiotic guidance before the lab is back.  Demo UI on top of the FastAPI backend.

Run (backend first):
    python -m uvicorn app.backend.main:app --port 8000          # from the project folder
    cd app/frontend && python -m streamlit run streamlit_app.py  # then open http://localhost:8501
Set API_URL if the backend runs elsewhere.
"""
import os

import streamlit as st

import ui

HERE = os.path.dirname(os.path.abspath(__file__))
BRAND = os.path.join(HERE, "static", "brand")

st.set_page_config(page_title="Empira", page_icon=os.path.join(BRAND, "empira-favicon-64.png"),
                   layout="wide", initial_sidebar_state="collapsed")

# Keep form answers when moving between pages (Streamlit drops state of widgets that are not on screen).
for k in list(st.session_state.keys()):
    if k.startswith(("f_", "w_")):
        st.session_state[k] = st.session_state[k]

st.logo(os.path.join(BRAND, "empira-sidebar.png"), size="large", icon_image=os.path.join(BRAND, "empira-sidebar.png"))
st.markdown(ui.CSS, unsafe_allow_html=True)

nav = st.navigation([
    st.Page("views/check.py", title="Check a patient", icon=":material/stethoscope:", default=True),
    st.Page("views/cases.py", title="Real cases", icon=":material/folder_open:"),
    st.Page("views/about.py", title="How it works", icon=":material/lightbulb:"),
], position="top")

nav.run()

st.markdown('<div class="foot">Empira is a research prototype. Not for treating patients.</div>', unsafe_allow_html=True)

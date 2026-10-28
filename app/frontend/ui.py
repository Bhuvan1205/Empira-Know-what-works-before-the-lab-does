"""Shared look, API access and result components for the Empira app."""
import html
import os

import requests
import streamlit as st

API = os.environ.get("API_URL", "http://localhost:8000")

INK, MUTED, SLATE, SAGE, STONE = "#2B3437", "#6B7873", "#34433F", "#8C9A92", "#9C9486"
VERDICT = {"likely_works": ("#5E7F67", "green", "Likely to work", "Works"),
           "uncertain": ("#A3874F", "orange", "Uncertain", "Uncertain"),
           "likely_resistant": ("#9E5A5A", "red", "Likely resistant", "Resistant"),
           "rare": (STONE, "gray", "Rarely tested", "Rarely tested")}

CSS = f"""
<style>
  .block-container {{ max-width: 1120px; padding-top: 5.4rem; }}
  h1 {{ font-size: 2.1rem !important; letter-spacing: -0.015em; margin-bottom: .1rem !important; }}
  h2, h3 {{ letter-spacing: -0.01em; }}
  .lede {{ color: {MUTED}; font-size: 1.04rem; margin: .2rem 0 1.4rem; max-width: 62ch; }}
  .step {{ display: flex; align-items: center; gap: .65rem; margin: 1.5rem 0 .55rem; }}
  .step .n {{ width: 1.75rem; height: 1.75rem; border-radius: 50%; background: {INK}; color: #F4F5F3; display: flex;
              align-items: center; justify-content: center; font-weight: 700; font-size: .88rem; flex: none; }}
  .step b {{ font-size: 1.15rem; }}

  /* recommendation card */
  .rec {{ background: {SLATE}; color: #EEF0EC; border-radius: 16px; padding: 1.35rem 1.55rem 1.25rem; margin-bottom: .7rem;
          position: relative; overflow: hidden; }}
  .rec::after {{ content: ""; position: absolute; right: -46px; top: -46px; width: 150px; height: 150px; border-radius: 50%;
                 border: 2px solid rgba(233,236,232,.14); box-shadow: inset 0 0 0 28px rgba(233,236,232,.05); }}
  .rec .k {{ font-size: .9rem; color: #B9C4BE; margin: 0; }}
  .rec .drug {{ font-size: 1.9rem; font-weight: 700; line-height: 1.15; margin: .2rem 0 .55rem; letter-spacing: -.01em; }}
  .rec .meter {{ display: flex; align-items: center; gap: .7rem; margin-bottom: .55rem; flex-wrap: wrap; }}
  .rec .bar {{ flex: 1; min-width: 120px; height: 9px; background: rgba(233,236,232,.18); border-radius: 6px; overflow: hidden; max-width: 240px; }}
  .rec .bar span {{ display: block; height: 100%; background: #E9ECE8; }}
  .rec .sum {{ font-size: .97rem; line-height: 1.55; color: #DDE2DD; margin: 0; max-width: 58ch; }}
  .chip {{ display: inline-block; font-size: .8rem; padding: .17rem .6rem; border-radius: 999px; margin: 0 .35rem .2rem 0; }}
  .rec .chip {{ background: rgba(233,236,232,.14); color: #E9ECE8; }}
  .rec .chip.lab-ok {{ background: #E3EBE4; color: #4E6E57; font-weight: 700; }}
  .rec .chip.lab-bad {{ background: #F2E3E2; color: #8E4B4B; font-weight: 700; }}
  .norec {{ background: #fff; border: 1px solid #D6DAD4; border-radius: 16px; padding: 1rem 1.2rem; margin-bottom: .8rem; color: {MUTED}; }}

  /* chosen items wrap onto new lines instead of scrolling sideways */
  [data-testid="stMultiSelectTagsContainer"] {{ flex-wrap: wrap !important; overflow: visible !important; mask-image: none !important; -webkit-mask-image: none !important; }}
  [data-testid="stMultiSelect"] .react-aria-ComboBox, [data-testid="stMultiSelect"] .react-aria-ComboBox > div[role="group"] {{ height: auto !important; max-height: none !important; overflow: visible !important; }}
  [data-testid="stMultiSelect"] .react-aria-ComboBox > div[role="group"] {{ padding-top: 4px; padding-bottom: 4px; }}
  [data-testid="stMultiSelectTagsContainer"] > span[role="group"] {{ flex-wrap: wrap !important; row-gap: 4px; min-width: 0 !important; max-width: 100%; }}

  /* antibiotic cards */
  .ab-name {{ font-weight: 700; font-size: 1rem; line-height: 1.25; min-height: 2.5rem; }}
  .ab-row {{ display: flex; white-space: nowrap; align-items: baseline; justify-content: space-between; gap: .5rem; margin-top: .25rem; }}
  .ab-chance {{ font-size: 1.35rem; font-weight: 700; }}
  .ab-unit {{ font-size: .82rem; color: {MUTED}; }}
  .mini {{ height: 6px; background: #E8EBE7; border-radius: 5px; overflow: hidden; margin: .35rem 0 .55rem; }}
  .mini span {{ display: block; height: 100%; }}
  .lab {{ font-size: .8rem; font-weight: 700; padding: .12rem .5rem; border-radius: 999px; white-space: nowrap; }}
  .lab-row {{ margin: -.15rem 0 .55rem; }}
  .lab.ok {{ background: #E3EBE4; color: #4E6E57; }}
  .lab.bad {{ background: #F2E3E2; color: #8E4B4B; }}
  .why li {{ margin-bottom: .3rem; }}
  .opts {{ width: 100%; border-collapse: collapse; font-size: .93rem; }}
  .opts td {{ padding: .4rem .2rem; border-bottom: 1px solid #E3E6E1; }}
  .opts td.r {{ text-align: right; white-space: nowrap; color: {MUTED}; }}

  .facts {{ margin: 0; padding-left: 1.1rem; }}
  .facts li {{ margin-bottom: .25rem; }}
  .empty {{ border: 1.5px dashed #C3C9C2; border-radius: 16px; padding: 2.3rem 1.6rem; color: {MUTED}; text-align: center; }}
  .empty img {{ width: 64px; opacity: .85; margin-bottom: .7rem; }}
  .impact {{ width: 100%; border-collapse: collapse; margin: .3rem 0 .2rem; }}
  .impact th {{ text-align: left; font-weight: 700; color: {MUTED}; font-size: .86rem; padding: .4rem .35rem; border-bottom: 2px solid #D6DAD4; }}
  .impact td {{ padding: .55rem .35rem; border-bottom: 1px solid #E3E6E1; }}
  .impact tr.tool td {{ font-weight: 700; }}
  .picked {{ padding-top: .5rem; font-size: .94rem; line-height: 1.3; }}

  /* bordered containers and metrics */
  div[class*="st-key-card_"], div[class*="st-key-box_"] {{ background: #fff; }}
  div[data-testid="stMetricValue"] {{ font-weight: 700; }}

  /* top bar: brand colour, logo on the left, pages as buttons */
  header[data-testid="stHeader"] {{ background: {INK}; height: 4.1rem; border-bottom: 1px solid #1F2729; box-shadow: 0 2px 10px rgba(20,28,30,.12); }}
  header[data-testid="stHeader"] [data-testid="stToolbar"] {{ height: 4.1rem; padding: 0 1.6rem; align-items: center; }}
  img[data-testid="stHeaderLogo"] {{ height: 30px !important; width: auto !important; max-width: none !important; margin-right: 1.6rem; }}
  @media (max-width: 640px) {{ header[data-testid="stHeader"] [data-testid="stToolbar"] {{ padding: 0 1rem; }} }}
  a[data-testid="stTopNavLink"] {{ border: 1px solid #44524E; border-radius: 10px; padding: .42rem .95rem !important; margin-right: .45rem;
      background: transparent; transition: background .15s, border-color .15s; }}
  a[data-testid="stTopNavLink"] p, a[data-testid="stTopNavLink"] [data-testid="stIconMaterial"] {{ color: #DCE2DD !important; font-weight: 500; }}
  a[data-testid="stTopNavLink"]:hover {{ background: #3A4744; border-color: #5C6B66; }}
  a[data-testid="stTopNavLink"][aria-current="page"] {{ background: #E9ECE8; border-color: #E9ECE8; }}
  a[data-testid="stTopNavLink"][aria-current="page"] p, a[data-testid="stTopNavLink"][aria-current="page"] [data-testid="stIconMaterial"] {{ color: {INK} !important; font-weight: 700; }}
  /* phones: the pages move into a slide-out menu, opened by a menu button on the right of the bar */
  header button[data-testid="stExpandSidebarButton"] {{ position: fixed; right: 1rem; top: .85rem; border: 1px solid #44524E; border-radius: 10px; width: 2.6rem; height: 2.4rem; }}
  header button[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"] {{ font-size: 0 !important; }}
  header button[data-testid="stExpandSidebarButton"] [data-testid="stIconMaterial"]::before {{ content: "menu"; font-size: 1.45rem;
      color: #DCE2DD; font-family: "Material Symbols Rounded"; }}
  section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{ border: 1px solid #3E4B48; border-radius: 10px; margin-bottom: .45rem; padding: .55rem .8rem; }}
  section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] {{ background: #E9ECE8; border-color: #E9ECE8; }}
  section[data-testid="stSidebar"] [data-testid="stSidebarNav"] a[aria-current="page"] span {{ color: {INK} !important; }}
  .foot {{ margin-top: 3rem; padding-top: 1rem; border-top: 1px solid #D6DAD4; color: {MUTED}; font-size: .82rem; text-align: center; }}
</style>
"""


def esc(t):
    return html.escape(str(t))


@st.cache_data(ttl=600, show_spinner=False)
def get(path):
    r = requests.get(API + path, timeout=30); r.raise_for_status(); return r.json()


def post(path, body):
    r = requests.post(API + path, json=body, timeout=30)
    if r.status_code == 422:
        raise ValueError(r.json().get("detail"))
    r.raise_for_status(); return r.json()


def unavailable():
    st.error("Empira is not available right now. Please try again in a moment.", icon=":material/cloud_off:")
    st.stop()


def options():
    try:
        o = get("/api/options")
    except Exception:
        unavailable()
    lbl = {k: {x["value"]: x["label"] for x in v} for k, v in o.items()}
    return o, lbl


def header(title, lede):
    st.title(title)
    st.markdown(f'<p class="lede">{lede}</p>', unsafe_allow_html=True)


def step(n, title):
    st.markdown(f'<div class="step"><span class="n">{n}</span><b>{esc(title)}</b></div>', unsafe_allow_html=True)


# ----------------------------------------------------------------------------- results
def rec_card(rec, key, show_lab=False):
    if not rec["available"]:
        st.markdown(f'<div class="norec">{esc(rec["summary"])}</div>', unsafe_allow_html=True)
        return
    pct = max(2, round(rec["chance_resistant"] * 100))
    lab = ""
    if show_lab and rec.get("lab_result"):
        ok = rec["lab_result"] == "Worked"
        lab = f'<span class="chip {"lab-ok" if ok else "lab-bad"}">Lab result: {"it worked" if ok else "resistant"}</span>'
    st.markdown(f"""
<div class="rec">
  <p class="k">Suggested first choice</p>
  <div class="drug">{esc(rec["name"])}</div>
  <div class="meter"><div class="bar"><span style="width:{pct}%"></span></div>
      <span>Chance of resistance: <b>{esc(rec["chance_text"])}</b></span></div>
  <p style="margin:0 0 .55rem"><span class="chip">{esc(rec["spectrum"])}</span>{lab}</p>
  <p class="sum">{esc(rec["summary"])}</p>
</div>""", unsafe_allow_html=True)
    with st.popover("Compare urine options", icon=":material/compare_arrows:"):
        st.markdown("**From narrowest to broadest.** Empira picks the first one whose chance of resistance is low enough.")
        rows = "".join(f'<tr><td>{esc(o["name"])}<br><span style="color:{MUTED};font-size:.83rem">{esc(o["spectrum"])}</span></td>'
                       f'<td class="r">{esc(o["chance_text"])}</td></tr>' for o in rec["options"])
        st.markdown(f'<table class="opts">{rows}</table>', unsafe_allow_html=True)


def _card(a, key, show_lab, i):
    color = VERDICT[a["verdict"]][0]
    pct = max(1, round(a["chance_resistant"] * 100))
    lab = ""
    if show_lab and a.get("lab_result"):
        lab = ('<span class="lab ok">Lab: it worked</span>' if a["lab_result"] == "Worked"
               else '<span class="lab bad">Lab: resistant</span>')
    with st.container(border=True, key=f"card_{key}_{i}"):
        chance = a["chance_text"].replace(" in 100", "")
        st.markdown(f'<div class="ab-name">{esc(a["name"])}</div>'
                    f'<div class="ab-row"><span><span class="ab-chance" style="color:{color}">{esc(chance)}</span>'
                    f' <span class="ab-unit">in 100 resistant</span></span></div>'
                    f'<div class="mini"><span style="width:{pct}%;background:{color}"></span></div>'
                    + (f'<div class="lab-row">{lab}</div>' if lab else ''), unsafe_allow_html=True)
        with st.popover("Why?", icon=":material/info:", use_container_width=True):
            st.markdown(f"**{a['name']}**: {a['chance_text']} chance of resistance ({a['verdict_label'].lower()}).")
            if a["reasons"]:
                items = "".join(f'<li>{"⬆" if r["direction"] == "raises" else "⬇"} {esc(r["text"])}'
                                f' <span style="color:{MUTED}">({"raises" if r["direction"] == "raises" else "lowers"} the chance)</span></li>'
                                for r in a["reasons"])
                st.markdown(f'<ul class="why">{items}</ul>', unsafe_allow_html=True)
            else:
                st.markdown("Close to the usual rate for this kind of sample. Nothing in the history stands out.")
            if not a["commonly_tested"]:
                st.caption("Rarely tested on this kind of sample, so this estimate is less reliable.")


def result_groups(items, key, show_lab=False):
    groups = {"likely_works": [a for a in items if a["commonly_tested"] and a["verdict"] == "likely_works"],
              "uncertain": [a for a in items if a["commonly_tested"] and a["verdict"] == "uncertain"],
              "likely_resistant": [a for a in items if a["commonly_tested"] and a["verdict"] == "likely_resistant"],
              "rare": [a for a in items if not a["commonly_tested"]]}
    keys = [k for k, v in groups.items() if v]
    labels = {k: f"{VERDICT[k][3]} ({len(groups[k])})" for k in keys}
    st.markdown("**All antibiotics**")
    choice = st.segmented_control("Show", keys, format_func=lambda k: labels[k], default=keys[0], key=f"grp_{key}",
                                  label_visibility="collapsed")
    choice = choice or keys[0]
    hint = {"likely_works": "Likely to work: resistance in under 10 of 100 similar patients.",
            "uncertain": "Uncertain: resistance in 10 to 30 of 100 similar patients.",
            "likely_resistant": "Likely resistant: resistance in over 30 of 100 similar patients.",
            "rare": "Seldom tested on this kind of sample, so these estimates are less reliable."}
    st.caption(hint[choice])
    cols = st.columns(2)
    for i, a in enumerate(groups[choice]):
        with cols[i % 2]:
            _card(a, key, show_lab, i)

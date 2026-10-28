/* Empira web app: one screen, live results. Talks only to the Empira API. */
(() => {
  "use strict";

  const params = new URLSearchParams(location.search);
  const API = (params.get("api") || `${location.protocol}//${location.hostname || "localhost"}:8000`).replace(/\/$/, "");

  const SPECIMENS = [["URINE", "Urine"], ["BLOOD", "Blood"], ["RESPIRATORY", "Airway"]];
  const SETTINGS = [["Outpatient", "Clinic"], ["ER", "Emergency"], ["Inpatient", "Ward"], ["ICU", "ICU"]];
  const SPECIMEN_WORD = { URINE: "urine", BLOOD: "blood", RESPIRATORY: "airway" };
  const KINDS = {
    res:   { group: "Resisted before",  verb: "Germ resisted", field: "past_resistance",    key: "antibiotic", when: "3_12_months" },
    germ:  { group: "Earlier infection", verb: "Earlier infection", field: "past_germs",     key: "germ",       when: "3_12_months" },
    abx:   { group: "Antibiotic taken",  verb: "Took",          field: "recent_antibiotics", key: "family",     when: "1_3_months" },
    dev:   { group: "Device or procedure", verb: "Had",         field: "devices",            key: "device",     when: "last_month" },
  };
  const DEFAULTS = { specimen: "URINE", setting: "Outpatient", age: "55-64 years", history: [], nh: false, mode: "balanced" };
  const EXAMPLE = {
    specimen: "URINE", setting: "Outpatient", age: "65-74 years", nh: false,
    history: [
      { kind: "res", value: "ciprofloxacin", when: "3_12_months" },
      { kind: "res", value: "trimethoprim/sulfamethoxazole", when: "1_3_months" },
      { kind: "germ", value: "escherichia", when: "3_12_months" },
      { kind: "abx", value: "fluoroquinolone", when: "1_3_months" },
    ],
  };
  const STORE = "empira.v2";

  const $ = (id) => document.getElementById(id);
  const el = (tag, attrs = {}, ...kids) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (v == null || v === false) continue;
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else n.setAttribute(k, v === true ? "" : v);
    }
    for (const kid of kids.flat()) if (kid != null) n.append(kid.nodeType ? kid : document.createTextNode(kid));
    return n;
  };
  const svgIcon = (d, cls = "") => {
    const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    s.setAttribute("viewBox", "0 0 20 20"); s.setAttribute("aria-hidden", "true"); if (cls) s.setAttribute("class", cls);
    s.innerHTML = d; return s;
  };
  const ICON_X = '<path d="M5 5l10 10M15 5 5 15" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>';
  const ICON_CHEV = '<path d="M7 4l6 6-6 6" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>';

  let opts = null;            // /api/options
  let labels = {};            // kind -> value -> label
  let index = [];             // search entries
  let state = load();
  let caseId = null;
  let lastResult = null;
  let open = new Set();
  let showRare = false;
  let inflight = null;
  let timer = null;
  let lastDotsKey = "";

  function load() {
    try { const s = JSON.parse(localStorage.getItem(STORE)); if (s && s.specimen) return { ...DEFAULTS, ...s }; } catch (_) {}
    return structuredClone(DEFAULTS);
  }
  function save() { try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (_) {} }

  async function api(path, body, signal) {
    const r = await fetch(API + path, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body), signal } : { signal });
    if (!r.ok) {
      let msg = `The service answered ${r.status}.`;
      try { const j = await r.json(); if (j.detail) msg = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch (_) {}
      const e = new Error(msg); e.status = r.status; throw e;
    }
    return r.json();
  }

  /* ---------------- form ---------------- */
  function seg(container, items, current, onPick) {
    container.replaceChildren(...items.map(([v, label]) => el("button", {
      type: "button", role: "radio", "aria-checked": String(v === current), tabindex: v === current ? "0" : "-1",
      text: label, onclick: () => onPick(v),
      onkeydown: (e) => {
        if (!["ArrowLeft", "ArrowRight"].includes(e.key)) return;
        const i = items.findIndex(([x]) => x === current); const j = (i + (e.key === "ArrowRight" ? 1 : -1) + items.length) % items.length;
        onPick(items[j][0]); requestAnimationFrame(() => container.querySelector('[aria-checked="true"]').focus());
      },
    })));
  }

  function renderForm() {
    seg($("specimenSeg"), SPECIMENS, state.specimen, (v) => { if (v !== state.specimen) { showRare = false; open = new Set(); } state.specimen = v; changed(); });
    seg($("settingSeg"), SETTINGS, state.setting, (v) => { state.setting = v; changed(); });
    const age = $("ageSelect");
    if (!age.options.length) age.replaceChildren(...opts.age_groups.map((a) => el("option", { value: a.value, text: a.label })));
    age.value = state.age;
    $("nhToggle").checked = !!state.nh;
    renderChips();
  }

  function renderChips() {
    const whenOpts = opts.when;
    $("chips").replaceChildren(...state.history.map((h, i) => {
      const k = KINDS[h.kind];
      const sel = el("select", { "aria-label": `When: ${labels[h.kind][h.value]}`, onchange: (e) => { h.when = e.target.value; save(); schedule(); } },
        whenOpts.map((w) => el("option", { value: w.value, text: shortWhen(w.label), selected: w.value === h.when })));
      return el("li", { class: "chip" },
        el("span", { class: "chip-text" }, el("small", { text: k.verb }), labels[h.kind][h.value]),
        el("span", { class: "select-wrap chip-when" }, sel),
        el("button", { type: "button", class: "chip-remove", "aria-label": `Remove ${labels[h.kind][h.value]}`,
          onclick: () => { state.history.splice(i, 1); changed(); $("historyInput").focus(); } }, svgIcon(ICON_X)));
    }));
  }
  const shortWhen = (s) => s.replace("In the last month", "Last month").replace("More than 2 years ago", "Over 2 years ago");

  /* ---------------- history search ---------------- */
  let active = -1, matches = [];
  function buildIndex() {
    const add = (kind, list) => list.forEach((o) => { labels[kind][o.value] = o.label; index.push({ kind, value: o.value, label: o.label, hay: (o.label + " " + o.value).toLowerCase() }); });
    labels = { res: {}, germ: {}, abx: {}, dev: {} };
    add("res", opts.antibiotics); add("germ", opts.germs); add("abx", opts.antibiotic_families); add("dev", opts.devices);
  }
  function search(q) {
    q = q.trim().toLowerCase();
    if (!q) return [];
    const words = q.split(/\s+/);
    const taken = new Set(state.history.map((h) => h.kind + "|" + h.value));
    return index.filter((e) => !taken.has(e.kind + "|" + e.value) && words.every((w) => e.hay.includes(w)))
      .sort((a, b) => (a.hay.startsWith(q) ? 0 : 1) - (b.hay.startsWith(q) ? 0 : 1)).slice(0, 12);
  }
  function renderList() {
    const list = $("historyList"), input = $("historyInput");
    const q = input.value;
    matches = search(q);
    if (!q.trim()) { list.hidden = true; input.setAttribute("aria-expanded", "false"); return; }
    const kids = [];
    if (!matches.length) kids.push(el("li", { class: "combo-empty", text: `Nothing matches “${q.trim()}”. Try a drug, germ or device name.` }));
    let lastKind = null;
    matches.forEach((m, i) => {
      if (m.kind !== lastKind) { kids.push(el("li", { class: "combo-group", role: "presentation", text: KINDS[m.kind].group })); lastKind = m.kind; }
      kids.push(el("li", { class: "combo-opt", role: "option", id: `opt-${i}`, "aria-selected": String(i === active),
        onmousedown: (e) => { e.preventDefault(); pick(i); }, onmousemove: () => { if (active !== i) { active = i; renderList(); } } },
        el("span", { text: m.label })));
    });
    list.replaceChildren(...kids);
    list.hidden = false; input.setAttribute("aria-expanded", "true");
    if (active >= 0) { input.setAttribute("aria-activedescendant", `opt-${active}`); $(`opt-${active}`)?.scrollIntoView({ block: "nearest" }); }
    else input.removeAttribute("aria-activedescendant");
  }
  function pick(i) {
    const m = matches[i]; if (!m) return;
    state.history.push({ kind: m.kind, value: m.value, when: KINDS[m.kind].when });
    $("historyInput").value = ""; active = -1; renderList(); changed();
  }

  /* ---------------- results ---------------- */
  function payload() {
    const p = { specimen: state.specimen, setting: state.setting, age_group: state.age, nursing_home: !!state.nh, choice_mode: state.mode,
      past_resistance: [], past_germs: [], recent_antibiotics: [], devices: [] };
    for (const h of state.history) { const k = KINDS[h.kind]; p[k.field].push({ [k.key]: h.value, when: h.when }); }
    return p;
  }

  function changed() { save(); renderForm(); schedule(); }
  function schedule() { clearTimeout(timer); timer = setTimeout(run, 180); $("answer").setAttribute("aria-busy", "true"); }

  async function run() {
    if (inflight) inflight.abort();
    inflight = new AbortController();
    const signal = inflight.signal;
    try {
      const data = caseId
        ? await api(`/api/cases/${caseId}?choice_mode=${state.mode}`, null, signal)
        : await api("/api/predict", payload(), signal);
      lastResult = data; renderAnswer(data);
      if (caseId) renderCase(data);
    } catch (e) {
      if (e.name === "AbortError") return;
      renderError(e);
    } finally {
      if (!signal.aborted) $("answer").setAttribute("aria-busy", "false");
    }
  }

  const verdictClass = (v) => ({ likely_works: "v-works", uncertain: "v-unsure", likely_resistant: "v-resist" })[v];
  const splitName = (name) => { const m = name.match(/^(.*?)\s*\((.*)\)$/); return m ? [m[1], m[2]] : [name, ""]; };
  const per100 = (p) => Math.max(0, Math.min(100, Math.round(p * 100)));

  function dotGrid(p) {
    const n = per100(p), key = `${caseId}|${n}`;
    const g = el("div", { class: "dots" + (key !== lastDotsKey ? " anim" : ""), role: "img", "aria-label": `${n} of 100 dots marked: resistant` });
    for (let i = 0; i < 100; i++) { const d = el("i", { class: i < n ? "on" : null }); d.style.setProperty("--i", i); g.append(d); }
    lastDotsKey = key;
    return g;
  }

  function hero(d) {
    const r = d.recommendation;
    const foot = el("div", { class: "hero-foot" },
      el("label", { class: "switch-row" },
        el("input", { type: "checkbox", class: "switch", checked: state.mode === "stewardship",
          onchange: (e) => { state.mode = e.target.checked ? "stewardship" : "balanced"; save(); schedule(); } }),
        el("span", { text: "Prefer narrower antibiotics" })),
      el("span", { class: "switch-help", text: state.mode === "stewardship"
        ? "Accepts up to 20 in 100 to keep broader drugs in reserve."
        : "Picks the narrowest drug at 15 in 100 or lower." }));

    if (!r.available) {
      const best = d.antibiotics.filter((a) => a.commonly_tested).slice(0, 3);
      return el("section", { class: "hero", "aria-label": "Result" },
        el("div", {},
          el("p", { class: "hero-kicker", text: `${capital(SPECIMEN_WORD[d.specimen])} sample` }),
          el("h2", { class: "hero-drug", text: "No single first choice" }),
          el("p", { class: "hero-line" }, "First choices were validated for urine only. Lowest chance of resistance here: ",
            ...best.flatMap((a, i) => [i ? ", " : "", el("b", { text: splitName(a.name)[0] }), ` (${a.chance_text})`]), ".")));
    }
    const [drug, brand] = splitName(r.name);
    const n = per100(r.chance_resistant);
    const within = r.chance_resistant <= (state.mode === "stewardship" ? 0.20 : 0.15) + 1e-9;
    const left = el("div", {},
      el("p", { class: "hero-kicker", text: "Suggested first choice" }),
      el("h2", { class: "hero-drug" }, drug, brand ? el("span", { class: "hero-brand", text: ` ${brand}` }) : null),
      el("p", { class: "hero-line" }, el("b", { text: `${r.chance_text}` }), " similar patients had a germ resistant to it."),
      el("p", { class: "tag", text: r.spectrum }),
      !within ? el("p", { class: "hero-warn", text: "Every usual option has a high chance of resistance, so this is the lowest one. Consider waiting for the lab or asking for specialist advice." }) : null,
      d.setting !== "Outpatient" ? el("p", { class: "hero-note", text: "Nitrofurantoin isn’t offered outside the clinic because it doesn’t treat kidney or blood infections." }) : null,
      r.lab_result ? el("span", { class: "lab-pill " + (r.lab_result === "Worked" ? "ok" : "bad"), text: r.lab_result === "Worked" ? "Lab result: it worked" : "Lab result: resistant" }) : null);
    const right = el("div", {}, dotGrid(r.chance_resistant), el("p", { class: "dots-caption", text: `${n === 0 ? "Under 1" : n} in 100 resistant` }));
    return el("section", { class: "hero", "aria-label": "Suggested first choice" }, left, right, foot);
  }

  function avoid(d) {
    const r = d.recommendation;
    if (!r.available) return null;
    const bad = r.options.filter((o) => o.chance_resistant >= 0.30).sort((a, b) => b.chance_resistant - a.chance_resistant);
    if (!bad.length) return null;
    return el("section", { class: "avoid", "aria-label": "Likely to fail" },
      el("h3", { text: "Likely to fail for this patient" }),
      el("ul", {}, bad.map((o) => el("li", {}, splitName(o.name)[0] + " ", el("span", { text: o.chance_text })))));
  }

  function row(a) {
    const id = a.antibiotic, isOpen = open.has(id);
    const [nm, brand] = splitName(a.name);
    const detailId = "d-" + id.replace(/[^a-z0-9]/gi, "");
    const reasons = a.reasons.length
      ? el("ul", { class: "reasons" }, a.reasons.map((x) => el("li", {},
          el("span", { class: "dir " + (x.direction === "raises" ? "up" : "down"), text: x.direction === "raises" ? "Raises" : "Lowers" }),
          el("span", { text: x.text }))))
      : el("p", { class: "hint", text: "Close to the usual rate for this sample. Nothing in the history stands out." });
    return el("li", { class: `row ${verdictClass(a.verdict)}${isOpen ? " open" : ""}` },
      el("button", { type: "button", class: "row-btn", "aria-expanded": String(isOpen), "aria-controls": detailId,
        onclick: () => { isOpen ? open.delete(id) : open.add(id); renderAnswer(lastResult); } },
        el("span", { class: "row-name" }, nm, brand ? el("small", { text: brand }) : null),
        el("span", { class: "bar", "aria-hidden": "true" }, (() => { const i = el("i"); i.style.width = Math.max(1, per100(a.chance_resistant)) + "%"; return i; })()),
        el("span", { class: "row-val" }, a.chance_text, el("small", { text: a.verdict_label }),
          a.lab_result ? el("span", { class: "row-lab " + (a.lab_result === "Worked" ? "ok" : "bad"), text: a.lab_result === "Worked" ? "Lab: worked" : "Lab: resistant" }) : null),
        svgIcon(ICON_CHEV, "chev")),
      isOpen ? el("div", { class: "row-detail", id: detailId },
        reasons,
        !a.commonly_tested ? el("p", { class: "hint", text: "Rarely tested on this kind of sample, so this estimate is less certain." }) : null) : null);
  }

  function list(d) {
    const byId = Object.fromEntries(d.antibiotics.map((a) => [a.antibiotic, a]));
    const r = d.recommendation;
    let focus, title;
    if (r.available) {
      focus = r.options.map((o) => byId[o.antibiotic]).filter(Boolean);
      title = "Usual urine options, narrowest first";
    } else {
      focus = d.antibiotics.filter((a) => a.commonly_tested).slice(0, 6);
      title = "Lowest chance of resistance";
    }
    const shown = new Set(focus.map((a) => a.antibiotic));
    const rest = d.antibiotics.filter((a) => !shown.has(a.antibiotic));
    const total = d.antibiotics.length;
    return el("section", { class: "list", "aria-label": title },
      el("div", { class: "list-head" },
        el("h3", { text: title }),
        el("div", { class: "legend", "aria-hidden": "true" },
          ...[["var(--works)", "Likely to work"], ["var(--unsure)", "Uncertain"], ["var(--resist)", "Likely resistant"]].map(([c, t]) =>
            el("span", {}, (() => { const i = el("i"); i.style.background = c; return i; })(), t)))),
      el("ol", {}, focus.map(row)),
      showRare && rest.length ? el("div", { class: "rest" },
        el("p", { class: "rest-head", text: "All other antibiotics, lowest risk first" }),
        el("ol", {}, rest.map(row))) : null,
      rest.length ? el("button", { type: "button", class: "btn btn-quiet btn-sm more-btn", "aria-expanded": String(showRare),
        onclick: () => { showRare = !showRare; renderAnswer(lastResult); },
        text: showRare ? "Show fewer" : `Show all ${total} antibiotics` }) : null);
  }

  function renderAnswer(d) {
    $("answerBody").replaceChildren(...[hero(d), avoid(d), list(d)].filter(Boolean));
    const r = d.recommendation, peek = $("peek");
    peek.replaceChildren(r.available
      ? el("span", {}, el("b", { text: splitName(r.name)[0] }), ` · ${r.chance_text}`)
      : el("span", { text: "See the antibiotics" }), svgIcon('<path d="M5 8l5 5 5-5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>'));
    watchHero();
  }
  let heroObs = null;
  function watchHero() {
    if (!("IntersectionObserver" in window)) return;
    heroObs?.disconnect();
    const h = document.querySelector(".hero"); if (!h) return;
    heroObs = new IntersectionObserver(([e]) => { $("peek").classList.toggle("show", !e.isIntersecting && e.boundingClientRect.top > 0); });
    heroObs.observe(h);
  }

  function renderError(e) {
    const down = !e.status;
    $("answerBody").replaceChildren(el("section", { class: "error", role: "alert" },
      el("h2", { text: down ? "Can’t reach the Empira service" : "This patient couldn’t be checked" }),
      down ? el("p", {}, "The app looks for it at ", el("code", { text: API }), ". Start it with ", el("code", { text: "app/run_demo.sh" }), " (or run_demo.bat), then try again.")
           : el("p", { text: e.message }),
      el("button", { type: "button", class: "btn btn-secondary", text: "Try again", onclick: () => boot() })));
  }

  const capital = (s) => s.charAt(0).toUpperCase() + s.slice(1);

  /* ---------------- past cases ---------------- */
  async function openCases() {
    const menu = $("casesMenu"), btn = $("casesBtn");
    const show = menu.hidden;
    menu.hidden = !show; btn.setAttribute("aria-expanded", String(show));
    if (!show) return;
    const holder = $("casesList");
    if (!holder.childElementCount) {
      holder.replaceChildren(el("p", { class: "menu-intro", text: "Loading cases…" }));
      try {
        const cases = await api("/api/cases");
        holder.replaceChildren(...cases.map((c) => el("button", { class: "menu-item", role: "menuitem", type: "button",
          onclick: () => { closeMenu(); loadCase(c); } },
          el("strong", { text: c.title }), el("span", { text: c.description.split(". ").slice(-1)[0].replace(/\.$/, "") }))));
      } catch (e) { holder.replaceChildren(el("p", { class: "menu-intro", text: "Past cases are unavailable right now." })); }
    }
    holder.querySelector("button")?.focus();
  }
  function closeMenu() { $("casesMenu").hidden = true; $("casesBtn").setAttribute("aria-expanded", "false"); }

  function loadCase(c) {
    caseId = c.case_id; open = new Set(); showRare = false;
    $("patientPanel").hidden = true; $("casePanel").hidden = false;
    $("caseTitle").textContent = c.title; $("caseMeta").textContent = "Loading…"; $("caseFacts").replaceChildren(); $("caseAgree").textContent = "";
    schedule(); window.scrollTo({ top: 0, behavior: "smooth" });
  }
  function renderCase(d) {
    $("caseMeta").textContent = `Past case from ${d.year} · only antibiotics the lab tested are shown`;
    $("caseFacts").replaceChildren(...d.patient.map((f) => el("li", { text: f })));
    $("caseAgree").textContent = d.agreement;
  }
  function leaveCase() {
    caseId = null; open = new Set();
    $("casePanel").hidden = true; $("patientPanel").hidden = false; schedule();
  }

  /* ---------------- wiring ---------------- */
  function wire() {
    $("ageSelect").addEventListener("change", (e) => { state.age = e.target.value; save(); schedule(); });
    $("nhToggle").addEventListener("change", (e) => { state.nh = e.target.checked; save(); schedule(); });
    $("exampleBtn").addEventListener("click", () => { state = { ...state, ...structuredClone(EXAMPLE) }; open = new Set(); changed(); });
    $("clearBtn").addEventListener("click", () => { state = { ...structuredClone(DEFAULTS), mode: state.mode }; open = new Set(); changed(); });
    $("backBtn").addEventListener("click", leaveCase);
    $("peek").addEventListener("click", () => document.querySelector(".hero")?.scrollIntoView({ behavior: "smooth", block: "start" }));
    $("casesBtn").addEventListener("click", openCases);
    document.addEventListener("click", (e) => { if (!e.target.closest(".menu-wrap")) closeMenu(); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("casesMenu").hidden) { closeMenu(); $("casesBtn").focus(); } });

    const input = $("historyInput");
    input.addEventListener("input", () => { active = 0; renderList(); });
    input.addEventListener("focus", renderList);
    input.addEventListener("blur", () => setTimeout(() => { $("historyList").hidden = true; input.setAttribute("aria-expanded", "false"); }, 120));
    input.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown") { e.preventDefault(); active = Math.min(active + 1, matches.length - 1); renderList(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); active = Math.max(active - 1, 0); renderList(); }
      else if (e.key === "Enter") { e.preventDefault(); if (matches.length) pick(Math.max(active, 0)); }
      else if (e.key === "Escape") { input.value = ""; renderList(); }
      else if (e.key === "Backspace" && !input.value && state.history.length) { state.history.pop(); changed(); }
    });
  }

  async function boot() {
    $("answer").setAttribute("aria-busy", "true");
    try {
      opts = await api("/api/options");
      buildIndex();
      state.history = state.history.filter((h) => labels[h.kind] && labels[h.kind][h.value]);
      renderForm();
      run();
    } catch (e) { renderError(e); $("answer").setAttribute("aria-busy", "false"); }
  }

  wire();
  boot();
})();

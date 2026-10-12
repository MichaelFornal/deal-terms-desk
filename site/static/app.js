"use strict";

// Every piece of API data is written with textContent or as an attribute; never as markup.
const STATES = {
  answered: "",
  not_stated: "Not stated in this agreement.",
  unfiled_schedule: "Stated in a schedule that was not filed with the agreement.",
  which_deal: "Which agreement? Name the company in your question, or pick one:",
  budget_cached: "The desk's model budget is used up for now (a daily or monthly cap), so this is a cached answer. Cached answers and Search still work.",
  budget_reached: "The desk's model budget is used up for now (a daily or monthly cap), so new questions can't be answered until it resets. Cached answers and Search still work.",
  busy: "The desk is busy. Try again shortly, or use Search.",
  error: "No answer this time. Try again, or use Search."
};

// which_deal with no candidates: no name in the question matched an agreement, so point at the picker instead.
const NO_CANDIDATES = "Which agreement? Name the company in your question, or choose it in the Agreement list above.";

const WAIT = "A new answer takes a while: the model reads the passages, then every quote is checked against the passage it cites. A cached answer comes back at once.";
// The citation gate drops any claim whose quote is not in its passage word for word, so this holds for every claim shown.
const CHECKED = "Every quote above was checked word for word against the passage it cites.";
const DEAL_HINT = "Type to filter the agreements, or leave it empty.";
const DEAL_UNKNOWN = "Pick an agreement from the list, or leave it empty.";
const SHOW_MORE = "Show the whole passage";
const SHOW_LESS = "Show less";

function el(tag, props, children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(props || {})) {
    if (key === "text") node.textContent = value;
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children || []) if (child) node.appendChild(child);
  return node;
}

function safeLink(url, text) {
  if (typeof url !== "string" || !url.startsWith("https://")) return el("span", { text: text });
  return el("a", { href: url, rel: "noopener noreferrer", text: text });
}

async function call(url, options) {
  let res;
  try { res = await fetch(url, options); } catch (e) { return { status: 0, body: null }; }
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { status: res.status, body: body };
}

function stateNote(state, data) {
  if (state === "which_deal" && !(data && Array.isArray(data.candidates) && data.candidates.length)) return NO_CANDIDATES;
  return Object.hasOwn(STATES, state) ? STATES[state] : STATES.error;
}

function failure(status) {
  if (status === 429) return "Too many requests from your address. Wait a little and try again.";
  if (status === 422) return "That question can't be asked as written: keep it short and not empty.";
  return "The desk did not answer. Try again, or use Search.";
}

function dealName(d) {
  return [d.target, d.parent].filter(Boolean).join(" – ") || d.id;
}

// The agreement picker is a text field over a datalist of every deal. Each label maps to the id of its deal and back; a
// label is matched trimmed, case-folded and with hyphens read as dashes, so a typed "Xilinx, Inc. - Advanced…" counts.
const deals = { byLabel: new Map(), byId: new Map() };

function labelKey(label) {
  return label.trim().toLowerCase().replace(/-/g, "–");
}

async function fillDeals() {
  const { status, body } = await call("/api/deals");
  if (status !== 200 || !Array.isArray(body)) return;
  const labels = body.map((d) => dealName(d) + (d.signed ? " (" + d.signed + ")" : ""));
  const counts = new Map();
  for (const label of labels) counts.set(labelKey(label), (counts.get(labelKey(label)) || 0) + 1);
  const list = document.getElementById("deal-options");
  body.forEach((d, i) => {
    // Two deals with the same name and date would share a label: the id tells them apart.
    const label = counts.get(labelKey(labels[i])) > 1 ? labels[i] + " · " + d.id : labels[i];
    deals.byLabel.set(labelKey(label), d.id);
    deals.byId.set(d.id, label);
    list.appendChild(el("option", { value: label }));
  });
}

// The deal the picker names: "" for none, null for text that names no agreement.
function pickedDeal() {
  const text = document.getElementById("deal").value.trim();
  if (!text) return "";
  const id = deals.byLabel.get(labelKey(text));
  return id === undefined ? null : id;
}

function dealNote(problem) {
  const note = document.getElementById("deal-note");
  note.textContent = problem ? DEAL_UNKNOWN : DEAL_HINT;
  note.classList.toggle("problem", problem);
  document.getElementById("deal").setAttribute("aria-invalid", problem ? "true" : "false");
}

function setDeal(id) {
  document.getElementById("deal").value = id ? deals.byId.get(id) || "" : "";
  dealNote(false);
}

function refusePick() {
  dealNote(true);
  document.getElementById("deal").focus();
}

const calm = window.matchMedia("(prefers-reduced-motion: reduce)");

// Bring a reply into view when its top is off screen or low on it; leave the page alone when it is already in view.
function reveal(node) {
  const top = node.getBoundingClientRect().top;
  if (top < 0 || top > window.innerHeight * 0.66) node.scrollIntoView({ block: "start", behavior: calm.matches ? "auto" : "smooth" });
}

function reading() {
  return el("div", { class: "reading" }, [
    el("p", { class: "label" }, [el("span", { text: "Reading the agreement" }), el("span", { class: "dots", "aria-hidden": "true", text: "..." })]),
    el("p", { class: "wait", text: WAIT })
  ]);
}

function dealHead(d) {
  return el("p", { class: "deal-head" }, [
    el("span", { class: "name", text: dealName(d) }),
    el("span", { class: "when" }, [el("span", { text: d.signed ? "Signed " + d.signed + " · " : "" }), safeLink(d.link, "source text ↗")])
  ]);
}

function renderAnswer(box, data) {
  box.replaceChildren();
  if (data.deal) box.appendChild(dealHead(data.deal));
  const known = Object.hasOwn(STATES, data.state);
  const note = stateNote(data.state, data);
  if (note) box.appendChild(el("p", { class: "state state-" + (known ? data.state : "error"), text: note }));
  // A cached reply under an exhausted budget carries the real outcome in cached_state: show it too.
  const outcome = data.state === "budget_cached" && data.cached_state ? data.cached_state : data.state;
  if (outcome !== data.state) {
    const cachedNote = stateNote(outcome, data);
    if (cachedNote) box.appendChild(el("p", { class: "state state-" + (Object.hasOwn(STATES, outcome) ? outcome : "error"), text: cachedNote }));
  }
  if (outcome === "which_deal" && Array.isArray(data.candidates) && data.candidates.length) {
    const list = el("ul", { class: "candidates" });
    for (const c of data.candidates) {
      const pick = el("button", { type: "button", class: "linkish", text: c.name });
      pick.addEventListener("click", () => { setDeal(c.id); ask(null, c.id); });
      list.appendChild(el("li", {}, [pick]));
    }
    box.appendChild(list);
  }
  if (data.amended) box.appendChild(el("p", { class: "meta amended", text: "This answer uses amended text." }));
  // The agreement is named once, above; a claim names its own source only when that differs.
  const home = data.deal ? data.deal.link : null;
  const claims = el("ol", { class: "claims" });
  for (const c of data.claims || []) {
    const cite = el("p", { class: "cite" }, [el("span", { text: c.section_path ? "§ " + c.section_path : "" })]);
    if (c.link !== home) {
      cite.appendChild(el("span", { text: " · " }));
      cite.appendChild(safeLink(c.link, c.agreement));
    }
    if (c.amendment_no) {
      cite.appendChild(el("span", { class: "amended", text: " · uses amended text (Amendment No. " + c.amendment_no + ") " }));
      cite.appendChild(safeLink(c.amendment_link, "amendment filing"));
    }
    claims.appendChild(el("li", { class: "claim" }, [el("p", { class: "claim-text", text: c.text }), el("blockquote", { class: "quote", text: c.quote }), cite]));
  }
  if ((data.claims || []).length) {
    box.appendChild(claims);
    box.appendChild(el("p", { class: "checked", text: CHECKED }));
  }
  if (data.served_from === "cache") box.appendChild(el("p", { class: "meta", text: "Served from the answer cache." }));
}

let latest = 0;

function busy(form, on) {
  const button = form.querySelector("button[type=submit]");
  if (button) button.disabled = on;
}

async function ask(event, dealId) {
  if (event) event.preventDefault();
  const form = document.getElementById("ask-form");
  if (form.querySelector("button[type=submit]").disabled) return;
  const deal = dealId || pickedDeal();
  if (deal === null) { refusePick(); return; }
  const box = document.getElementById("answer");
  const question = document.getElementById("question").value;
  const mine = ++latest;
  busy(form, true);
  box.replaceChildren(reading());
  reveal(box);
  const { status, body } = await call("/api/ask", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: question, deal: deal || null })
  });
  busy(form, false);
  if (mine !== latest) return;
  if (status !== 200 || !body) { box.replaceChildren(el("p", { class: "state state-error", text: failure(status) })); reveal(box); return; }
  renderAnswer(box, body);
  reveal(box);
}

// Enter asks; Shift+Enter starts a new line. Keys pressed while an input method is composing (Japanese, Chinese…)
// belong to it. requestSubmit runs the checks of the form itself, so an empty question is refused as before.
function submitOnEnter(field, form) {
  field.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
}

function stage(name, s) {
  return s ? name + " rank " + s.rank + " (" + Number(s.score).toFixed(3) + ")" : name + ": not found";
}

function searchedWhere(data, hits) {
  const id = data.scope && data.scope.deal;
  if (!id) return "across all agreements";
  const hit = hits.find((h) => h.deal && h.deal.id === id);
  return "inside " + (hit ? dealName(hit.deal) : deals.byId.get(id) || id);
}

function renderSearch(box, data) {
  box.replaceChildren();
  const hits = data.hits || [];
  if (!hits.length) { box.appendChild(el("p", { class: "state", text: "No passages matched." })); return; }
  box.appendChild(el("p", { class: "label", text: (hits.length === 1 ? "One passage" : hits.length + " passages") + ", " + searchedWhere(data, hits) }));
  const candidates = data.scope && !data.scope.deal && Array.isArray(data.scope.candidates) ? data.scope.candidates : [];
  if (candidates.length) {
    // R7 never guesses between deals: an ambiguous name means every agreement was searched.
    box.appendChild(el("p", { class: "meta", text: "The name in the search matches several agreements (" + candidates.map((c) => c.name).join("; ") + "), so every agreement was searched. Choose one in the Agreement field to search inside it." }));
  }
  const list = el("ol", { class: "hits" });
  for (const h of hits) {
    // Blank lines around a passage would pass for hidden text and earn it a toggle; the first line keeps its indent.
    const passage = el("pre", { class: "passage", text: h.text.replace(/^\s*\n/, "").replace(/\s+$/, "") });
    const more = el("button", { type: "button", class: "linkish more", "aria-expanded": "false", text: SHOW_MORE });
    more.hidden = true;
    more.addEventListener("click", () => {
      const open = passage.classList.toggle("open");
      more.setAttribute("aria-expanded", open ? "true" : "false");
      more.textContent = open ? SHOW_LESS : SHOW_MORE;
    });
    list.appendChild(el("li", { class: "hit" }, [
      el("p", { class: "hit-head" }, [safeLink(h.link, h.deal ? dealName(h.deal) : "source text"), el("span", { text: " · § " + h.section_path })]),
      passage,
      more,
      el("p", { class: "meta", text: "Fused score " + Number(h.score).toFixed(4) + " · " + stage("BM25", h.stages.bm25) + " · " + stage("dense", h.stages.dense) }),
      h.definitions && h.definitions.length ? el("p", { class: "meta", text: "Definitions used: " + h.definitions.join(", ") }) : null
    ]));
  }
  box.appendChild(list);
  // Measured once the passages are on the page: only a passage that runs past its eight lines gets the toggle.
  for (const p of list.querySelectorAll(".passage")) {
    if (p.scrollHeight > p.clientHeight + 1) {
      p.classList.add("clamped");
      p.nextElementSibling.hidden = false;
    }
  }
}

async function search(event) {
  if (event) event.preventDefault();
  const form = document.getElementById("search-form");
  if (form.querySelector("button[type=submit]").disabled) return;
  const deal = pickedDeal();
  if (deal === null) { refusePick(); return; }
  const box = document.getElementById("results");
  const mine = ++latest;
  busy(form, true);
  const params = new URLSearchParams({ q: document.getElementById("q").value });
  if (deal) params.set("deal", deal);
  box.replaceChildren(el("p", { class: "meta", text: "Searching…" }));
  const { status, body } = await call("/api/search?" + params.toString());
  busy(form, false);
  if (mine !== latest) return;
  if (status !== 200 || !body) { box.replaceChildren(el("p", { class: "state state-error", text: failure(status) })); return; }
  renderSearch(box, body);
  reveal(box);
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  const deal = document.getElementById("deal");
  if (deal) {
    fillDeals();
    deal.addEventListener("input", () => dealNote(false));
  }
  if (page === "ask") {
    const form = document.getElementById("ask-form");
    form.addEventListener("submit", ask);
    submitOnEnter(document.getElementById("question"), form);
    // An example is asked with no agreement chosen: that is how warm cached it, so it costs nothing.
    for (const button of document.querySelectorAll("button.example")) {
      button.addEventListener("click", () => {
        document.getElementById("question").value = button.dataset.question;
        setDeal(null);
        ask();
      });
    }
  }
  if (page === "search") document.getElementById("search-form").addEventListener("submit", search);
});

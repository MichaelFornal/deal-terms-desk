"use strict";

// Every piece of API data is written with textContent or as an attribute; never as markup.
const STATES = {
  answered: "",
  not_stated: "Not stated in this agreement.",
  unfiled_schedule: "Stated in a schedule that was not filed with the agreement.",
  which_deal: "Which agreement? Name the company in your question, or pick one:",
  budget_cached: "Monthly budget reached, showing a cached answer.",
  budget_reached: "Monthly budget reached. New questions wait until next month; Search still works.",
  busy: "The desk is busy. Try again shortly, or use Search.",
  error: "No answer this time. Try again, or use Search."
};

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
  const res = await fetch(url, options);
  let body = null;
  try { body = await res.json(); } catch (e) { body = null; }
  return { status: res.status, body: body };
}

function failure(status) {
  if (status === 429) return "Too many requests from your address. Wait a little and try again.";
  if (status === 422) return "That question can't be asked as written: keep it short and not empty.";
  return "The desk did not answer. Try again, or use Search.";
}

function dealName(d) {
  return [d.target, d.parent].filter(Boolean).join(" and ") || d.id;
}

async function fillDeals(select) {
  const { status, body } = await call("/api/deals");
  if (status !== 200 || !Array.isArray(body)) return;
  for (const d of body) {
    select.appendChild(el("option", { value: d.id, text: dealName(d) + (d.signed ? " (" + d.signed + ")" : "") }));
  }
}

function renderAnswer(box, data) {
  box.replaceChildren();
  if (data.deal) {
    box.appendChild(el("p", { class: "deal" }, [el("span", { text: "Agreement: " }), safeLink(data.deal.link, dealName(data.deal))]));
  }
  const note = STATES[data.state];
  if (note) box.appendChild(el("p", { class: "state state-" + data.state, text: note }));
  if (data.state === "which_deal") {
    const list = el("ul", { class: "candidates" });
    for (const c of data.candidates || []) {
      const pick = el("button", { type: "button", text: c.name });
      pick.addEventListener("click", () => { document.getElementById("deal").value = c.id; ask(); });
      list.appendChild(el("li", {}, [pick]));
    }
    box.appendChild(list);
  }
  if (data.amended) box.appendChild(el("p", { class: "amended", text: "This answer uses amended text." }));
  const claims = el("ol", { class: "claims" });
  for (const c of data.claims || []) {
    const source = el("p", { class: "source" }, [safeLink(c.link, c.agreement), el("span", { text: " · " + c.section_path })]);
    if (c.amendment_no) {
      source.appendChild(el("span", { class: "amended", text: " · uses amended text (Amendment No. " + c.amendment_no + ") " }));
      source.appendChild(safeLink(c.amendment_link, "amendment filing"));
    }
    claims.appendChild(el("li", { class: "claim" }, [el("p", { text: c.text }), el("blockquote", { text: c.quote }), source]));
  }
  if ((data.claims || []).length) box.appendChild(claims);
  if (data.served_from === "cache") box.appendChild(el("p", { class: "meta", text: "Served from the answer cache." }));
}

async function ask(event) {
  if (event) event.preventDefault();
  const box = document.getElementById("answer");
  const question = document.getElementById("question").value;
  const deal = document.getElementById("deal").value || null;
  box.replaceChildren(el("p", { class: "meta", text: "Reading the agreement…" }));
  const { status, body } = await call("/api/ask", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ question: question, deal: deal })
  });
  if (status !== 200 || !body) { box.replaceChildren(el("p", { class: "state state-error", text: failure(status) })); return; }
  renderAnswer(box, body);
}

async function fillExamples(box) {
  const { status, body } = await call("/examples.json");
  if (status !== 200 || !Array.isArray(body)) return;
  for (const ex of body) {
    const chip = el("button", { type: "button", class: "chip", text: ex.question });
    chip.addEventListener("click", () => {
      document.getElementById("question").value = ex.question;
      document.getElementById("deal").value = "";
      ask();
    });
    box.appendChild(chip);
  }
}

function stage(name, s) {
  return s ? name + " rank " + s.rank + " (" + Number(s.score).toFixed(3) + ")" : name + ": not found";
}

function renderSearch(box, data) {
  box.replaceChildren();
  const hits = data.hits || [];
  if (!hits.length) { box.appendChild(el("p", { class: "state", text: "No passages matched." })); return; }
  const list = el("ol", { class: "hits" });
  for (const h of hits) {
    list.appendChild(el("li", { class: "hit" }, [
      el("p", { class: "source" }, [safeLink(h.link, h.deal ? dealName(h.deal) : ""), el("span", { text: " · " + h.section_path })]),
      el("pre", { class: "passage", text: h.text }),
      el("p", { class: "meta", text: "Fused score " + Number(h.score).toFixed(4) + " · " + stage("BM25", h.stages.bm25) + " · " + stage("dense", h.stages.dense) }),
      h.definitions && h.definitions.length ? el("p", { class: "meta", text: "Definitions used: " + h.definitions.join(", ") }) : null
    ]));
  }
  box.appendChild(list);
}

async function search(event) {
  if (event) event.preventDefault();
  const box = document.getElementById("results");
  const params = new URLSearchParams({ q: document.getElementById("q").value });
  const deal = document.getElementById("deal").value;
  if (deal) params.set("deal", deal);
  box.replaceChildren(el("p", { class: "meta", text: "Searching…" }));
  const { status, body } = await call("/api/search?" + params.toString());
  if (status !== 200 || !body) { box.replaceChildren(el("p", { class: "state state-error", text: failure(status) })); return; }
  renderSearch(box, body);
}

document.addEventListener("DOMContentLoaded", () => {
  const page = document.body.dataset.page;
  const deal = document.getElementById("deal");
  if (deal) fillDeals(deal);
  if (page === "ask") {
    document.getElementById("ask-form").addEventListener("submit", ask);
    fillExamples(document.getElementById("examples"));
  }
  if (page === "search") document.getElementById("search-form").addEventListener("submit", search);
});

# M5 — Live service, cost controls, site, deployment (design spec)

Decisions made in conversation on 2026-10-05, when Michael approved the M5/M6 roadmap. Michael
reviews this file. `superpowers:writing-plans` then turns it into
`docs/superpowers/plans/2026-10-05-m5-live-service.md`. No product code is written before that plan
is approved.

## Context

M0–M4 built and measured everything offline:
- retrieval R1–R7, with R7n (no reranker) frozen as the answer path;
- answering with the word-for-word citation gate;
- answer, abstention and citation evals.

All model calls so far went through `claude -p`. Nothing a visitor can touch exists yet. M5 (PRD §9)
delivers the service, cost controls, deployment to `deals.forn.al` and the four pages. It confirms
the model and its price, and checks the index against the server.

Exit condition: a visitor can ask a question and get a cited answer, and the cap trips in a test.
M6 (README and launch post by Michael, final facts check, public) is a separate later cycle.

### Decisions made in conversation

| Topic | Decision |
|---|---|
| Live model | `claude-haiku-4-5-20251001`, the model M4's published answer numbers describe. Sonnet 5.5 was considered (better on the tune split, close in cost per answer) and declined |
| Host | Hetzner 4 GB shared-vCPU VPS, EU (CAX11, arm64: same architecture as the machine that built the vectors). Supersedes PRD §6's 1 GB machine and retires the §10 memory risk |
| Site | Static HTML rendered in Python from `facts.json` (the `facts/report_*.py` pattern), with vanilla JS for Ask and Search. Caddy serves the pages and proxies `/api/*` to uvicorn on the same box: one origin, no CORS |
| GitHub | Private repo during M5 so CI runs; public at M6 after an audit |
| History | Commit metadata never carries the SEC contact (rewritten to the GitHub noreply address on 2026-10-05, before any push) |
| Live retrieval | R7n, with no reranker model loaded |
| Budget | $10/month all in. Model cap = $10 − hosting, plus a daily ceiling. Two Anthropic Console workspaces: `dtd-live` (server only, spend limit just above the cap) and `dtd-dev` (calibration and smoke) |

## 1. Components

### Live answer path (`retrieval/`, `answer/`)
- **`scope_question(resolver, question, contract_id=None) -> (Scope, stripped)`** in `retrieval/scope.py` is the one resolve-and-strip.
  - `Ladder.run("R7n")` uses it, and must honour a passed `contract_id`; today it re-resolves.
  - `Answerer.prepare` uses it too, and keeps the `which_deal` state.
- **The Answerer takes its rung from `load_answer_path()`** and validates it against `ANSWER_RUNGS`. This ends the hard-coded R6n.
- **Per-stage scores for Search:** `Ladder.run` records each leg's rank and raw score (BM25, dense) in `Retrieved.stages`. `rrf` and the final order are untouched.
- **Parity rule:** the refactor must leave every M4 report-split `prompt_sha` unchanged.

### Live bundle (`pipeline/bundle.py`, `retrieval/live.py`)
- **`dtd bundle` builds `data/live/live.db`:** one file that ships to the server (PRD §6).
  - It is `VACUUM INTO` from `deals.db`.
  - It keeps `passages_fts`, because the resolver's common-word rule counts stemmed tokens from it.
  - It drops `terms`.
  - It adds `texts`, `amendment_texts`, `links` (EDGAR, MAUD and amendment URLs) and `meta` (source and config hashes).
  - Built through a temp file, hashed, then renamed; `bundle.json` records the sha.
- **`build_live_ladder(bundle)`:**
  - opens read-only (`mode=ro&immutable=1`) with `check_same_thread=False`;
  - passes `reranker=None`;
  - reads texts from the bundle;
  - writes no files.
- **Parity:** R7n over the bundle equals R7n over `deals.db` on about 200 M4 questions.
- **T-human recall over the bundle:** R6n recall@5 is re-measured on the bundle's 88 MAUD agreements, because the M4 evals ran on `maud.db`.

### API runner (`answer/api_runner.py`)
- **`run_api(prompt, model, *, max_tokens, client=None)`** keeps the `run_claude` contract (`{"result", "usage"}`) plus `stop_reason`.
  - Usage nulls become 0.
  - Haiku extended thinking (budget from config; decided 2026-10-06 after calibration showed the no-thinking API path scoring below the CLI evaluation runs), `max_retries=0`, 90 s timeout.
- **Typed failures:** rate_limited, overloaded, timeout, connection, bad_request, billing, refusal.
  - A truncated reply is a parse error, never an answer.
  - Every failure after a billed response carries its usage.
- **`dtd m5 calibrate --n 40`** runs tune-split items through the API and compares them with the M4 CLI answers for the same items: tokens, truncations, cost, gate pass rate, state agreement, T-human accuracy. It is ledgered and resumable.

### Cost controls (`service/`)
- **`service/prices.json`:** per-MTok prices with the source URL and the date checked on the pricing page.
- **`Budget` (SQLite, WAL):**
  - `reserve` under one lock, against both the month cap (UTC calendar month) and the daily ceiling, at worst case (prompt chars/3 tokens in, `max_tokens` out);
  - `settle` at actual usage, and `release` when nothing was billed;
  - crash leftovers settle at worst case on startup.
- **`AnswerCache`:**
  - keyed by (model, `prompt_sha`), so any change to the bundle, lexicon, settings or template misses;
  - stores answered, not_stated and unfiled_schedule only.
- **`dtd warm`** pre-answers the Ask page's example questions on the server, running as the service user.
- **Limits:**
  - per-client token buckets, with IPv6 bucketed by /64;
  - a question length cap;
  - a fail-fast `/ask` concurrency slot (a `busy` state, never a queue);
  - an hourly global limit on fresh calls;
  - the deal id must exist.
  - Client IP is taken only from uvicorn's proxy handling, with 127.0.0.1 as the trusted proxy.

### Service (`service/app.py`)
- **`create_app()`** is a zero-argument factory (`uvicorn --factory`). It loads the bundle, forces the embedder to load (2 threads), and loads the lexicon and resolver. Endpoints are sync; retrieval runs under one lock and the model call outside it.
- **Endpoints:**
  - `GET /api/health` → git, bundle and facts shas, model, budget state;
  - `GET /api/deals`;
  - `GET /api/search` → no model call, never capped, per-stage scores;
  - `POST /api/ask`.
- **`/ask` order:** validate → prepare (which_deal is free) → cache → reserve → call → settle → cache.
- **States:**
  - answered, not_stated, unfiled_schedule and which_deal, as before;
  - `budget_cached` (reserved in the M4 spec);
  - new: `budget_reached`, `busy` and `error`.
  - A claim that quotes amended text carries the amendment number and a link to the amendment's filing.
- **Privacy:** there are no access logs. One JSON line per request (route, state, ms, tokens, cache hit), with no IP and no question text.

### Site (`site/`, renderer `facts/site.py`)
- **Pages:** Ask, Search, Results and Method. Every page carries "This is not legal advice."
  - `site/` is not a Python package, so it can't shadow stdlib `site`.
  - `site/dist/` is generated and gitignored.
- **Results:**
  - the ladders on both tiers with CIs, plus the bundle recall;
  - per question family;
  - tier agreement;
  - abstention with false-answer rate;
  - citation accuracy (gate and refute);
  - the failure breakdown across all six §5.3 classes, with superseded text stated as not classified;
  - latency and tokens per rung, plus server latency;
  - the LegalBench-RAG comparison;
  - cost.
- **Method:**
  - the corpus;
  - human vs machine labels;
  - what is not new;
  - the §10 limits, plus three new ones: answers were measured through `claude -p` and bridged by calibration; T-human was measured on `maud.db`; ladder latencies are from the development machine;
  - MAUD attribution;
  - the SEC public-information statement;
  - model and price;
  - what is logged.
- **Labels:** `facts/labels.py` maps fact keys to "machine-built" or "human-labelled (MAUD)". A test cross-checks it against the labels the existing reports already print.
- **Safety:** `app.js` writes API data with `textContent` only.

### Deployment (`deploy/`)
- **Caddyfile:**
  - automatic TLS;
  - static pages plus `/api/*` → `127.0.0.1:8000`;
  - CSP `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`;
  - HSTS, nosniff, Referrer-Policy;
  - no access log.
- **systemd unit:**
  - user `dtd`, runs `.venv/bin/uvicorn --factory … --workers 1 --no-access-log --forwarded-allow-ips 127.0.0.1`;
  - env file `/etc/dtd/env` (0600);
  - `MemoryMax=2G`, `ProtectSystem=strict`;
  - state in `/var/lib/dtd`.
- **`provision.sh`** (idempotent):
  - updates and unattended-upgrades;
  - ufw 22/80/443 and key-only SSH;
  - Caddy and uv, using the system Python 3.12;
  - a journald size cap.
- **`push.sh`:**
  - refuses a dirty tree;
  - runs tests, `dtd facts --check`, `dtd site` and `dtd bundle`;
  - ships `git archive HEAD`, the site and the bundle (only when its sha changed) into a release directory;
  - runs `uv sync --frozen` and swaps the `current` symlink;
  - polls `/api/health` until all shas match;
  - re-warms when needed.
- **`deploy/hosting.json`:** the published price, exchange rate and date. It sets the model cap and is updated from the first invoice.
- **`deploy/smoke.py`:** checks against the live URL.

## 2. Calibration and the stop rule

Calibration bills the `dtd-dev` workspace; Michael approves the estimate first (under $1 at Haiku prices).
- **`max_tokens`** is set from the observed p99 output plus a margin.
- **The worst-case estimator** must be ≥ actual on every calibrated item.
- **Stop rule:** n = 40 detects only large differences. If API-vs-CLI state agreement falls below 0.8, or T-human accuracy differs by more than 0.15, stop before deploying and bring the options to Michael:
  - a priced API rerun of the report split; or
  - accept and label the difference on the Method page.
- **Cost lever:** if answers per month under the cap are too few, cap definitions at runtime. That changes the prompt, so the report-split answers are re-run through `claude -p` ($0).

## 3. Running, resume, failures

- **Kill-tested stages:**
  - `dtd bundle`: kill mid-build leaves no `live.db`, rerun finishes;
  - `dtd m5 calibrate`: ledger resume, unique keys;
  - the service: `systemctl kill -s KILL` during a burst, then restart with the ledger reconciled.
- **Release gates:**
  - the default suite makes no network or model calls;
  - `dtd facts --check` needs `data/`, so it runs in `push.sh`;
  - CI runs the committed-render checks and `dtd site`.

## 4. Testing, facts, report

- **Tests:** each component above has unit tests with fakes (`FakeEmbedder`, a counting runner, a fake API client, a fake clock, a tiny fixture bundle).
  - **The cap trips in a test:** drive spend to the cap; then an uncached `/ask` is `budget_reached`, a cached one is `budget_cached`, and the runner is never called.
  - 50 threads never overshoot either cap.
  - Crash reconciliation is covered.
  - Every state is reachable through `TestClient`.
- **Facts:** `facts/m5.py` is gated on its inputs:
  - bundle bytes and sha;
  - prices and date checked;
  - API tokens in/out;
  - cost per answer;
  - caps;
  - answers per month under the cap;
  - API-vs-CLI parity;
  - bundle recall;
  - server RSS and latency;
  - server query-embedding parity;
  - the cap-trip result;
  - live-path latency from M4's outputs.
  - Wall-clock values are unstable for `--check`.
- **Report:** `facts/report_m5.py` writes `docs/m5/REPORT.md`, with the M4 report's tests (digit scan, committed render).
- **Also closed in M5:**
  - the `test_cli.py` fixture must not be able to overwrite real reports;
  - `facts.json` is written atomically;
  - `--check` flags stale keys;
  - M1 gets a digit scan and M0 a committed-render test.

## Order of work

1. Facts-tool gaps and test hazards; `service` package registered.
2. One live answer path, with prompt-sha parity.
3. Per-stage scores.
4. Live bundle and live ladder, with both parities and bundle recall.
5. API runner and `dtd m5 calibrate`.
6. Prices, budget.
7. Cache and warm.
8. Limits.
9. Service.
10. Site.
11. M5 facts, report, `dtd m5 measure`.
12. Deploy files.
13. Calibration run (approved spend).
14. Provision, push, warm, measure.
15. Smoke, cap trip and kill test on the box.
16. Final facts and report, PRD outcome note, final review, merge.

## Verification

- `uv run pytest` is green locally and in GitHub CI from a clean clone.
- `uv run pytest -m model` makes one real API call on `dtd-dev`.
- Prompt-sha parity holds on the M4 report split, and R7n bundle parity on about 200 questions. Server embedding parity is recorded in facts.
- `deploy/smoke.py https://deals.forn.al` passes:
  - health shas;
  - search with stages;
  - cached and fresh `/ask`, with a sec.gov link;
  - which_deal;
  - 422 and 429;
  - spoofed `X-Forwarded-For` ignored;
  - disclaimer and CSP on every page.
- The cap trips on the real box with a tiny cap: `budget_reached` and `budget_cached`, ledger unchanged.
- `dtd facts --check`, `dtd report` and `dtd site` are clean.
- Exit: a visitor asks a question at `deals.forn.al` and gets a cited answer, and the cap trips in a test.

# Deal Terms Desk — spec

Written 2026-09-30. Design approved in conversation the same day; this file is the record.
How the idea was chosen (two brainstorm rounds, 118 candidate shapes, 18 checked against live
sources) is in the private notes `jb/docs/RAG-PROJECT-BRAINSTORM-2026-09-30.md`.

## 1. Purpose and decisions

**Primary purpose: a hiring showcase.** A hiring manager at a seed–Series B AI startup should
conclude "he can make RAG measurably good", and RAG should be on the resume honestly. It is a
second showcase alongside Agent Census, not a replacement.

**The product in one sentence:** ask what a signed acquisition agreement really says about
employee stock, break-up fees or what happens to employees' pay and benefits, and get the clause quoted
from the contract.

| Decision | Value |
|---|---|
| Subject | Merger agreements: MAUD's 152 lawyer-labelled agreements plus technology-target agreements filed as 8-K EX-2.1 exhibits on EDGAR |
| Centerpiece | A real RAG system: messy contracts in, grounded answers with quoted, cited clauses out. Evals sit behind it and are published |
| Lead questions | (1) treatment of employee equity awards, (2) termination ("break-up") fee size and triggers, (3) employees' pay and benefits after the deal (the post-closing compensation and benefits covenant). Changed 2026-10-02 from earn-outs and other contingent consideration; see §9 |
| Eval anchor | Two tiers, labelled differently: human-labelled (MAUD) and machine-built (lead questions on tech deals) |
| Demo | Fully live: any question gets retrieval plus a generated, cited answer |
| Budget | **$10 per month hard cap, all in**, for the live demo (hosting plus model calls). Everything offline (ingestion, indexing, evals) costs $0: Claude Max plan via `claude -p`, local open-source models, free data |
| Architecture | One small always-on server; the code that serves visitors is the code the evals measure |
| Hosting | `deals.forn.al` (own subdomain; forn.al's CSP forbids JavaScript) |
| Repo | `~/Documents/deal-terms-desk`, public under `github.com/MichaelFornal` |
| SEC contact | Michael's Gmail, read from the `SEC_CONTACT` environment variable. Never written into the repo |
| Validation | No hand-labelled gold set by Michael. Human labels come from MAUD; everything else is machine-run and labelled as such |
| Time | No cap; smaller is better when equally convincing |
| Not in v1 | Mutation-testing the eval suite; agreements outside technology targets; non-US filings; user accounts; any legal-advice framing |

**What is and is not new.** Retrieval over MAUD is a published benchmark (LegalBench-RAG). This
project does not claim the task. It claims a working, measured, deployed system on top of that
benchmark, plus three question families the benchmark's labels do not cover. The write-up says
so and compares against the published baselines.

## 2. Corpus

### 2.1 Labelled half: MAUD

- Source: `theatticusproject/maud` on Hugging Face, CC BY 4.0. Attribution in the README and on
  the Method page.
- As reported by verification on 2026-09-30 (from the Hugging Face API, not recounted here): 152
  agreements, 47,457 annotations, 92 question types. M1 recounts these with a named query.
- **Correction, measured in M1:** the three label CSVs hold 39,231 label rows, not 47,457
  (`maud_label_rows_all` in `facts/queries.py`). The 152 agreements and 92 question types
  recount as stated. Use the facts value, not either figure here, wherever a count is printed.
- **Correction, measured while planning M1:** at revision `37d5c3b9` only 100 of the 152
  agreements named in the label files have a contract text file; the other 52 return 404. The
  labelled half is therefore 100 agreements unless the missing texts are found elsewhere.
- One agreement was read during verification: 113,471 words, 199 inline defined terms, no
  standalone definitions article, no redaction markers, 46 references to an unfiled disclosure
  letter. One document is not a rate; M1 measures the distribution.
- MAUD has no question about equity awards, fee amounts, employees' post-closing pay and benefits, or
  earn-outs.

### 2.2 Tech half: EDGAR EX-2.1

Nothing about this half has been measured. sec.gov blocked the development machine on
2026-09-30, so every number here is an M0 output, and M0 is a gate (§9).

- **Selection rule (by rule, not hand-picked):** an exhibit of type EX-2.1 attached to an 8-K,
  whose text is an agreement and plan of merger, signed on or after 2015-01-01, where the
  **target** is an EDGAR registrant with SIC code in 3570–3579, 3661–3679 or 7370–7379.
- **Enumeration:** EDGAR full-text search, partitioned by date window so no window exceeds the
  10,000-result cap. The target is read from the agreement preamble and resolved to a CIK
  through `data.sec.gov/submissions`.
- **Licence:** sec.gov states its content "is considered public information and may be copied
  or further distributed by users of the web site without the SEC's permission". The repo ships
  accession numbers and the fetch script, not the documents. The live demo quotes clauses and
  links to EDGAR.
- **Access rules (hard):** one process, never parallel; at most 2 requests per second; a
  persistent ledger so a rerun fetches nothing twice; User-Agent carries `SEC_CONTACT`; on a 403
  the fetcher stops and waits, it does not retry or change identity.

### 2.3 What ingestion must solve

| Problem | Handling |
|---|---|
| Both parties file the same agreement | A deal identity (target CIK, acquirer name, signing date). One canonical copy per deal; other copies are recorded, not indexed |
| Amendments ("Amendment No. 1 to Agreement and Plan of Merger") | Linked to the deal. Passages carry `superseded_by`; retrieval prefers current text and an answer that uses amended text says so |
| Defined terms scattered inline | A per-agreement map of term → definition passage, extracted deterministically from the quoted-term pattern, with an LLM pass only for terms the pattern misses |
| Section structure | Passages are cut on article/section boundaries and keep their section path (e.g. `Article II › 2.3 › (b)`). Oversized sections are split at sub-clause boundaries |
| Unfiled schedules | References to a disclosure letter or schedule are tagged, so the system can answer "this is in a schedule that was not filed" |
| HTML, plain-text and paginated exhibits | One normaliser to plain text with page-break and running-header removal; the original offsets are kept so a quote can be located in the source |

## 3. Product surfaces

1. **Ask.** A question box and a deal picker (optional). The answer is two to four sentences.
   Each claim is followed by the quoted clause, the agreement name, the section path and a link
   to the filing. States it can show: answered; "not stated in this agreement"; "stated in a
   schedule that was not filed"; "answer uses amended text (Amendment No. N)"; "monthly budget
   reached, showing a cached answer".
2. **Search.** The same box with generation off: ranked passages with their scores per retrieval
   stage. No model call, never capped.
3. **Results.** The retrieval ladder table with confidence intervals, results per question
   family, the two-tier agreement check, abstention and citation accuracy, the failure
   breakdown, and latency and tokens per rung.
4. **Method.** How the corpus was built, which labels are human and which are machine-built,
   what is not new, stated limits (§10).

Every page carries "This is not legal advice."

## 4. Retrieval and answering

### 4.1 The ladder

Each rung adds to the one before and is measured on the same question sets.

| Rung | What it adds |
|---|---|
| R1 | BM25 (SQLite FTS5) over section-aware passages |
| R2 | Dense only: a local open-source embedding model (default candidate `bge-small-en-v1.5`), vectors in `sqlite-vec` |
| R3 | Hybrid: R1 + R2 by reciprocal rank fusion |
| R4 | R3 + cross-encoder reranker (default candidate `bge-reranker-base`), in-process |
| R5 | R4 + query rewriting from a lexicon built offline: lay terms mapped to contract vocabulary ("stock options" → "Company Equity Awards", "Company Options"). Applied deterministically at query time, so it costs no model call |
| R6 | R5 + defined-term expansion: each passage is indexed and shown with the definitions it depends on |
| R7 | R6 + deal scoping: a company name in the question is resolved to a deal and retrieval is filtered to it |

Separate comparisons, not rungs: section-aware versus fixed-size chunking (on R3); the lexicon
rewrite versus a live LLM rewrite (offline only, to show what the cheaper choice costs).

A rung that does not help is reported as not helping and may be left out of the live path.

### 4.2 Answering

- Input to the model: the question, the top passages from the live rung, their definitions.
  No tools.
- The model must return claims, each with a verbatim quote and a passage id.
- **Citation gate (deterministic):** each quote must occur word for word, after whitespace
  normalisation, in the cited passage. A claim that fails is dropped. No surviving claims
  becomes "not stated in this agreement".
- Default candidate model: `claude-haiku-4-5-20251001`. M5 confirms the model and its current
  price from the pricing documentation before the cap arithmetic is published. Offline answer
  evals run the same model id through `claude -p`.

## 5. Evals

### 5.1 Two tiers

| Tier | Questions | Answer key | Label on the site |
|---|---|---|---|
| T-human | MAUD's question types across its agreements | Lawyers' annotated spans and answers | "human-labelled (MAUD)" |
| T-machine | The three lead families on tech deals | Two independent model passes that each locate the governing clause and state the answer; only items where the passes agree are kept, and the agreement rate is published | "machine-built" |

Headline retrieval numbers come from T-human.

### 5.2 Metrics

- **Retrieval:** recall@k (k = 1, 5, 10), MRR, nDCG@10, scored on overlap with the gold span.
- **Answers:** accuracy against MAUD's answer labels (T-human); agreement with the kept
  machine answers (T-machine).
- **Tier agreement:** on the MAUD agreements only, the two-pass machine procedure is also run
  on MAUD's own question types, giving the same questions two answer keys. Reported: how often
  the machine key matches the lawyers' span, and Kendall's tau between the rung ordering under
  human labels and under machine labels. This is the evidence for or against trusting T-machine.
- **Abstention:** correct-decline rate on questions known to be absent: earn-out questions put
  to agreements with no contingent-consideration language; questions whose answer is tagged as
  in an unfiled schedule; right question, wrong deal. False-answer rate is published beside it.
- **Citation accuracy:** share of claims passing the gate, and share a second model pass, shown
  only the quote and the claim and told to refute, fails to refute.
- **Break-up fee cross-check:** the fee as answered versus the fee as restated in the press
  release (EX-99.1) of the same 8-K. Included only if M0 shows the restatement exists in a
  usable share of filings.

### 5.3 Reporting rules

- Bootstrap confidence intervals clustered by agreement; rung comparisons are paired.
- Results per question family and per tier, never only an average.
- Every miss is classified: wrong deal; wrong section; right section but definition missing;
  superseded text; answer in unfiled schedule; label disputed.
- Latency (p50, p95) and tokens per question beside quality for every rung.
- Comparison against LegalBench-RAG's published MAUD baselines, with the differences in setup
  stated.

## 6. Live service

- One Python service (FastAPI) on one always-on 4 GB machine (Hetzner; was 1 GB, changed
  2026-10-05, see the M5 note in §9). SQLite holds FTS5, `sqlite-vec`
  and metadata in a single file built offline and shipped to the server. The embedding model and
  reranker load in-process.
- Endpoints: `/search` (no model call), `/ask` (model call), `/health`.
- **Cost controls on `/ask`:**
  - a spend ledger (tokens in and out per call, priced from a config value); when the month's
    total reaches the cap, `/ask` serves cache hits only and the UI says so
  - an answer cache keyed by normalised question plus deal
  - a per-IP rate limit, a question length cap, an output token cap
- Budget split: hosting at its published price; the model cap is the remainder of the $10, with a
  daily ceiling under it. M5 measures cost per answer and the site prints the split from facts.
- The site is static pages plus calls to the service.

## 7. Numbers contract

Every number the site or README prints comes from `facts.json`, produced by a named query in
`facts/`. No digit is hard-coded in page copy. Machine-built numbers carry the label
"machine-built" wherever they appear.

## 8. Stack, layout, operability

- Python, `uv`, `pytest`. SQLite. Local models through `sentence-transformers` or ONNX.
- Layout: `pipeline/` (fetch, normalise, segment, terms, identity, index), `retrieval/` (rungs),
  `answer/` (prompt, gate), `evals/` (sets, metrics, report), `service/`, `site/`, `facts/`,
  `tests/`, `docs/`.
- Every pipeline stage is idempotent and resumable from its ledger. Resume is tested by killing
  the stage.
- CI is visible: tests plus a facts check.
- The README and the launch post are written by Michael by hand.
- Commits carry an `Assisted-by: Claude` trailer.

## 9. Milestones

M1 and M2 touch only MAUD, so they do not wait on the SEC.

| Milestone | Delivers | Exit condition |
|---|---|---|
| M0 | The EDGAR gate. One slow script measures: agreements returned by the selection rule; target-resolution rate; duplicate-copy and amendment rates; presence of each lead family in a sample of 30 agreements; share of 8-Ks whose press release restates the fee; passages per agreement, hence index size | A written M0 report. **Gate:** fewer than 100 tech agreements, or a lead family present in under half the sample, triggers the fallback in §10 before M3 is planned |
| M1 | MAUD ingested (normalise, segment, defined terms), R1, the T-human harness with metrics and confidence intervals | First command-backed retrieval numbers for BM25 on MAUD |
| M2 | R2–R6 and the chunking comparison on T-human; failure classification; latency and tokens per rung | The ladder table for T-human |
| M3 | Tech deals fetched and ingested (identity, amendments), R7, T-machine built, tier agreement | The ladder table for T-machine and the tau |
| M4 | Answering, the citation gate, abstention and citation-accuracy evals, the fee cross-check if M0 allowed it | Answer-quality tables for both tiers |
| M5 | The service, cost controls, deployment to `deals.forn.al`, the four pages. Model and price confirmed; index size and memory checked on the server | A visitor can ask a question and get a cited answer; the cap trips in a test |
| M6 | Michael's README and launch post; final facts check | Public |

**M0 outcome (2026-10-02, recorded in `docs/m0/REPORT.md`):** the gate failed on its family
condition, not on corpus size. Tech agreements met the count, but earn-outs and other contingent
consideration were present in none of the 30 sampled public tech-target agreements (machine-built,
quote-gated). §10's fallback, written for a thin corpus, did not fit. Michael's decision: replace the
third lead family with employees' pay and benefits after the deal, which is not a MAUD deal point and
was measured present in nearly all of the same sample. Earn-out questions stay in the evals as
abstention items (§5.2), where their absence is the correct answer.

**M4 decisions (2026-10-04, recorded in `docs/superpowers/specs/2026-10-04-m4-answers-design.md`):** the §5.2
break-up fee cross-check is dropped, because M0 found no press release that restates the fee. The answer path
leaves out the R4 reranker, which lowered recall in M2 and M3 (R7 without it, measured as R7n). A question that
names no deal, or names several, gets a "which agreement?" state instead of an answer. T-human answers are
scored by having the model pick one of MAUD's answer options.

**M5 decisions (2026-10-05, recorded in `docs/superpowers/specs/2026-10-05-m5-live-design.md`):**
- The live model is Haiku 4.5, the model the M4 answer numbers describe.
- The host is a Hetzner 4 GB machine within the hosting budget, which retires the §10 memory risk.
- The site is static HTML rendered in Python from `facts.json`, served with the API from that one box.
- The repo goes to a private GitHub repo first and becomes public at M6.
- Commit metadata was rewritten so it never carries the SEC contact.
- The model budget has a daily ceiling, and calibration spend uses a separate Console workspace from
  the live service.
- 2026-10-06: the host is a Hetzner CX23 (x86, 4 GB) in Falkenstein, billed in USD, replacing the CAX11.
- 2026-10-06: the live answerer uses Haiku's extended thinking, as the M4 evaluation runs did.
- 2026-10-06: one API key serves calibration and the live service (Michael's choice), so the Console
  spend limit covers both; the separate-workspace bullet above no longer holds.

**M5 outcome (2026-10-06, numbers in `facts.json` as `m5_*`, report in `docs/m5/REPORT.md`):** the desk is live at
`deals.forn.al`. It runs the measured path: re-preparing M4's answer items through the live code reproduced
every prompt (`m5_prompt_parity_*`), and R7n over the shipped index matched the evaluation index
(`m5_bundle_parity_*`). An API calibration first ran without extended thinking and fell below the command-line
evaluation runs on MAUD's questions, which stopped the deploy. With thinking on, the sample passed the stop rule
(`m5_calibration_stop_rule`): the same MAUD accuracy as the command-line runs on its human-keyed half, and state
agreement above the threshold (`m5_calibration_*`). A sample that size detects only large differences. The cap
trips on the real box (`m5_cap_trip_*`) and in the test suite. A SIGKILL of the service during fresh answers left
only reservations booked at worst case, which settled after the stale window without spend ever going down
(`docs/m5/kill-test.log`). The server's searches returned the same top passages as the development machine's for
nearly every sampled question (`m5_server_embed_parity`, `m5_server_embed_parity_n`); query embeddings are
computed on each machine. The model budget is `m5_model_cap_usd` a month after hosting (`m5_hosting_usd_month`),
about `m5_answers_per_month` new answers.

**M6 decisions (2026-10-06, recorded in `docs/superpowers/plans/2026-10-06-m6-launch.md`):**
- The code is released under the MIT License; `NOTICE.md` carries the data, model and dependency licences.
- An external uptime check (UptimeRobot, free) watches `/api/health`.
- The site build is strict in CI and in the deploy: a missing or empty fact fails it, so no page can say "pending".
- `dtd copycheck` checks every number in the hand-written README and launch post against `facts.json`, and flags a
  machine-built number printed without its label. It reports; the copy stays Michael's.
- The first Ask example was replaced: its answer led with an unfiled-schedule note although its first claim
  answered the question.

## 10. Risks and stated limits (these appear on the Method page)

- **The tech half may be thin or low on startup pull.** These are public-company acquisitions;
  small private exits rarely file the agreement. Fallback: index whatever tech deals exist,
  lead the demo with the most recognisable, and describe the corpus as "public acquisition
  agreements" without the startup framing.
- **Server memory (resolved 2026-10-05).** The 1 GB risk no longer applies: the live host has
  4 GB within the hosting budget, and the live path loads no reranker. M5 records the measured
  memory use.
- **The SEC block may recur.** Hence the access rules in §2.2.
- **T-machine labels are model-built.** Two-pass agreement and the tier-agreement check are
  evidence, not proof. The site says which numbers are which.
- **MAUD's agreements predate 2023, follow one annotation scheme and are not tech-specific.**
  Results on it may not transfer to the tech deals; nothing in this design measures that
  transfer directly, because the tech deals have no human labels.
- **Lay questions are ambiguous.** "What happens to my options" depends on vesting status and
  the agreement's own categories; the answer quotes the categories and does not pick one for
  the reader.
- **Not legal advice,** and the system can be wrong; every claim shows its source so a reader
  can check it.

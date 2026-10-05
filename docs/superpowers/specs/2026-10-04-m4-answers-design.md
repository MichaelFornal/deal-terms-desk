# M4 — Answering, citation gate, answer evals (design spec)

Approved section by section in conversation on 2026-10-04. On exit from plan mode this file is saved
as `docs/superpowers/specs/2026-10-04-m4-answers-design.md` and committed (with the
`Assisted-by: Claude` trailer). Michael reviews it there. Then `superpowers:writing-plans` produces
`docs/superpowers/plans/2026-10-04-m4-answers.md`. No product code is written before that plan is approved.

## Context

Retrieval R1–R7 is built and measured (M1–M3). The "G" in RAG, PRD §4.2 and milestone M4, is not.
M4 covers:
- answering with quoted, cited claims
- a deterministic citation gate
- answer accuracy on both tiers
- abstention
- citation accuracy

M4's exit condition is answer-quality tables for both tiers, every number from facts.json. M5
(service, cost controls, deploy) is a separate later cycle. The §5.2 fee cross-check is dropped:
M0 measured 0/20 press releases restating the fee.

### Decisions made in conversation

| Topic | Decision |
|---|---|
| Scope | M4 only |
| T-human scoring | Option mode: the prompt carries the MAUD answer options, the model picks one plus cited claims, scored by exact match, with a majority-class baseline |
| Retrieval path | R7 without the reranker (R4 lowered recall in M2 and M3), measured as R6n/R7n, then frozen as `answer_path` |
| No deal determined | New `which_deal` state, no model call, ambiguous candidates listed |
| T-machine scoring | Sonnet 5.5 judge, agree / partial / disagree / declined, labelled machine-built |
| Answerer model | Haiku 4.5 on everything; Sonnet 5.5 on the tune split of both tiers for comparison; tokens recorded for M5 pricing |
| Abstention | All four groups (Claude's pick, Michael deferred): T-machine absent rows, earn-outs on M0's sample, unknown or ambiguous deal, unfiled schedule (weakest key) |
| Answer architecture | Approach A: one call returning JSON claims, gated deterministically. Native Citations API rejected because `claude -p` can't use it, so the evals would measure a different system |

## 1. Components

### Retrieval (`retrieval/`)
- **R7 fixes, done first:**
  - a capitalised word at the start of a sentence doesn't scope on its own ("True or false…", "Base salary…")
  - corporate suffixes (Inc, Corporation, Ltd, …) are stripped from the query after the company name
  - code: `retrieval/scope.py` (`Resolver.resolve`, `strip_alias`); tests in `tests/test_scope.py`
- **No-rerank variants R6n and R7n:**
  - in `retrieval/ladder.py` `Ladder.run`, skip the `n >= 4` rerank block and keep the lexicon (n≥5) and the defs table (n==6)
  - R7n = R7's resolve and strip, then R6n
  - run on both tiers through `evals/run_rung.py` so their recall sits beside R6/R7
  - then frozen in `retrieval/settings.json` as `"answer_path"`
- **Answer path entry point:**
  - deal picked → R6n inside that contract, resolver bypassed
  - deal resolved from the question → name stripped, then R6n
  - neither → `which_deal` carrying `Scope.candidates`
- Context is the top `CONTEXT_K` (= 5, `retrieval/result.py`).

### New package `answer/` (PRD §8 layout; add to `[tool.hatch.build.targets.wheel] packages`)
- **`blocks.py`:**
  - turns hits into `[P1]…[P5]` blocks; each block lists its parts with offsets: passage, each definition (`passage_defs`), each amendment (`superseded`)
  - reuses the logic of `Ladder._shown` / `_amendments`, with the part boundaries kept instead of concatenated away
- **`prompt.py`:**
  - one template, with an optional `choices` block for option mode
  - asks for JSON `{state: answered|not_stated|unfiled_schedule, choice?, claims:[{text, quote, ref}]}`
  - the answer is 2–4 sentences, and the agreement's own categories are quoted rather than one picked for the reader (PRD §10)
  - `prompt_sha` (as in `evals/tmachine.py`) goes into every ledger key
- **`gate.py`, pure functions:**
  - normalise whitespace; check each quote is an exact substring of one part of the block named by `ref`
  - return the part kind (passage, definition, amendment N)
  - drop reasons: `quote_not_found`, `bad_ref`, `empty_quote`
- **`answerer.py`:**
  - `Answerer(ladder, runner, model, conn).ask(question, contract_id=None, choices=None) -> Answer`
  - steps: retrieve → blocks → prompt → `runner(prompt, model)` → parse (reuse `_json_object` from `pipeline/m0.py`) → gate → state
  - the offline runner is `pipeline/claude.py` `run_claude`; M5 adds an API runner with the same signature

### Answer states (set by code, never trusted from the model alone)
- `answered`: at least one claim survives the gate. Flag `amended` if any surviving quote is from an amendment part.
- `not_stated`: no claim survives, or the model says not stated.
- `unfiled_schedule`: the model says the answer is in a schedule and a surviving quote sits in a passage tagged `schedule_ref` (`passage_tags`). Otherwise it becomes `not_stated`.
- `which_deal`: no deal could be determined. The runner is not called.
- `budget_cached`: reserved for M5.

`Answer` fields:
- `state`, `amended`
- surviving claims: text, quote, passage_id, section path, part
- dropped claims with reason
- `choice`
- `tokens_in`, `tokens_out`, `ms`, `scope`

## 2. Eval sets (deterministic builders → `data/m4/*_items.jsonl`, no model calls)

- **T-human, option mode:**
  - one item per (report-split agreement, MAUD answer question), with the question text taken from the item's MAUD label query (`evals/items.py`)
  - the contract is passed as if picked
  - choices are that question's distinct answers (`evals/maud_labels.py` `load_rows`)
  - excluded and counted: questions with more than 10 options (2 of 92), and agreements whose label rows disagree on the answer
  - baseline is the majority answer per question from the **tune** split
- **T-machine:**
  - kept report-split rows of `data/m3/tmachine.jsonl`, with the company-naming lay question (`evals/tmachine.py` `items_from_rows`), run through the full live path (R7n)
  - the judge input is the question, kept answers `a` and `b`, and the system's answer
- **Abstention, four groups, each with correct-decline and false-answer rates:**
  1. **Absent rows:** the 43 `absent` rows, expected `not_stated`. The text-not-filed rows (e.g. RealNetworks) are their own subgroup.
  2. **Earn-outs:** one earn-out / contingent-consideration question per agreement in M0's 30-agreement sample (`data/m0/sample.jsonl`), expected `not_stated`.
  3. **Unknown or ambiguous deal:** lead questions naming either an M0 candidate target absent from `aliases` (local data only, never sec.gov) or an alias mapping to more than one contract. Expected `which_deal`.
  4. **Unfiled schedule:** kept rows whose gold span overlaps a `schedule_ref` passage and where both kept answers mention the schedule. Expected `unfiled_schedule`. Labelled as the weakest key.
- **Citation accuracy:**
  - gate pass rate (surviving / returned claims) per tier
  - refute pass: Sonnet 5.5 sees only the claim and quote and is told to refute; reported as the share it fails to refute (machine-built)
- **Model comparison:** Sonnet 5.5 as answerer on the tune split of T-human and T-machine. Reports accuracy, gate pass rate, and tokens in and out per answer.

## 3. Running, resume, failures

- **Commands:**
  - `dtd answers --set thuman|tmachine|abstain --model <id> [--split] [--max-new N]` in `evals/run_answers.py`, wired into `pipeline/cli.py`
  - `dtd answers-judge` and `dtd answers-refute` for the second passes
- **Ledgers:**
  - `data/m4/<set>_<model>_ledger.jsonl`, keyed `item_id|model|prompt_sha`; a rerun skips keys already present
  - append-and-flush under a lock, torn last line ignored (`pipeline/ledger.py` pattern)
  - judge and refute ledgers are keyed by the answer record's hash, so re-answering means re-judging
- **Concurrency:** 4 workers, as in T-machine's `label_all`. sec.gov is never touched.
- **Errors:**
  - a runner `RuntimeError` is recorded as `error`, excluded from accuracy, and counted
  - unparseable JSON is `error: parse`, never `not_stated`
  - a run with more than 5% errors stops with a plain message
  - an out-of-list `choice` is scored wrong and counted separately
- **Resume:** SIGKILL `dtd answers` mid-run and rerun, both in tests (fake runner) and once in the real run (`data/m4/answers_kill.log`, as M3's `tier_kill.log`).
- **Tokens:** tokens in and out come from each reply's `usage`. Everything offline is `claude -p`, $0 cash.

## 4. Testing, facts, report

- **Tests (TDD; default suite makes no model calls; fake runner in `tests/fakes.py`):**
  - `test_gate.py`: exact, whitespace variants, a quote spanning passage and definition fails, part kind, amended flag, bad ref
  - `test_answerer.py`: every state; `which_deal` makes no call; schedule downgrade; parse error ≠ abstention; out-of-list choice
  - `test_scope.py`: the R7 fixes
  - `test_ladder.py`: R6n/R7n equal R6/R7 minus rerank
  - `test_answer_sets.py`: exclusion rules, the four abstention groups
  - `test_run_answers.py`: ledger skip, prompt-hash miss, error threshold, SIGKILL resume
  - one `-m model` end-to-end test
- **Facts:**
  - `facts/m4.py` with named queries for every printed number, labelled machine-built where they are:
    - T-human accuracy vs baseline, per category with CIs clustered by agreement (`evals/bootstrap.py`)
    - T-machine agree/partial per family
    - the four abstention groups
    - gate pass rate and refute survival
    - Haiku vs Sonnet
    - error and exclusion counts
    - R6n/R7n recall
  - `facts/build.py` picks the new queries up; `tests/test_facts*.py` allow `m4_` keys
- **Report:** `facts/report_m4.py` generates `docs/m4/REPORT.md` (pattern: `facts/report_m3.py`).
- **PRD note:** a dated note under §9 records that the fee cross-check was dropped (M0 0/20) and that R4 is out of the answer path.

## Order of work

1. R7 fixes, then R6n/R7n, then their recall on both tiers.
2. `answer/`: gate, blocks, prompt, answerer.
3. Set builders.
4. Runner and ledgers.
5. Smoke runs (`--max-new 20` per set).
6. Full runs: T-human, T-machine, abstention, then the Sonnet comparison.
7. Judge and refute passes.
8. Facts, report, PRD note.

## Verification

- `uv run pytest` is green; `uv run pytest -m model -k answer` passes one real end-to-end call.
- A smoke run on each set produces ledgers whose records show tokens, states and gate results.
- Resume: kill the real `dtd answers` mid-run, rerun, and confirm one record per item with no duplicate calls (log kept).
- `dtd facts` (or `uv run python -m facts.build`) writes the `m4_*` keys. `docs/m4/REPORT.md` regenerates from them with no hard-coded digits (same digit test as M3's report).
- Exit: answer-quality tables for both tiers, plus abstention and citation accuracy, in the report.

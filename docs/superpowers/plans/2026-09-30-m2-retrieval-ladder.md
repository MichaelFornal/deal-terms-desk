# M2: The Retrieval Ladder on T-human — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure rungs R2–R6 against M1's BM25 baseline on the human-labelled MAUD items, with paired, contract-clustered comparisons, per-family results, a failure breakdown, latency and context tokens per rung, the chunking comparison, the lexicon-versus-LLM rewrite comparison and a stated comparison with LegalBench-RAG.

**Architecture:** The M1 index gains section paths, per-passage definitions and a second FTS table (passage plus definitions). A resumable embedding cache feeds a `sqlite-vec` table inside the same index file, partitioned by contract so the contract filter runs inside the nearest-neighbour search. One `Ladder` class serves every rung (R1 BM25, R2 dense, R3 RRF hybrid, R4 + cross-encoder rerank, R5 + lexicon rewrite, R6 + definition expansion), and one generic runner scores any rung into the M1 result format. Settings are tuned on the tune split only. A second facts builder turns the M2 results into named facts and `docs/m2/REPORT.md`.

**Tech Stack:** Python 3.12, `uv`, `pytest`, SQLite FTS5, `sqlite-vec` 0.1.9, `fastembed` 0.8.x (ONNX runtime, no torch), `claude -p` for the offline model passes.

**Spec:** `docs/PRD.md` (milestone M2 of §9; §4.1 rungs, §5.2 metrics, §5.3 reporting rules). M1's plan and report: `docs/superpowers/plans/2026-09-30-m1-maud-bm25-baseline.md`, `docs/m1/REPORT.md`.

## Global Constraints

- $0 cash. Local models and `claude -p` on the Max plan only. No API key, no paid service.
- Nothing in M2 may request `sec.gov`, `data.sec.gov` or `efts.sec.gov`.
- Every number the site or README prints comes from `facts.json`, produced by a named query in `facts/`. No digit is hard-coded in report copy. Machine-built numbers carry "machine-built" wherever they appear.
- Every stage is idempotent and resumable. Resume is tested by killing the stage (Task 16), not by reasoning.
- M1's numbers must not move. After every task that touches the index, `uv run dtd facts --check` passes against M1's `facts.json`, apart from facts that the task adds.
- Headline numbers are read on the report split. Settings are chosen on the tune split only (`evals.bootstrap.split_of`). Nothing reads report-split results to choose a setting.
- Results per question family (MAUD category) and per rung, never only an average (PRD §5.3).
- The README and the launch post are written by Michael by hand; never create or edit `README.md`.
- No personal email address in any request header or any committed file.
- Commits end with these two trailer lines:
  `Assisted-by: Claude`
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- Python `>=3.12,<3.13`. All character offsets refer to the canonical text returned by `pipeline.normalise.load_contract`.

## Numbers this plan starts from (M1 of record, `facts.json` at `d4582fc`)

- 100 agreements, 22,789 indexed passages, 1,856 scored items (report split: 76 agreements, 1,406 items; tune split: the other 24 agreements, 450 items).
- R1 on the report split: recall@5 0.4892 (0.4666–0.5123), recall@10 0.5955, MRR@10 0.4025, nDCG@10 0.3902. Latency p50 9.67 ms, p95 49.24 ms.
- R1 recall@5 per family: Conditions to Closing 0.2026, General Information 0.2921, Knowledge 0.3571, Deal Protection 0.4526, Operating and Efforts Covenant 0.5802, Material Adverse Effect 0.9949, Remedies 1.0. MAE and Remedies are ceilings: their MAUD query names list the clause's own vocabulary, so no rung can show a gain there. Gains are read per family.
- 1,072 of 1,856 items miss at least one gold span at k=5, so there is room above R1.
- There are 22 distinct deal-point names (`text_type`) behind the 1,856 items. Every item's query is its deal-point name plus its question stems.

## Measured while writing this plan (2026-09-30, this machine: Apple M1, 16 GB)

Seeds that shaped the design, not published numbers; Task 16 re-derives everything.

- `sqlite-vec` 0.1.9 loads in the project's uv Python (arm64, SQLite 3.53.1). A `vec0` table with `contract_id text partition key` answers `embedding MATCH ? AND k = ? AND contract_id = ?`, so the contract filter is inside the KNN query (this is what M3 needs at ~300k passages).
- `fastembed` 0.8.1 ships `BAAI/bge-small-en-v1.5` (384 dimensions) and the cross-encoders `BAAI/bge-reranker-base`, `Xenova/ms-marco-MiniLM-L-6-v2`, `jinaai/jina-reranker-v1-tiny-en`, `jinaai/jina-reranker-v1-turbo-en`. ONNX, CPU provider.
- Passage length in bge-small tokens (sample of 64 indexed passages): median about 370, maximum 743; about 5% exceed the model's 512-token window and are embedded truncated. Task 4 counts them.
- Speed, measured with the machine under heavy load (load average 12; a game using most of one core), so treat as pessimistic: embedding about 5 passages per second at real passage length (a 4-token string runs at about 890 per second, so the cost is length, not setup); one query embedding about 20 ms.
- Reranking 20 real passages for one query: `bge-reranker-base` 18–22 s, `ms-marco-MiniLM-L-6-v2` 2.8 s, `jina-reranker-v1-tiny-en` 2.4 s, `jina-reranker-v1-turbo-en` 3.6 s. The PRD's default reranker candidate is roughly ten times too slow for a live path on a 1 GB server; PRD §10 names "a lighter reranker" as the first fallback. Task 10 picks the reranker on the tune split under a stated latency rule.
- Offline compute this implies: embedding all 22,789 passages about 75 minutes, the fixed-size index about the same again; the reranker bake-off on the tune split about 3 hours (two thirds of it `bge-reranker-base`); the report-split rerank runs about 1–2 hours per rung with a small reranker. Every one of these stages is cached and resumable.
- 94 of 100 MAUD texts have a line-start `ARTICLE` heading. 48% of the texts have a median line length under 120 characters (hard-wrapped), so a single newline does not end a definition or a sentence.
- LegalBench-RAG (Pipitone and Houir Alami, arXiv:2408.10343v1): retrieval over the whole corpus of all documents, questions of the form "Consider the …; Does this contract …?", character-level precision@k and recall@k for k = 1…64, with `text-embedding-3-large`, naive 500-character chunks or a recursive splitter, and optionally the Cohere reranker. Their MAUD recall figures are single-digit to low-thirties percent. Task 14 transcribes the tables from the paper itself.

## Review Focus

1. **The embedding stage killed mid-run.** Rerunning must embed only what is missing and the vector table must end complete; a partial cache must never produce a partial vector table. (Test in Task 4; real kill in Task 16.)
2. **A passage longer than the embedding model's 512-token window.** It is embedded truncated and counted, never dropped and never a crash. (Test in Task 4.)
3. **A query that is empty, punctuation, FTS5 operators, or that the lexicon does not touch.** Every rung returns a list, possibly empty, and never raises. (Test in Task 5.)
4. **An agreement with fewer passages than the fusion or rerank depth.** Every rung returns the passages there are, fewer than k, without error. (Test in Task 5.)
5. **Nested defined terms** ("Company" inside "Company Options", "Company Stock Option"). The longest term wins, and a definition is not attached twice or to the passage that defines it. (Test in Task 9.)

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/segment.py` (modify) | Adds `section_path` (Article › section › clause) to each passage |
| `pipeline/definitions.py` | Definition span per defined term; terms a passage uses |
| `pipeline/chunk_fixed.py` | Fixed-size chunker for the chunking comparison |
| `pipeline/build_lexicon.py` | Offline, machine-built lexicon via one `claude -p` call |
| `pipeline/claude.py` | The one place that shells out to `claude -p` |
| `pipeline/ledger.py` (modify) | Key name becomes a parameter so caches reuse it |
| `pipeline/paths.py` (modify) | `INDEX_FIXED`, `CACHE` |
| `pipeline/cli.py` (modify) | `dtd build [--fixed]`, `embed`, `lexicon`, `rewrite`, `tune`, `eval --rung`, `failures`, `disputes`, `facts`, `report` |
| `retrieval/index.py` (modify) | `section_path` column, `passage_defs`, `passages_x_fts`, pluggable chunker |
| `retrieval/bm25.py` (modify) | Chooses between the two FTS tables |
| `retrieval/result.py` | `Retrieved` (hits, compute ms, shown context) |
| `retrieval/models.py` | `Embedder`, `Reranker` (fastembed), model names |
| `retrieval/vectors.py` | Embedding cache and the `vec0` table |
| `retrieval/dense.py` | R2 search, contract filter inside the KNN |
| `retrieval/hybrid.py` | Reciprocal rank fusion |
| `retrieval/rerank_cache.py` | Resumable cache of reranker scores and their compute time |
| `retrieval/lexicon.py`, `retrieval/lexicon.json` | Deterministic rewrite; the machine-built lexicon |
| `retrieval/ladder.py`, `retrieval/settings.json` | R1–R6 in one class; tuned settings with their evidence |
| `evals/run_rung.py` | Generic scorer for any rung (M1's `run_r1` becomes a wrapper) |
| `evals/compare.py` | Paired, contract-clustered bootstrap between two rungs |
| `evals/metrics.py` (modify) | Character-level precision and recall for the LegalBench-RAG comparison |
| `evals/tune.py` | Grid search on the tune split |
| `evals/llm_rewrite.py` | Offline LLM rewrite of each distinct query (comparison, not a rung) |
| `evals/failures.py` | Per-miss failure classes |
| `evals/disputes.py` | Machine-built "label disputed" estimate on a sample of misses |
| `facts/external.json` | LegalBench-RAG's published MAUD numbers, transcribed with table references |
| `facts/m2.py`, `facts/report_m2.py` | M2 named facts; `docs/m2/REPORT.md` |
| `tests/fakes.py` | Deterministic fake embedder, reranker and `claude` runner; no downloads in tests |

---

### Task 1: Section paths on passages

**Files:**
- Modify: `pipeline/segment.py`, `retrieval/index.py`, `facts/queries.py`
- Test: `tests/test_segment.py`, `tests/test_index.py`, `tests/test_facts.py`

**Interfaces:**
- Produces: `pipeline.segment.Passage` gains a last field `section_path: str = ""`, e.g. `"Article II › 2.3 › (b)"`. Front matter and table-of-contents passages have `""`.
- Produces: `passages.section_path TEXT NOT NULL` in the index.
- Produces: named fact `maud_passages_with_article_share` (share of indexed passages whose path starts with `Article`).
- Passage boundaries must not change. M1's facts stay identical.

How the path is built. The article is the last `ARTICLE <numeral>` line before the section heading whose numeral equals the section's major number (`2` for `2.3`); when there is none, the article is left out rather than guessed. The clause is the sub-clause marker a piece starts with, only for pieces after the first in a split section.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_segment.py`:

```python
PATH_DOC = (
    "TABLE OF CONTENTS\n"
    "ARTICLE I DEFINITIONS\nSection 1.1 Definitions 1\n"
    "ARTICLE II THE MERGER\nSection 2.1 The Merger 5\nSection 3.1 Stray 9\n\n"
    "ARTICLE I\nDEFINITIONS\n\n"
    "Section 1.1 Definitions. “Company” means Acme Corp.\n\n"
    "ARTICLE II\nTHE MERGER\n\n"
    "Section 2.1 The Merger. At the Effective Time: (a) Merger Sub shall merge with and into the Company and cease to exist; "
    "(b) the Company shall survive the Merger as a wholly owned subsidiary of Parent; "
    "(c) the certificate of incorporation of the Company shall be amended in its entirety.\n\n"
    "Section 3.1 Stray. This section has no article heading of its own.\n"
)


def test_section_path_carries_article_section_and_clause():
    ps = segment("c", PATH_DOC, max_chars=120)
    s21 = [p for p in ps if p.section_id == "2.1"]
    assert len(s21) >= 3
    assert s21[0].section_path == "Article II › 2.1"
    for p in s21[1:]:
        marker = PATH_DOC[p.start:].lstrip()[:3]
        assert marker.startswith("(")
        assert p.section_path == f"Article II › 2.1 › {marker}"


def test_section_path_uses_the_body_article_and_omits_a_missing_one():
    ps = segment("c", PATH_DOC, max_chars=2400)
    by_id = {p.section_id: p.section_path for p in ps if p.kind == "section"}
    assert by_id["1.1"] == "Article I › 1.1"
    assert by_id["3.1"] == "3.1"
    assert all(p.section_path == "" for p in ps if p.kind in ("front", "toc"))


def test_section_path_reads_arabic_article_numbers_and_skips_clause_on_sentence_cuts():
    doc = ("Article 4\nCOVENANTS\n\nSection 4.1 Conduct. " + "The Company shall operate in the ordinary course. " * 6 + "\n")
    ps = [p for p in segment("c", doc, max_chars=120) if p.section_id == "4.1"]
    assert len(ps) >= 2
    assert all(p.section_path == "Article 4 › 4.1" for p in ps)


def test_passages_with_paths_still_tile_the_text():
    # Boundaries are guarded for real by `dtd facts --check` on MAUD (Step 5); this pins the invariant.
    ps = segment("c", PATH_DOC, max_chars=120)
    assert ps[0].start == 0 and ps[-1].end == len(PATH_DOC)
    assert all(a.end == b.start for a, b in zip(ps, ps[1:]))
```

Append to `tests/test_index.py`:

```python
def test_index_stores_section_paths(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    doc = "ARTICLE I\nTERMS\n\nSection 1.1 Closing. The closing occurs.\n\nSection 1.2 Merger. The merger occurs.\n"
    db = tmp_path / "i.db"
    build_index(db, {"c": doc})
    paths = [r[0] for r in sqlite3.connect(db).execute(
        "SELECT section_path FROM passages WHERE kind = 'section' ORDER BY ordinal")]
    assert paths == ["Article I › 1.1", "Article I › 1.2"]
```

In `tests/test_facts.py`, extend `test_build_runs_every_named_query` with:

```python
    assert 0 <= facts["maud_passages_with_article_share"] <= 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_segment.py tests/test_index.py tests/test_facts.py -q`
Expected: FAIL with `AttributeError: 'Passage' object has no attribute 'section_path'` (and a missing fact).

- [ ] **Step 3: Implement**

In `pipeline/segment.py`, add below `TOC_MIN_SECTION_NUMBERS`:

```python
ARTICLE = re.compile(r"(?m)^[ \t]*(?:ARTICLE|Article)[ \t]+([IVXLC]+|\d{1,2})\b")
CLAUSE = re.compile(r"\s*\(([a-z]|[ivx]{1,4}|[A-Z])\)\s")
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
PATH_SEP = " › "
```

Add the field last in `Passage`:

```python
    section_path: str = ""
```

Add helpers:

```python
def _numeral(s: str) -> int:
    if s.isdigit():
        return int(s)
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total


def _article(articles: list[tuple[int, str]], pos: int, section_id: str) -> str:
    """The numeral of the last article heading before pos that matches the section's major number."""
    major = int(section_id.split(".")[0])
    found = ""
    for apos, numeral in articles:
        if apos >= pos:
            break
        if _numeral(numeral) == major:
            found = numeral
    return found
```

In `segment`, after `pieces` is built, and in the output loop:

```python
    articles = [(m.start(), m.group(1)) for m in ARTICLE.finditer(text)]
    out: list[Passage] = []
    for s, e, section_id, title, kind in pieces:
        article = _article(articles, s, section_id) if kind == "section" else ""
        for a, b in _cut(text, s, e, max_chars):
            k = kind
            if kind == "front" and len(SECTION_NUMBER.findall(text[a:b])) >= TOC_MIN_SECTION_NUMBERS:
                k = "toc"
            path = ""
            if kind == "section":
                parts = ([f"Article {article}"] if article else []) + [section_id]
                clause = CLAUSE.match(text, a) if a > s else None
                if clause:
                    parts.append(f"({clause.group(1)})")
                path = PATH_SEP.join(parts)
            out.append(Passage(contract_id, len(out), a, b, section_id, title, k, path))
    return out
```

In `retrieval/index.py`, add `section_path TEXT NOT NULL` after `kind TEXT NOT NULL` in the `passages` table, and insert it:

```python
            cur = conn.execute(
                "INSERT INTO passages(contract_id, ordinal, start_char, end_char, section_id, section_title, kind,"
                " section_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p.contract_id, p.ordinal, p.start, p.end, p.section_id, p.section_title, p.kind, p.section_path),
            )
```

In `facts/queries.py`, add:

```python
def _article_share(conn, r1, labels):
    total, with_article = conn.execute(
        "SELECT COUNT(*), SUM(section_path LIKE 'Article %') FROM passages WHERE kind != 'toc'").fetchone()
    return round(with_article / total, 4)
```

and the entry `"maud_passages_with_article_share": _article_share,` in `QUERIES`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass (M1's 112 plus the new ones).

- [ ] **Step 5: Check that passage boundaries did not move on MAUD**

Run: `uv run dtd build && uv run dtd eval && uv run dtd facts --check`
Expected: exit 0 except for `maud_passages_with_article_share`, which is new (`--check` lists it as stale because the committed `facts.json` lacks it). Any other stale fact means boundaries moved: stop and fix. Then `uv run dtd facts` to add the new fact.

- [ ] **Step 6: Commit**

```bash
git add facts.json pipeline/segment.py retrieval/index.py facts/queries.py tests/test_segment.py tests/test_index.py tests/test_facts.py
git commit -m "m2: section paths (Article › section › clause) on passages

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Paired, contract-clustered bootstrap for rung comparisons

**Files:**
- Create: `evals/compare.py`
- Test: `tests/test_compare.py`

**Interfaces:**
- Consumes: `evals.bootstrap.cluster_bootstrap`; per-item rows in the `r1_items.jsonl` format (`item_id`, `contract_id`, `category`, `split`, one key per metric).
- Produces: `evals.compare.load_items(path: Path) -> dict[str, dict]` keyed by `item_id`.
- Produces: `evals.compare.paired_bootstrap(a: dict[str, dict], b: dict[str, dict], metric: str, split: str | None = "report", category: str | None = None, n_boot: int = 2000, seed: int = 0) -> dict` with keys `delta, lo, hi, n_items, n_clusters, a_mean, b_mean`. `delta` is b minus a. Raises `ValueError` if the two rungs were scored on different items.

Why paired: both rungs are scored on the same items, so the interval is on the per-item difference, resampled by agreement. That is much tighter than comparing two separate intervals, and honest because items within one agreement are not independent.

- [ ] **Step 1: Write the failing test**

`tests/test_compare.py`:

```python
import json

import pytest

from evals.compare import load_items, paired_bootstrap


def rows(values, split="report", category="Knowledge"):
    return {f"c{c}|q{i}": {"item_id": f"c{c}|q{i}", "contract_id": f"c{c}", "split": split,
                           "category": category, "recall@5": v}
            for c, vs in enumerate(values) for i, v in enumerate(vs)}


def test_identical_rungs_have_zero_difference():
    a = rows([[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]])
    out = paired_bootstrap(a, a, "recall@5", n_boot=200)
    assert out["delta"] == 0 and out["lo"] == 0 and out["hi"] == 0
    assert out["n_items"] == 6 and out["n_clusters"] == 3


def test_a_uniform_gain_has_a_degenerate_interval_at_the_gain():
    a = rows([[0.2, 0.4], [0.1, 0.3]])
    b = {k: {**r, "recall@5": r["recall@5"] + 0.25} for k, r in a.items()}
    out = paired_bootstrap(a, b, "recall@5", n_boot=200)
    assert out["delta"] == pytest.approx(0.25)
    assert out["lo"] == pytest.approx(0.25) and out["hi"] == pytest.approx(0.25)
    assert out["b_mean"] - out["a_mean"] == pytest.approx(0.25)


def test_a_gain_from_one_agreement_has_an_interval_reaching_zero():
    a = rows([[0.0]] * 10)
    b = dict(a)
    b["c0|q0"] = {**a["c0|q0"], "recall@5": 1.0}
    out = paired_bootstrap(a, b, "recall@5", n_boot=500)
    assert out["delta"] == pytest.approx(0.1)
    assert out["lo"] == 0.0


def test_rungs_scored_on_different_items_are_refused():
    a = rows([[1.0, 0.0]])
    b = rows([[1.0]])
    with pytest.raises(ValueError, match="different items"):
        paired_bootstrap(a, b, "recall@5")


def test_split_and_category_filters_apply_to_both_rungs():
    a = {**rows([[0.0]], split="tune"), **{k + "r": {**v, "item_id": k + "r"} for k, v in rows([[0.5]]).items()}}
    b = {k: {**v, "recall@5": v["recall@5"] + 0.5} for k, v in a.items()}
    assert paired_bootstrap(a, b, "recall@5", split="report", n_boot=50)["n_items"] == 1
    with pytest.raises(ValueError, match="no items"):
        paired_bootstrap(a, b, "recall@5", category="Remedies")


def test_load_items_reads_the_m1_items_format(tmp_path):
    p = tmp_path / "r1_items.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows([[1.0, 0.0]]).values()))
    assert set(load_items(p)) == {"c0|q0", "c0|q1"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_compare.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.compare'`

- [ ] **Step 3: Implement**

`evals/compare.py`:

```python
import json
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap


def load_items(path: Path) -> dict[str, dict]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["item_id"]] = row
    return out


def _select(rows: dict[str, dict], split: str | None, category: str | None) -> dict[str, dict]:
    return {i: r for i, r in rows.items()
            if (split is None or r["split"] == split) and (category is None or r["category"] == category)}


def paired_bootstrap(a: dict[str, dict], b: dict[str, dict], metric: str, split: str | None = "report",
                     category: str | None = None, n_boot: int = 2000, seed: int = 0) -> dict:
    """b minus a on the same items, with an interval from resampling agreements."""
    a, b = _select(a, split, category), _select(b, split, category)
    if set(a) != set(b):
        raise ValueError(f"rungs were scored on different items ({len(set(a) - set(b))} only in the first, "
                         f"{len(set(b) - set(a))} only in the second); rerun both on the same eval set")
    if not a:
        raise ValueError("no items to compare after the split and category filters")
    diffs: dict[str, list[float]] = defaultdict(list)
    for item_id in sorted(a):
        diffs[a[item_id]["contract_id"]].append(b[item_id][metric] - a[item_id][metric])
    ci = cluster_bootstrap(diffs, n_boot=n_boot, seed=seed)
    n = len(a)
    return {"delta": ci["mean"], "lo": ci["lo"], "hi": ci["hi"], "n_items": ci["n_items"],
            "n_clusters": ci["n_clusters"],
            "a_mean": sum(r[metric] for r in a.values()) / n, "b_mean": sum(r[metric] for r in b.values()) / n}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_compare.py -q`
Expected: PASS. Then on the real M1 file, as a smoke check: `uv run python -c "from evals.compare import load_items, paired_bootstrap as p; a = load_items('data/out/r1_items.jsonl'); print(p(a, a, 'recall@5'))"` prints `delta` 0.

- [ ] **Step 5: Commit**

```bash
git add evals/compare.py tests/test_compare.py
git commit -m "m2: paired, contract-clustered bootstrap for rung comparisons

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: A generic rung runner

**Files:**
- Create: `retrieval/result.py`, `evals/run_rung.py`
- Modify: `evals/run_r1.py` (becomes a wrapper), `evals/metrics.py`
- Test: `tests/test_run_rung.py`, `tests/test_metrics.py`

**Interfaces:**
- Produces: `retrieval.result.CONTEXT_K = 5` and the frozen dataclass `Retrieved(hits: list[Hit], ms: float, context: list[str])`. `ms` is the compute time for this query, including the recorded compute time of any stage served from a cache. `context` is the text a model would be shown for the top `CONTEXT_K` hits.
- Produces: `evals.run_rung.Context` with `items: list[Item]`, `alignment: dict`, `texts: dict[str, str]`, `passages: dict[str, list[tuple[int, int]]]` (non-toc spans per contract).
- Produces: `evals.run_rung.load_context(db_path: Path, csv_paths: list[Path], contracts_dir: Path) -> Context`
- Produces: `evals.run_rung.Retriever = Callable[[str, str | None, int], Retrieved]`, called as `(query, contract_id or None, k)`.
- Produces: `evals.run_rung.evaluate(ctx, rung: str, retrieve, out_dir: Path, n_boot: int = 2000, count_tokens: Callable[[str], int] | None = None, scope: str = "within-agreement", k: int = 10, char_ks: tuple[int, ...] = (), extra: dict | None = None) -> dict`. It writes `out_dir/<name>.json` and `out_dir/<name>_items.jsonl`, where `name = rung.lower().replace("-", "_")` (`R1` → `r1.json`, `R3-fixed` → `r3_fixed.json`), and also `out_dir/alignment.json`. With `scope="corpus-wide"` it passes `None` as the contract, and hits from other agreements are never relevant.
- Produces: `evals.metrics.char_recall_at_k(hits, gold, k) -> float` and `char_precision_at_k(hits, gold, k) -> float` (share of gold characters covered by the union of the top k spans; share of retrieved characters that are gold).
- `evals.run_r1.run(...)` keeps its M1 signature and output. Its result gains `context_tokens` and `load`.

The result dict is M1's, plus:

```json
{
  "context_tokens": {"mean": 0.0},
  "load": {"before": [0.0, 0.0, 0.0], "after": [0.0, 0.0, 0.0]},
  "extra": {}
}
```

`context_tokens` is `null` when no counter is given. `load` is `os.getloadavg()` before and after, because latency on a busy development machine means little without it.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_metrics.py`:

```python
from evals.metrics import char_precision_at_k, char_recall_at_k


def test_char_recall_counts_gold_characters_covered_once():
    hits = [hit(0, 50), hit(40, 60), hit(500, 600)]
    gold = [(30, 70), (1000, 1010)]
    assert char_recall_at_k(hits, gold, 2) == pytest.approx(30 / 50)
    assert char_recall_at_k(hits, gold, 1) == pytest.approx(20 / 50)


def test_char_precision_is_gold_share_of_retrieved_characters():
    hits = [hit(0, 50), hit(40, 60)]
    assert char_precision_at_k(hits, [(30, 70)], 2) == pytest.approx(30 / 60)
    assert char_precision_at_k([], [(30, 70)], 2) == 0.0
```

(`hit` and `pytest` are already defined and imported at the top of `tests/test_metrics.py`.)

`tests/test_run_rung.py`:

```python
import json

from evals.run_rung import evaluate, load_context
from retrieval.bm25 import search
from retrieval.index import build_index
from retrieval.result import CONTEXT_K, Retrieved

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"


def contract(fee):
    return (
        "Section 1.1 Closing. The closing shall occur at the offices of counsel on the Closing Date.\n\n"
        "Section 2.6 Type of Consideration. Each Company Share shall be converted into the right to receive cash.\n\n"
        f"Section 8.3 Termination Fee. The Company shall pay Parent a termination fee of {fee} dollars in cash.\n"
    )


def setup(tmp_path):
    cdir = tmp_path / "raw" / "contracts"
    cdir.mkdir(parents=True)
    texts = {f"contract_{i}": contract(f"{i + 1}0,000,000") for i in range(4)}
    for cid, t in texts.items():
        (cdir / f"{cid}.txt").write_text(t, encoding="utf-8")
    body = ""
    for i, (cid, t) in enumerate(texts.items()):
        fee = t.split("\n\n")[2].strip()
        body += f'main,{cid},"{fee} (Page 70)",Yes,1,Termination Fee-Answer,<NONE>,Termination Fee,{i},Deal Protection and Related Provisions\n'
    csv_path = tmp_path / "raw" / "MAUD_dev.csv"
    csv_path.write_text(HEADER + body, encoding="utf-8")
    db = tmp_path / "index" / "maud.db"
    build_index(db, texts)
    return db, [csv_path], cdir, tmp_path / "out"


def bm25_retriever(db, ctx):
    import sqlite3
    conn = sqlite3.connect(db)

    def retrieve(query, contract_id, k):
        hits = search(conn, query, contract_id=contract_id, k=k)
        return Retrieved(hits, 2.5, [ctx.texts[h.contract_id][h.start:h.end] for h in hits[:CONTEXT_K]])
    return retrieve


def test_evaluate_names_files_by_rung_and_records_tokens_and_load(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    ctx = load_context(db, csvs, cdir)
    result = evaluate(ctx, "R3-fixed", bm25_retriever(db, ctx), out, n_boot=50,
                      count_tokens=lambda s: len(s.split()), extra={"note": "x"})
    assert json.loads((out / "r3_fixed.json").read_text()) == result
    rows = [json.loads(l) for l in (out / "r3_fixed_items.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and all(r["latency_ms"] == 2.5 and r["context_tokens"] > 0 for r in rows)
    assert rows[0]["query"].startswith("Termination Fee")
    assert result["rung"] == "R3-fixed" and result["extra"] == {"note": "x"}
    assert result["context_tokens"]["mean"] > 0
    assert len(result["load"]["before"]) == 3
    assert result["latency_ms"]["p50"] == 2.5


def test_corpus_wide_scope_passes_no_contract_and_never_credits_another_agreement(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    ctx = load_context(db, csvs, cdir)
    seen = []
    inner = bm25_retriever(db, ctx)

    def retrieve(query, contract_id, k):
        seen.append(contract_id)
        r = inner(query, contract_id, k)
        return Retrieved([h for h in r.hits if h.contract_id == "contract_0"], r.ms, r.context)
    result = evaluate(ctx, "R1-corpus", retrieve, out, n_boot=50, scope="corpus-wide", k=64, char_ks=(1, 2))
    assert set(seen) == {None}
    rows = {r["contract_id"]: r for r in map(json.loads, (out / "r1_corpus_items.jsonl").read_text().splitlines())}
    assert rows["contract_0"]["recall@10"] == 1.0
    assert rows["contract_1"]["recall@10"] == 0.0
    assert "char_recall@2" in rows["contract_0"] and "char_precision@1" in result["overall"]


def test_run_r1_output_is_unchanged_in_shape(tmp_path):
    from evals.run_r1 import METRICS, run
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=50)
    assert result["rung"] == "R1" and set(METRICS) <= set(result["overall"])
    assert (out / "r1_items.jsonl").exists() and (out / "alignment.json").exists()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_run_rung.py tests/test_metrics.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.run_rung'` and an import error for the char metrics.

- [ ] **Step 3: Implement**

Append to `evals/metrics.py`:

```python
def _union(spans) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return [(s, e) for s, e in out]


def _covered(spans, gold) -> int:
    return sum(_overlap(s, e, g0, g1) for s, e in _union(spans) for g0, g1 in _union(gold))


def char_recall_at_k(hits, gold, k: int) -> float:
    total = sum(e - s for s, e in _union(gold))
    return _covered([(h.start, h.end) for h in hits[:k]], gold) / total if total else 0.0


def char_precision_at_k(hits, gold, k: int) -> float:
    spans = _union([(h.start, h.end) for h in hits[:k] if h.end > h.start])
    total = sum(e - s for s, e in spans)
    return _covered(spans, gold) / total if total else 0.0
```

`retrieval/result.py`:

```python
from dataclasses import dataclass

from retrieval.bm25 import Hit

CONTEXT_K = 5


@dataclass(frozen=True)
class Retrieved:
    hits: list[Hit]
    ms: float
    context: list[str]
```

`evals/run_rung.py` (moves M1's helpers here; `run_r1.py` keeps thin re-exports):

```python
import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from evals.bootstrap import cluster_bootstrap, split_of
from evals.items import Item, build_items
from evals.maud_labels import load_rows
from evals.metrics import char_precision_at_k, char_recall_at_k, is_relevant, mrr, ndcg_at_k, recall_at_k
from pipeline.normalise import load_contract
from retrieval.result import Retrieved

METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")
K = 10
Retriever = Callable[[str, str | None, int], Retrieved]


@dataclass
class Context:
    items: list[Item]
    alignment: dict
    texts: dict[str, str]
    passages: dict[str, list[tuple[int, int]]]


def load_context(db_path: Path, csv_paths: list[Path], contracts_dir: Path) -> Context:
    conn = sqlite3.connect(db_path)
    contract_ids = [r[0] for r in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id")]
    texts = {cid: load_contract(Path(contracts_dir) / f"{cid}.txt") for cid in contract_ids}
    toc: dict[str, list[tuple[int, int]]] = defaultdict(list)
    passages: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cid, s, e, kind in conn.execute("SELECT contract_id, start_char, end_char, kind FROM passages"):
        (toc if kind == "toc" else passages)[cid].append((s, e))
    items, alignment = build_items(load_rows(csv_paths), texts, toc=dict(toc))
    conn.close()
    return Context(items, alignment, texts, dict(passages))


def _summarise(per_item: list[dict], metrics: tuple[str, ...], n_boot: int) -> dict:
    out = {}
    for metric in metrics:
        by_contract: dict[str, list[float]] = defaultdict(list)
        for row in per_item:
            by_contract[row["contract_id"]].append(row[metric])
        out[metric] = cluster_bootstrap(by_contract, n_boot=n_boot)
    return out


def _percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def evaluate(ctx: Context, rung: str, retrieve: Retriever, out_dir: Path, n_boot: int = 2000,
             count_tokens: Callable[[str], int] | None = None, scope: str = "within-agreement", k: int = K,
             char_ks: tuple[int, ...] = (), extra: dict | None = None) -> dict:
    metrics = METRICS + tuple(f"char_{m}@{c}" for c in char_ks for m in ("recall", "precision"))
    load_before = list(os.getloadavg())
    per_item = []
    for item in ctx.items:
        got = retrieve(item.query, item.contract_id if scope == "within-agreement" else None, k)
        # A hit from another agreement can never be relevant: blank its span before scoring.
        hits = [h if h.contract_id == item.contract_id else replace(h, start=-1, end=-1) for h in got.hits]
        n_relevant = sum(1 for s, e in ctx.passages.get(item.contract_id, []) if is_relevant(s, e, item.gold))
        row = {
            "item_id": item.item_id,
            "contract_id": item.contract_id,
            "category": item.category,
            "query": item.query,
            "split": split_of(item.contract_id),
            "recall@1": recall_at_k(hits, item.gold, 1),
            "recall@5": recall_at_k(hits, item.gold, 5),
            "recall@10": recall_at_k(hits, item.gold, 10),
            "mrr@10": mrr(hits, item.gold, K),
            "ndcg@10": ndcg_at_k(hits, item.gold, n_relevant, K),
            "gold": [list(g) for g in item.gold],
            "top_passage_ids": [h.passage_id for h in got.hits[:K]],
            "latency_ms": got.ms,
            "context_tokens": count_tokens("\n\n".join(got.context)) if count_tokens else None,
        }
        for c in char_ks:
            row[f"char_recall@{c}"] = char_recall_at_k(hits, item.gold, c)
            row[f"char_precision@{c}"] = char_precision_at_k(hits, item.gold, c)
        per_item.append(row)
    if not per_item:
        raise ValueError("no scorable eval items: check that the index and the label CSVs describe the same contracts")
    latencies = sorted(r["latency_ms"] for r in per_item)
    tokens = [r["context_tokens"] for r in per_item if r["context_tokens"] is not None]
    result = {
        "rung": rung,
        "scope": scope,
        "alignment": ctx.alignment,
        "overall": _summarise(per_item, metrics, n_boot),
        "by_split": {
            split: _summarise([r for r in per_item if r["split"] == split], metrics, n_boot)
            for split in sorted({r["split"] for r in per_item})
        },
        "by_category": {
            cat: _summarise([r for r in per_item if r["category"] == cat], metrics, n_boot)
            for cat in sorted({r["category"] for r in per_item})
        },
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "context_tokens": {"mean": sum(tokens) / len(tokens)} if tokens else None,
        "load": {"before": load_before, "after": list(os.getloadavg())},
        "extra": extra or {},
    }
    name = rung.lower().replace("-", "_")
    out_dir = Path(out_dir)
    _write_json(out_dir / "alignment.json", ctx.alignment)
    _write_jsonl(out_dir / f"{name}_items.jsonl", sorted(per_item, key=lambda r: r["item_id"]))
    _write_json(out_dir / f"{name}.json", result)
    return result
```

Replace the body of `evals/run_r1.py` with:

```python
import sqlite3
import time
from pathlib import Path

from evals.run_rung import K, METRICS, evaluate, load_context
from retrieval.bm25 import search
from retrieval.result import CONTEXT_K, Retrieved

__all__ = ["K", "METRICS", "run"]


def run(db_path: Path, csv_paths: list[Path], contracts_dir: Path, out_dir: Path, n_boot: int = 2000) -> dict:
    ctx = load_context(db_path, csv_paths, contracts_dir)
    conn = sqlite3.connect(db_path)

    def retrieve(query, contract_id, k):
        t0 = time.perf_counter()
        hits = search(conn, query, contract_id=contract_id, k=k)
        ms = (time.perf_counter() - t0) * 1000.0
        return Retrieved(hits, ms, [ctx.texts[h.contract_id][h.start:h.end] for h in hits[:CONTEXT_K]])
    return evaluate(ctx, "R1", retrieve, out_dir, n_boot=n_boot)
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest -q`
Expected: all pass, including M1's `tests/test_run_r1.py` unchanged.

- [ ] **Step 5: Check that R1's numbers did not move**

Run: `uv run dtd eval && uv run dtd facts --check`
Expected: exit 0 (latency is not compared). If a fact is reported stale, stop: the refactor changed scoring.

- [ ] **Step 6: Commit**

```bash
git add retrieval/result.py evals/run_rung.py evals/run_r1.py evals/metrics.py tests/test_run_rung.py tests/test_metrics.py
git commit -m "m2: generic rung runner with latency, context tokens, load and corpus-wide scope

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 4: Embedding cache, vector table and dense search (rung R2)

**Files:**
- Modify: `pyproject.toml`, `pipeline/paths.py`
- Create: `retrieval/models.py`, `retrieval/vectors.py`, `retrieval/dense.py`, `tests/fakes.py`
- Test: `tests/test_vectors.py`, `tests/test_models.py`

**Interfaces:**
- Produces: `pipeline.paths.INDEX_FIXED: Path` (`data/index/maud_fixed.db`), `CACHE: Path` (`data/cache`).
- Produces: `retrieval.models.EMBED_MODEL = "BAAI/bge-small-en-v1.5"`, `EMBED_DIM = 384`, `MAX_TOKENS = 512`, `QUERY_PREFIX` (bge's retrieval instruction).
- Produces: `retrieval.models.Embedder(name: str = EMBED_MODEL, threads: int | None = None)` with `.name`, `.embed_passages(texts: list[str]) -> list[list[float]]`, `.embed_query(q: str) -> list[float]`, `.count_tokens(text: str) -> int` (untruncated, including special tokens). The model loads on first use, not in `__init__`.
- Produces: `retrieval.vectors.connect(db_path: Path) -> sqlite3.Connection` (sqlite-vec loaded), `sha1(text: str) -> str`, `open_cache(path: Path) -> sqlite3.Connection`, `indexed_passages(conn) -> list[tuple[int, str, str]]` as `(passage_id, contract_id, text)`, `fill_cache(cache, embedder, texts: list[str], batch: int = 32, on_batch=None) -> dict` with keys `embedded, cached`, `build_vectors(conn, cache, model: str, dim: int = EMBED_DIM) -> dict` with keys `vectors, truncated`.
- Produces: `retrieval.dense.search_dense(conn, qvec: list[float], contract_id: str | None = None, k: int = 10) -> list[Hit]`, score `1 - cosine distance`, ties broken by `passage_id`.
- Produces: `tests/fakes.py` with `FakeEmbedder`, `FakeReranker` and `fake_claude(result: str)`. All tests use these; nothing in the default test run downloads a model.

Why a separate cache: `build_index` replaces `maud.db` atomically, which drops the vector table. The cache (`data/cache/embeddings.db`, keyed by model and text hash, committed after every batch) is the ledger that makes embedding resumable and a rebuild cheap. The vector table is rebuilt from the cache in seconds and is never written from a partial cache.

- [ ] **Step 1: Add the dependencies and the test marker**

In `pyproject.toml` set:

```toml
dependencies = ["fastembed>=0.8.1,<0.9", "sqlite-vec>=0.1.9,<0.2"]
```

and extend the pytest section:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
markers = ["model: downloads and runs a real model (run with -m model)"]
addopts = "-m 'not model'"
```

Run: `uv lock && uv sync`
Expected: `fastembed`, `onnxruntime`, `tokenizers`, `numpy` and `sqlite-vec` installed.

In `pipeline/paths.py` add:

```python
INDEX_FIXED = DATA / "index" / "maud_fixed.db"
CACHE = DATA / "cache"
```

- [ ] **Step 2: Write the fakes**

`tests/fakes.py`:

```python
import hashlib
import math

from retrieval.bm25 import TOKEN

DIM = 384


class FakeEmbedder:
    """Bag of hashed words, L2-normalised: deterministic and similar for texts sharing words."""
    name = "fake-embedder"

    def __init__(self):
        self.embedded = 0

    def _vec(self, text: str) -> list[float]:
        v = [0.0] * DIM
        for t in TOKEN.findall(text.lower()):
            v[int(hashlib.sha1(t.encode()).hexdigest(), 16) % DIM] += 1.0
        norm = math.sqrt(sum(x * x for x in v))
        if norm == 0:
            v[0], norm = 1.0, 1.0
        return [x / norm for x in v]

    def embed_passages(self, texts):
        self.embedded += len(texts)
        return [self._vec(t) for t in texts]

    def embed_query(self, q):
        return self._vec(q)

    def count_tokens(self, text):
        return len(TOKEN.findall(text)) + 2


class FakeReranker:
    """Scores by shared lowercase words; reports a fixed compute time."""
    name = "fake-reranker"

    def __init__(self, ms: float = 7.0):
        self.calls = 0
        self.ms = ms

    def score(self, query, texts):
        self.calls += 1
        q = set(TOKEN.findall(query.lower()))
        return [float(len(q & set(TOKEN.findall(t.lower())))) for t in texts], self.ms


def fake_claude(result: str, input_tokens: int = 100, output_tokens: int = 20):
    calls = []

    def runner(prompt: str, model: str) -> dict:
        calls.append((prompt, model))
        return {"result": result, "usage": {"input_tokens": input_tokens, "output_tokens": output_tokens},
                "duration_api_ms": 50}
    runner.calls = calls
    return runner
```

- [ ] **Step 3: Write the failing tests**

`tests/test_vectors.py`:

```python
import pytest

from retrieval.dense import search_dense
from retrieval.index import build_index
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder

DOCS = {
    "a": "Section 1.1 Fees. The Company shall pay the Termination Fee to Parent.\n\n"
         "Section 1.2 Options. Each Company Option shall vest at the Effective Time.\n",
    "b": "Section 1.1 Fees. Parent shall pay a Reverse Termination Fee to the Company.\n",
}


@pytest.fixture
def index(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, DOCS)
    return db, tmp_path / "cache" / "emb.db"


def test_fill_cache_embeds_each_distinct_text_once_and_resumes(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    texts = [t for _, _, t in indexed_passages(conn)]
    first = fill_cache(cache, emb, texts[:2], batch=1)
    assert first == {"embedded": 2, "cached": 0}
    second = fill_cache(open_cache(cache_path), emb, texts + texts, batch=1)
    assert second == {"embedded": len(set(texts)) - 2, "cached": 2}
    assert emb.embedded == len(set(texts))


def test_build_vectors_refuses_a_partial_cache(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    texts = [t for _, _, t in indexed_passages(conn)]
    fill_cache(cache, emb, texts[:1])
    with pytest.raises(ValueError, match="dtd embed"):
        build_vectors(conn, cache, emb.name)
    assert conn.execute("SELECT COUNT(*) FROM passages_vec").fetchone()[0] == 0


def test_build_vectors_counts_truncated_passages(index):
    db, cache_path = index
    conn, cache = connect(db), open_cache(cache_path)

    class Long(FakeEmbedder):
        def count_tokens(self, text):
            return 600 if "Reverse" in text else 10
    emb = Long()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    out = build_vectors(conn, cache, emb.name)
    assert out == {"vectors": 3, "truncated": 1}


def test_dense_search_filters_by_contract_inside_the_knn(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    hits = search_dense(conn, emb.embed_query("termination fee"), contract_id="a", k=10)
    assert [h.contract_id for h in hits] == ["a", "a"]
    assert "Termination Fee" in DOCS["a"][hits[0].start:hits[0].end]
    assert hits[0].score >= hits[1].score
    everywhere = search_dense(conn, emb.embed_query("termination fee"), k=10)
    assert {h.contract_id for h in everywhere} == {"a", "b"}


def test_dense_search_returns_fewer_hits_than_k_for_a_small_contract(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    assert len(search_dense(conn, emb.embed_query("fee"), contract_id="b", k=50)) == 1
```

`tests/test_models.py` (real model; runs only with `-m model`):

```python
import pytest

from retrieval.models import EMBED_DIM, MAX_TOKENS, Embedder

pytestmark = pytest.mark.model


def test_real_embedder_shapes_and_untruncated_token_count():
    e = Embedder()
    [v] = e.embed_passages(["The Company shall pay the Termination Fee."])
    assert len(v) == EMBED_DIM and len(e.embed_query("termination fee")) == EMBED_DIM
    assert e.count_tokens("fee " * 700) > MAX_TOKENS
```

- [ ] **Step 4: Run the tests to verify they fail**

Run: `uv run pytest tests/test_vectors.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval.dense'`

- [ ] **Step 5: Implement**

`retrieval/models.py`:

```python
import time

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
MAX_TOKENS = 512
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RERANKERS = ("BAAI/bge-reranker-base", "Xenova/ms-marco-MiniLM-L-6-v2", "jinaai/jina-reranker-v1-tiny-en")


class Embedder:
    def __init__(self, name: str = EMBED_MODEL, threads: int | None = None):
        self.name = name
        self._threads = threads
        self._model = None

    def _m(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.name, threads=self._threads)
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._m().embed(texts, batch_size=16)]

    def embed_query(self, q: str) -> list[float]:
        return [float(x) for x in next(iter(self._m().embed([QUERY_PREFIX + q])))]

    def count_tokens(self, text: str) -> int:
        tok = self._m().model.tokenizer
        tok.no_truncation()
        try:
            return len(tok.encode(text).ids)
        finally:
            tok.enable_truncation(MAX_TOKENS)


class Reranker:
    def __init__(self, name: str, threads: int | None = None):
        self.name = name
        self._threads = threads
        self._model = None

    def score(self, query: str, texts: list[str]) -> tuple[list[float], float]:
        """Scores in input order and the milliseconds the model took."""
        if not texts:
            return [], 0.0
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(self.name, threads=self._threads)
        t0 = time.perf_counter()
        scores = [float(s) for s in self._model.rerank(query, texts, batch_size=len(texts))]
        return scores, (time.perf_counter() - t0) * 1000.0
```

`retrieval/vectors.py`:

```python
import hashlib
import sqlite3
from pathlib import Path

import sqlite_vec

from retrieval.models import EMBED_DIM, MAX_TOKENS

CACHE_SCHEMA = ("CREATE TABLE IF NOT EXISTS emb(model TEXT NOT NULL, sha1 TEXT NOT NULL, n_tokens INTEGER NOT NULL,"
                " vec BLOB NOT NULL, PRIMARY KEY(model, sha1))")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def open_cache(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(path)
    cache.execute(CACHE_SCHEMA)
    cache.commit()
    return cache


def indexed_passages(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    return conn.execute(
        "SELECT p.passage_id, p.contract_id, f.text FROM passages p"
        " JOIN passages_fts f ON f.rowid = p.passage_id ORDER BY p.passage_id").fetchall()


def fill_cache(cache: sqlite3.Connection, embedder, texts: list[str], batch: int = 32, on_batch=None) -> dict:
    """Embed every text not yet cached for this model. Commits after each batch, so a kill loses one batch."""
    have = {r[0] for r in cache.execute("SELECT sha1 FROM emb WHERE model = ?", (embedder.name,))}
    distinct = {sha1(t): t for t in texts}
    todo = [t for h, t in distinct.items() if h not in have]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        vecs = embedder.embed_passages(chunk)
        cache.executemany(
            "INSERT OR REPLACE INTO emb VALUES (?, ?, ?, ?)",
            [(embedder.name, sha1(t), embedder.count_tokens(t), sqlite_vec.serialize_float32(v))
             for t, v in zip(chunk, vecs)])
        cache.commit()
        if on_batch:
            on_batch(i + len(chunk), len(todo))
    return {"embedded": len(todo), "cached": len(distinct) - len(todo)}


def build_vectors(conn: sqlite3.Connection, cache: sqlite3.Connection, model: str, dim: int = EMBED_DIM) -> dict:
    """(Re)create passages_vec from the cache. Refuses, leaving it empty, if any passage is missing."""
    conn.execute("DROP TABLE IF EXISTS passages_vec")
    conn.execute(f"CREATE VIRTUAL TABLE passages_vec USING vec0(passage_id integer primary key,"
                 f" contract_id text partition key, embedding float[{dim}] distance_metric=cosine)")
    rows, missing, truncated = [], 0, 0
    for pid, cid, text in indexed_passages(conn):
        got = cache.execute("SELECT vec, n_tokens FROM emb WHERE model = ? AND sha1 = ?", (model, sha1(text))).fetchone()
        if got is None:
            missing += 1
            continue
        rows.append((pid, cid, got[0]))
        truncated += got[1] > MAX_TOKENS
    if missing:
        conn.commit()
        raise ValueError(f"{missing} passages have no cached embedding for {model}; run `dtd embed` to finish")
    conn.executemany("INSERT INTO passages_vec(passage_id, contract_id, embedding) VALUES (?, ?, ?)", rows)
    conn.execute("CREATE TABLE IF NOT EXISTS vec_meta(model TEXT NOT NULL, vectors INTEGER NOT NULL,"
                 " truncated INTEGER NOT NULL)")
    conn.execute("DELETE FROM vec_meta")
    conn.execute("INSERT INTO vec_meta VALUES (?, ?, ?)", (model, len(rows), truncated))
    conn.commit()
    return {"vectors": len(rows), "truncated": truncated}
```

`retrieval/dense.py`:

```python
import sqlite3

import sqlite_vec

from retrieval.bm25 import Hit


def search_dense(conn: sqlite3.Connection, qvec: list[float], contract_id: str | None = None, k: int = 10) -> list[Hit]:
    """Nearest passages by cosine. The contract filter is the vec0 partition key, so it runs inside the KNN."""
    where = "embedding MATCH ? AND k = ?"
    params: list = [sqlite_vec.serialize_float32(qvec), k]
    if contract_id is not None:
        where += " AND contract_id = ?"
        params.append(contract_id)
    sql = ("SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, 1.0 - v.distance"
           f" FROM (SELECT passage_id, distance FROM passages_vec WHERE {where}) v"
           " JOIN passages p ON p.passage_id = v.passage_id ORDER BY v.distance, p.passage_id")
    return [Hit(*row) for row in conn.execute(sql, params)]
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q` then `uv run pytest -m model -q`
Expected: all pass. The second command downloads bge-small once (about 130 MB) and passes.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock pipeline/paths.py retrieval/models.py retrieval/vectors.py retrieval/dense.py tests/fakes.py tests/test_vectors.py tests/test_models.py
git commit -m "m2: resumable embedding cache, sqlite-vec table partitioned by contract, dense search (R2)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Fusion, the reranker cache and the ladder (R1–R4)

**Files:**
- Create: `retrieval/hybrid.py`, `retrieval/rerank_cache.py`, `retrieval/ladder.py`
- Modify: `retrieval/bm25.py`
- Test: `tests/test_hybrid.py`, `tests/test_ladder.py`

**Interfaces:**
- Consumes: `retrieval.dense.search_dense`, `retrieval.result.Retrieved`, `CONTEXT_K`, `tests.fakes`.
- Produces: `retrieval.bm25.search(conn, query, contract_id=None, k=10, table="passages_fts")`, where `table` is one of `FTS_TABLES = ("passages_fts", "passages_x_fts")`. R1's default call is unchanged.
- Produces: `retrieval.hybrid.rrf(rankings: list[list[Hit]], k0: int = 60, k: int = 10) -> list[Hit]`. The fused score is the sum of `1 / (k0 + rank)`; ties go to the lower `passage_id`.
- Produces: `retrieval.rerank_cache.CachedReranker(inner, path: Path)` with `.name` and `.score(query, texts) -> tuple[list[float], float]`. A cache hit returns the stored scores and the compute milliseconds recorded when they were first computed.
- Produces: `retrieval.ladder.RUNGS = ("R1", "R2", "R3", "R4", "R5", "R6")`, `Settings(depth=50, rrf_k0=60, reranker="BAAI/bge-reranker-base", rerank_depth=20)`, `SETTINGS_PATH`, `load_settings(path=SETTINGS_PATH) -> Settings`.
- Produces: `retrieval.ladder.Ladder(conn, texts: dict[str, str], embedder=None, reranker=None, lexicon: dict | None = None, settings: Settings = Settings())` with `.run(rung: str, query: str, contract_id: str | None = None, k: int = 10, rewritten: str | None = None) -> Retrieved`, and attributes `.embedder`, `.lexicon`, `.settings`.

What each rung does in `Ladder.run`:

| Rung | Retrieval legs | Query for the legs | Reranker | Shown context |
|---|---|---|---|---|
| R1 | BM25 over `passages_fts` | as given | none | passage |
| R2 | dense | as given | none | passage |
| R3 | RRF of BM25 and dense, each to `depth` | as given | none | passage |
| R4 | R3 | as given | top `rerank_depth` of R3, original query | passage |
| R5 | R4 | lexicon rewrite (or `rewritten` if passed) | original query | passage |
| R6 | R5, BM25 leg over `passages_x_fts` | as R5 | original query, passage text only | passage plus its definitions |

The reranker sees the original query because the rewrite is a keyword expansion made for matching, not a sentence a cross-encoder reads well. Latency: the wall time of the call, with any cached reranker call replaced by the compute time recorded when it first ran. The cache exists so that tuning and reruns are resumable without faking speed.

(R5 and R6 need Tasks 7 and 9. This task implements their branches, and their tests arrive with those tasks.)

- [ ] **Step 1: Write the failing tests**

`tests/test_hybrid.py`:

```python
from retrieval.bm25 import Hit
from retrieval.hybrid import rrf


def h(pid):
    return Hit(pid, "c", pid * 10, pid * 10 + 5, 0.0)


def test_rrf_rewards_agreement_between_lists():
    fused = rrf([[h(1), h(2), h(3)], [h(3), h(1), h(4)]], k0=60, k=10)
    assert [x.passage_id for x in fused][:2] == [1, 3]
    assert fused[0].score == 1 / 61 + 1 / 62


def test_rrf_breaks_ties_by_passage_id_and_truncates():
    fused = rrf([[h(5)], [h(2)]], k0=60, k=1)
    assert [x.passage_id for x in fused] == [2]


def test_rrf_of_nothing_is_nothing():
    assert rrf([[], []]) == []
```

`tests/test_ladder.py`:

```python
import pytest

from retrieval.index import build_index
from retrieval.ladder import RUNGS, Ladder, Settings
from retrieval.rerank_cache import CachedReranker
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder, FakeReranker

DOCS = {
    "big": (
        "ARTICLE I\nDEFINITIONS\n\n"
        "Section 1.1 Definitions. “Company Termination Fee” means an amount in cash equal to $50,000,000.\n\n"
        "Section 1.2 Closing. The closing shall occur at the offices of counsel.\n\n"
        "Section 8.3 Fees. The Company shall pay Parent the Company Termination Fee if this Agreement is terminated.\n\n"
        "Section 8.4 Expenses. Each party shall bear its own expenses.\n"
    ),
    "tiny": "Section 1.1 Fees. Parent shall pay a fee.\n",
}


@pytest.fixture
def ladder(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, DOCS)
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    rr = CachedReranker(FakeReranker(ms=7.0), tmp_path / "rerank.db")
    lexicon = {"walk-away payment": ["Termination Fee"]}
    return Ladder(conn, DOCS, emb, rr, lexicon, Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3))


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
def test_every_rung_stays_inside_the_contract(ladder, rung):
    got = ladder.run(rung, "termination fee", "big", k=10)
    assert got.hits and all(h.contract_id == "big" for h in got.hits)
    assert len(got.context) == min(5, len(got.hits))
    assert got.ms >= 0


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
@pytest.mark.parametrize("query", ["", "   ", "?!", '"'])
def test_queries_without_words_return_empty_lists(ladder, rung, query):
    assert ladder.run(rung, query, "big", k=10).hits == []


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
@pytest.mark.parametrize("query", ["AND OR NOT", 'what\'s the "fee"?', "NEAR(fee closing)", "fee*"])
def test_fts_operators_in_queries_are_inert(ladder, rung, query):
    got = ladder.run(rung, query, "big", k=10)
    assert isinstance(got.hits, list) and all(h.contract_id == "big" for h in got.hits)


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
def test_a_contract_smaller_than_the_depth_returns_what_it_has(ladder, rung):
    assert len(ladder.run(rung, "fee", "tiny", k=10).hits) == 1


def test_r4_orders_the_head_by_reranker_score(ladder):
    got = ladder.run("R4", "Company Termination Fee terminated", "big", k=10)
    scores = [h.score for h in got.hits[:3]]
    assert scores == sorted(scores, reverse=True)


def test_r4_latency_uses_recorded_compute_time_on_a_cache_hit(ladder):
    first = ladder.run("R4", "termination fee", "big", k=10)
    again = ladder.run("R4", "termination fee", "big", k=10)
    assert ladder.reranker.inner.calls == 1
    assert again.ms >= 7.0 and abs(again.ms - first.ms) < 50


def test_unknown_rung_is_refused(ladder):
    with pytest.raises(ValueError, match="unknown rung"):
        ladder.run("R9", "fee", "big")


def test_rungs_are_the_spec_ladder():
    assert RUNGS == ("R1", "R2", "R3", "R4", "R5", "R6")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_hybrid.py tests/test_ladder.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval.hybrid'`

- [ ] **Step 3: Implement**

In `retrieval/bm25.py`, add `FTS_TABLES = ("passages_fts", "passages_x_fts")` and change `search`:

```python
def search(conn: sqlite3.Connection, query: str, contract_id: str | None = None, k: int = 10,
           table: str = "passages_fts") -> list[Hit]:
    if table not in FTS_TABLES:
        raise ValueError(f"unknown FTS table {table!r}")
    match = fts_query(query)
    if not match:
        return []
    sql = (
        f"SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, -bm25({table})"
        f" FROM {table} JOIN passages p ON p.passage_id = {table}.rowid"
        f" WHERE {table} MATCH ?"
    )
    params: list = [match]
    if contract_id is not None:
        sql += " AND p.contract_id = ?"
        params.append(contract_id)
    sql += f" ORDER BY bm25({table}), p.passage_id LIMIT ?"
    params.append(k)
    return [Hit(*row) for row in conn.execute(sql, params)]
```

(Moving the contract filter inside MATCH is M3's job; this task does not change R1's query.)

`retrieval/hybrid.py`:

```python
from collections import defaultdict
from dataclasses import replace

from retrieval.bm25 import Hit


def rrf(rankings: list[list[Hit]], k0: int = 60, k: int = 10) -> list[Hit]:
    score: dict[int, float] = defaultdict(float)
    first: dict[int, Hit] = {}
    for ranking in rankings:
        for rank, h in enumerate(ranking, start=1):
            score[h.passage_id] += 1.0 / (k0 + rank)
            first.setdefault(h.passage_id, h)
    order = sorted(score, key=lambda pid: (-score[pid], pid))
    return [replace(first[pid], score=score[pid]) for pid in order[:k]]
```

`retrieval/rerank_cache.py`:

```python
import json
import sqlite3
from pathlib import Path

from retrieval.vectors import sha1


class CachedReranker:
    """Reranker scores keyed by model, query and the exact candidate texts; committed per query."""

    def __init__(self, inner, path: Path):
        self.inner = inner
        self.name = inner.name
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS rr(model TEXT NOT NULL, key TEXT NOT NULL, scores TEXT NOT NULL,"
                         " ms REAL NOT NULL, PRIMARY KEY(model, key))")
        self._db.commit()

    def score(self, query: str, texts: list[str]) -> tuple[list[float], float]:
        if not texts:
            return [], 0.0
        key = sha1(query + "\x00" + "\x01".join(sha1(t) for t in texts))
        row = self._db.execute("SELECT scores, ms FROM rr WHERE model = ? AND key = ?", (self.name, key)).fetchone()
        if row:
            return json.loads(row[0]), row[1]
        scores, ms = self.inner.score(query, texts)
        self._db.execute("INSERT OR REPLACE INTO rr VALUES (?, ?, ?, ?)", (self.name, key, json.dumps(scores), ms))
        self._db.commit()
        return scores, ms
```

`retrieval/ladder.py`:

```python
import json
import time
from dataclasses import dataclass, replace
from pathlib import Path

from retrieval import bm25
from retrieval.dense import search_dense
from retrieval.hybrid import rrf
from retrieval.lexicon import rewrite
from retrieval.result import CONTEXT_K, Retrieved

RUNGS = ("R1", "R2", "R3", "R4", "R5", "R6")
SETTINGS_PATH = Path(__file__).with_name("settings.json")


@dataclass(frozen=True)
class Settings:
    depth: int = 50
    rrf_k0: int = 60
    reranker: str = "BAAI/bge-reranker-base"
    rerank_depth: int = 20


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    return Settings(**json.loads(path.read_text(encoding="utf-8"))["settings"])


class Ladder:
    def __init__(self, conn, texts: dict[str, str], embedder=None, reranker=None, lexicon: dict | None = None,
                 settings: Settings = Settings()):
        self.conn = conn
        self.texts = texts
        self.embedder = embedder
        self.reranker = reranker
        self.lexicon = lexicon
        self.settings = settings

    def _passage(self, h) -> str:
        return self.texts[h.contract_id][h.start:h.end]

    def _shown(self, h, with_defs: bool) -> str:
        text = self._passage(h)
        if not with_defs:
            return text
        defs = [self.texts[h.contract_id][s:e] for s, e in self.conn.execute(
            "SELECT def_start, def_end FROM passage_defs WHERE passage_id = ? ORDER BY rank", (h.passage_id,))]
        return "\n\n".join([text] + defs)

    def _dense(self, q: str, contract_id: str | None, k: int):
        if not bm25.TOKEN.search(q):
            return []
        return search_dense(self.conn, self.embedder.embed_query(q), contract_id, k)

    def run(self, rung: str, query: str, contract_id: str | None = None, k: int = 10,
            rewritten: str | None = None) -> Retrieved:
        if rung not in RUNGS:
            raise ValueError(f"unknown rung {rung!r}; expected one of {RUNGS}")
        n = RUNGS.index(rung) + 1
        if n >= 5 and rewritten is None and self.lexicon is None:
            raise ValueError("R5 and R6 need the lexicon; run `dtd lexicon` first")
        t0 = time.perf_counter()
        adjust = 0.0
        q = query if n < 5 else (rewritten if rewritten is not None else rewrite(query, self.lexicon))
        table = "passages_x_fts" if n == 6 else "passages_fts"
        if n == 1:
            hits = bm25.search(self.conn, q, contract_id, k)
        elif n == 2:
            hits = self._dense(q, contract_id, k)
        else:
            depth = max(k, self.settings.depth)
            legs = [bm25.search(self.conn, q, contract_id, depth, table=table), self._dense(q, contract_id, depth)]
            fused = rrf(legs, self.settings.rrf_k0, 2 * depth)
            if n == 3:
                hits = fused[:k]
            else:
                head = fused[:self.settings.rerank_depth]
                t1 = time.perf_counter()
                scores, compute_ms = self.reranker.score(query, [self._passage(h) for h in head])
                adjust += compute_ms - (time.perf_counter() - t1) * 1000.0
                order = sorted(range(len(head)), key=lambda i: (-scores[i], head[i].passage_id))
                hits = ([replace(head[i], score=scores[i]) for i in order] + fused[len(head):])[:k]
        ms = (time.perf_counter() - t0) * 1000.0 + adjust
        return Retrieved(hits, ms, [self._shown(h, n == 6) for h in hits[:CONTEXT_K]])
```

`retrieval/ladder.py` imports `retrieval.lexicon.rewrite`, which Task 7 writes. Create it now as the identity so this task stands alone. Task 7 replaces it:

```python
def rewrite(query: str, lexicon: dict) -> str:
    return query
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. M1's BM25 tests are unchanged.

- [ ] **Step 5: Commit**

```bash
git add retrieval/bm25.py retrieval/hybrid.py retrieval/rerank_cache.py retrieval/ladder.py retrieval/lexicon.py tests/test_hybrid.py tests/test_ladder.py
git commit -m "m2: RRF hybrid, cached reranker and the ladder (R1-R4)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: `dtd embed` and `dtd eval --rung`

**Files:**
- Modify: `pipeline/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: everything from Tasks 3–5.
- Produces: `pipeline.cli._models() -> tuple[Embedder, Callable[[str], Reranker]]`, the one place the CLI makes real models. Tests monkeypatch it with fakes.
- Produces: `dtd build [--fixed]` (`--fixed` arrives in Task 11), `dtd embed [--fixed]`, `dtd eval [--rung R1|R2|R3|R4|R5|R6|R3-fixed|R5-llm|corpus]` (default `R1`). Task 6 wires `R1`–`R4`; later tasks add the rest to the same dispatch.
- Every rung, R1 included, runs through `Ladder` and `evaluate`, with context tokens counted by the embedder's tokenizer. R1's scores are the same as M1's because R1 is the same `bm25.search` call.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cli.py`, extend the `data` fixture with:

```python
    from tests.fakes import FakeEmbedder, FakeReranker
    monkeypatch.setattr(cli, "INDEX_FIXED", tmp_path / "index" / "maud_fixed.db")
    monkeypatch.setattr(cli, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cli, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(cli, "LEXICON_PATH", tmp_path / "lexicon.json")
    monkeypatch.setattr(cli, "_models", lambda: (FakeEmbedder(), lambda name: FakeReranker()))
```

and add:

```python
def test_embed_then_every_ladder_rung_evaluates(data):
    assert cli.entry(["build"]) == 0
    assert cli.entry(["embed"]) == 0
    for rung in ("R1", "R2", "R3", "R4"):
        assert cli.entry(["eval", "--rung", rung]) == 0
        result = json.loads((data / "out" / f"{rung.lower()}.json").read_text())
        assert result["rung"] == rung and result["context_tokens"]["mean"] > 0


def test_eval_of_a_dense_rung_before_embed_fails_clearly(data, capsys):
    cli.entry(["build"])
    assert cli.entry(["eval", "--rung", "R2"]) == 2
    assert "dtd embed" in capsys.readouterr().err


def test_embed_twice_embeds_nothing_the_second_time(data, capsys):
    cli.entry(["build"])
    cli.entry(["embed"])
    capsys.readouterr()
    assert cli.entry(["embed"]) == 0
    assert json.loads(capsys.readouterr().out)["embedded"] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL (no `embed` command, no `--rung`).

- [ ] **Step 3: Implement**

In `pipeline/cli.py`, add the imports:

```python
from dataclasses import asdict

from evals.run_rung import evaluate, load_context
from pipeline.paths import CACHE, INDEX_FIXED
from retrieval import vectors
from retrieval.ladder import RUNGS, SETTINGS_PATH, Ladder, load_settings
from retrieval.lexicon import LEXICON_PATH, load_lexicon
from retrieval.models import Embedder, Reranker
from retrieval.rerank_cache import CachedReranker
```

(`LEXICON_PATH` and `load_lexicon` are written in Task 7. Add them to `retrieval/lexicon.py` now: `LEXICON_PATH = Path(__file__).with_name("lexicon.json")`, with `load_lexicon(path=LEXICON_PATH)` returning `json.loads(Path(path).read_text(encoding="utf-8"))["entries"]`.)

Then:

```python
def _models():
    return Embedder(), Reranker


def _has_vectors(db: Path) -> bool:
    conn = vectors.connect(db)
    row = conn.execute("SELECT name FROM sqlite_master WHERE name = 'vec_meta'").fetchone()
    return bool(row) and conn.execute("SELECT vectors FROM vec_meta").fetchone()[0] > 0


def _cmd_embed(args) -> int:
    db = INDEX_FIXED if args.fixed else INDEX
    if not db.exists():
        print(f"{db} missing; run `dtd build{' --fixed' if args.fixed else ''}` first", file=sys.stderr)
        return 2
    embedder, _ = _models()
    conn = vectors.connect(db)
    cache = vectors.open_cache(CACHE / "embeddings.db")
    texts = [t for _, _, t in vectors.indexed_passages(conn)]
    summary = vectors.fill_cache(cache, embedder, texts,
                                 on_batch=lambda done, n: print(f"embedded {done}/{n}", file=sys.stderr, flush=True))
    summary |= vectors.build_vectors(conn, cache, embedder.name)
    print(json.dumps(summary))
    return 0


def _ladder(db: Path, texts: dict[str, str]) -> Ladder:
    embedder, make_reranker = _models()
    settings = load_settings(SETTINGS_PATH)
    reranker = CachedReranker(make_reranker(settings.reranker), CACHE / "rerank.db")
    lexicon = load_lexicon(LEXICON_PATH) if LEXICON_PATH.exists() else None
    return Ladder(vectors.connect(db), texts, embedder, reranker, lexicon, settings)


def _eval_rung(rung: str, db: Path, name: str, ctx, **kw) -> dict:
    ladder = _ladder(db, ctx.texts)
    return evaluate(ctx, name, lambda q, c, k: ladder.run(rung, q, c, k), OUT,
                    count_tokens=ladder.embedder.count_tokens,
                    extra={"settings": asdict(ladder.settings)}, **kw)


def _cmd_eval(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    rung = args.rung
    if rung != "R1" and not _has_vectors(INDEX):
        print("no vectors in the index; run `dtd embed` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    if rung in RUNGS:
        result = _eval_rung(rung, INDEX, rung, ctx)
    else:
        print(f"unknown rung {rung}", file=sys.stderr)
        return 2
    print(json.dumps(result["overall"], indent=2))
    return 0
```

In `entry`, register:

```python
    embed = sub.add_parser("embed")
    embed.add_argument("--fixed", action="store_true")
    embed.set_defaults(fn=_cmd_embed)
    ev = sub.add_parser("eval")
    ev.add_argument("--rung", default="R1")
    ev.set_defaults(fn=_cmd_eval)
```

(and remove the old `sub.add_parser("eval")` line). `_cmd_facts` still reads `OUT / "r1.json"`, which `dtd eval` keeps writing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, including M1's CLI chain test (now with fakes).

- [ ] **Step 5: Commit**

```bash
git add pipeline/cli.py retrieval/lexicon.py tests/test_cli.py
git commit -m "m2: dtd embed and dtd eval --rung for R1-R4

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 7: The lexicon and rung R5

**Files:**
- Create: `pipeline/claude.py`, `pipeline/build_lexicon.py`
- Modify: `retrieval/lexicon.py` (replace the identity stub), `pipeline/cli.py`
- Test: `tests/test_lexicon.py`, `tests/test_build_lexicon.py`, `tests/test_ladder.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `pipeline.claude.run_claude(prompt: str, model: str, timeout: int = 900) -> dict`, the parsed `--output-format json` result of `claude -p` (keys used: `result`, `usage`, `duration_api_ms`). This is the only function in the repo that starts `claude`.
- Produces: `retrieval.lexicon.LEXICON_PATH`, `load_lexicon(path=LEXICON_PATH) -> dict[str, list[str]]`, `rewrite(query: str, lexicon: dict[str, list[str]]) -> str`.
- Produces: `pipeline.build_lexicon.LEXICON_MODEL = "claude-opus-5-5"`, `TOP_TERMS = 400`, `vocabulary(conn, top: int = TOP_TERMS) -> list[str]`, `prompt(vocab: list[str]) -> str`, `parse(result_text: str, tune_texts: list[str]) -> dict[str, list[str]]`, `build(conn, tune_texts: list[str], out_path: Path, runner=run_claude, model: str = LEXICON_MODEL) -> dict`.
- Produces: `dtd lexicon`, which writes `retrieval/lexicon.json`:

```json
{"_meta": {"built_by": "machine", "model": "claude-opus-5-5", "built_on": "YYYY-MM-DD",
           "source": "defined terms of the tune-split MAUD agreements", "saw_eval_queries": false,
           "usage": {}},
 "entries": {"break-up fee": ["Termination Fee", "Company Termination Fee"]}}
```

How the lexicon is kept honest:
1. **Blind to the eval.** The prompt gets defined terms from tune-split agreements only, and never sees a MAUD deal-point name, a question, or anything from the report split. `prompt` takes only the vocabulary, so it cannot leak by accident.
2. **Grounded.** An expansion is kept only if it occurs verbatim (case-insensitive) in some tune-split agreement.
3. **Labelled.** It is machine-built and says so in `_meta`, and the report labels R5 "machine-built lexicon".

The remaining limit, stated in the report: the model has read about merger agreements and may know MAUD. The lexicon is committed, so a reader can inspect it.

The rewrite is deterministic. For each lexicon phrase found in the query (lowercase, whole words, longest phrase first), it appends the phrase's expansions that are not already in the query. The query is otherwise unchanged.

**The queries note (goes in the M2 report).** R1's queries are MAUD's own deal-point and question names, which are already contract vocabulary. R5 is measured against that baseline on the same queries, so a small or zero R5 gain on T-human says little about lay questions. Lay questions arrive with M3's machine-built set.

- [ ] **Step 1: Write the failing tests**

`tests/test_lexicon.py`:

```python
from retrieval.lexicon import rewrite

LEX = {
    "break-up fee": ["Termination Fee", "Company Termination Fee"],
    "fee": ["Expenses"],
    "stock options": ["Company Options"],
}


def test_rewrite_appends_expansions_for_phrases_found():
    assert rewrite("What is the break-up fee?", LEX) == "What is the break-up fee? Termination Fee Company Termination Fee Expenses"


def test_rewrite_matches_whole_words_case_insensitively():
    assert rewrite("STOCK OPTIONS vesting", LEX) == "STOCK OPTIONS vesting Company Options"
    assert rewrite("feeling fine", LEX) == "feeling fine"


def test_rewrite_skips_terms_already_in_the_query_and_never_repeats():
    assert rewrite("termination fee and break-up fee", LEX) == \
        "termination fee and break-up fee Company Termination Fee Expenses"


def test_rewrite_with_no_match_or_empty_lexicon_is_the_identity():
    assert rewrite("Knowledge Definition", LEX) == "Knowledge Definition"
    assert rewrite("", LEX) == ""
    assert rewrite("break-up fee", {}) == "break-up fee"
```

`tests/test_build_lexicon.py`:

```python
import inspect
import json
import sqlite3

from evals.bootstrap import split_of
from pipeline.build_lexicon import build, parse, prompt, vocabulary
from retrieval.index import build_index
from tests.fakes import fake_claude

TUNE = [c for c in (f"contract_{i}" for i in range(60)) if split_of(c) == "tune"][:2]
REPORT = [c for c in (f"contract_{i}" for i in range(60)) if split_of(c) == "report"][:1]


def docs():
    d = {c: f"Section 1.1 Fees. “Company Termination Fee” means $1. “Tune Only {i}” means x.\n"
         for i, c in enumerate(TUNE)}
    d[REPORT[0]] = "Section 1.1 Fees. “Report Secret Term” means y.\n"
    return d


def test_vocabulary_comes_from_tune_split_agreements_only(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, docs())
    vocab = vocabulary(sqlite3.connect(db))
    assert vocab[0] == "Company Termination Fee"
    assert "Report Secret Term" not in vocab


def test_prompt_sees_only_the_vocabulary():
    assert list(inspect.signature(prompt).parameters) == ["vocab"]
    assert "Company Termination Fee" in prompt(["Company Termination Fee"])


def test_parse_keeps_only_grounded_expansions_and_tolerates_prose():
    text = 'Here you go:\n{"break-up fee": ["Company Termination Fee", "Invented Phrase"], "x": ["Fee"], "bad": 3}\nDone.'
    assert parse(text, ["The Company Termination Fee is due."]) == {"break-up fee": ["Company Termination Fee"]}


def test_build_writes_a_machine_labelled_lexicon(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, docs())
    runner = fake_claude('{"break-up fee": ["Company Termination Fee"]}')
    out = tmp_path / "lexicon.json"
    doc = build(sqlite3.connect(db), list(docs()[c] for c in TUNE), out, runner=runner, model="m")
    assert json.loads(out.read_text()) == doc
    assert doc["_meta"]["built_by"] == "machine" and doc["_meta"]["saw_eval_queries"] is False
    assert doc["entries"] == {"break-up fee": ["Company Termination Fee"]}
    assert len(runner.calls) == 1 and "Report Secret Term" not in runner.calls[0][0]
```

Append to `tests/test_ladder.py`:

```python
def test_r5_finds_the_clause_through_the_lexicon(ladder):
    plain = ladder.run("R1", "walk-away payment", "big", k=3)
    assert not any("Termination Fee" in DOCS["big"][h.start:h.end] for h in plain.hits)
    got = ladder.run("R5", "walk-away payment", "big", k=3)
    assert any("Termination Fee" in DOCS["big"][h.start:h.end] for h in got.hits)


def test_r5_without_a_lexicon_is_refused(ladder):
    ladder.lexicon = None
    with pytest.raises(ValueError, match="dtd lexicon"):
        ladder.run("R5", "fee", "big")
```

Append to `tests/test_cli.py`:

```python
def test_lexicon_command_writes_the_lexicon_and_r5_then_runs(data, monkeypatch):
    from tests.fakes import fake_claude
    monkeypatch.setattr(cli, "run_claude", fake_claude('{"cash deal": ["Type of Consideration"]}'))
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["lexicon"]) == 0
    assert json.loads((data / "lexicon.json").read_text())["_meta"]["built_by"] == "machine"
    assert cli.entry(["eval", "--rung", "R5"]) == 0
```

(The CLI fixture's contracts may all fall in the report split, leaving the tune vocabulary empty. `build` then skips the model call and writes empty `entries`, and the test holds either way.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_lexicon.py tests/test_build_lexicon.py tests/test_ladder.py -q`
Expected: FAIL (identity rewrite; no `pipeline.build_lexicon`).

- [ ] **Step 3: Implement**

`pipeline/claude.py`:

```python
import json
import subprocess


def run_claude(prompt: str, model: str, timeout: int = 900) -> dict:
    """One non-interactive `claude -p` call on the Max plan; $0 cash. Raises on a non-zero exit."""
    done = subprocess.run(["claude", "-p", "--model", model, "--output-format", "json"],
                          input=prompt, capture_output=True, text=True, timeout=timeout, check=True)
    return json.loads(done.stdout)
```

Before writing it, run `claude -p --help` and confirm that `--model` and `--output-format json` are spelled this way in the installed version (2.1.286 on 2026-09-30). If they differ, use the installed spelling and say so in the commit message.

`retrieval/lexicon.py`:

```python
import json
import re
from functools import lru_cache
from pathlib import Path

LEXICON_PATH = Path(__file__).with_name("lexicon.json")


def load_lexicon(path: Path = LEXICON_PATH) -> dict[str, list[str]]:
    return json.loads(Path(path).read_text(encoding="utf-8"))["entries"]


@lru_cache(maxsize=4096)
def _pattern(phrase: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])" + re.escape(phrase.lower()) + r"(?![a-z0-9])")


def rewrite(query: str, lexicon: dict[str, list[str]]) -> str:
    low = query.lower()
    extra: list[str] = []
    for phrase in sorted(lexicon, key=lambda p: (-len(p), p)):
        if _pattern(phrase).search(low):
            for term in lexicon[phrase]:
                if not _pattern(term).search(low) and term not in extra:
                    extra.append(term)
    return query if not extra else query + " " + " ".join(extra)
```

(`test_rewrite_skips_terms_already_in_the_query_and_never_repeats` relies on "Termination Fee" being found in "termination fee and …" as whole words, so it is skipped.)

`pipeline/build_lexicon.py`:

```python
import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from evals.bootstrap import split_of
from pipeline.claude import run_claude

LEXICON_MODEL = "claude-opus-5-5"
TOP_TERMS = 400
PROMPT = """You are building a search lexicon for merger agreements (agreements and plans of merger for acquisitions of US public companies).

People ask questions in everyday words. The agreements use their own vocabulary. Map everyday words and phrases to the words a merger agreement uses for the same thing.

Here are defined terms that occur in merger agreements, most common first:
{terms}

Write between 150 and 300 entries. Each key is an everyday word or short phrase that a non-lawyer, or a lawyer using shorthand or an abbreviation, might type. Each value is a list of one to six words or phrases that appear in merger agreements, preferring the defined terms above where they fit. Cover the whole of a typical merger agreement: the merger and its consideration, employee equity awards, representations and warranties, covenants, closing conditions, termination and termination fees, earn-outs and contingent value rights, remedies and definitions.

Output one JSON object and nothing else."""


def vocabulary(conn: sqlite3.Connection, top: int = TOP_TERMS) -> list[str]:
    """Defined terms by the number of tune-split agreements that define them."""
    df: Counter = Counter()
    for cid, term in conn.execute("SELECT DISTINCT contract_id, term FROM terms WHERE style IN ('means', 'paren')"):
        if split_of(cid) == "tune":
            df[term] += 1
    return [t for t, _ in sorted(df.items(), key=lambda x: (-x[1], x[0]))[:top]]


def prompt(vocab: list[str]) -> str:
    return PROMPT.format(terms="\n".join(vocab))


def parse(result_text: str, tune_texts: list[str]) -> dict[str, list[str]]:
    m = re.search(r"\{.*\}", result_text, re.S)
    raw = json.loads(m.group(0)) if m else {}
    corpus = "\n".join(tune_texts).lower()
    out: dict[str, list[str]] = {}
    for phrase, terms in raw.items():
        key = phrase.strip().lower()
        if len(key) < 3 or not isinstance(terms, list):
            continue
        kept = [t.strip() for t in terms if isinstance(t, str) and t.strip() and t.strip().lower() in corpus]
        if kept:
            out[key] = list(dict.fromkeys(kept))
    return dict(sorted(out.items()))


def build(conn: sqlite3.Connection, tune_texts: list[str], out_path: Path, runner=run_claude,
          model: str = LEXICON_MODEL) -> dict:
    vocab = vocabulary(conn)
    resp = runner(prompt(vocab), model) if vocab else {"result": "{}", "usage": {}}
    doc = {
        "_meta": {"built_by": "machine", "model": model, "built_on": date.today().isoformat(),
                  "source": "defined terms of the tune-split MAUD agreements", "saw_eval_queries": False,
                  "usage": resp.get("usage", {})},
        "entries": parse(resp["result"], tune_texts),
    }
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return doc
```

In `pipeline/cli.py`:

```python
from evals.bootstrap import split_of
from pipeline.build_lexicon import build as build_lexicon
from pipeline.claude import run_claude


def _cmd_lexicon(args) -> int:
    if not INDEX.exists():
        print("index missing; run `dtd build` first", file=sys.stderr)
        return 2
    files = sorted((RAW / "contracts").glob("*.txt"))
    tune_texts = [load_contract(p) for p in files if split_of(p.stem) == "tune"]
    doc = build_lexicon(sqlite3.connect(INDEX), tune_texts, LEXICON_PATH, runner=run_claude)
    print(json.dumps({"entries": len(doc["entries"])}))
    return 0
```

Register `sub.add_parser("lexicon").set_defaults(fn=_cmd_lexicon)` and add `import sqlite3`. In `_cmd_eval`, before `ctx = load_context(...)`, add:

```python
    if rung in ("R5", "R6") and not LEXICON_PATH.exists():
        print("no lexicon; run `dtd lexicon` first", file=sys.stderr)
        return 2
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/claude.py pipeline/build_lexicon.py retrieval/lexicon.py pipeline/cli.py tests/test_lexicon.py tests/test_build_lexicon.py tests/test_ladder.py tests/test_cli.py
git commit -m "m2: machine-built lexicon blind to the eval queries, deterministic rewrite (R5)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The live-LLM rewrite comparison (offline, not a rung)

**Files:**
- Modify: `pipeline/ledger.py`
- Create: `evals/llm_rewrite.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_ledger.py`, `tests/test_llm_rewrite.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `pipeline.ledger.Ledger(path: Path, key: str = "url")`. Existing callers are unchanged.
- Produces: `evals.llm_rewrite.REWRITE_MODEL = "claude-haiku-4-5-20251001"` (the PRD's default answering model, so the comparison prices the live alternative), `PROMPT`, `clean(result_text: str, query: str) -> str`, `rewrite_all(queries: list[str], cache_path: Path, runner=run_claude, model: str = REWRITE_MODEL) -> dict[str, dict]`. Each value has `query, rewrite, input_tokens, output_tokens, api_ms`.
- Produces: `dtd rewrite` (fills `data/cache/llm_rewrites.jsonl`), then `dtd eval --rung R5-llm`. That is R5 with the LLM's rewrite in place of the lexicon's. Latency adds the recorded `api_ms`, and the result's `extra` carries the mean input and output tokens and the query count.

PRD §4.1: "the lexicon rewrite versus a live LLM rewrite (offline only, to show what the cheaper choice costs)". It is measured on the same items, and the report compares it with a paired bootstrap against R5.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_ledger.py`:

```python
def test_ledger_key_is_configurable(tmp_path):
    from pipeline.ledger import Ledger
    led = Ledger(tmp_path / "l.jsonl", key="query")
    led.put({"query": "fee", "rewrite": "termination fee"})
    assert Ledger(tmp_path / "l.jsonl", key="query").get("fee")["rewrite"] == "termination fee"
```

`tests/test_llm_rewrite.py`:

```python
from evals.llm_rewrite import clean, rewrite_all
from tests.fakes import fake_claude


def test_clean_takes_the_first_line_and_falls_back_to_the_query():
    assert clean('"Termination Fee payable by the Company"\nextra', "fee") == "Termination Fee payable by the Company"
    assert clean("  \n ", "fee") == "fee"


def test_rewrite_all_calls_once_per_distinct_query_and_resumes(tmp_path):
    runner = fake_claude("Company Termination Fee")
    cache = tmp_path / "rw.jsonl"
    out = rewrite_all(["fee", "fee", "options"], cache, runner=runner, model="m")
    assert set(out) == {"fee", "options"} and len(runner.calls) == 2
    assert out["fee"] == {"query": "fee", "rewrite": "Company Termination Fee", "input_tokens": 100,
                          "output_tokens": 20, "api_ms": 50}
    again = fake_claude("never used")
    assert rewrite_all(["fee", "options"], cache, runner=again, model="m") == out
    assert again.calls == []
```

Append to `tests/test_cli.py`:

```python
def test_r5_llm_runs_after_rewrite(data, monkeypatch):
    from tests.fakes import fake_claude
    monkeypatch.setattr(cli, "run_claude", fake_claude("Type of Consideration cash"))
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["eval", "--rung", "R5-llm"]) == 2
    assert cli.entry(["rewrite"]) == 0
    assert cli.entry(["eval", "--rung", "R5-llm"]) == 0
    result = json.loads((data / "out" / "r5_llm.json").read_text())
    assert result["extra"]["input_tokens_mean"] == 100 and result["latency_ms"]["p50"] >= 50
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_ledger.py tests/test_llm_rewrite.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

In `pipeline/ledger.py`, give `__init__` a `key: str = "url"` parameter, store it as `self.key`, and use `rec[self.key]` in both the loader and `put` in place of `rec["url"]`. Rename the `url` parameter of `get` to `key_value`. The docstring becomes "Append-only JSONL keyed by one field (`url` by default)."

`evals/llm_rewrite.py`:

```python
from pathlib import Path

from pipeline.claude import run_claude
from pipeline.ledger import Ledger

REWRITE_MODEL = "claude-haiku-4-5-20251001"
PROMPT = ("Rewrite this search query for finding the relevant clause in a merger agreement. Keep its meaning, "
          "and add the words a merger agreement would use for the same thing. Reply with the rewritten query "
          "only, on one line.\n\nQuery: {query}")


def clean(result_text: str, query: str) -> str:
    for line in result_text.splitlines():
        line = line.strip().strip('"').strip()
        if line:
            return line
    return query


def rewrite_all(queries: list[str], cache_path: Path, runner=run_claude, model: str = REWRITE_MODEL) -> dict[str, dict]:
    ledger = Ledger(Path(cache_path), key="query")
    out = {}
    for q in dict.fromkeys(queries):
        rec = ledger.get(q)
        if rec is None:
            resp = runner(PROMPT.format(query=q), model)
            usage = resp.get("usage", {})
            rec = {"query": q, "rewrite": clean(resp["result"], q),
                   "input_tokens": usage.get("input_tokens", 0), "output_tokens": usage.get("output_tokens", 0),
                   "api_ms": resp.get("duration_api_ms", 0)}
            ledger.put(rec)
        out[q] = rec
    return out
```

In `pipeline/cli.py` add `_cmd_rewrite` and the `R5-llm` branch:

```python
from evals.llm_rewrite import REWRITE_MODEL, rewrite_all
from retrieval.result import Retrieved

REWRITES = "llm_rewrites.jsonl"


def _cmd_rewrite(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    out = rewrite_all([i.query for i in ctx.items], CACHE / REWRITES, runner=run_claude)
    print(json.dumps({"queries": len(out)}))
    return 0
```

and inside `_cmd_eval`, before the `else` branch:

```python
    elif rung == "R5-llm":
        path = CACHE / REWRITES
        if not path.exists():
            print("no LLM rewrites; run `dtd rewrite` first", file=sys.stderr)
            return 2
        rewrites = rewrite_all([i.query for i in ctx.items], path, runner=_refuse_new_calls)
        ladder = _ladder(INDEX, ctx.texts)

        def retrieve(q, c, k):
            r = rewrites[q]
            got = ladder.run("R5", q, c, k, rewritten=r["rewrite"])
            return Retrieved(got.hits, got.ms + r["api_ms"], got.context)
        n = len(rewrites)
        result = evaluate(ctx, "R5-llm", retrieve, OUT, count_tokens=ladder.embedder.count_tokens, extra={
            "settings": asdict(ladder.settings), "model": REWRITE_MODEL, "queries": n,
            "input_tokens_mean": sum(r["input_tokens"] for r in rewrites.values()) / n,
            "output_tokens_mean": sum(r["output_tokens"] for r in rewrites.values()) / n})
```

with

```python
def _refuse_new_calls(prompt, model):
    raise SystemExit("a query has no cached LLM rewrite; run `dtd rewrite` first")
```

`_eval_rung`'s lexicon check does not apply here, because `rewritten` is always passed. Register `sub.add_parser("rewrite").set_defaults(fn=_cmd_rewrite)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass (M1's ledger and fetch tests unchanged).

- [ ] **Step 5: Commit**

```bash
git add pipeline/ledger.py evals/llm_rewrite.py pipeline/cli.py tests/test_ledger.py tests/test_llm_rewrite.py tests/test_cli.py
git commit -m "m2: offline LLM query rewrite, cached, for the lexicon-versus-LLM comparison

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Definitions per passage and rung R6

**Files:**
- Create: `pipeline/definitions.py`
- Modify: `retrieval/index.py`
- Test: `tests/test_definitions.py`, `tests/test_index.py`, `tests/test_ladder.py`

**Interfaces:**
- Consumes: `pipeline.terms.Term`, `extract_terms`.
- Produces: `pipeline.definitions.MAX_DEF_CHARS = 800`, `MAX_DEFS = 6`, `UBIQUITY = 0.2`.
- Produces: `definition_spans(text: str, terms: list[Term]) -> dict[str, tuple[int, int]]`. There is one span per term. A `means` definition is preferred over a parenthetical one.
- Produces: `term_pattern(names: list[str]) -> re.Pattern | None` and `terms_used(passage_text: str, pattern) -> list[str]` (first-occurrence order, no repeats, longest term wins).
- Produces in the index: `passage_defs(passage_id INTEGER, rank INTEGER, term TEXT, def_start INTEGER, def_end INTEGER)` and `passages_x_fts(text)` (passage text plus its definitions, one row per indexed passage, same rowid as `passages_fts`).
- Produces: `retrieval.index.build_index(db_path, contracts, chunker=segment)`. The `chunker(contract_id, text) -> list[Passage]` parameter is used by Task 11.

The rules, and why:
- A **`means` definition** runs from the opening quote to the first blank line, or to the next line that opens with a quoted capitalised term, capped at 800 characters. A single newline does not end it, because about half of MAUD's texts are hard-wrapped.
- A **parenthetical definition** is the sentence around it. It starts after the last `.` or `;` followed by whitespace, or after a blank line, and ends at the next one. It is capped at 800 characters, keeping the part nearest the term.
- A passage gets the definitions of terms it uses, in order of first use. It skips terms defined inside the passage itself and terms used in more than 20% of the agreement's passages, not counting the passage that defines them. Those ("Company", "Parent", "Agreement") would fill every slot and add nothing. At most 6 are attached.

- [ ] **Step 1: Write the failing tests**

`tests/test_definitions.py`:

```python
from pipeline.definitions import MAX_DEF_CHARS, definition_spans, term_pattern, terms_used
from pipeline.terms import extract_terms

HARD_WRAPPED = (
    "“Company Option” means each option to purchase\nshares of Company Common Stock granted under\na Company Plan.\n"
    "“Company Plan” means each equity plan.\n\n"
    "Section 2.1 Options. Each Company Option shall vest.\n"
)


def test_means_definition_spans_wrapped_lines_and_stops_at_the_next_definition():
    spans = definition_spans(HARD_WRAPPED, extract_terms(HARD_WRAPPED))
    s, e = spans["Company Option"]
    assert HARD_WRAPPED[s:e].endswith("a Company Plan.")
    s, e = spans["Company Plan"]
    assert HARD_WRAPPED[s:e] == "“Company Plan” means each equity plan."


def test_parenthetical_definition_is_its_sentence():
    text = "Recitals. Acme Inc is a Delaware corporation (the “Company”). Parent is a buyer."
    s, e = definition_spans(text, extract_terms(text))["Company"]
    assert text[s:e] == "Acme Inc is a Delaware corporation (the “Company”)."
    # Known limit, stated in the report: an abbreviation such as "Corp." ends the sentence early.


def test_means_is_preferred_over_a_parenthetical():
    text = "The buyer (“Parent”) agrees.\n\n“Parent” means Buyer Inc.\n"
    s, e = definition_spans(text, extract_terms(text))["Parent"]
    assert text[s:e].startswith("“Parent” means")


def test_long_definitions_are_capped():
    text = "“Material Adverse Effect” means " + "any change, " * 200 + "\n\n"
    s, e = definition_spans(text, extract_terms(text))["Material Adverse Effect"]
    assert e - s == MAX_DEF_CHARS


def test_longest_term_wins_and_terms_are_listed_once_in_order():
    pat = term_pattern(["Company", "Company Option", "Company Stock Option", "Parent"])
    got = terms_used("Each Company Stock Option and Company Option of the Company, per Parent and the Company.", pat)
    assert got == ["Company Stock Option", "Company Option", "Company", "Parent"]


def test_term_matching_is_case_sensitive_and_whole_word():
    pat = term_pattern(["Company"])
    assert terms_used("the company and Companywide policy", pat) == []
    assert term_pattern([]) is None
```

Append to `tests/test_index.py`:

```python
def test_passages_carry_definitions_of_terms_they_use(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    parts = ["Section 1.1 Definitions. “Company Termination Fee” means an amount in cash equal to $50,000,000.\n\n",
             "Section 8.3 Fees. The Company shall pay the Company Termination Fee.\n\n"]
    parts += [f"Section 9.{i} Misc. Filler clause number {i}.\n\n" for i in range(1, 5)]
    doc = "".join(parts)
    db = tmp_path / "i.db"
    build_index(db, {"c": doc})
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT p.section_id, d.term FROM passage_defs d JOIN passages p USING (passage_id)").fetchall()
    assert rows == [("8.3", "Company Termination Fee")]
    [x] = conn.execute("SELECT x.text FROM passages_x_fts x JOIN passages p ON p.passage_id = x.rowid"
                       " WHERE p.section_id = '8.3'").fetchall()
    assert "amount in cash" in x[0]
    assert conn.execute("SELECT COUNT(*) FROM passages_x_fts").fetchone() == conn.execute(
        "SELECT COUNT(*) FROM passages_fts").fetchone()
```

Append to `tests/test_ladder.py`:

```python
def test_r6_shows_definitions_and_matches_through_them(ladder):
    got = ladder.run("R6", "amount in cash", "big", k=5)
    fee = [c for c in got.context if c.startswith("Section 8.3")]
    assert fee and "amount in cash equal to $50,000,000" in fee[0]
    r5 = ladder.run("R5", "amount in cash", "big", k=5)
    assert all(not c.startswith("Section 8.3") or "$50,000,000" not in c for c in r5.context)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_definitions.py tests/test_index.py tests/test_ladder.py -q`
Expected: FAIL.

- [ ] **Step 3: Implement**

`pipeline/definitions.py`:

```python
import re

from pipeline.terms import Term

MAX_DEF_CHARS = 800
MAX_DEFS = 6
UBIQUITY = 0.2
MEANS_END = re.compile(r"\n\s*\n|\n\s*[“\"][A-Z]")
SENTENCE_END = re.compile(r"(?<=[.;])\s|\n\s*\n")


def _means_span(text: str, t: Term) -> tuple[int, int]:
    m = MEANS_END.search(text, t.end)
    end = m.start() if m else len(text)
    return t.start, min(end, t.start + MAX_DEF_CHARS)


def _paren_span(text: str, t: Term) -> tuple[int, int]:
    lo = max(0, t.start - MAX_DEF_CHARS)
    starts = [m.end() for m in SENTENCE_END.finditer(text, lo, t.start)]
    s = starts[-1] if starts else lo
    m = SENTENCE_END.search(text, t.end)
    e = m.start() if m else len(text)
    if e - s > MAX_DEF_CHARS:
        s = max(s, t.end - MAX_DEF_CHARS // 2)
        e = min(e, s + MAX_DEF_CHARS)
    return s, e


def definition_spans(text: str, terms: list[Term]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for style, span in (("means", _means_span), ("paren", _paren_span)):
        for t in sorted(terms, key=lambda t: t.start):
            if t.style == style and t.term not in out:
                out[t.term] = span(text, t)
    return out


def term_pattern(names: list[str]) -> re.Pattern | None:
    if not names:
        return None
    alts = "|".join(re.escape(n) for n in sorted(set(names), key=lambda n: (-len(n), n)))
    return re.compile(r"(?<![A-Za-z0-9])(" + alts + r")(?![A-Za-z0-9])")


def terms_used(passage_text: str, pattern: re.Pattern | None) -> list[str]:
    if pattern is None:
        return []
    return list(dict.fromkeys(m.group(1) for m in pattern.finditer(passage_text)))
```

In `retrieval/index.py`, add to `SCHEMA`:

```sql
CREATE TABLE passage_defs(
    passage_id INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    term TEXT NOT NULL,
    def_start INTEGER NOT NULL,
    def_end INTEGER NOT NULL
);
CREATE INDEX passage_defs_passage ON passage_defs(passage_id);
CREATE VIRTUAL TABLE passages_x_fts USING fts5(text, tokenize='porter unicode61');
```

and rewrite the per-contract loop (same insert order as before, so passage ids do not change):

```python
from collections import Counter

from pipeline.definitions import MAX_DEFS, UBIQUITY, definition_spans, term_pattern, terms_used


def build_index(db_path: Path, contracts: dict[str, str], chunker=segment) -> dict:
    ...
    for contract_id in sorted(contracts):
        text = contracts[contract_id]
        conn.execute("INSERT INTO contracts VALUES (?, ?)", (contract_id, len(text)))
        summary["contracts"] += 1
        terms = extract_terms(text)
        spans = definition_spans(text, terms)
        pattern = term_pattern(list(spans))
        passages = chunker(contract_id, text)
        used = {p.ordinal: terms_used(text[p.start:p.end], pattern) for p in passages}
        # A term's own defining passage does not count as a use of it.
        uses = Counter(t for p in passages for t in used[p.ordinal] if not (p.start <= spans[t][0] < p.end))
        n = max(1, len(passages))
        for p in passages:
            cur = conn.execute(
                "INSERT INTO passages(contract_id, ordinal, start_char, end_char, section_id, section_title, kind,"
                " section_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p.contract_id, p.ordinal, p.start, p.end, p.section_id, p.section_title, p.kind, p.section_path),
            )
            summary["passages"] += 1
            if p.kind == "toc":
                continue
            pid = cur.lastrowid
            defs = [t for t in used[p.ordinal]
                    if uses[t] / n <= UBIQUITY and not (p.start <= spans[t][0] < p.end)][:MAX_DEFS]
            for rank, t in enumerate(defs):
                conn.execute("INSERT INTO passage_defs VALUES (?, ?, ?, ?, ?)", (pid, rank, t, *spans[t]))
            body = text[p.start:p.end]
            conn.execute("INSERT INTO passages_fts(rowid, text) VALUES (?, ?)", (pid, body))
            conn.execute("INSERT INTO passages_x_fts(rowid, text) VALUES (?, ?)",
                         (pid, "\n\n".join([body] + [text[s:e] for s, e in (spans[t] for t in defs)])))
            summary["indexed"] += 1
        for t in terms:
            conn.execute("INSERT INTO terms VALUES (?, ?, ?, ?, ?)", (contract_id, t.term, t.start, t.end, t.style))
            summary["terms"] += 1
    ...
```

- [ ] **Step 4: Run the tests, then check that M1's numbers did not move**

Run: `uv run pytest -q`
Expected: all pass.
Run: `uv run dtd build && uv run dtd eval && uv run dtd facts --check`
Expected: exit 0. `dtd build` drops the vector table, so run `uv run dtd embed` afterwards; with a warm cache it takes seconds.

- [ ] **Step 5: Commit**

```bash
git add pipeline/definitions.py retrieval/index.py tests/test_definitions.py tests/test_index.py tests/test_ladder.py
git commit -m "m2: per-passage definitions, the passage-plus-definitions index and R6

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Tuning on the tune split

**Files:**
- Create: `evals/tune.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_tune.py`

**Interfaces:**
- Consumes: `Ladder`, `Settings`, `CachedReranker`, `evals.run_rung.Context`, `split_of`, `recall_at_k`.
- Produces: `evals.tune.GRID_DEPTH = (20, 50, 100)`, `GRID_K0 = (10, 60)`, `PROBE_DEPTH = 20`, `GRID_RERANK_DEPTH = (10, 20, 30)`, `MAX_P95_MS = 3000.0`.
- Produces: `evals.tune.tune(ctx, conn, embedder, make_reranker, cache_path: Path, out_path: Path, rerankers: tuple[str, ...] = RERANKERS) -> dict`, which writes `retrieval/settings.json`:

```json
{"settings": {"depth": 50, "rrf_k0": 60, "reranker": "...", "rerank_depth": 20},
 "live_path_ok": true,
 "rule": "...",
 "tuned_on": {"split": "tune", "items": 450, "contracts": 24},
 "load": [0.0, 0.0, 0.0],
 "evidence": {"fusion": [{"depth": 20, "rrf_k0": 10, "recall@5": 0.0, "p95_ms": 0.0, "n_items": 0}],
              "rerankers": [{"reranker": "...", "rerank_depth": 20, "recall@5": 0.0, "p95_ms": 0.0, "n_items": 0}],
              "rerank_depth": [{"reranker": "...", "rerank_depth": 10, "recall@5": 0.0, "p95_ms": 0.0, "n_items": 0}]}}
```

- Produces: `dtd tune`.

The rule, written into `settings.json` and the report:
1. **Fusion.** Pick the `(depth, rrf_k0)` with the highest tune recall@5 for R3. Ties go to the smaller depth, then the larger k0.
2. **Reranker.** Compare the rerankers at `PROBE_DEPTH` on R4. A candidate qualifies if its per-query p95 latency on this machine is at most `MAX_P95_MS`. The highest recall@5 among qualifiers wins, and ties go to the faster.
3. **Rerank depth.** Run the chosen reranker over `GRID_RERANK_DEPTH` and apply the same rule.
4. **No qualifier.** Pick the fastest, and set `live_path_ok` to false. PRD §4.1 lets a rung be left out of the live path, and M5 reads this flag.

The 3,000 ms limit is this plan's proposal for a live search that answers inside a few seconds on a 1 GB server, which will be slower than the development machine. Michael confirms or changes it before Task 16 runs.

Only tune-split items are read. The report split is never touched here.

- [ ] **Step 1: Write the failing test**

`tests/test_tune.py`:

```python
import json

from evals.bootstrap import split_of
from evals.run_rung import load_context
from evals.tune import GRID_DEPTH, GRID_K0, GRID_RERANK_DEPTH, tune
from retrieval.index import build_index
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder, FakeReranker

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
IDS = [f"contract_{i}" for i in range(60)]
TUNE = [c for c in IDS if split_of(c) == "tune"][:3]
REPORT = [c for c in IDS if split_of(c) == "report"][:2]
DOC = ("Section 1.1 Closing. The closing shall occur at the offices of counsel.\n\n"
       "Section 8.3 Termination Fee. The Company shall pay Parent a termination fee in cash.\n")


def setup(tmp_path):
    cdir = tmp_path / "contracts"
    cdir.mkdir()
    texts = {c: DOC for c in TUNE + REPORT}
    for c, t in texts.items():
        (cdir / f"{c}.txt").write_text(t, encoding="utf-8")
    fee = DOC.split("\n\n")[1].strip()
    body = "".join(f'main,{c},"{fee} (Page 70)",Yes,1,Termination Fee-Answer,<NONE>,Termination Fee,{i},'
                   f'Deal Protection and Related Provisions\n' for i, c in enumerate(texts))
    (tmp_path / "l.csv").write_text(HEADER + body, encoding="utf-8")
    db = tmp_path / "maud.db"
    build_index(db, texts)
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    return load_context(db, [tmp_path / "l.csv"], cdir), conn, emb


class Named(FakeReranker):
    def __init__(self, name, ms):
        super().__init__(ms)
        self.name = name


def test_tune_reads_only_the_tune_split_and_records_its_evidence(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    out = tmp_path / "settings.json"
    doc = tune(ctx, conn, emb, lambda name: Named(name, 5.0), tmp_path / "rr.db", out, rerankers=("a", "b"))
    assert json.loads(out.read_text()) == doc
    assert doc["tuned_on"] == {"split": "tune", "items": 3, "contracts": 3}
    assert len(doc["evidence"]["fusion"]) == len(GRID_DEPTH) * len(GRID_K0)
    assert [r["rerank_depth"] for r in doc["evidence"]["rerank_depth"]] == list(GRID_RERANK_DEPTH)
    assert doc["live_path_ok"] is True


def test_a_reranker_over_the_latency_limit_is_not_chosen_while_another_qualifies(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    speeds = {"slow": 9000.0, "fast": 5.0}
    doc = tune(ctx, conn, emb, lambda name: Named(name, speeds[name]), tmp_path / "rr.db", tmp_path / "s.json",
               rerankers=("slow", "fast"))
    assert doc["settings"]["reranker"] == "fast"


def test_with_no_qualifying_reranker_the_fastest_is_kept_and_flagged(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    speeds = {"slow": 9000.0, "slower": 12000.0}
    doc = tune(ctx, conn, emb, lambda name: Named(name, speeds[name]), tmp_path / "rr.db", tmp_path / "s.json",
               rerankers=("slow", "slower"))
    assert doc["settings"]["reranker"] == "slow" and doc["live_path_ok"] is False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_tune.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.tune'`

- [ ] **Step 3: Implement**

`evals/tune.py`:

```python
import json
import os
from dataclasses import asdict, replace
from pathlib import Path

from evals.bootstrap import split_of
from evals.metrics import recall_at_k
from evals.run_rung import Context
from retrieval.ladder import Ladder, Settings
from retrieval.models import RERANKERS
from retrieval.rerank_cache import CachedReranker

GRID_DEPTH = (20, 50, 100)
GRID_K0 = (10, 60)
PROBE_DEPTH = 20
GRID_RERANK_DEPTH = (10, 20, 30)
MAX_P95_MS = 3000.0
RULE = ("Fusion: highest tune recall@5 on R3 (ties: smaller depth, then larger k0). Reranker, then rerank depth: "
        "highest tune recall@5 on R4 among settings whose p95 latency on the development machine is at most "
        "MAX_P95_MS (ties: faster); if none qualifies, the fastest, with live_path_ok false.")


def _score(ladder: Ladder, rung: str, items) -> dict:
    recalls, ms = [], []
    for it in items:
        got = ladder.run(rung, it.query, it.contract_id, 10)
        recalls.append(recall_at_k(got.hits, it.gold, 5))
        ms.append(got.ms)
    ms.sort()
    return {"recall@5": round(sum(recalls) / len(recalls), 4),
            "p95_ms": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))], 2), "n_items": len(items)}


def _pick(rows: list[dict]) -> tuple[dict, bool]:
    ok = [r for r in rows if r["p95_ms"] <= MAX_P95_MS]
    if not ok:
        return min(rows, key=lambda r: r["p95_ms"]), False
    return max(ok, key=lambda r: (r["recall@5"], -r["p95_ms"])), True


def tune(ctx: Context, conn, embedder, make_reranker, cache_path: Path, out_path: Path,
         rerankers: tuple[str, ...] = RERANKERS) -> dict:
    items = [i for i in ctx.items if split_of(i.contract_id) == "tune"]
    if not items:
        raise ValueError("no tune-split items to tune on")
    fusion = [{"depth": d, "rrf_k0": k0,
               **_score(Ladder(conn, ctx.texts, embedder, None, None, Settings(depth=d, rrf_k0=k0)), "R3", items)}
              for d in GRID_DEPTH for k0 in GRID_K0]
    best = max(fusion, key=lambda r: (r["recall@5"], -r["depth"], r["rrf_k0"]))
    base = Settings(depth=best["depth"], rrf_k0=best["rrf_k0"])
    made: dict[str, CachedReranker] = {}

    def run(name: str, rdepth: int) -> dict:
        if name not in made:
            made[name] = CachedReranker(make_reranker(name), cache_path)
        ladder = Ladder(conn, ctx.texts, embedder, made[name], None, replace(base, reranker=name, rerank_depth=rdepth))
        return {"reranker": name, "rerank_depth": rdepth, **_score(ladder, "R4", items)}

    bake = [run(name, PROBE_DEPTH) for name in rerankers]
    chosen, _ = _pick(bake)
    depths = [run(chosen["reranker"], d) for d in GRID_RERANK_DEPTH]
    final, live = _pick(depths)
    doc = {
        "settings": asdict(replace(base, reranker=final["reranker"], rerank_depth=final["rerank_depth"])),
        "live_path_ok": live,
        "rule": RULE.replace("MAX_P95_MS", f"{MAX_P95_MS:g} ms"),
        "tuned_on": {"split": "tune", "items": len(items), "contracts": len({i.contract_id for i in items})},
        "load": list(os.getloadavg()),
        "evidence": {"fusion": fusion, "rerankers": bake, "rerank_depth": depths},
    }
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return doc
```

In `pipeline/cli.py`:

```python
from evals.tune import tune


def _cmd_tune(args) -> int:
    if not INDEX.exists() or not _csv_paths() or not _has_vectors(INDEX):
        print("index, vectors or label CSVs missing; run `dtd build` then `dtd embed` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    embedder, make_reranker = _models()
    doc = tune(ctx, vectors.connect(INDEX), embedder, make_reranker, CACHE / "rerank.db", SETTINGS_PATH)
    print(json.dumps({"settings": doc["settings"], "live_path_ok": doc["live_path_ok"]}))
    return 0
```

Register `sub.add_parser("tune").set_defaults(fn=_cmd_tune)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add evals/tune.py pipeline/cli.py tests/test_tune.py
git commit -m "m2: tune fusion, reranker and rerank depth on the tune split under a latency rule

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 11: The chunking comparison (section-aware versus fixed-size, on R3)

**Files:**
- Create: `pipeline/chunk_fixed.py`
- Modify: `evals/run_rung.py`, `pipeline/cli.py`
- Test: `tests/test_chunk_fixed.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `pipeline.chunk_fixed.fixed_size(conn) -> int`, the median length of the section-aware index's non-toc passages rounded to the nearest 100 characters (at least 100).
- Produces: `fixed_chunks(contract_id: str, text: str, size: int) -> list[Passage]`. Windows of `size` characters, each end moved forward to the next whitespace (at most 100 characters), contiguous and covering the text. `kind` is `"toc"` for a window lying wholly inside a section-aware table-of-contents span, else `"fixed"`. `section_id` and `section_path` are empty.
- Produces: `fixed_chunker(size: int) -> Callable[[str, str], list[Passage]]`.
- Produces: `evals.run_rung.with_passages(ctx: Context, db_path: Path) -> Context`. It is the same context, with nDCG's ideal computed from another index's passages.
- Produces: `dtd build --fixed` (needs `maud.db`; writes `data/index/maud_fixed.db` and a `chunking(size)` table), and `dtd eval --rung R3-fixed`, which runs R3 over the fixed index with the tuned settings on the same items as `r3`.

Why the size is the median of the section-aware passages: passage length changes recall on its own, because a longer passage overlaps more gold. Matching the median isolates what the comparison is about, which is where the boundaries fall. The items are the section-aware context's, so both chunkings are scored on identical items and the paired bootstrap applies.

- [ ] **Step 1: Write the failing tests**

`tests/test_chunk_fixed.py`:

```python
import sqlite3

from pipeline.chunk_fixed import fixed_chunks, fixed_size
from retrieval.index import build_index

TEXT = ("TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 Merger 6  Section 2.1 Stock 9  Section 2.2 Options 9  "
        "Section 3.1 Fees 12\n\n" + "Section 1.1 Closing. " + "The closing shall occur at the offices of counsel. " * 40)


def test_fixed_chunks_tile_the_text_and_break_at_whitespace():
    ps = fixed_chunks("c", TEXT, 300)
    assert ps[0].start == 0 and ps[-1].end == len(TEXT)
    assert all(a.end == b.start for a, b in zip(ps, ps[1:]))
    assert all(300 <= p.end - p.start <= 400 for p in ps[:-1])
    assert all(TEXT[p.end].isspace() for p in ps[:-1])
    assert all(p.section_id == "" and p.section_path == "" for p in ps)


def test_windows_inside_the_table_of_contents_are_marked_toc():
    ps = fixed_chunks("c", "TABLE OF CONTENTS  " + "Section 1.1 Closing 6  " * 40 + "\n\nSection 1.1 Closing. Body text here.", 200)
    assert ps[0].kind == "toc" and ps[-1].kind == "fixed"


def test_empty_text_has_no_chunks():
    assert fixed_chunks("c", "", 300) == []


def test_fixed_size_is_the_rounded_median_section_passage(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": "Section 1.1 A. " + "x " * 70 + "\n\nSection 1.2 B. " + "y " * 120 + "\n"})
    assert fixed_size(sqlite3.connect(db)) in (100, 200, 300)
```

Append to `tests/test_cli.py`:

```python
def test_fixed_index_is_evaluated_on_the_same_items(data):
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["build", "--fixed"]) == 0
    assert cli.entry(["embed", "--fixed"]) == 0
    assert cli.entry(["eval", "--rung", "R3"]) == 0
    assert cli.entry(["eval", "--rung", "R3-fixed"]) == 0
    a = [json.loads(l)["item_id"] for l in (data / "out" / "r3_items.jsonl").read_text().splitlines()]
    b = [json.loads(l)["item_id"] for l in (data / "out" / "r3_fixed_items.jsonl").read_text().splitlines()]
    assert a == b


def test_fixed_build_needs_the_section_index_first(data, capsys):
    assert cli.entry(["build", "--fixed"]) == 2
    assert "dtd build" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_chunk_fixed.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`pipeline/chunk_fixed.py`:

```python
import re
import sqlite3

from pipeline.segment import Passage, segment

WHITESPACE = re.compile(r"\s")
MAX_SNAP = 100


def fixed_size(conn: sqlite3.Connection) -> int:
    lengths = sorted(e - s for s, e in conn.execute("SELECT start_char, end_char FROM passages WHERE kind != 'toc'"))
    return max(100, round(lengths[len(lengths) // 2] / 100) * 100)


def fixed_chunks(contract_id: str, text: str, size: int) -> list[Passage]:
    toc = [(p.start, p.end) for p in segment(contract_id, text) if p.kind == "toc"]
    out: list[Passage] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            m = WHITESPACE.search(text, end, min(len(text), end + MAX_SNAP))
            if m:
                end = m.start()
        kind = "toc" if any(a <= start and end <= b for a, b in toc) else "fixed"
        out.append(Passage(contract_id, len(out), start, end, "", "", kind, ""))
        start = end
    return out


def fixed_chunker(size: int):
    return lambda contract_id, text: fixed_chunks(contract_id, text, size)
```

(`TEXT[p.end].isspace()` holds because a window ends where the whitespace starts. The last window can be shorter than `size`.)

In `evals/run_rung.py`:

```python
def with_passages(ctx: Context, db_path: Path) -> Context:
    conn = sqlite3.connect(db_path)
    passages: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cid, s, e in conn.execute("SELECT contract_id, start_char, end_char FROM passages WHERE kind != 'toc'"):
        passages[cid].append((s, e))
    conn.close()
    return replace(ctx, passages=dict(passages))
```

In `pipeline/cli.py`, give `build` a `--fixed` flag:

```python
from pipeline.chunk_fixed import fixed_chunker, fixed_size


def _cmd_build(args) -> int:
    files = sorted((RAW / "contracts").glob("*.txt")) if (RAW / "contracts").exists() else []
    if not files:
        print(f"no contracts under {RAW / 'contracts'}; run `dtd fetch` first", file=sys.stderr)
        return 2
    contracts = {p.stem: load_contract(p) for p in files}
    if not args.fixed:
        print(json.dumps(build_index(INDEX, contracts)))
        return 0
    if not INDEX.exists():
        print("the section-aware index sets the chunk size; run `dtd build` first", file=sys.stderr)
        return 2
    size = fixed_size(sqlite3.connect(INDEX))
    summary = build_index(INDEX_FIXED, contracts, chunker=fixed_chunker(size))
    conn = sqlite3.connect(INDEX_FIXED)
    conn.execute("CREATE TABLE chunking(size INTEGER NOT NULL)")
    conn.execute("INSERT INTO chunking VALUES (?)", (size,))
    conn.commit()
    print(json.dumps(summary | {"size": size}))
    return 0
```

and in `_cmd_eval`, add a branch before `else`:

```python
    elif rung == "R3-fixed":
        if not INDEX_FIXED.exists() or not _has_vectors(INDEX_FIXED):
            print("fixed-size index or its vectors missing; run `dtd build --fixed` then `dtd embed --fixed`",
                  file=sys.stderr)
            return 2
        result = _eval_rung("R3", INDEX_FIXED, "R3-fixed", with_passages(ctx, INDEX_FIXED))
```

Register `--fixed` on the `build` parser.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/chunk_fixed.py evals/run_rung.py pipeline/cli.py tests/test_chunk_fixed.py tests/test_cli.py
git commit -m "m2: fixed-size chunking at the section-aware median, compared on R3

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 12: Failure classification per miss

**Files:**
- Create: `evals/failures.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_failures.py`

**Interfaces:**
- Consumes: a rung's `<rung>_items.jsonl`; the index's `passages` and `passage_defs`.
- Produces: `evals.failures.K = 5`, `CLASSES`, `NOT_APPLICABLE: dict[str, str]`, `classify(conn, items_path: Path, k: int = K) -> dict`:

```json
{"k": 5,
 "by_split": {"report": {"misses": 0, "definition_missing": 0, "right_section_wrong_passage": 0,
                         "unsectioned_gold": 0, "wrong_section": 0},
              "tune": {}},
 "by_category_report": {"<category>": {"definition_missing": 0}},
 "not_applicable": {"wrong_deal": "...", "superseded_text": "...", "unfiled_schedule": "..."}}
```

- Produces: `dtd failures`, which writes `data/out/failures_<rung>.json` for each of R1–R6 whose items file exists.

A **miss** is one gold span that none of the top k passages touches (the same overlap rule as recall@k). Its **home** is the non-toc passage that overlaps it most. The classes are tried in order, and the first match wins:

| Class | Rule | PRD §5.3 name |
|---|---|---|
| `definition_missing` | The gold span overlaps the definition attached to a top-k passage | "right section but definition missing" |
| `right_section_wrong_passage` | The home's section id is among the top-k passages' section ids | (added: a split section) |
| `unsectioned_gold` | The home has no section id (front matter or undetected heading) | (added) |
| `wrong_section` | Otherwise | "wrong section" |

Three PRD classes cannot occur on T-human, and the report says why rather than printing a zero (`NOT_APPLICABLE`). "Label disputed" needs a judgement, so it is estimated on a sample by Task 13 and not assigned per miss.

Note for the report: under R6, a `definition_missing` miss is one where the definition was shown to the model, but the retrieval metric credits only passages.

- [ ] **Step 1: Write the failing test**

`tests/test_failures.py`:

```python
import json
import sqlite3

from evals.failures import CLASSES, NOT_APPLICABLE, classify
from retrieval.index import build_index

DOC = (
    "AGREEMENT AND PLAN OF MERGER among Parent, Merger Sub and the Company, dated as of the date below.\n\n"
    "Section 1.1 Definitions. “Company Termination Fee” means an amount in cash equal to $50,000,000.\n\n"
    "Section 5.1 Covenants. " + "The Company shall conduct its business in the ordinary course. " * 60 + "\n\n"
    "Section 8.3 Fees. The Company shall pay the Company Termination Fee on termination.\n\n"
    + "".join(f"Section 9.{i} Misc. Miscellaneous clause number {i} of this Agreement.\n\n" for i in range(1, 6))
)


def ids(conn):
    rows = conn.execute("SELECT passage_id, section_id, start_char, end_char, kind FROM passages ORDER BY ordinal").fetchall()
    return rows


def test_each_class_is_assigned_by_its_rule(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    conn = sqlite3.connect(db)
    rows = ids(conn)
    sec = {}
    for pid, sid, s, e, kind in rows:
        sec.setdefault(sid or kind, []).append((pid, s, e))
    front, s11, s83 = sec["front"][0], sec["1.1"][0], sec["8.3"][0]
    s51a, s51b = sec["5.1"][0], sec["5.1"][1]
    s91, s92 = sec["9.1"][0], sec["9.2"][0]
    fee = DOC.index("$50,000,000")

    def item(name, gold, top):
        return {"item_id": f"c|{name}", "contract_id": "c", "category": "Remedies", "split": "report",
                "gold": [list(g) for g in gold], "top_passage_ids": top}
    items = [
        item("def", [(fee - 30, fee + 11)], [s83[0]]),
        item("split", [(s51b[1] + 10, s51b[1] + 200)], [s51a[0]]),
        item("front", [(front[1] + 5, front[1] + 60)], [s91[0]]),
        item("wrong", [(s92[1] + 2, s92[2] - 2)], [s91[0]]),
        item("hit", [(s91[1] + 2, s91[2] - 2)], [s91[0]]),
    ]
    path = tmp_path / "r6_items.jsonl"
    path.write_text("".join(json.dumps(i) + "\n" for i in items))
    out = classify(conn, path)
    assert out["by_split"]["report"] == {"misses": 4, "definition_missing": 1, "right_section_wrong_passage": 1,
                                         "unsectioned_gold": 1, "wrong_section": 1}
    assert out["by_category_report"]["Remedies"]["wrong_section"] == 1
    assert set(out["not_applicable"]) == set(NOT_APPLICABLE)
    assert CLASSES == ("definition_missing", "right_section_wrong_passage", "unsectioned_gold", "wrong_section")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_failures.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`evals/failures.py`:

```python
import sqlite3
from collections import defaultdict
from pathlib import Path

from evals.compare import load_items
from evals.metrics import is_relevant

K = 5
CLASSES = ("definition_missing", "right_section_wrong_passage", "unsectioned_gold", "wrong_section")
NOT_APPLICABLE = {
    "wrong_deal": "retrieval is scoped to the item's own agreement, so it cannot return another deal",
    "superseded_text": "the MAUD agreements are single documents with no amendments",
    "unfiled_schedule": "every gold span is text inside the filed agreement",
}


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def classify(conn: sqlite3.Connection, items_path: Path, k: int = K) -> dict:
    passages = {pid: (cid, s, e, sec) for pid, cid, s, e, sec in conn.execute(
        "SELECT passage_id, contract_id, start_char, end_char, section_id FROM passages WHERE kind != 'toc'")}
    by_contract: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)
    for pid, (cid, s, e, sec) in passages.items():
        by_contract[cid].append((pid, s, e, sec))
    defs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for pid, s, e in conn.execute("SELECT passage_id, def_start, def_end FROM passage_defs"):
        defs[pid].append((s, e))
    counts = {split: dict.fromkeys(CLASSES, 0) for split in ("report", "tune")}
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(CLASSES, 0))
    for row in load_items(items_path).values():
        top = [p for p in row["top_passage_ids"][:k] if p in passages]
        top_sections = {passages[p][3] for p in top if passages[p][3]}
        top_defs = [d for p in top for d in defs[p]]
        for g0, g1 in row["gold"]:
            if any(is_relevant(passages[p][1], passages[p][2], [(g0, g1)]) for p in top):
                continue
            home = max(by_contract[row["contract_id"]], key=lambda x: (_overlap(x[1], x[2], g0, g1), -x[0]))
            if any(_overlap(s, e, g0, g1) > 0 for s, e in top_defs):
                cls = "definition_missing"
            elif home[3] and home[3] in top_sections:
                cls = "right_section_wrong_passage"
            elif not home[3]:
                cls = "unsectioned_gold"
            else:
                cls = "wrong_section"
            counts[row["split"]][cls] += 1
            if row["split"] == "report":
                by_category[row["category"]][cls] += 1
    return {"k": k,
            "by_split": {s: {"misses": sum(c.values()), **c} for s, c in counts.items()},
            "by_category_report": dict(by_category),
            "not_applicable": NOT_APPLICABLE}
```

In `pipeline/cli.py`:

```python
from evals.failures import classify


def _cmd_failures(args) -> int:
    done = []
    for rung in RUNGS:
        items = OUT / f"{rung.lower()}_items.jsonl"
        if items.exists():
            out = classify(sqlite3.connect(INDEX), items)
            (OUT / f"failures_{rung.lower()}.json").write_text(json.dumps(out, indent=2, sort_keys=True), encoding="utf-8")
            done.append(rung)
    if not done:
        print("no rung results; run `dtd eval --rung ...` first", file=sys.stderr)
        return 2
    print(json.dumps({"classified": done}))
    return 0
```

Register `sub.add_parser("failures").set_defaults(fn=_cmd_failures)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. (If section 5.1 does not split into two passages in the fixture, increase the repeat count until `sec["5.1"]` has two entries; the segmenter cuts at 2,400 characters.)

- [ ] **Step 5: Commit**

```bash
git add evals/failures.py pipeline/cli.py tests/test_failures.py
git commit -m "m2: failure classification per missed gold span

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 13: "Label disputed", estimated by a machine pass on a sample

**Files:**
- Create: `evals/disputes.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_disputes.py`

**Interfaces:**
- Consumes: per-item rows (they carry `query`, from Task 3), `pipeline.claude.run_claude`, `pipeline.ledger.Ledger(key=...)`, `pipeline.normalise.squash`, `cluster_bootstrap`.
- Produces: `evals.disputes.DISPUTE_MODEL = "claude-opus-5-5"`, `SAMPLE = 150`, `PROMPT`, `sample_misses(rows: dict[str, dict], n: int = SAMPLE, seed: int = 0, split: str = "report") -> list[dict]`, `verdict(result_text: str, retrieved: str) -> bool`, `judge(sample, texts, conn, cache_path, runner=run_claude, model=DISPUTE_MODEL) -> list[dict]`, `summarise(judged, n_boot=2000) -> dict`.
- Produces: `dtd disputes`. It reads the ladder rung with the highest report recall@5 and writes `data/out/disputes.json` with `rung, model, sample, share (mean, lo, hi, n_items, n_clusters), machine_built: true, prompt`.

The question put to the model: the lawyers marked GOLD, but the system's first result was RETRIEVED instead. Does RETRIEVED also contain the answer? The judgement counts only if the model's supporting quote occurs verbatim, ignoring whitespace, in RETRIEVED. That is the citation gate of PRD §4.2 applied to the judge. The share, with an interval clustered by agreement, is published as machine-built. It is evidence about how much of the "miss" rate is label incompleteness, and it relabels nothing.

- [ ] **Step 1: Write the failing tests**

`tests/test_disputes.py`:

```python
import json
import sqlite3

from evals.disputes import judge, sample_misses, summarise, verdict
from retrieval.index import build_index
from tests.fakes import fake_claude

DOC = "Section 1.1 Fees. The Company shall pay the Termination Fee.\n\nSection 1.2 Other. The Parent shall pay the Reverse Termination Fee.\n"


def rows():
    base = {"contract_id": "c", "category": "Remedies", "query": "Termination Fee", "gold": [[0, 40]]}
    return {
        "c|a": {**base, "item_id": "c|a", "split": "report", "mrr@10": 0.5, "top_passage_ids": [2, 1]},
        "c|b": {**base, "item_id": "c|b", "split": "report", "mrr@10": 1.0, "top_passage_ids": [1]},
        "c|t": {**base, "item_id": "c|t", "split": "tune", "mrr@10": 0.0, "top_passage_ids": [2]},
    }


def test_sample_takes_report_items_whose_first_result_is_not_gold():
    assert [r["item_id"] for r in sample_misses(rows(), n=10)] == ["c|a"]


def test_verdict_needs_true_and_a_verbatim_quote():
    retrieved = "The Parent shall pay the\nReverse Termination Fee."
    assert verdict('{"answers": true, "quote": "shall pay the Reverse Termination Fee"}', retrieved)
    assert not verdict('{"answers": true, "quote": "shall pay a fee"}', retrieved)
    assert not verdict('{"answers": false, "quote": "shall pay the"}', retrieved)
    assert not verdict("not json", retrieved)


def test_judge_asks_once_per_item_and_resumes(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    conn = sqlite3.connect(db)
    runner = fake_claude('{"answers": true, "quote": "Reverse Termination Fee"}')
    sample = sample_misses(rows(), n=10)
    first = judge(sample, {"c": DOC}, conn, tmp_path / "d.jsonl", runner=runner, model="m")
    assert [r["disputed"] for r in first] == [True] and len(runner.calls) == 1
    assert "Reverse Termination Fee" in runner.calls[0][0] and "Termination Fee" in runner.calls[0][0]
    again = fake_claude("unused")
    assert judge(sample, {"c": DOC}, conn, tmp_path / "d.jsonl", runner=again, model="m") == first
    assert again.calls == []
    assert summarise(first, n_boot=50)["mean"] == 1.0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_disputes.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`evals/disputes.py`:

```python
import json
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap
from pipeline.claude import run_claude
from pipeline.ledger import Ledger
from pipeline.normalise import squash

DISPUTE_MODEL = "claude-opus-5-5"
SAMPLE = 150
MAX_GOLD_CHARS = 3000
PROMPT = """Lawyers marked the text under GOLD as the part of a merger agreement that answers the question. A search system returned the passage under RETRIEVED instead.

Question: {query}

GOLD:
{gold}

RETRIEVED:
{retrieved}

Does RETRIEVED also contain the clause that answers the question, so that a reader given only RETRIEVED would find the answer? Reply with one JSON object and nothing else: {{"answers": true or false, "quote": "the shortest verbatim quote from RETRIEVED that answers it, or an empty string"}}"""


def sample_misses(rows: dict[str, dict], n: int = SAMPLE, seed: int = 0, split: str = "report") -> list[dict]:
    pool = sorted((r for r in rows.values()
                   if r["split"] == split and r["mrr@10"] < 1.0 and r["top_passage_ids"]),
                  key=lambda r: r["item_id"])
    return sorted(random.Random(seed).sample(pool, min(n, len(pool))), key=lambda r: r["item_id"])


def verdict(result_text: str, retrieved: str) -> bool:
    m = re.search(r"\{.*\}", result_text, re.S)
    try:
        obj = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return False
    quote = str(obj.get("quote", "")).strip()
    return obj.get("answers") is True and bool(quote) and squash(quote)[0] in squash(retrieved)[0]


def judge(sample: list[dict], texts: dict[str, str], conn: sqlite3.Connection, cache_path: Path,
          runner=run_claude, model: str = DISPUTE_MODEL) -> list[dict]:
    ledger = Ledger(Path(cache_path), key="item_id")
    out = []
    for row in sample:
        rec = ledger.get(row["item_id"])
        if rec is None:
            text = texts[row["contract_id"]]
            s, e = conn.execute("SELECT start_char, end_char FROM passages WHERE passage_id = ?",
                                (row["top_passage_ids"][0],)).fetchone()
            retrieved = text[s:e]
            gold = "\n…\n".join(text[a:b] for a, b in row["gold"])[:MAX_GOLD_CHARS]
            resp = runner(PROMPT.format(query=row["query"], gold=gold, retrieved=retrieved), model)
            rec = {"item_id": row["item_id"], "contract_id": row["contract_id"], "category": row["category"],
                   "disputed": verdict(resp["result"], retrieved), "raw": resp["result"][:2000]}
            ledger.put(rec)
        out.append(rec)
    return out


def summarise(judged: list[dict], n_boot: int = 2000) -> dict:
    by_contract: dict[str, list[float]] = defaultdict(list)
    for r in judged:
        by_contract[r["contract_id"]].append(1.0 if r["disputed"] else 0.0)
    return cluster_bootstrap(by_contract, n_boot=n_boot)
```

In `pipeline/cli.py`:

```python
from evals.compare import load_items
from evals.disputes import DISPUTE_MODEL, PROMPT as DISPUTE_PROMPT, judge, sample_misses, summarise


def _best_rung() -> str | None:
    scored = {r: json.loads((OUT / f"{r.lower()}.json").read_text())["by_split"]["report"]["recall@5"]["mean"]
              for r in RUNGS if (OUT / f"{r.lower()}.json").exists()}
    return max(scored, key=lambda r: (scored[r], -RUNGS.index(r))) if scored else None


def _cmd_disputes(args) -> int:
    rung = _best_rung()
    if rung is None:
        print("no rung results; run `dtd eval --rung ...` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    sample = sample_misses(load_items(OUT / f"{rung.lower()}_items.jsonl"))
    judged = judge(sample, ctx.texts, sqlite3.connect(INDEX), CACHE / "disputes.jsonl", runner=run_claude)
    # No misses to judge (only on toy data): record an empty sample instead of bootstrapping nothing.
    share = summarise(judged) if judged else {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n_items": 0, "n_clusters": 0}
    doc = {"rung": rung, "model": DISPUTE_MODEL, "sample": len(judged), "share": share,
           "machine_built": True, "prompt": DISPUTE_PROMPT}
    (OUT / "disputes.json").write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"rung": rung, "share": doc["share"]["mean"]}))
    return 0
```

Register `sub.add_parser("disputes").set_defaults(fn=_cmd_disputes)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add evals/disputes.py pipeline/cli.py tests/test_disputes.py
git commit -m "m2: machine-built estimate of disputed labels on a sample of misses, quote-gated

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 14: The LegalBench-RAG comparison and corpus-wide runs

**Files:**
- Create: `facts/external.json`
- Modify: `pipeline/cli.py`
- Test: `tests/test_external.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `facts/external.json`, LegalBench-RAG's MAUD numbers transcribed from the paper. The key names are fixed by the test below.
- Produces: `dtd eval --rung corpus`. It runs R1 and the best ladder rung (by report recall@5) with no contract filter, at k = 64, with character-level precision and recall at k = 1, 2, 4, 8, 16, 32 and 64. It writes `r1_corpus.json` and `best_corpus.json`, and `best_corpus.json`'s `extra.rung` names the rung.

What the report must say, plainly, before any number. Our headline metric and theirs are **not directly comparable**:

| | LegalBench-RAG | This project's headline |
|---|---|---|
| Search space | All documents in the corpus | One agreement (the item's own) |
| Query | A question naming the document ("Consider …; Does this contract …?") | MAUD's deal-point and question names |
| Unit scored | Characters: precision@k and recall@k over character overlap | A gold span is found if a retrieved passage overlaps it by 20 characters |
| Chunks | 500-character fixed or recursive splitter | Section-aware, median about 1,500 characters |

The corpus-wide, character-level runs close the first and third gaps. The queries and chunks still differ, so even those runs are a reference point, not a like-for-like result.

- [ ] **Step 1: Transcribe the published numbers**

Open the paper itself, https://arxiv.org/pdf/2408.10343v1 (not a summary of it). Find the MAUD row or column in the tables for (a) naive chunking without a reranker, (b) the recursive splitter (RCTS) without a reranker, and (c) RCTS with the Cohere reranker. Write `facts/external.json`, recording for each the table number, the k values in the order printed, and precision and recall in percent exactly as printed. The values below were read from an automated summary of the HTML version while writing this plan. **They are unverified.** Correct any that differ from the PDF, and only then set `verified_against_pdf` to `true`.

```json
{
  "legalbench_rag": {
    "source": "Pipitone and Houir Alami, LegalBench-RAG, arXiv:2408.10343v1",
    "url": "https://arxiv.org/abs/2408.10343",
    "verified_against_pdf": false,
    "setup": {
      "search_space": "whole corpus",
      "embedding": "text-embedding-3-large",
      "unit": "characters",
      "query_form": "Consider (document description); (question)"
    },
    "k": [1, 2, 4, 8, 16, 32, 64],
    "methods": {
      "naive": {"label": "Naive 500-character chunks, no reranker", "table": 4,
                "precision_pct": [3.36, 2.65, 2.18, 1.89, 1.48, 1.06, 0.75],
                "recall_pct": [2.54, 3.12, 4.53, 8.75, 13.16, 18.36, 25.62]},
      "rcts": {"label": "Recursive splitter, no reranker", "table": 5,
               "precision_pct": [2.65, 1.77, 1.96, 1.40, 1.39, 1.15, 0.82],
               "recall_pct": [1.65, 2.09, 4.59, 6.18, 12.93, 21.04, 28.28]},
      "rcts_cohere": {"label": "Recursive splitter, Cohere rerank-english-v3.0", "table": 7,
                      "precision_pct": [1.94, 2.63, 2.05, 1.77, 1.79, 1.55, 1.12],
                      "recall_pct": [0.52, 2.48, 4.39, 7.24, 14.03, 22.60, 31.46]}
    }
  }
}
```

- [ ] **Step 2: Write the failing tests**

`tests/test_external.py`:

```python
import json
from pathlib import Path

DOC = json.loads(Path("facts/external.json").read_text())["legalbench_rag"]


def test_external_numbers_were_checked_against_the_paper():
    assert DOC["verified_against_pdf"] is True


def test_every_method_has_a_table_and_a_value_per_k():
    assert set(DOC["methods"]) == {"naive", "rcts", "rcts_cohere"}
    for m in DOC["methods"].values():
        assert isinstance(m["table"], int)
        assert len(m["precision_pct"]) == len(m["recall_pct"]) == len(DOC["k"])
        assert all(0 <= v <= 100 for v in m["precision_pct"] + m["recall_pct"])
```

Append to `tests/test_cli.py`:

```python
def test_corpus_wide_runs_r1_and_the_best_rung(data):
    cli.entry(["build"]); cli.entry(["embed"])
    for rung in ("R1", "R2"):
        cli.entry(["eval", "--rung", rung])
    assert cli.entry(["eval", "--rung", "corpus"]) == 0
    r1 = json.loads((data / "out" / "r1_corpus.json").read_text())
    best = json.loads((data / "out" / "best_corpus.json").read_text())
    assert r1["scope"] == "corpus-wide" and "char_recall@64" in r1["overall"]
    assert best["extra"]["rung"] in ("R1", "R2")
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_external.py tests/test_cli.py -q`
Expected: FAIL: `verified_against_pdf` is still false (until Step 1 is complete), and `corpus` is an unknown rung.

- [ ] **Step 4: Implement the corpus-wide branch**

In `pipeline/cli.py`:

```python
CHAR_KS = (1, 2, 4, 8, 16, 32, 64)
```

and in `_cmd_eval`, before `else`:

```python
    elif rung == "corpus":
        best = _best_rung() or "R1"
        _eval_rung("R1", INDEX, "R1-corpus", ctx, scope="corpus-wide", k=max(CHAR_KS), char_ks=CHAR_KS)
        ladder = _ladder(INDEX, ctx.texts)
        result = evaluate(ctx, "best-corpus", lambda q, c, k: ladder.run(best, q, c, k), OUT,
                          count_tokens=ladder.embedder.count_tokens, scope="corpus-wide", k=max(CHAR_KS),
                          char_ks=CHAR_KS, extra={"rung": best, "settings": asdict(ladder.settings)})
```

(`_eval_rung` forwards `**kw` to `evaluate`. `_best_rung` comes from Task 13.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add facts/external.json pipeline/cli.py tests/test_external.py tests/test_cli.py
git commit -m "m2: LegalBench-RAG's MAUD numbers, checked against the paper, and corpus-wide runs

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 15: M2 facts and `docs/m2/REPORT.md`

**Files:**
- Create: `facts/m2.py`, `facts/report_m2.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_report_m2.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: every M2 output file, `retrieval/settings.json`, `retrieval/lexicon.json`, `facts/external.json`, both index files.
- Produces: `facts.m2.LADDER`, `SIDE`, `CORPUS`, `CHAR_KS`, `CEILING_LO = 0.95`, `LBR_METHODS`, `is_unstable(name) -> bool`, `slug(name) -> str`, `present(out_dir) -> bool`, `build_m2(out_dir, index_db, fixed_db, settings_path, lexicon_path, external_path, n_boot=2000) -> dict`. Every M2 fact name starts with `m2_`.
- Produces: `facts.report_m2.render_m2(f) -> str`.
- `dtd facts` merges M1 and M2 facts once M2 results exist (`r2.json` present). If any M2 input is missing, it names the missing files and returns 2. `--check` skips unstable facts (`latency_ms`, `load_avg`, `index_bytes`). `dtd report` writes `docs/m1/REPORT.md` as before, plus `docs/m2/REPORT.md` when M2 facts exist.

**Reading rules the report encodes:**
- Headline figures are on the report split. Per-family figures are also on the report split, for every rung including R1, so the families compare like with like. M1's per-family table was on all agreements; this report says so.
- Every gain is a paired, agreement-clustered difference with its interval. A rung "helps" only if the interval's lower bound is above zero, "hurts" if its upper bound is below zero, and otherwise shows "no measurable change". PRD §4.1: a rung that does not help is reported as not helping.
- A family is marked a **ceiling** when R1's report-split recall@5 has a lower bound of at least `CEILING_LO`. Gains cannot show there, and the report says so beside the numbers.
- Everything machine-built is labelled: the lexicon, the LLM rewrite comparison and the disputed-label share.
- Latency is from the development machine, with its load average printed beside it; M5 remeasures on the server. Context tokens are counted with the embedding model's tokenizer, a stand-in for the answering model's count, which M4 measures.

- [ ] **Step 1: Write the failing tests**

`tests/test_report_m2.py`:

```python
import re

from facts.report_m2 import render_m2

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


ALLOWED = re.compile(
    r"recall@\d+|precision@\d+|MRR@\d+|nDCG@\d+|\bR\d\b|\bM\d\b|\bk0\b|p50|p95|95%|bge-small-en-v1\.5|"
    r"^\| \d+ \|", re.M)


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m2(Every()).replace(str(SENTINEL), "")
    stray = re.findall(r"\d", ALLOWED.sub("", text))
    assert stray == [], [line for line in text.splitlines() if re.search(r"\d", ALLOWED.sub("", line))]


def test_the_report_carries_the_required_statements():
    text = render_m2(Every())
    assert "machine-built" in text
    assert "not directly comparable" in text
    assert "label names" in text
    assert "This is not legal advice." in text
```

Append to `tests/test_cli.py`:

```python
def test_full_m2_chain_produces_facts_and_both_reports(data, monkeypatch):
    from pathlib import Path

    from evals.bootstrap import split_of
    from tests.fakes import fake_claude
    raw = data / "raw" / "maud"
    part = DOC.split(chr(10) * 2)[1].strip()
    extra = ""
    for i, cid in enumerate([c for c in (f"contract_t{i}" for i in range(40)) if split_of(c) == "tune"][:2]):
        (raw / "contracts" / f"{cid}.txt").write_text(DOC, encoding="utf-8")
        extra += (f'main,{cid},"{part} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,'
                  f'Type of Consideration,{50 + i},General Information\n')
    with open(raw / "MAUD_dev.csv", "a", encoding="utf-8") as fh:
        fh.write(extra)
    monkeypatch.setattr(cli, "run_claude", fake_claude('{"answers": true, "quote": "Closing"}'))
    monkeypatch.setattr(cli, "EXTERNAL", Path("facts/external.json").resolve())
    monkeypatch.setattr(cli, "REPORT_M2", data / "docs" / "m2" / "REPORT.md")
    steps = [["build"], ["embed"], ["lexicon"], ["tune"]]
    steps += [["eval", "--rung", r] for r in ("R1", "R2", "R3", "R4", "R5", "R6")]
    steps += [["rewrite"], ["eval", "--rung", "R5-llm"], ["build", "--fixed"], ["embed", "--fixed"],
              ["eval", "--rung", "R3-fixed"], ["eval", "--rung", "corpus"], ["failures"], ["disputes"],
              ["facts"], ["facts", "--check"], ["report"]]
    for step in steps:
        assert cli.entry(step) == 0, step
    facts = json.loads((data / "facts.json").read_text())
    assert facts["m2_r1_report_recall_at_5"] == facts["r1_report_recall_at_5"]
    assert "machine-built" in (data / "docs" / "m2" / "REPORT.md").read_text()


def test_facts_with_partial_m2_results_name_what_is_missing(data, capsys):
    cli.entry(["build"]); cli.entry(["embed"]); cli.entry(["eval"]); cli.entry(["eval", "--rung", "R2"])
    assert cli.entry(["facts"]) == 2
    assert "r3.json" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_report_m2.py tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'facts.report_m2'`.

- [ ] **Step 3: Implement the facts**

`facts/m2.py`:

```python
import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap
from evals.compare import load_items, paired_bootstrap
from evals.failures import CLASSES
from evals.tune import MAX_P95_MS
from facts.queries import CATEGORIES, REPORT_METRICS

LADDER = ("r1", "r2", "r3", "r4", "r5", "r6")
SIDE = ("r3_fixed", "r5_llm")
CORPUS = ("r1_corpus", "best_corpus")
CMP_METRICS = {"recall_at_5": "recall@5", "mrr_at_10": "mrr@10", "ndcg_at_10": "ndcg@10"}
CHAR_KS = (1, 2, 4, 8, 16, 32, 64)
CEILING_LO = 0.95
LBR_METHODS = ("naive", "rcts", "rcts_cohere")


def is_unstable(name: str) -> bool:
    return "latency_ms" in name or "load_avg" in name or name.endswith("index_bytes")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def present(out_dir: Path) -> bool:
    return (Path(out_dir) / "r2.json").exists()


def _required(out_dir: Path) -> list[Path]:
    names = [f"{r}.json" for r in LADDER + SIDE + CORPUS] + [f"{r}_items.jsonl" for r in LADDER + SIDE]
    names += [f"failures_{r}.json" for r in LADDER] + ["disputes.json"]
    return [Path(out_dir) / n for n in names]


def _ci(f: dict, name: str, block: dict) -> None:
    f[name] = round(block["mean"], 4)
    f[name + "_lo"] = round(block["lo"], 4)
    f[name + "_hi"] = round(block["hi"], 4)


def _delta(f: dict, name: str, cmp: dict) -> None:
    f[name + "_delta"] = round(cmp["delta"], 4)
    f[name + "_lo"] = round(cmp["lo"], 4)
    f[name + "_hi"] = round(cmp["hi"], 4)


def _json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_m2(out_dir: Path, index_db: Path, fixed_db: Path, settings_path: Path, lexicon_path: Path,
             external_path: Path, n_boot: int = 2000) -> dict:
    out_dir = Path(out_dir)
    needed = _required(out_dir) + [Path(p) for p in (fixed_db, settings_path, lexicon_path, external_path)]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        raise FileNotFoundError("M2 inputs missing: " + ", ".join(missing))
    res = {r: _json(out_dir / f"{r}.json") for r in LADDER + SIDE + CORPUS}
    items = {r: load_items(out_dir / f"{r}_items.jsonl") for r in LADDER + SIDE}
    f: dict = {}

    for r in LADDER + SIDE:
        report = res[r]["by_split"]["report"]
        for name, key in REPORT_METRICS.items():
            _ci(f, f"m2_{r}_report_{name}", report[key])
        f[f"m2_{r}_latency_ms_p50"] = round(res[r]["latency_ms"]["p50"], 2)
        f[f"m2_{r}_latency_ms_p95"] = round(res[r]["latency_ms"]["p95"], 2)
        f[f"m2_{r}_load_avg"] = round(res[r]["load"]["before"][0], 2)
        tokens = res[r]["context_tokens"]
        f[f"m2_{r}_context_tokens_mean"] = round(tokens["mean"], 1) if tokens else None
    f["m2_report_items"] = res["r1"]["by_split"]["report"]["recall@5"]["n_items"]
    f["m2_report_contracts"] = res["r1"]["by_split"]["report"]["recall@5"]["n_clusters"]
    f["m2_deal_points"] = len({i.split("|", 1)[1] for i in items["r1"]})

    for i, r in enumerate(LADDER[1:], start=1):
        for name, key in CMP_METRICS.items():
            _delta(f, f"m2_cmp_{r}_vs_r1_{name}", paired_bootstrap(items["r1"], items[r], key, n_boot=n_boot))
            if i > 1:
                prev = LADDER[i - 1]
                _delta(f, f"m2_cmp_{r}_vs_prev_{name}", paired_bootstrap(items[prev], items[r], key, n_boot=n_boot))
    for name, key in CMP_METRICS.items():
        _delta(f, f"m2_cmp_r3_fixed_vs_r3_{name}", paired_bootstrap(items["r3"], items["r3_fixed"], key, n_boot=n_boot))
        _delta(f, f"m2_cmp_r5_llm_vs_r5_{name}", paired_bootstrap(items["r5"], items["r5_llm"], key, n_boot=n_boot))

    for s, category in CATEGORIES.items():
        rows = [row for row in items["r1"].values() if row["split"] == "report" and row["category"] == category]
        f[f"m2_cat_{s}_items"] = len(rows)
        if not rows:
            continue
        by_contract: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            by_contract[row["contract_id"]].append(row["recall@5"])
        r1 = cluster_bootstrap(by_contract, n_boot=n_boot)
        f[f"m2_cat_{s}_contracts"] = len(by_contract)
        f[f"m2_cat_{s}_ceiling"] = r1["lo"] >= CEILING_LO
        f[f"m2_r1_cat_{s}_recall_at_5"] = round(r1["mean"], 4)
        for r in LADDER[1:]:
            cmp = paired_bootstrap(items["r1"], items[r], "recall@5", category=category, n_boot=n_boot)
            f[f"m2_{r}_cat_{s}_recall_at_5"] = round(cmp["b_mean"], 4)
            _delta(f, f"m2_cmp_{r}_vs_r1_cat_{s}_recall_at_5", cmp)

    for r in LADDER:
        fail = _json(out_dir / f"failures_{r}.json")["by_split"]["report"]
        f[f"m2_fail_{r}_misses"] = fail["misses"]
        for c in CLASSES:
            f[f"m2_fail_{r}_{c}"] = fail[c]
    disputes = _json(out_dir / "disputes.json")
    _ci(f, "m2_machine_disputed_share", disputes["share"])
    f["m2_machine_disputed_n"] = disputes["sample"]
    f["m2_machine_disputed_rung"] = disputes["rung"]
    f["m2_machine_disputed_model"] = disputes["model"]

    tuned = _json(settings_path)
    for key in ("depth", "rrf_k0", "reranker", "rerank_depth"):
        f[f"m2_tuned_{key}"] = tuned["settings"][key]
    f["m2_tuned_live_path_ok"] = tuned["live_path_ok"]
    f["m2_tuned_items"] = tuned["tuned_on"]["items"]
    f["m2_tuned_contracts"] = tuned["tuned_on"]["contracts"]
    f["m2_tune_max_p95_ms"] = MAX_P95_MS
    for row in tuned["evidence"]["rerankers"]:
        f[f"m2_bake_{slug(row['reranker'])}_recall_at_5"] = row["recall@5"]
        f[f"m2_bake_{slug(row['reranker'])}_p95_ms"] = row["p95_ms"]

    lexicon = _json(lexicon_path)
    f["m2_lexicon_entries"] = len(lexicon["entries"])
    f["m2_lexicon_model"] = lexicon["_meta"]["model"]
    llm = res["r5_llm"]["extra"]
    f["m2_llm_rewrite_model"] = llm["model"]
    f["m2_llm_rewrite_queries"] = llm["queries"]
    f["m2_llm_rewrite_input_tokens_mean"] = round(llm["input_tokens_mean"], 1)
    f["m2_llm_rewrite_output_tokens_mean"] = round(llm["output_tokens_mean"], 1)

    conn = sqlite3.connect(index_db)
    model, vectors, truncated = conn.execute("SELECT model, vectors, truncated FROM vec_meta").fetchone()
    indexed = conn.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]
    f["m2_vec_model"], f["m2_vec_passages"], f["m2_vec_truncated"] = model, vectors, truncated
    f["m2_defs_per_passage_mean"] = round(conn.execute("SELECT COUNT(*) FROM passage_defs").fetchone()[0] / indexed, 2)
    f["m2_passages_with_defs_share"] = round(
        conn.execute("SELECT COUNT(DISTINCT passage_id) FROM passage_defs").fetchone()[0] / indexed, 4)
    f["m2_index_bytes"] = os.path.getsize(index_db)
    fixed = sqlite3.connect(fixed_db)
    f["m2_fixed_size_chars"] = fixed.execute("SELECT size FROM chunking").fetchone()[0]
    f["m2_fixed_passages_indexed"] = fixed.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]

    for which in CORPUS:
        overall = res[which]["overall"]
        f[f"m2_{which}_rung"] = res[which]["extra"].get("rung", "R1")
        f[f"m2_{which}_recall_at_5"] = round(overall["recall@5"]["mean"], 4)
        for k in CHAR_KS:
            f[f"m2_{which}_char_recall_at_{k}_pct"] = round(100 * overall[f"char_recall@{k}"]["mean"], 2)
            f[f"m2_{which}_char_precision_at_{k}_pct"] = round(100 * overall[f"char_precision@{k}"]["mean"], 2)

    ext = _json(external_path)["legalbench_rag"]
    if list(ext["k"]) != list(CHAR_KS):
        raise ValueError(f"facts/external.json k {ext['k']} differs from CHAR_KS {CHAR_KS}")
    f["m2_lbr_verified"] = ext["verified_against_pdf"]
    f["m2_lbr_source"] = ext["source"]
    for m in LBR_METHODS:
        method = ext["methods"][m]
        f[f"m2_lbr_{m}_table"] = method["table"]
        for k, p, r in zip(ext["k"], method["precision_pct"], method["recall_pct"]):
            f[f"m2_lbr_{m}_precision_at_{k}_pct"] = p
            f[f"m2_lbr_{m}_recall_at_{k}_pct"] = r
    return dict(sorted(f.items()))
```

- [ ] **Step 4: Implement the report**

`facts/report_m2.py`:

```python
from evals.failures import CLASSES, NOT_APPLICABLE
from facts.m2 import CHAR_KS, LADDER, LBR_METHODS, slug
from facts.queries import CATEGORIES
from retrieval.models import RERANKERS

ADDS = {
    "r1": "BM25 over section-aware passages",
    "r2": "Dense only (bge-small-en-v1.5 in sqlite-vec)",
    "r3": "R1 and R2 fused by reciprocal rank",
    "r4": "R3 reranked by a cross-encoder",
    "r5": "R4 with the lexicon rewrite (machine-built lexicon)",
    "r6": "R5 with defined-term expansion",
}
CLASS_LABELS = {
    "definition_missing": "Right passage found, answer is in a definition it uses",
    "right_section_wrong_passage": "Right section, other passage of it",
    "unsectioned_gold": "Answer in text with no section heading",
    "wrong_section": "Wrong section",
}
LBR_LABELS = {"naive": "naive chunks", "rcts": "recursive splitter", "rcts_cohere": "recursive splitter, Cohere rerank"}


def _ci(f, p):
    return f"{f[p]} ({f[p + '_lo']} to {f[p + '_hi']})"


def _d(f, p):
    return f"{f[p + '_delta']:+} ({f[p + '_lo']:+} to {f[p + '_hi']:+})"


def _verdict(f, p):
    if f[p + "_lo"] > 0:
        return "helps"
    if f[p + "_hi"] < 0:
        return "hurts"
    return "no measurable change"


def _ladder(f):
    rows = []
    for i, r in enumerate(LADDER):
        p = f"m2_{r}_report"
        vs_r1 = "baseline" if r == "r1" else f"{_d(f, f'm2_cmp_{r}_vs_r1_recall_at_5')}, {_verdict(f, f'm2_cmp_{r}_vs_r1_recall_at_5')}"
        vs_prev = "" if i < 2 else f"{_d(f, f'm2_cmp_{r}_vs_prev_recall_at_5')}, {_verdict(f, f'm2_cmp_{r}_vs_prev_recall_at_5')}"
        rows.append(f"| {r.upper()} | {ADDS[r]} | {_ci(f, p + '_recall_at_5')} | {f[p + '_recall_at_10']} "
                    f"| {f[p + '_mrr_at_10']} | {f[p + '_ndcg_at_10']} | {vs_r1} | {vs_prev} "
                    f"| {f[f'm2_{r}_latency_ms_p50']} / {f[f'm2_{r}_latency_ms_p95']} "
                    f"| {f[f'm2_{r}_context_tokens_mean']} |")
    return "\n".join(rows)


def _families(f):
    rows = []
    for s, category in CATEGORIES.items():
        if not f[f"m2_cat_{s}_items"]:
            rows.append(f"| {category} | no report-split items |" + " |" * (len(LADDER) + 1))
            continue
        values = " | ".join(str(f[f"m2_{r}_cat_{s}_recall_at_5"]) for r in LADDER)
        note = "ceiling under R1: the query already names the clause's own words" if f[f"m2_cat_{s}_ceiling"] else ""
        rows.append(f"| {category} | {f[f'm2_cat_{s}_items']} | {values} | {note} |")
    return "\n".join(rows)


def _family_deltas(f):
    rows = []
    for s, category in CATEGORIES.items():
        if not f[f"m2_cat_{s}_items"]:
            continue
        cells = " | ".join(_d(f, f"m2_cmp_{r}_vs_r1_cat_{s}_recall_at_5") for r in LADDER[1:])
        rows.append(f"| {category} | {cells} |")
    return "\n".join(rows)


def _failures(f):
    return "\n".join(
        f"| {r.upper()} | {f[f'm2_fail_{r}_misses']} | " + " | ".join(str(f[f"m2_fail_{r}_{c}"]) for c in CLASSES) + " |"
        for r in LADDER)


def _bake(f):
    return "\n".join(f"| {name} | {f[f'm2_bake_{slug(name)}_recall_at_5']} | {f[f'm2_bake_{slug(name)}_p95_ms']} |"
                     for name in RERANKERS)


def _lbr(f, what):
    rows = []
    for k in CHAR_KS:
        theirs = " | ".join(str(f[f"m2_lbr_{m}_{what}_at_{k}_pct"]) for m in LBR_METHODS)
        rows.append(f"| {k} | {theirs} | {f[f'm2_r1_corpus_char_{what}_at_{k}_pct']} "
                    f"| {f[f'm2_best_corpus_char_{what}_at_{k}_pct']} |")
    return "\n".join(rows)


def render_m2(f) -> str:
    rung_heads = " | ".join(r.upper() for r in LADDER)
    delta_heads = " | ".join(f"{r.upper()} minus R1" for r in LADDER[1:])
    class_heads = " | ".join(CLASS_LABELS[c] for c in CLASSES)
    lbr_heads = " | ".join(f"LegalBench-RAG, {LBR_LABELS[m]}" for m in LBR_METHODS)
    not_applicable = "\n".join(f"- {name.replace('_', ' ')}: {why}." for name, why in NOT_APPLICABLE.items())
    return f"""# M2 report: the retrieval ladder on MAUD

Generated by `dtd report` from `facts.json`. Do not edit by hand. This is not legal advice.

## How to read this

- Human-labelled (MAUD) items only. Headline numbers are on the report split ({f['m2_report_contracts']} agreements, {f['m2_report_items']} items); settings were chosen on the tune split alone ({f['m2_tuned_contracts']} agreements, {f['m2_tuned_items']} items).
- **The queries are MAUD's label names**, one of {f['m2_deal_points']} deal points plus its question names, less their "Answer" suffixes. They are already contract vocabulary. R5 rewrites everyday words into contract vocabulary, so it is measured against R1 on these same label-name queries, and a small or zero R5 gain here says little about lay questions; those arrive with M3's machine-built set.
- Every gain is a paired difference on the same items, with a 95% interval from resampling agreements. "Helps" means the interval is above zero, "hurts" below it, and anything else is "no measurable change".
- Latency is per query on the development machine (load average {f['m2_r1_load_avg']} when R1 ran; each rung's own is in `facts.json`). M5 remeasures on the server. Context tokens: the text a model would be shown for the top five passages, counted with the embedding model's tokenizer as a stand-in; M4 measures the answering model's own count.

## The ladder (report split)

| Rung | Adds | recall@5 | recall@10 | MRR@10 | nDCG@10 | recall@5 minus R1 | recall@5 minus previous rung | p50 / p95 ms | Context tokens |
|---|---|---|---|---|---|---|---|---|---|
{_ladder(f)}

R4 uses `{f['m2_tuned_reranker']}` on the top {f['m2_tuned_rerank_depth']} fused passages; fusion takes {f['m2_tuned_depth']} from each leg with k0 = {f['m2_tuned_rrf_k0']}.

## Per question family (recall@5, report split)

Read gains here, not only on average. M1's per-family table was on all agreements; this one is on the report split for every rung.

| Family | Items | {rung_heads} | Note |
|---|---|{"---|" * len(LADDER)}---|
{_families(f)}

| Family | {delta_heads} |
|---|{"---|" * (len(LADDER) - 1)}
{_family_deltas(f)}

## Tuning (tune split only)

Rule: fusion by highest tune recall@5; then the reranker and its depth by highest tune recall@5 among settings whose p95 latency is at most {f['m2_tune_max_p95_ms']} ms on the development machine. Live path within the limit: {f['m2_tuned_live_path_ok']}.

| Reranker | Tune recall@5 | Tune p95 ms |
|---|---|---|
{_bake(f)}

## Chunking: section-aware versus fixed-size (on R3)

Fixed-size chunks are {f['m2_fixed_size_chars']} characters, the median section-aware passage, so that length does not decide the comparison ({f['m2_fixed_passages_indexed']} fixed-size passages indexed). Fixed-size R3 recall@5: {_ci(f, 'm2_r3_fixed_report_recall_at_5')}. Fixed minus section-aware: {_d(f, 'm2_cmp_r3_fixed_vs_r3_recall_at_5')}, {_verdict(f, 'm2_cmp_r3_fixed_vs_r3_recall_at_5')}.

## Query rewriting: the lexicon versus a live LLM (offline comparison)

The lexicon ({f['m2_lexicon_entries']} entries, machine-built by `{f['m2_lexicon_model']}` from defined terms in tune-split agreements, never shown an eval query) costs no model call. The LLM rewrite used `{f['m2_llm_rewrite_model']}` on {f['m2_llm_rewrite_queries']} distinct queries, at a mean of {f['m2_llm_rewrite_input_tokens_mean']} input and {f['m2_llm_rewrite_output_tokens_mean']} output tokens per query; its latency includes the model's reported API time (p50 / p95 {f['m2_r5_llm_latency_ms_p50']} / {f['m2_r5_llm_latency_ms_p95']} ms). LLM rewrite minus lexicon, recall@5: {_d(f, 'm2_cmp_r5_llm_vs_r5_recall_at_5')}, {_verdict(f, 'm2_cmp_r5_llm_vs_r5_recall_at_5')}.

## Why retrieval misses (report split, gold spans not touched by the top five)

| Rung | Misses | {class_heads} |
|---|---|{"---|" * len(CLASSES)}
{_failures(f)}

Under R6 a definition-class miss is one where the definition was shown to the model but the retrieval metric, which credits passages only, does not count it.

Not applicable to these items:
{not_applicable}

**Label disputed (machine-built):** on a sample of {f['m2_machine_disputed_n']} report-split items where {f['m2_machine_disputed_rung']}'s first result was not gold, `{f['m2_machine_disputed_model']}` judged that the first result also answers the question in {_ci(f, 'm2_machine_disputed_share')} of cases, counting a judgement only when its supporting quote occurs verbatim in that result. This estimates how much of the miss rate is label incompleteness; it relabels nothing.

## Index

Vectors: {f['m2_vec_passages']} passages embedded with `{f['m2_vec_model']}`; {f['m2_vec_truncated']} were longer than the model's window and embedded truncated. Definitions attached per passage, mean: {f['m2_defs_per_passage_mean']}; share of passages with at least one: {f['m2_passages_with_defs_share']}. Index file: {f['m2_index_bytes']} bytes.

## Against LegalBench-RAG

The numbers are **not directly comparable**. LegalBench-RAG ({f['m2_lbr_source']}) searches the whole corpus with questions that name the document, scores precision and recall over characters, and uses short fixed-size or recursive chunks. This project's headline searches one agreement with MAUD's label names and counts a gold span found when a retrieved passage overlaps it. To narrow the gap, R1 and the best rung ({f['m2_best_corpus_rung']}) were also run over the whole corpus and scored over characters, below; the queries and the chunks still differ. Their figures are in percent as printed (Tables {f['m2_lbr_naive_table']}, {f['m2_lbr_rcts_table']} and {f['m2_lbr_rcts_cohere_table']}); ours are in percent over all agreements.

Recall over characters, top k:

| k | {lbr_heads} | This project, R1, whole corpus | This project, best rung, whole corpus |
|---|---|---|---|---|---|
{_lbr(f, 'recall')}

Precision over characters, top k:

| k | {lbr_heads} | This project, R1, whole corpus | This project, best rung, whole corpus |
|---|---|---|---|---|---|
{_lbr(f, 'precision')}

Our own metric over the whole corpus, recall@5: R1 {f['m2_r1_corpus_recall_at_5']}, best rung {f['m2_best_corpus_recall_at_5']}.
"""
```

- [ ] **Step 5: Wire the CLI**

In `pipeline/cli.py`:

```python
from facts.build import UNSTABLE
from facts.m2 import build_m2, is_unstable
from facts.m2 import present as m2_present
from facts.report_m2 import render_m2

EXTERNAL = Path("facts/external.json")
REPORT_M2 = Path("docs/m2/REPORT.md")


def _all_facts() -> dict:
    facts = build_facts(INDEX, OUT / "r1.json", _csv_paths())
    if m2_present(OUT):
        facts |= build_m2(OUT, INDEX, INDEX_FIXED, SETTINGS_PATH, LEXICON_PATH, EXTERNAL)
    return facts


def _cmd_facts(args) -> int:
    r1 = OUT / "r1.json"
    if not INDEX.exists() or not r1.exists() or not _csv_paths():
        print("index, r1.json or label CSVs missing; run `dtd fetch`, `dtd build` then `dtd eval` first",
              file=sys.stderr)
        return 2
    try:
        fresh = _all_facts()
    except FileNotFoundError as e:
        print(str(e), file=sys.stderr)
        return 2
    if args.check:
        stored = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.exists() else {}
        stale = sorted(n for n in fresh if n not in UNSTABLE and not is_unstable(n) and stored.get(n) != fresh[n])
        if stale:
            print("stale facts: " + ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    FACTS.write_text(json.dumps(fresh, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _cmd_report(args) -> int:
    if not FACTS.exists():
        print("facts.json missing; run `dtd facts` first", file=sys.stderr)
        return 2
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(facts), encoding="utf-8")
    if "m2_r1_report_recall_at_5" in facts:
        REPORT_M2.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M2.write_text(render_m2(facts), encoding="utf-8")
    return 0
```

The `check_facts` import is no longer used by the CLI. Leave `facts.build.check` in place for its own tests.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. If `test_every_digit_in_the_report_comes_from_facts` fails, it prints the offending lines. Move the digit into a fact; never widen `ALLOWED` for a number.

- [ ] **Step 7: Commit**

```bash
git add facts/m2.py facts/report_m2.py pipeline/cli.py tests/test_report_m2.py tests/test_cli.py
git commit -m "m2: named facts for the ladder and the generated M2 report

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 16: The real run, resume tested by killing, and the numbers of record

**Files:**
- Modify (generated): `facts.json`, `docs/m2/REPORT.md`, `retrieval/settings.json`, `retrieval/lexicon.json`
- Nothing under `data/` is committed (it is gitignored).

This task runs for hours of wall-clock time, mostly unattended. Each long stage is killed once on purpose and resumed, which is the project's resume test. Record each kill's outcome in the commit message.

- [ ] **Step 1: Preconditions**

- Michael has confirmed `MAX_P95_MS` (Task 10). If he changed it, update `evals/tune.py`, run the tests and commit before starting.
- Close heavy applications before the latency-bearing stages (Steps 5–8). The load average is recorded either way.
- `uv run pytest -q && uv run pytest -m model -q` pass.
- `claude -p --help` works (the lexicon, rewrite and disputes stages use it).

- [ ] **Step 2: Rebuild and confirm M1 did not move**

Run: `uv run dtd build && uv run dtd eval && uv run dtd facts --check`
Expected: exit 0, or only new facts reported as stale (`maud_passages_with_article_share`). Any other stale fact: stop.

- [ ] **Step 3: Embed, with a kill**

Run `uv run dtd embed` in the background. When `sqlite3 data/cache/embeddings.db "SELECT COUNT(*) FROM emb"` passes 500, kill it with `kill -9`. Run `uv run dtd embed` again to completion (about 75 minutes at the rate measured while planning).
Expected: the second run's `cached` is at least the count seen at the kill, `embedded + cached` equals the distinct passage count, and `vectors` equals `maud_passages_indexed` in `facts.json` (22,789 at M1).

- [ ] **Step 4: Build the lexicon and look at it**

Run: `uv run dtd lexicon`
Expected: one `claude -p` call, and `retrieval/lexicon.json` with `entries` in the low hundreds. Read 20 entries at random. Discard and rebuild if they are mostly wrong. If a rebuild is needed, say so in the commit.

- [ ] **Step 5: Tune, with a kill**

Run `uv run dtd tune` in the background (about 3 hours, two thirds of it `bge-reranker-base`). After `sqlite3 data/cache/rerank.db "SELECT COUNT(*) FROM rr"` passes 100, `kill -9` it and rerun it to completion.
Expected: the rerun spends its first minutes on cache hits (no reranker compute for those rows) and writes `retrieval/settings.json`. Show Michael the chosen settings and `live_path_ok` before going on.

- [ ] **Step 6: The ladder**

Run: `for r in R1 R2 R3 R4 R5 R6; do uv run dtd eval --rung $r || break; done`
Expected: `r1.json` … `r6.json`. R1's report recall@5 still reads 0.4892.

- [ ] **Step 7: The side comparisons, with a kill on the rewrite**

Run `uv run dtd rewrite`, `kill -9` it after about ten ledger lines (`wc -l data/cache/llm_rewrites.jsonl`), and rerun it. Then:
`uv run dtd eval --rung R5-llm && uv run dtd build --fixed && uv run dtd embed --fixed && uv run dtd eval --rung R3-fixed && uv run dtd eval --rung corpus`
Expected: the rerun of `rewrite` makes no call for the queries already in the ledger (`wc -l` grows only by the remainder).

- [ ] **Step 8: Failures and disputes, with a kill**

Run: `uv run dtd failures`. Then run `uv run dtd disputes`, `kill -9` it after about 20 lines in `data/cache/disputes.jsonl`, and rerun it.
Expected: `failures_r1.json` … `failures_r6.json` and `disputes.json`. The resumed run judges only the remainder of the sample.

- [ ] **Step 9: Facts and report**

Run: `uv run dtd facts && uv run dtd facts --check && uv run dtd report`
Expected: exit 0 each. Then read `docs/m2/REPORT.md` top to bottom and check:
- `m2_r1_report_recall_at_5` equals `r1_report_recall_at_5`.
- Every rung whose interval against R1 includes zero says "no measurable change", and none is described as helping in any other text.
- The MAE and Remedies families are marked as ceilings, or, if the rule did not mark them, say why in the commit message.
- Everything machine-built says so.

- [ ] **Step 10: Commit the numbers of record**

```bash
git add facts.json docs/m2/REPORT.md retrieval/settings.json retrieval/lexicon.json
git commit -m "m2: measured ladder R1-R6 on MAUD with paired intervals, failures and the LegalBench-RAG comparison

Resume tested by kill -9 on embed, tune, rewrite and disputes: <one line each on what the rerun did>.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## What M2 deliberately leaves for later plans

- **R7 deal scoping, and the FTS5 contract filter moved inside `MATCH`** (M3). The current p95 is 49 ms at 22.8k passages, and M3 may reach about 300k. Dense search already filters inside the KNN through the partition key.
- **Lay questions.** T-human's queries are label names. M3's machine-built questions on tech deals are where R5 can be judged on the input it was built for.
- **Answering, the citation gate and abstention** (M4). Context tokens here are a tokenizer stand-in, and M4 counts the answering model's own tokens.
- **Latency on the 1 GB server and the index size against 1 GB** (M5). `live_path_ok` in `retrieval/settings.json` tells M5 whether R4 and above may be served.
- **"Label disputed" per miss.** M2 estimates the share on a sample, and does not assign it per miss.

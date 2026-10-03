# M3: Tech Deals, Deal Scoping (R7) and the Machine-Built Tier — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest M0's technology-target merger agreements with their deal identity, amendments and unfiled-schedule tags into one index with MAUD; add rung R7 (deal scoping by company name); build the machine-built tier T-machine for the three lead families; report the ladder on T-machine and the tier-agreement check (machine key against MAUD's lawyers, and Kendall's tau between rung orderings).

**Architecture:** M0's fetched exhibits are normalised by a new EDGAR text normaliser, assembled into a tech corpus (one canonical agreement per deal, amendments linked) and indexed together with MAUD in `data/index/deals.db`. `maud.db` stays the index of record for M1 and M2, so their numbers cannot move. The index builder gains the M2 carry-overs: a per-contract passage-id range so the FTS5 contract filter runs inside the full-text query, a contentless passage-plus-definitions table and a sized `vec0` chunk. R7 resolves a company named in the question to its deal and runs R6 inside it. T-machine labels come from two independent model passes, each of which reads the agreement's section outline and then the sections it chose. The retrieval ladder never chooses what the labeller reads, so the labels are not biased toward any rung. The same procedure, run on a sample of MAUD agreements, gives the tier-agreement numbers.

**Tech Stack:** Python 3.12, `uv`, `pytest`, SQLite FTS5 and `sqlite-vec` 0.1.9, `fastembed`, `claude -p` (run through `pipeline/claude.py`: no tools, no settings, temporary cwd) for the two labelling passes.

**Spec:** `docs/PRD.md` (milestone M3 of §9; §2.2 and §2.3 ingestion; §4.1 R7; §5.1 T-machine; §5.2 tier agreement; the M0-outcome note before §10). Measured inputs: `docs/m0/REPORT.md`, `docs/m2/REPORT.md`, `facts.json`.

## Global Constraints

- $0 cash. Local models and `claude -p` on the Max plan only.
- sec.gov: M3 needs **no** new request (M0 holds every exhibit). If a task ever needs one, it goes through `pipeline/sec_client.py` in one process, at most 2 requests per second, stops on 403/429, and never through an agent. The contact comes from `SEC_CONTACT`; never write it anywhere.
- Every number the site or README prints comes from `facts.json`, produced by a named query in `facts/`. No digit is hard-coded in report copy. Machine-built numbers carry "machine-built" wherever they appear.
- Every stage is idempotent and resumable. Resume is tested by killing the stage (Task 11), not by reasoning.
- M1's and M2's numbers must not move: `uv run dtd facts --check` passes after every task that touches the index or the ladder.
- Settings are chosen on the tune split only (`evals.bootstrap.split_of`). Headline numbers are read on the report split.
- Results per question family and per tier, never only an average. Rung comparisons are paired and clustered by agreement.
- The README and the launch post are written by Michael by hand; never create or edit `README.md`.
- Commits end with `Assisted-by: Claude` and a `Co-Authored-By:` line naming the model that wrote them.
- Python `>=3.12,<3.13`. Character offsets refer to the canonical text of each contract as stored under `data/raw/maud/contracts` (MAUD) or `data/raw/edgar/contracts` (tech).

## Numbers this plan starts from

M0 (`docs/m0/REPORT.md`, 2026-10-02):
- 319 tech agreements, 313 distinct targets. 20 tech deals have at least one amendment; 72 were seen in more than one copy.
- 66,469 passages from the tech agreements (mean 208 per agreement). Estimated index size at M2's bytes per passage: about 955 MB.
- Lead families: equity awards present in 30 of 30 sampled agreements, termination fee in 29, earn-outs in 0, and employees' pay and benefits (the adopted replacement) in 29. Earn-outs stay as abstention items for M4.
- Press releases never restate the fee (0 of 20), so M4 does not get the PRD §5.2 cross-check in its planned form.

M2 (`docs/m2/REPORT.md`):
- On T-human, R5 (lexicon rewrite) helps, R4 (rerank) shows no measurable change, and R6 shows no change over R5.
- `maud.db` is 327 MB at 22,789 passages. Of that, about 150 MB is empty `vec0` chunk space (one 1,024-row chunk per contract) and about 78 MB is `passages_x_fts` duplicating text. The FTS5 contract filter runs after `MATCH` (p95 49 ms at 22.8k passages).
- The LLM-rewrite comparison replaced the query while the lexicon appended to it. An append variant can be rerun from the cached rewrites without any model call.

Measured on the 319 tech agreements while writing this plan (offline, from `data/m0`):
- Text length: median 318k characters, max 519k. Defined terms: median 133 per agreement. References to a disclosure letter or schedule: median 37 per agreement.
- The section outline (section id and title, one line per section) has a median of 2.8k characters and a max of 4.3k. That is small enough for a model to read whole.
- **12 agreements break the current segmenter.** One is a termination agreement that passed M0's title check. The other 11 are over 200k characters but yield fewer than 10 sections, because EDGAR puts "Section 4.7" and its title on separate lines and uses narrow no-break spaces (U+202F). The fix belongs in an EDGAR normaliser, not the segmenter, so MAUD's passages do not move.
- Task 2's assembly code, dry-run on `data/m0` into a scratch directory: 318 agreements kept, 1 excluded (the termination agreement), 31 amendments linked to 21 deals. 8 targets appear in two deals each (e.g. a re-signed or competing deal), so R7 must treat a bare name for them as ambiguous. Split: 223 report, 95 tune. Only 51 deals get a second alias (a ticker or a filer name), so most questions must name the target roughly as the agreement does.
- Model calls this plan makes, all through `claude -p` on the Max plan ($0 cash): T-machine 318 agreements × 2 passes × 2 calls (outline, then sections for all three families) = 1,272. The tier check is at most 30 × 2 × (1 + 4) = 300, because MAUD has 22 deal points and each sections call carries at most 6. Pass A is `claude-opus-5-5` (the model M0's lead-family pass used), pass B `claude-sonnet-5-5`. Step-2 prompts are capped at 60k characters.
- Embedding: about 66k new tech passages; MAUD's are already cached.
- Of 111 amendment documents, 46 use the explicit form "Section X.Y of the Agreement is hereby amended", which is what deterministic linking can rely on.

## Review Focus

1. **A question naming a company that matches more than one deal** (an acquirer with several targets, or a common word like "Oracle" as buyer and target). R7 must not guess; it falls back to corpus-wide R6 and records the ambiguity. (Test in Task 5.)
2. **An amendment that changes text by a form other than "Section X.Y … is hereby amended"** (e.g. "Exhibit A is replaced", a renumbered clause). No `superseded_by` link may be created from a guess. Only the explicit form links, and the rest are counted. (Test in Task 4.)
3. **An agreement the segmenter still cannot sectionise after normalisation.** The labelling pass must get a fallback outline of fixed chunks, not an empty prompt, and the item is flagged. (Test in Task 6.)
4. **A model quote that occurs more than once in the agreement** (repeated defined-term sentences). The gold span is the occurrence inside the sections that pass chose. If it is not found there, the quote counts as not found; it is never placed at the first match anywhere in the agreement. (Test in Task 6.)
5. **A company name or contract id containing FTS5 operators or punctuation** ("AND", quotes, "&", "+"). The `MATCH` with the contract filter must stay safe and return a list. (Test in Task 3.)

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/edgar_text.py` | EDGAR-specific normalisation: spaces, split headings, repeated running lines, the document's own title |
| `pipeline/tech_corpus.py` | Tech corpus from M0: one canonical agreement per deal, amendments, display names, aliases |
| `pipeline/amendments.py` | Explicit "Section X.Y … is hereby amended" spans and amendment numbers |
| `retrieval/deals.py` | Deal metadata, aliases, `schedule_ref` tags and `superseded` links on the deals index |
| `retrieval/index.py` (modify) | Per-contract passage-id range, contentless passage-plus-definitions table |
| `retrieval/bm25.py` (modify) | Contract filter inside the FTS5 query (passage-id range) |
| `retrieval/vectors.py` (modify) | `vec0` chunk size |
| `retrieval/scope.py` | Company-name resolver for R7 |
| `retrieval/ladder.py`, `retrieval/result.py` (modify) | R7; amended text shown beside a superseded passage; `Retrieved.amended` and `.scope` |
| `evals/tmachine.py` | The two-pass labelling procedure (outline, then sections), agreement, items, R7 scope outcomes |
| `evals/tier.py` | Tier agreement on MAUD: machine key against lawyers' spans, Kendall's tau |
| `facts/m3.py`, `facts/report_m3.py` | M3 named facts; `docs/m3/REPORT.md` |
| `pipeline/cli.py` (modify) | `dtd m3 corpus`, `dtd build --deals`, `dtd embed --deals`, `dtd m3 label`, `dtd m3 eval`, `dtd m3 tier`, `dtd eval --rung R5-llm-append`, facts and report |

---
### Task 1: EDGAR text normaliser

**Files:**
- Create: `pipeline/edgar_text.py`
- Test: `tests/test_edgar_text.py`

**Interfaces:**
- Produces: `normalise_edgar(text: str) -> str`. It replaces Unicode space characters (U+00A0, U+1680, U+2000–U+200B, U+202F, U+205F, U+3000) with a plain space, and joins a section heading split over lines (`Section 4.7` / `4.7.` on its own line, followed by a capitalised title) into one line. It drops running lines, meaning lines 4–79 characters long that occur 8 or more times and are not a section, article or sub-clause heading. Finally it collapses three or more newlines to two.
- Produces: `own_title(text: str) -> str`, the document's own title: the first line under 160 characters, within the first 3,000 characters, that contains the whole word "AGREEMENT" or "PLAN" in capitals, whitespace-normalised and lowercased. (Whole words: "EXPLANATORY NOTE" contains "PLAN", and one tech exhibit opens with an explanatory note.)
- Produces: `is_merger_agreement(text: str) -> bool` — `own_title` contains one of "agreement and plan of merger", "plan and agreement of merger", "agreement of merger", "plan of merger", "merger agreement", and does not start with "termination", "voting", "support", "tender" or "letter".

Why a separate normaliser: `pipeline/segment.py` must not change, because MAUD's passages and therefore M1's and M2's numbers depend on it. EDGAR's HTML conversion splits headings over two lines and uses narrow no-break spaces. Normalising that text before segmentation took the agreements with fewer than 10 sections from 12 to 3 when the code below was run on all 319 tech agreements while writing this plan. Those 3 are the termination agreement (excluded by the title check) and two agreements with no numbered headings at all; the fixed-chunk fallback in Task 6 covers those two. The title check excluded exactly one agreement, the termination agreement.

- [ ] **Step 1: Write the failing tests**

`tests/test_edgar_text.py`:

```python
from pipeline.edgar_text import is_merger_agreement, normalise_edgar, own_title
from pipeline.segment import segment


def test_split_headings_are_joined_and_segment():
    raw = ("TABLE OF CONTENTS\n\nSection 1.1\nThe Merger 2\n\nSection 1.2\nClosing 3\n\n"
           "ARTICLE I\n\nSection 1.1\nThe Merger. Merger Sub merges into the Company.\n\n"
           "Section 1.2\nClosing. The closing occurs on the Closing Date.\n")
    t = normalise_edgar(raw)
    assert "Section 1.1 The Merger." in t
    ids = [p.section_id for p in segment("c", t) if p.kind == "section"]
    assert ids == ["1.1", "1.2"]


def test_bare_numbered_headings_are_joined():
    t = normalise_edgar("3.17.\n\nIntellectual Property. The Company owns its IP.\n\n3.18.\n\nBrokers. None.\n")
    assert "3.17. Intellectual Property." in t and "3.18. Brokers." in t


def test_unicode_spaces_become_plain_spaces():
    assert normalise_edgar("Company\u202fOptions\u00a0vest") == "Company Options vest"


def test_running_lines_are_dropped_but_headings_and_body_kept():
    page = "Body text of the agreement continues here.\n[Signature Page to Agreement and Plan of Merger]\n"
    raw = page * 9 + "Section 2.1 Effect. Each share converts.\n" * 9
    t = normalise_edgar(raw)
    assert "Signature Page" not in t
    assert t.count("Section 2.1 Effect.") == 9
    assert "Body text of the agreement continues here." in t


def test_own_title_and_merger_check():
    assert own_title("Exhibit 2.1\n\nAGREEMENT AND PLAN OF MERGER\n\nby and among …") == "agreement and plan of merger"
    assert is_merger_agreement("Exhibit 2.1\nAGREEMENT AND PLAN OF MERGER\namong …")
    assert not is_merger_agreement("Exhibit 2.1 TERMINATION AGREEMENT Reference is made to the Agreement and Plan of Merger")
    assert not is_merger_agreement("VOTING AND SUPPORT AGREEMENT relating to the Agreement and Plan of Merger")


def test_explanatory_note_is_not_the_title():
    text = ("Exhibit 2.1\n\nEXPLANATORY NOTE TO THIS EXHIBIT\n\nThe representations in this Agreement and Plan of "
            "Merger were made for the parties' benefit.\n\nAGREEMENT AND PLAN OF MERGER\n\namong …")
    assert own_title(text) == "agreement and plan of merger"
    assert is_merger_agreement(text)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_edgar_text.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`pipeline/edgar_text.py`:

```python
import re
from collections import Counter

UNICODE_SPACES = re.compile(r"[\u00a0\u1680\u2000-\u200b\u202f\u205f\u3000]")
SPLIT_HEADING = re.compile(r"(?m)^([ \t]*(?:(?:Section|SECTION)[ \t]+)?\d{1,2}\.\d{1,2}\.?)[ \t]*\n+[ \t]*(?=[A-Z])")
HEADING_LINE = re.compile(r"(?i)^(?:section|article)\b|^\(?[a-z0-9]{1,4}\)")
RUNNING_MIN = 8
TITLES = ("agreement and plan of merger", "plan and agreement of merger", "agreement of merger", "plan of merger",
          "merger agreement")
NOT_THE_AGREEMENT = ("termination", "voting", "support", "tender", "letter")


def _drop_running_lines(text: str) -> str:
    lines = text.split("\n")
    counts = Counter(s for s in (l.strip() for l in lines) if 3 < len(s) < 80)
    drop = {s for s, n in counts.items() if n >= RUNNING_MIN and not HEADING_LINE.match(s)}
    return "\n".join(l for l in lines if l.strip() not in drop)


def normalise_edgar(text: str) -> str:
    t = UNICODE_SPACES.sub(" ", text)
    t = SPLIT_HEADING.sub(r"\1 ", t)
    t = _drop_running_lines(t)
    return re.sub(r"\n{3,}", "\n\n", t)


def own_title(text: str) -> str:
    for line in text[:3000].split("\n"):
        if len(line) < 160 and re.search(r"\b(?:AGREEMENT|PLAN)\b", line):
            return " ".join(line.split()).lower()
    return " ".join(text[:200].split()).lower()


def is_merger_agreement(text: str) -> bool:
    title = own_title(text)
    title = re.sub(r"^exhibit\s+[\d.]+\s*", "", title)
    return any(t in title for t in TITLES) and not title.startswith(NOT_THE_AGREEMENT)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Measure on the real tech agreements (read-only)**

Run:

```bash
uv run python - <<'EOF'
import json
from pathlib import Path
from pipeline.edgar_text import is_merger_agreement, normalise_edgar
from pipeline.segment import segment
deals = [json.loads(l) for l in open("data/m0/deals.jsonl")]
tech = [d for d in deals if d["tech"] and d["signed"] >= "2015-01-01"]
bad = sum(1 for d in tech if len({p.section_id for p in segment("x", normalise_edgar(Path(d["canonical"]["text"]).read_text())) if p.section_id}) < 10)
notm = sum(1 for d in tech if not is_merger_agreement(Path(d["canonical"]["text"]).read_text()))
print({"tech": len(tech), "under_10_sections": bad, "not_merger_by_own_title": notm})
EOF
```

Expected (measured while writing this plan): `under_10_sections` 3 and `not_merger_by_own_title` 1. If either differs, find out why before committing. Record the printed line in the commit message.

- [ ] **Step 6: Commit**

```bash
git add pipeline/edgar_text.py tests/test_edgar_text.py
git commit -m "m3: EDGAR text normaliser (spaces, split headings, running lines) and own-title check

<the Step 5 line>

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 2: The tech corpus

**Files:**
- Create: `pipeline/tech_corpus.py`
- Modify: `pipeline/paths.py`, `pipeline/cli.py`
- Test: `tests/test_tech_corpus.py`

**Interfaces:**
- Consumes: `data/m0/deals.jsonl`, `data/m0/docs.jsonl` and the normalised texts (Task 1); `pipeline.edgar_search.START`, `doc_url`; `pipeline.target.norm`.
- Produces: `pipeline.paths.EDGAR = DATA / "raw" / "edgar"` and `DEALS_INDEX = DATA / "index" / "deals.db"`.
- Produces: `pipeline.tech_corpus.contract_id_for(adsh: str) -> str`, which is `"edgar_" + adsh.replace("-", "")`. It sorts after MAUD's `contract_N` ids, so MAUD's passages keep the lowest ids in a combined index.
- Produces: `assemble(m0_dir: Path, out_dir: Path) -> dict`. It writes `out_dir/contracts/<contract_id>.txt` (normalised canonical agreement) and `out_dir/amendments/<contract_id>.txt` (normalised amendments of those deals), and returns the summary `{deals, kept, excluded_not_merger, amendments, aliases}`. It also writes `out_dir/deals.jsonl`, one row per kept deal:

```json
{"contract_id": "edgar_000119312516…", "target": "Linear Technology Corporation", "parent": "Analog Devices, Inc.",
 "target_cik": "0000791907", "signed": "2016-07-26", "url": "https://www.sec.gov/Archives/edgar/data/…/d…ex21.htm",
 "aliases": ["linear technology", "lltc"], "amendments": [{"contract_id": "edgar_…", "file_date": "2016-…", "url": "…"}],
 "split": "report"}
```

- Produces: `dtd m3 corpus`.

The rules:
- **Which deals.** Every M0 gate deal (`tech` and signed on or after `START`) whose canonical copy passes `is_merger_agreement` after normalisation. Any other is excluded and counted, never dropped silently.
- **Display names.** The display names `target` and `parent` come from the canonical copy's parsed preamble (`docs.jsonl` fields `company`, `parent`), as written in the agreement.
- **Aliases** come from M0's filer display names for the target CIK: the normalised name, and the ticker in parentheses when one is present (e.g. `ACME SOFTWARE INC  (ACME)  (CIK …)` gives `"acme software"` and `"acme"`). An alias of fewer than 4 characters, or one in a short stop list, is dropped.
- **Amendments.** An amendment belongs to a deal when its normalised `(company, parent)` equals the deal key's first two parts. M0 already linked them that way.
- **Split.** `split` is `evals.bootstrap.split_of(contract_id)`.

- [ ] **Step 1: Write the failing test**

`tests/test_tech_corpus.py` builds a miniature `data/m0` in `tmp_path`, with two tech deals (one with an amendment), one non-tech deal, and one tech deal whose canonical text is a termination agreement. It writes the `deals.jsonl` and `docs.jsonl` rows with the fields M0's stages produce (`key`, `signed`, `tech`, `target_cik`, `canonical` with `adsh`, `filename`, `ciks`, `file_date`, `text`; `docs.jsonl` rows with `adsh`, `filename`, `company`, `parent`, `amendment`, `names`, `ciks`, `text`, `missing`, `file_date`). It then asserts:

```python
def test_assemble_keeps_tech_merger_agreements_and_links_amendments(tmp_path):
    m0, out = make_m0(tmp_path)
    summary = assemble(m0, out)
    assert summary == {"deals": 3, "kept": 2, "excluded_not_merger": 1, "amendments": 1, "aliases": 3}
    rows = [json.loads(l) for l in (out / "deals.jsonl").read_text().splitlines()]
    acme = next(r for r in rows if r["target"] == "Acme Software, Inc.")
    assert acme["aliases"] == ["acme software", "acme"]
    assert len(acme["amendments"]) == 1 and (out / "amendments" / f"{acme['amendments'][0]['contract_id']}.txt").exists()
    assert (out / "contracts" / f"{acme['contract_id']}.txt").read_text().startswith("AGREEMENT AND PLAN OF MERGER")
    assert acme["contract_id"].startswith("edgar_") and acme["contract_id"] > "contract_99"


def test_assemble_is_idempotent(tmp_path):
    m0, out = make_m0(tmp_path)
    first = assemble(m0, out)
    assert assemble(m0, out) == first
```

(Write `make_m0` in the test file with the fixture described above; the canonical texts are short strings beginning "AGREEMENT AND PLAN OF MERGER" or "TERMINATION AGREEMENT", and the Acme filer display name is `"ACME SOFTWARE INC  (ACME)  (CIK 0000000011)"`.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_tech_corpus.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`pipeline/tech_corpus.py`:

```python
import json
import re
from pathlib import Path

from evals.bootstrap import split_of
from pipeline.edgar_search import START, doc_url
from pipeline.edgar_text import is_merger_agreement, normalise_edgar
from pipeline.target import norm

STOP = {"the", "and", "inc", "corp", "group", "holdings", "company", "parent", "merger"}
TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})\)")


def contract_id_for(adsh: str) -> str:
    return "edgar_" + adsh.replace("-", "")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _aliases(target: str, display_names: list[str]) -> list[str]:
    out = [norm(target)] if target else []
    for d in display_names:
        out.append(norm(re.sub(r"\(.*?\)|/[A-Z]{2,3}/?", " ", d)))  # "ARI NETWORK SERVICES INC /WI"
        out += [m.group(1).lower() for m in TICKER.finditer(d) if not m.group(1).startswith("CIK")]
    keep = []
    for a in out:
        if len(a) >= 4 and a not in STOP and a not in keep:
            keep.append(a)
    return keep


def assemble(m0_dir: Path, out_dir: Path) -> dict:
    m0_dir, out_dir = Path(m0_dir), Path(out_dir)
    deals = [d for d in _read_jsonl(m0_dir / "deals.jsonl") if d["tech"] and d["signed"] >= START.isoformat()]
    docs = [d for d in _read_jsonl(m0_dir / "docs.jsonl") if not d.get("missing")]
    by_adsh = {d["adsh"]: d for d in docs}
    rows, excluded, n_amend, n_alias = [], 0, 0, 0
    for d in sorted(deals, key=lambda d: d["canonical"]["adsh"]):
        c = d["canonical"]
        text = normalise_edgar(Path(c["text"]).read_text(encoding="utf-8"))
        if not is_merger_agreement(text):
            excluded += 1
            continue
        cid = contract_id_for(c["adsh"])
        _write(out_dir / "contracts" / f"{cid}.txt", text)
        doc = by_adsh.get(c["adsh"], {})
        names = [n for cik, n in zip(doc.get("ciks", []), doc.get("names", [])) if cik == d["target_cik"]]
        amends = []
        for a in docs:
            if a.get("amendment") and a.get("company") and a.get("parent") and \
                    [norm(a["company"]), norm(a["parent"])] == d["key"][:2]:
                acid = contract_id_for(a["adsh"])
                _write(out_dir / "amendments" / f"{acid}.txt", normalise_edgar(Path(a["text"]).read_text(encoding="utf-8")))
                amends.append({"contract_id": acid, "file_date": a["file_date"], "url": doc_url(a)})
        aliases = _aliases(doc.get("company") or "", names)
        n_amend += len(amends)
        n_alias += len(aliases)
        rows.append({"contract_id": cid, "target": doc.get("company"), "parent": doc.get("parent"),
                     "target_cik": d["target_cik"], "signed": d["signed"], "url": doc_url(c), "aliases": aliases,
                     "amendments": sorted(amends, key=lambda a: a["file_date"]), "split": split_of(cid)})
    _write(out_dir / "deals.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    return {"deals": len(deals), "kept": len(rows), "excluded_not_merger": excluded, "amendments": n_amend,
            "aliases": n_alias}
```

In `pipeline/paths.py` add `EDGAR = DATA / "raw" / "edgar"` and `DEALS_INDEX = DATA / "index" / "deals.db"`. In `pipeline/cli.py` add `m3` with sub-command `corpus`, which runs `assemble(DATA / "m0", EDGAR)`, writes the summary atomically to `EDGAR / "summary.json"` (Task 10's facts read it) and prints it. (Task 7 adds the other `m3` sub-commands.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/tech_corpus.py pipeline/paths.py pipeline/cli.py tests/test_tech_corpus.py
git commit -m "m3: tech corpus from M0 — one canonical agreement per deal, amendments, aliases

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 3: Index carry-overs (contract filter inside FTS5, contentless definitions table, sized vec0 chunks)

**Files:**
- Modify: `retrieval/index.py`, `retrieval/bm25.py`, `retrieval/vectors.py`, `retrieval/dense.py`, `pipeline/cli.py`
- Test: `tests/test_index.py`, `tests/test_bm25.py`, `tests/test_vectors.py`, `tests/test_cli.py`

**Interfaces:**
- Produces in every index: `contracts(contract_id, n_chars, first_passage_id, last_passage_id)`. A contract's passages are inserted contiguously, so its rows are exactly the id range.
- Produces: `retrieval.bm25.search(conn, query, contract_id=None, k=10, table="passages_fts")`. When `contract_id` is given, the filter is `<table>.rowid BETWEEN first AND last` inside the FTS5 query (no join filter). The result list, ids and scores are identical to M2's.
- Produces: `passages_x_fts` created with `content=''` (contentless). Nothing reads its text: `Ladder._shown` builds the definitions from `passage_defs` and the canonical text.
- Produces: `retrieval.vectors.VEC_CHUNK = 128` in the `vec0` declaration (`chunk_size=128`, verified accepted by sqlite-vec 0.1.9 while writing this plan). KNN results are unchanged (exact search); only the empty space shrinks.
- Produces: `dtd eval --rung <R> --out <dir>`. It writes the results to `<dir>` instead of `data/out`, so a parity check never overwrites the numbers of record.

Measured while writing this plan on `maud.db` (one contract, 50 repeats): the row-id range filter returned identical ids and scores to M2's join filter and took 0.71 ms against 3.19 ms. Adding a contract column to the FTS tables was rejected because it changed BM25 scores slightly (the per-row length normalisation counts every column).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_bm25.py`:

```python
def test_contract_filter_runs_inside_fts_with_identical_results(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    from retrieval.bm25 import search
    docs = {f"c{i}": f"Section 1.1 Fees. The Company shall pay a termination fee of {i} dollars.\n\n"
                      f"Section 1.2 Closing. The closing shall occur on the closing date.\n" for i in range(5)}
    db = tmp_path / "i.db"
    build_index(db, docs)
    conn = sqlite3.connect(db)
    for cid in docs:
        old = conn.execute(
            "SELECT p.passage_id, -bm25(passages_fts) FROM passages_fts JOIN passages p ON p.passage_id = passages_fts.rowid"
            " WHERE passages_fts MATCH ? AND p.contract_id = ? ORDER BY bm25(passages_fts), p.passage_id LIMIT 10",
            ('"termination" OR "fee"', cid)).fetchall()
        new = [(h.passage_id, h.score) for h in search(conn, "termination fee", contract_id=cid)]
        assert new == old and new


def test_contract_filter_is_safe_for_operator_like_ids(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    from retrieval.bm25 import search
    db = tmp_path / "i.db"
    build_index(db, {'AND "x" OR': "Section 1.1 Fees. A termination fee applies.\n"})
    conn = sqlite3.connect(db)
    assert len(search(conn, "fee", contract_id='AND "x" OR')) == 1
    assert search(conn, "fee", contract_id="unknown") == []
```

Append to `tests/test_index.py`:

```python
def test_contracts_record_their_passage_id_range_and_x_fts_is_contentless(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    db = tmp_path / "i.db"
    build_index(db, {"a": "Section 1.1 A. One.\n\nSection 1.2 B. Two.\n", "b": "Section 1.1 C. Three.\n"})
    conn = sqlite3.connect(db)
    for cid, lo, hi in conn.execute("SELECT contract_id, first_passage_id, last_passage_id FROM contracts"):
        ids = [r[0] for r in conn.execute("SELECT passage_id FROM passages WHERE contract_id = ? ORDER BY passage_id", (cid,))]
        assert ids == list(range(lo, hi + 1))
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'passages_x_fts'").fetchone()[0]
    assert "content=''" in ddl.replace('"', "'")
```

Append to `tests/test_vectors.py`:

```python
def test_vec_table_declares_a_chunk_size(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'passages_vec'").fetchone()[0]
    assert "chunk_size=128" in ddl.replace(" ", "")
```

Append to `tests/test_cli.py` a test that `dtd eval --rung R1 --out <tmp>` writes `r1.json` under `<tmp>` and leaves `data/out` (the fixture's `OUT`) without an `r1.json`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_bm25.py tests/test_index.py tests/test_vectors.py tests/test_cli.py -q`
Expected: FAIL (no id-range columns, join filter still used, no chunk size, no `--out`).

- [ ] **Step 3: Implement**

`retrieval/index.py`: change the `contracts` table to `contracts(contract_id TEXT PRIMARY KEY, n_chars INTEGER NOT NULL, first_passage_id INTEGER, last_passage_id INTEGER)`. After each contract's passages are inserted, `UPDATE contracts SET first_passage_id = ?, last_passage_id = ? WHERE contract_id = ?` with the min and max ids just inserted (both NULL for a contract with no passages). Declare `CREATE VIRTUAL TABLE passages_x_fts USING fts5(text, content='', tokenize='porter unicode61');`. Inserts are unchanged (rowid plus text).

`retrieval/bm25.py`:

```python
def _range(conn: sqlite3.Connection, contract_id: str) -> tuple[int, int] | None:
    row = conn.execute("SELECT first_passage_id, last_passage_id FROM contracts WHERE contract_id = ?",
                       (contract_id,)).fetchone()
    return (row[0], row[1]) if row and row[0] is not None else None


def search(conn: sqlite3.Connection, query: str, contract_id: str | None = None, k: int = 10,
           table: str = "passages_fts") -> list[Hit]:
    if table not in FTS_TABLES:
        raise ValueError(f"unknown FTS table {table!r}")
    match = fts_query(query)
    if not match:
        return []
    where, params = f"{table} MATCH ?", [match]
    if contract_id is not None:
        rng = _range(conn, contract_id)
        if rng is None:
            return []
        where += f" AND {table}.rowid BETWEEN ? AND ?"
        params += list(rng)
    sql = (f"SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, s.score FROM"
           f" (SELECT rowid AS rid, -bm25({table}) AS score FROM {table} WHERE {where}"
           f"  ORDER BY bm25({table}), rowid LIMIT ?) s JOIN passages p ON p.passage_id = s.rid"
           f" ORDER BY s.score DESC, p.passage_id")
    params.append(k)
    return [Hit(*row) for row in conn.execute(sql, params)]
```

(The inner query ranks inside FTS5 and the join only attaches the passage rows, so the order is unchanged. The outer `ORDER BY` keeps M2's tie-break on passage id.)

`retrieval/vectors.py`: `VEC_CHUNK = 128` and the `vec0` declaration gains `, chunk_size={VEC_CHUNK}`. `retrieval/dense.py` is unchanged; it already filters by the partition key.

`pipeline/cli.py`: `eval` gains `--out` (a path; default `OUT`), passed through to every `evaluate` call and to the files it writes.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, including M1's and M2's tests.

- [ ] **Step 5: Prove parity on MAUD**

```bash
cp data/index/maud.db /tmp/maud.before.db
uv run dtd build && uv run dtd embed && uv run dtd build --fixed && uv run dtd embed --fixed
for r in R1 R2 R3 R4 R5 R6 R3-fixed; do uv run dtd eval --rung $r --out data/out/parity || exit 1; done
uv run python - <<'EOF'
import json
for r in ("r1", "r2", "r3", "r4", "r5", "r6", "r3_fixed"):
    a = {x["item_id"]: x["top_passage_ids"] for x in map(json.loads, open(f"data/out/{r}_items.jsonl"))}
    b = {x["item_id"]: x["top_passage_ids"] for x in map(json.loads, open(f"data/out/parity/{r}_items.jsonl"))}
    print(r, "identical top-10 for every item:", a == b)
EOF
ls -l /tmp/maud.before.db data/index/maud.db
uv run dtd facts --check
```

Expected: every rung prints `True`, the index file is markedly smaller (the M2 review estimated about 150 MB of empty chunks and 78 MB of duplicated text), and `facts --check` passes. Reranker scores come from `data/cache/rerank.db`, so R4–R6 cost almost nothing. If any rung is not identical, stop: parity is the condition for this task. Put the before and after sizes in the commit message.

- [ ] **Step 6: Commit**

```bash
git add retrieval/index.py retrieval/bm25.py retrieval/vectors.py pipeline/cli.py tests/
git commit -m "m3: contract filter inside FTS5 by passage-id range, contentless definitions table, vec0 chunk 128

Parity on MAUD: R1–R6 top-10 identical for every item. maud.db <before> -> <after> bytes.

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 4: The deals index (MAUD plus tech), deal metadata, schedule tags and amendment links

**Files:**
- Create: `pipeline/amendments.py`, `retrieval/deals.py`
- Modify: `retrieval/result.py`, `retrieval/ladder.py`, `pipeline/cli.py`
- Test: `tests/test_amendments.py`, `tests/test_deals.py`, `tests/test_ladder.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `EDGAR`, `DEALS_INDEX` and `out_dir/deals.jsonl` (Task 2). From Task 3: `build_index`, which now records each contract's passage-id range. `pipeline.target.preamble`, `norm`.
- Produces: `pipeline.amendments.amended_sections(text: str) -> list[tuple[str, int, int]]`. Each tuple is `(section_id, start, end)`: one per explicit "Section X.Y … of the [Merger] Agreement is hereby amended" (also "amended and restated" and "deleted and replaced"). The span runs from the match to the next match, or to the end of the text, capped at `AMEND_SPAN_MAX = 4000` characters. Nothing else links.
- Produces: `pipeline.amendments.amendment_no(text: str, fallback: int) -> int`. It reads "Amendment No. N" or "First/Second/Third Amendment" in the first 2,000 characters, and otherwise returns `fallback`, the amendment's 1-based position in file-date order.
- Produces: `retrieval.deals.add_deals(db_path, deals: list[dict], texts: dict[str, str], amendment_texts: dict[str, str]) -> dict`. It creates, inside one transaction, these tables:
  - `deals(contract_id PRIMARY KEY, source, target, parent, signed, url, split)`
  - `aliases(alias, contract_id, kind)`, where `kind` is `'target'` or `'parent'`
  - `passage_tags(passage_id, tag)`
  - `superseded(passage_id, amendment_id, amendment_no, file_date, section_id, amend_start, amend_end)`

  It returns `{deals, maud_deals, aliases, schedule_tagged, amendments, amendments_linked, amendments_unlinked, passages_superseded}`.
- Produces: `retrieval.deals.SCHEDULE_REF`, the regex for the `schedule_ref` tag: "Company/Parent Disclosure Letter/Schedule", or "set forth (in|on) Schedule X".
- Produces: `Retrieved.amended: tuple[str, ...] = ()`, the amendment ids whose text was added to the context. `Ladder(…, amendment_texts: dict[str, str] | None = None)`. On an index with a `superseded` table, `_shown` appends `"\n\n[Amended by Amendment No. N, filed YYYY-MM-DD]\n"` plus the amending text, for every superseded hit in the context.
- Produces: `dtd build --deals`. It builds `DEALS_INDEX` from MAUD's contracts plus `EDGAR/contracts`, then calls `add_deals`.

Design decisions (from PRD §2.3, settled here):
- **Amendments add context; they never re-rank.** The amended section is still the right section for the question; what changes is its wording. So ranking is unchanged, and the current wording travels beside the original in the context. `Retrieved.amended` lets M4's answerer say "answer uses amended text (Amendment No. N)". Amendment documents are not indexed as passages. Indexing them would break the contiguous passage-id range per contract that Task 3's filter relies on, and their bare "Section 2.1 is hereby amended" sentences make poor passages.
- **Aliases are at least 4 characters.** `norm` strips company suffixes, so "Big Co" would become the alias "big", and every question using that word would scope to it.
- **MAUD deals get aliases** from `preamble(text).company` and `.parent` when parsed, so a question naming a MAUD company also scopes in R7. MAUD has no URL.
- **Schedule tags** apply to indexed passages only (not TOC).

- [ ] **Step 1: Write the failing tests**

`tests/test_amendments.py`:

```python
from pipeline.amendments import AMEND_SPAN_MAX, amended_sections, amendment_no

AMEND = ("AMENDMENT NO. 2 TO AGREEMENT AND PLAN OF MERGER\n\n1. Section 7.3(b) of the Merger Agreement is hereby "
         "amended and restated in its entirety as follows: \"(b) The Termination Fee shall be $40,000,000.\"\n\n"
         "2. Section 1.4 of the Agreement is hereby amended by replacing \"June 30\" with \"September 30\".\n\n"
         "3. Exhibit A to the Agreement is hereby replaced in its entirety.\n")


def test_explicit_section_amendments_are_found_with_their_spans():
    got = amended_sections(AMEND)
    assert [g[0] for g in got] == ["7.3", "1.4"]
    s, e = got[0][1], got[0][2]
    assert "Termination Fee shall be $40,000,000" in AMEND[s:e] and "Section 1.4" not in AMEND[s:e]


def test_other_forms_never_link():
    assert amended_sections("Exhibit A to the Agreement is hereby replaced in its entirety.") == []
    assert amended_sections("The parties agree that the Outside Date shall be extended to May 1.") == []


def test_span_is_capped():
    text = "Section 2.1 of the Agreement is hereby amended as follows: " + "x" * 10000
    (_, s, e), = amended_sections(text)
    assert e - s == AMEND_SPAN_MAX


def test_amendment_number():
    assert amendment_no(AMEND, fallback=1) == 2
    assert amendment_no("FIRST AMENDMENT TO AGREEMENT AND PLAN OF MERGER", fallback=3) == 1
    assert amendment_no("AMENDMENT TO MERGER AGREEMENT", fallback=3) == 3
```

`tests/test_deals.py` builds an index with `build_index` from two small contracts (`"contract_1"` for MAUD and `"edgar_0001"` for tech). The tech contract has sections "Section 1.4 Outside Date. … June 30 …" and "Section 7.3 Fees. … Company Disclosure Letter …". The test then calls `add_deals` with one tech deal row, which has one amendment (the `AMEND` text above, id `"edgar_0002"`, file date `"2020-02-01"`), and asserts:

```python
def test_add_deals_links_explicit_amendments_and_tags_schedules(deals_db):
    db, summary = deals_db
    assert summary["deals"] == 2 and summary["maud_deals"] == 1
    assert summary["amendments"] == 1 and summary["amendments_linked"] == 1 and summary["amendments_unlinked"] == 0
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT p.section_id, s.amendment_no FROM superseded s JOIN passages p USING(passage_id)"
                        " ORDER BY p.section_id").fetchall()
    assert rows == [("1.4", 2), ("7.3", 2)]
    tagged = conn.execute("SELECT p.section_id FROM passage_tags t JOIN passages p USING(passage_id)"
                          " WHERE t.tag = 'schedule_ref'").fetchall()
    assert tagged == [("7.3",)]
    assert ("acme software", "edgar_0001", "target") in conn.execute("SELECT alias, contract_id, kind FROM aliases").fetchall()


def test_an_amendment_with_no_explicit_form_is_counted_not_linked(tmp_path):
    db, summary = make_deals_db(tmp_path, amendment_text="Exhibit A to the Agreement is hereby replaced in its entirety.")
    assert summary["amendments_linked"] == 0 and summary["amendments_unlinked"] == 1
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM superseded").fetchone()[0] == 0


def test_add_deals_is_idempotent(tmp_path):
    db, first = make_deals_db(tmp_path)
    assert add_deals(db, *deals_inputs(tmp_path)) == first
```

(`make_deals_db`, `deals_inputs` and the `deals_db` fixture live in the test file. The MAUD contract's text starts "AGREEMENT AND PLAN OF MERGER … among Beta Holdings, Inc., … and Gamma Corp. (the "Company")", so its preamble parses.)

Append to `tests/test_ladder.py`. The `deals_ladder` fixture builds the Task 4 deals index the way the existing `ladder` fixture builds its index (`fill_cache` and `build_vectors` with `FakeEmbedder`, the same `CachedReranker(FakeReranker(...))`, lexicon and `Settings`), then calls `add_deals` using `make_deals_db`'s inputs from `tests/test_deals.py`. It returns a `Ladder` over that index with `amendment_texts={"edgar_0002": AMEND}`. Task 5 adds `resolver=Resolver(conn)` to the same fixture.

```python
def test_superseded_hit_carries_the_amending_text(deals_ladder):
    got = deals_ladder.run("R1", "Outside Date June 30", "edgar_0001", k=5)
    assert got.amended == ("edgar_0002",)
    shown = next(c for c in got.context if "Outside Date" in c)
    assert "[Amended by Amendment No. 2, filed 2020-02-01]" in shown and "September 30" in shown


def test_maud_index_has_no_amendments(ladder):
    got = ladder.run("R1", "termination fee", None, k=5)
    assert got.amended == ()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_amendments.py tests/test_deals.py tests/test_ladder.py -q`
Expected: FAIL (`ModuleNotFoundError`, no `amended` field).

- [ ] **Step 3: Implement**

`pipeline/amendments.py`:

```python
import re

AMEND_SPAN_MAX = 4000
AMENDS = re.compile(r"Section\s+(\d{1,2}\.\d{1,2})(?:\([A-Za-z0-9]+\))*\s+of\s+the\s+(?:Merger\s+)?Agreement\s+"
                    r"(?:is|shall\s+be)\s+(?:hereby\s+)?(?:amended|deleted\s+and\s+replaced)", re.I)
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
NUMBER = re.compile(r"Amendment\s+No\.?\s*(\d+)|\b(First|Second|Third|Fourth|Fifth)\s+Amendment\b", re.I)


def amended_sections(text: str) -> list[tuple[str, int, int]]:
    hits = list(AMENDS.finditer(text))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((m.group(1), m.start(), min(end, m.start() + AMEND_SPAN_MAX)))
    return out


def amendment_no(text: str, fallback: int) -> int:
    m = NUMBER.search(text[:2000])
    if not m:
        return fallback
    return int(m.group(1)) if m.group(1) else ORDINALS[m.group(2).lower()]
```

`retrieval/deals.py`:

```python
import re
import sqlite3
from pathlib import Path

from evals.bootstrap import split_of
from pipeline.amendments import amended_sections, amendment_no
from pipeline.target import norm, preamble

SCHEDULE_REF = re.compile(r"\b(?:Company|Parent|Seller|Buyer)\s+Disclosure\s+(?:Letter|Schedule)\b|"
                          r"\bset\s+forth\s+(?:in|on)\s+Schedule\s+\d", re.I)
SCHEMA = """
DROP TABLE IF EXISTS deals; DROP TABLE IF EXISTS aliases; DROP TABLE IF EXISTS passage_tags;
DROP TABLE IF EXISTS superseded;
CREATE TABLE deals(contract_id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT, parent TEXT, signed TEXT,
                   url TEXT, split TEXT NOT NULL);
CREATE TABLE aliases(alias TEXT NOT NULL, contract_id TEXT NOT NULL, kind TEXT NOT NULL);
CREATE INDEX aliases_alias ON aliases(alias);
CREATE TABLE passage_tags(passage_id INTEGER NOT NULL, tag TEXT NOT NULL);
CREATE TABLE superseded(passage_id INTEGER NOT NULL, amendment_id TEXT NOT NULL, amendment_no INTEGER NOT NULL,
                        file_date TEXT NOT NULL, section_id TEXT NOT NULL, amend_start INTEGER NOT NULL,
                        amend_end INTEGER NOT NULL);
CREATE INDEX superseded_passage ON superseded(passage_id);
"""
MIN_ALIAS = 4  # "Big Co" normalises to "big"; a 3-letter alias would scope any question using the word


def _maud_row(cid: str, text: str) -> tuple[dict, list[tuple[str, str]]]:
    p = preamble(text)
    aliases = [(norm(n), kind) for n, kind in ((p.company, "target"), (p.parent, "parent")) if n]
    return ({"contract_id": cid, "source": "maud", "target": p.company, "parent": p.parent,
             "signed": p.signed.isoformat() if p.signed else None, "url": None, "split": split_of(cid)},
            [(a, k) for a, k in aliases if len(a) >= MIN_ALIAS])


def add_deals(db_path: Path, deals: list[dict], texts: dict[str, str], amendment_texts: dict[str, str]) -> dict:
    conn = sqlite3.connect(db_path)
    tech = {d["contract_id"]: d for d in deals}
    s = dict.fromkeys(("deals", "maud_deals", "aliases", "schedule_tagged", "amendments", "amendments_linked",
                       "amendments_unlinked", "passages_superseded"), 0)
    conn.executescript("BEGIN;" + SCHEMA)
    try:
        for (cid,) in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id").fetchall():
            if cid in tech:
                d = tech[cid]
                row = {k: d.get(k) for k in ("target", "parent", "signed", "url", "split")} | {
                    "contract_id": cid, "source": "edgar"}
                aliases = [(a, "target") for a in d["aliases"]] + (
                    [(norm(d["parent"]), "parent")] if d.get("parent") else [])
            else:
                row, aliases = _maud_row(cid, texts[cid])
                s["maud_deals"] += 1
            conn.execute("INSERT INTO deals VALUES (:contract_id, :source, :target, :parent, :signed, :url, :split)",
                         row)
            for a, kind in dict.fromkeys(aliases):
                if len(a) >= MIN_ALIAS:
                    conn.execute("INSERT INTO aliases VALUES (?, ?, ?)", (a, cid, kind))
                    s["aliases"] += 1
            s["deals"] += 1
            passages = conn.execute("SELECT passage_id, section_id, start_char, end_char FROM passages"
                                    " WHERE contract_id = ? AND kind != 'toc'", (cid,)).fetchall()
            for pid, _, a, b in passages:
                if SCHEDULE_REF.search(texts[cid][a:b]):
                    conn.execute("INSERT INTO passage_tags VALUES (?, 'schedule_ref')", (pid,))
                    s["schedule_tagged"] += 1
            for n, am in enumerate(tech.get(cid, {}).get("amendments", []), start=1):
                s["amendments"] += 1
                atext = amendment_texts[am["contract_id"]]
                links = amended_sections(atext)
                s["amendments_linked" if links else "amendments_unlinked"] += 1
                no = amendment_no(atext, fallback=n)
                for sec, a0, a1 in links:
                    for pid, psec, _, _ in passages:
                        if psec == sec:
                            conn.execute("INSERT INTO superseded VALUES (?, ?, ?, ?, ?, ?, ?)",
                                         (pid, am["contract_id"], no, am["file_date"], sec, a0, a1))
                            s["passages_superseded"] += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return s
```

`retrieval/result.py`: add `amended: tuple[str, ...] = ()` to `Retrieved`.

`retrieval/ladder.py`: `Ladder.__init__` gains `amendment_texts: dict[str, str] | None = None`, kept as `self.amendment_texts = amendment_texts or {}`. It also gains `self.has_amendments`, true when `sqlite_master` holds a table named `superseded`. Then:

```python
    def _amendments(self, h) -> list[tuple]:
        if not self.has_amendments:
            return []
        return self.conn.execute(
            "SELECT amendment_id, amendment_no, file_date, amend_start, amend_end FROM superseded"
            " WHERE passage_id = ? ORDER BY file_date, amendment_id", (h.passage_id,)).fetchall()

    def _shown(self, h, with_defs: bool) -> str:
        text = self._passage(h)
        if with_defs:
            defs = [self.texts[h.contract_id][s:e] for s, e in self.conn.execute(
                "SELECT def_start, def_end FROM passage_defs WHERE passage_id = ? ORDER BY rank", (h.passage_id,))]
            text = "\n\n".join([text] + defs)
        for aid, no, filed, a0, a1 in self._amendments(h):
            text += f"\n\n[Amended by Amendment No. {no}, filed {filed}]\n" + self.amendment_texts[aid][a0:a1]
        return text
```

At the end of `run`, `amended = tuple(dict.fromkeys(a[0] for h in hits[:CONTEXT_K] for a in self._amendments(h)))` goes into the returned `Retrieved`.

`pipeline/cli.py`: `build` gains `--deals`. With it, the command reads every `RAW/contracts/*.txt` and every `EDGAR/contracts/*.txt` with `load_contract`, and refuses with exit 2 if `EDGAR/deals.jsonl` is missing ("run `dtd m3 corpus` first"). It then calls `build_index(DEALS_INDEX, contracts)` and `add_deals(DEALS_INDEX, deals, contracts, amendment_texts)`, where `amendment_texts` comes from `EDGAR/amendments/*.txt`. It writes both summaries as one JSON object, atomically, to `DATA/m3/deals_summary.json` (Task 10's facts read it) and prints it. A helper `_deals_texts() -> tuple[dict, dict]` returns `(contracts, amendment_texts)` and is reused by Tasks 7 and 8.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. M1 and M2 tests are unchanged, because `amended` defaults to `()` and `maud.db` has no `superseded` table.

- [ ] **Step 5: Commit**

```bash
git add pipeline/amendments.py retrieval/deals.py retrieval/result.py retrieval/ladder.py pipeline/cli.py tests/
git commit -m "m3: deals index — deal metadata, aliases, schedule tags, explicit amendment links

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 5: R7 — deal scoping by company name

**Files:**
- Create: `retrieval/scope.py`
- Modify: `retrieval/ladder.py`, `retrieval/result.py`
- Test: `tests/test_scope.py`, `tests/test_ladder.py`

**Interfaces:**
- Consumes: the `aliases` table (Task 4).
- Produces: `retrieval.scope.Scope(contract_id: str | None, alias: str | None, candidates: tuple[str, ...])` (frozen dataclass). `candidates` lists the deals the longest matching alias names; it is empty when no alias matched.
- Produces: `retrieval.scope.Resolver(conn)` with `resolve(query: str) -> Scope`. The rules:
  1. Tokenise the query and every alias with `[a-z0-9]+` on the lowercased text. `&` becomes `and`, as in `norm`.
  2. Find every alias whose tokens occur as a contiguous run in the query.
  3. Look at target aliases first. Among those that match, take the longest by token count. If that length is shared by aliases pointing at more than one deal, or one alias points at more than one deal, the result is ambiguous.
  4. Only if no target alias matched, apply the same rule to parent aliases.
  5. A unique deal gives `Scope(cid, alias, (cid,))`. An ambiguous match gives `Scope(None, alias, tuple(sorted(cids)))`. No match gives `Scope(None, None, ())`.
- Produces: `retrieval.ladder.DEAL_RUNGS = RUNGS + ("R7",)`. `RUNGS` itself is unchanged, so M2's loops over it are unchanged. `Ladder(…, resolver=None)`, stored as `self.resolver`; Task 7 reads `ladder.resolver`. `run("R7", query, contract_id=None, …)` resolves the scope and runs R6 with `contract_id=scope.contract_id`. An explicit `contract_id` argument is ignored for R7, because R7 exists to find the deal. `run` raises `ValueError` for R7 without a resolver.
- Produces: `Retrieved.scope: Scope | None = None`, set by R7 only.

- [ ] **Step 1: Write the failing tests**

`tests/test_scope.py`:

```python
import sqlite3

from retrieval.scope import Resolver, Scope


def make(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", rows)
    return Resolver(conn)


def test_unique_target_alias_scopes():
    r = make([("linear technology", "edgar_1", "target"), ("lltc", "edgar_1", "target"),
              ("analog devices", "edgar_1", "parent")])
    assert r.resolve("What happens to Linear Technology's stock options?") == Scope("edgar_1", "linear technology", ("edgar_1",))
    assert r.resolve("lltc termination fee").contract_id == "edgar_1"


def test_longest_alias_wins():
    r = make([("acme", "edgar_1", "target"), ("acme software", "edgar_2", "target")])
    assert r.resolve("Acme Software break-up fee").contract_id == "edgar_2"


def test_ambiguous_alias_falls_back_and_says_so():
    r = make([("oracle", "edgar_1", "parent"), ("oracle", "edgar_2", "parent")])
    s = r.resolve("What did Oracle agree to pay?")
    assert s == Scope(None, "oracle", ("edgar_1", "edgar_2"))


def test_target_beats_parent():
    r = make([("oracle", "edgar_1", "target"), ("oracle", "edgar_2", "parent"), ("oracle", "edgar_3", "parent")])
    assert r.resolve("oracle options").contract_id == "edgar_1"


def test_no_match_and_punctuation_safe():
    r = make([("at and t", "edgar_9", "target")])
    assert r.resolve("AT&T employees' benefits").contract_id == "edgar_9"
    assert r.resolve('"AND" OR NEAR(* fee') == Scope(None, None, ())
    assert r.resolve("") == Scope(None, None, ())
```

Append to `tests/test_ladder.py` a test using the `deals_ladder` fixture from Task 4, with `resolver=Resolver(conn)` added (its aliases include `"acme software"` → `"edgar_0001"`). It asserts that `run("R7", "Acme Software outside date", k=5)` returns hits only from `edgar_0001`, with `scope.contract_id == "edgar_0001"`. A second assertion: a query naming no company gives the same passage ids as `run("R6", same_query, None, k=5)` and `scope == Scope(None, None, ())`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_scope.py tests/test_ladder.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`retrieval/scope.py`:

```python
import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

WORD = re.compile(r"[a-z0-9]+")


def tokens(s: str) -> tuple[str, ...]:
    return tuple(WORD.findall(s.lower().replace("&", " and ")))


@dataclass(frozen=True)
class Scope:
    contract_id: str | None
    alias: str | None
    candidates: tuple[str, ...]


class Resolver:
    def __init__(self, conn: sqlite3.Connection):
        self.by_kind: dict[str, dict[tuple[str, ...], set[str]]] = {"target": defaultdict(set),
                                                                     "parent": defaultdict(set)}
        for alias, cid, kind in conn.execute("SELECT alias, contract_id, kind FROM aliases"):
            t = tokens(alias)
            if t:
                self.by_kind[kind][t].add(cid)

    @staticmethod
    def _occurs(alias: tuple[str, ...], q: tuple[str, ...]) -> bool:
        n = len(alias)
        return any(q[i:i + n] == alias for i in range(len(q) - n + 1))

    def resolve(self, query: str) -> Scope:
        q = tokens(query)
        for kind in ("target", "parent"):
            hits = [a for a in self.by_kind[kind] if self._occurs(a, q)]
            if not hits:
                continue
            longest = max(len(a) for a in hits)
            top = [a for a in hits if len(a) == longest]
            cids = sorted(set().union(*(self.by_kind[kind][a] for a in top)))
            alias = " ".join(sorted(top)[0])
            return Scope(cids[0], alias, tuple(cids)) if len(cids) == 1 else Scope(None, alias, tuple(cids))
        return Scope(None, None, ())
```

`retrieval/result.py`: add `scope: object = None` to `Retrieved` (typed `Scope | None` in a comment). This avoids an import cycle with `retrieval.scope`.

`retrieval/ladder.py`: add `DEAL_RUNGS = RUNGS + ("R7",)`, and `resolver=None` in `__init__`. At the top of `run`:

```python
        if rung == "R7":
            if self.resolver is None:
                raise ValueError("R7 needs a resolver over the deals index")
            scope = self.resolver.resolve(query)
            got = self.run("R6", query, scope.contract_id, k, rewritten)
            return replace(got, scope=scope)
```

The existing check becomes `if rung not in DEAL_RUNGS`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add retrieval/scope.py retrieval/ladder.py retrieval/result.py tests/test_scope.py tests/test_ladder.py
git commit -m "m3: R7 — resolve a company named in the question to its deal, fall back on ambiguity

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 6: T-machine — the two-pass labelling procedure

**Files:**
- Create: `evals/tmachine.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_tmachine.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `pipeline.claude.run_claude(prompt, model) -> dict` (reply with `"result"` and `"usage"`); `pipeline.ledger.Ledger(path, key="key")`; `pipeline.m0._json_object(s, keys)`; `pipeline.m0.LEAD_TOPICS` and `CANDIDATE_SPECS` (the topic sentences M0 measured with); `pipeline.normalise.squash`; `evals.items.Item`, `evals.items._merged`; `evals.bootstrap.split_of`; the deals index's `passages` table.
- Produces, in `evals/tmachine.py`:
  - `FAMILIES = ("equity_awards", "termination_fee", "employee_benefits")`, `TOPICS: dict[str, str]` (the M0 topic sentence per family) and `TEMPLATES: dict[str, str]` (a lay question per family with `{target}`).
  - `PASSES = (("a", "claude-opus-5-5"), ("b", "claude-sonnet-5-5"))`. Two different models, so the passes are independent, not one model asked twice.
  - `Outline(lines: tuple[str, ...], sections: dict[str, tuple[int, int]], fallback: bool)`.
  - `outline(passages: list[tuple[str, str, int, int]], text: str) -> Outline`. The input is the contract's non-TOC passages as `(section_id, section_title, start, end)` in document order. Each consecutive run of one non-empty section id becomes one outline line `"<id> <title>"`. A repeated id later in the text becomes `"<id>#2"`. With fewer than `MIN_SECTIONS = 10` sections, the outline falls back to fixed chunks of `CHUNK = 6000` characters, `"C1"`, `"C2"`, …, each line showing its first 100 non-space-collapsed characters, and sets `fallback=True`.
  - `locate(quote: str, text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]`. Curly quotes and dashes are folded to ASCII and whitespace is ignored. The quote is split on ellipses, and each piece of at least `MIN_QUOTE = 20` non-space characters is searched for **only inside `spans`**, in order. A piece found nowhere in `spans` is not located, even if it occurs elsewhere in the agreement.
  - `label_contract(cid, text, ol, topics, model, runner, ledger, pass_name, group=6) -> dict[str, dict]` gives, per topic, `{"found": bool, "sections": [ids], "spans": [[s, e], …], "answer": str, "unlocated": int, "truncated": bool, "error": bool}`. It makes one step-1 call (outline → up to 3 section ids per topic) and one step-2 call per group of at most `group` topics (the chosen sections' text, capped at `STEP2_CAP = 60000` characters → found, quotes, answer). Replies are cached in the ledger under `"{pass}|{model}|{cid}|outline"` and `"{pass}|{model}|{cid}|sections|{i}"`. Parsing is recomputed from the cached reply text, so a parser fix needs no new call.
  - `status(a: dict, b: dict, section_at) -> str` returns one of `"kept"`, `"absent"`, `"disagree"`, `"one_found"`, `"error"`. `section_at(pos) -> str` gives the section id of the passage containing `pos`, or `""`.
  - `label_all(conn, texts, contracts: list[tuple[str, str]], topics, passes, runner, ledger_path, workers=4, max_new=None, topics_by_contract=None) -> tuple[list[dict], dict]`. `contracts` is `(contract_id, target display name)`. `topics_by_contract`, if given, maps a contract id to its own topics and overrides `topics` for that contract (Task 8 uses it, because each MAUD agreement has its own deal points). It returns one row per (contract, topic) for every contract whose calls are all cached, and a summary. Model calls run in a thread pool of `workers`; ledger reads and writes are serialised by a lock. `max_new` bounds how many contracts that still need calls are started in this run.
  - `items_from_rows(rows) -> list[Item]`. Kept rows only: `item_id = f"{cid}|{family}"`, `text_type = category = family`, `query = TEMPLATES[family].format(target=…)`, `gold` = the merged spans of both passes.
- Produces: `dtd m3 label [--workers 4] [--max-new N]`. It writes `DATA/m3/tmachine.jsonl` (rows) and `DATA/m3/tmachine_summary.json`, from the ledger `DATA/m3/tmachine_ledger.jsonl`.

How the procedure keeps the labels independent of the ladder: neither pass sees a retrieval result. Each reads the agreement's own outline, picks sections, then reads those sections. A pass's gold is where its quotes sit in the canonical text.

**Agreement rule.** A pass counts as found when the model said found **and** at least one quote was located. Two found passes agree when one pass's span overlaps the other's, or both start in the same non-empty section. `kept` items become T-machine retrieval items, with gold equal to the merged spans of both passes. `absent` (both passes said not found) is recorded for M4's abstention set and is not a retrieval item. The agreement rate published per family is `kept / (kept + disagree + one_found)`. Both answers are stored beside each kept row; M4 scores answers against them.

- [ ] **Step 1: Write the failing tests**

`tests/test_tmachine.py`:

```python
import json

import pytest

from evals.tmachine import (CHUNK, MIN_SECTIONS, TEMPLATES, items_from_rows, label_all, label_contract, locate,
                            outline, status)
from pipeline.ledger import Ledger

TEXT = ("AGREEMENT AND PLAN OF MERGER\n\n"
        "Section 2.3 Treatment of Company Options. Each Company Option shall be cancelled and converted into the "
        "right to receive cash equal to the spread.\n\n"
        "Section 6.9 Employee Matters. For one year after the Closing, Parent shall provide each Continuing "
        "Employee base pay no less favorable than before.\n\n"
        "Section 8.3 Termination Fee. The Company shall pay Parent a fee of $25,000,000 (the “Termination Fee”).\n\n"
        "Section 9.1 Notices. Each Company Option holder shall be notified.\n")


def passages_of(text):
    out = []
    for sid, title in (("2.3", "Treatment of Company Options"), ("6.9", "Employee Matters"),
                       ("8.3", "Termination Fee"), ("9.1", "Notices")):
        s = text.index(f"Section {sid}")
        e = text.find("\n\nSection", s + 1)
        out.append((sid, title, s, len(text) if e < 0 else e))
    return out


def test_outline_lines_and_fallback():
    ol = outline(passages_of(TEXT), TEXT)
    assert ol.fallback  # only 4 sections, under MIN_SECTIONS
    big = [(f"{i}.1", f"Title {i}", i * 100, i * 100 + 90) for i in range(1, MIN_SECTIONS + 1)]
    ol2 = outline(big, "x" * 2000)
    assert not ol2.fallback and ol2.lines[0] == "1.1 Title 1" and ol2.sections["1.1"] == (100, 190)
    fb = outline([], "y" * (CHUNK * 2 + 5))
    assert fb.fallback and list(fb.sections) == ["C1", "C2", "C3"] and fb.sections["C3"] == (CHUNK * 2, CHUNK * 2 + 5)


def test_repeated_section_id_gets_a_suffix():
    rows = [(f"{i}.1", "T", i * 10, i * 10 + 5) for i in range(1, MIN_SECTIONS + 1)] + [("1.1", "Again", 500, 520)]
    assert "1.1#2" in outline(rows, "z" * 600).sections


def test_locate_only_inside_the_given_spans():
    s23 = TEXT.index("Section 2.3")
    s91 = TEXT.index("Section 9.1")
    quote = "Each Company Option"
    # the phrase occurs in 2.3 and 9.1; with only 9.1 given, it is found there and nowhere else
    got = locate(quote + " holder shall be notified", TEXT, [(s91, len(TEXT))])
    assert got and got[0][0] >= s91
    assert locate("Each Company Option shall be cancelled", TEXT, [(s91, len(TEXT))]) == []
    assert locate("Each Company Option shall be cancelled", TEXT, [(s23, s91)])[0][0] >= s23


def test_locate_folds_quotes_whitespace_and_ellipses():
    s83 = TEXT.index("Section 8.3")
    got = locate('a fee of $25,000,000   (the "Termination Fee")', TEXT, [(s83, len(TEXT))])
    assert len(got) == 1
    two = locate("For one year after the Closing ... base pay no less favorable than before", TEXT, [(0, len(TEXT))])
    assert len(two) == 2


class FakeRunner:
    """Step 1 picks sections by keyword; step 2 quotes from the sections shown."""

    SECTION_IDS = {"equity_awards": ["2.3"], "termination_fee": ["8.3"], "employee_benefits": ["6.9"]}

    def __init__(self, quotes, ids=None):
        self.quotes, self.ids, self.calls = quotes, ids or self.SECTION_IDS, []

    def __call__(self, prompt, model):
        self.calls.append(model)
        if prompt.startswith("Below is the outline"):
            reply = self.ids
        else:
            reply = {t: ({"found": True, "quotes": [q], "answer": f"{t} answer"} if q else
                         {"found": False, "quotes": [], "answer": ""}) for t, q in self.quotes.items()
                     if f'"{t}"' in prompt}
        return {"result": json.dumps(reply), "usage": {"input_tokens": 10, "output_tokens": 5}}


QUOTES = {"equity_awards": "Each Company Option shall be cancelled and converted",
          "termination_fee": "The Company shall pay Parent a fee of $25,000,000",
          "employee_benefits": "base pay no less favorable than before"}
CHUNK_IDS = {t: ["C1"] for t in QUOTES}  # TEXT has 4 sections, so its outline is one fixed chunk, C1


def big_outline():
    from evals.tmachine import Outline
    ps = passages_of(TEXT)
    return Outline(tuple(f"{s} {t}" for s, t, _, _ in ps), {s: (a, b) for s, _, a, b in ps}, False)


def test_label_contract_locates_quotes_in_the_chosen_sections_and_caches(tmp_path):
    from evals.tmachine import TOPICS
    runner = FakeRunner(QUOTES)
    ledger = Ledger(tmp_path / "l.jsonl", key="key")
    got = label_contract("edgar_1", TEXT, big_outline(), TOPICS, "m", runner, ledger, "a")
    assert all(got[f]["found"] and got[f]["spans"] for f in QUOTES)
    assert got["termination_fee"]["sections"] == ["8.3"]
    n = len(runner.calls)
    label_contract("edgar_1", TEXT, big_outline(), TOPICS, "m", runner, ledger, "a")
    assert len(runner.calls) == n  # second run is all cache


def test_status_rules():
    sec = lambda pos: "2.3" if pos < 200 else "6.9"
    f = lambda spans, found=True: {"found": found, "spans": spans, "error": False}
    assert status(f([[10, 50]]), f([[40, 90]]), sec) == "kept"
    assert status(f([[10, 20]]), f([[100, 120]]), sec) == "kept"  # same section 2.3
    assert status(f([[10, 20]]), f([[300, 320]]), sec) == "disagree"
    assert status(f([], False), f([], False), sec) == "absent"
    assert status(f([[10, 20]]), f([], False), sec) == "one_found"
    assert status(f([]), f([[10, 20]]), sec) == "one_found"  # said found, quote not located
    assert status({"found": False, "spans": [], "error": True}, f([[10, 20]]), sec) == "error"
    assert status(f([[10, 20]]), f([[300, 320]]), lambda pos: "") == "disagree"  # no section: overlap only


def test_unparseable_reply_marks_error_not_absent(tmp_path):
    from evals.tmachine import TOPICS
    runner = lambda prompt, model: {"result": "I cannot help with that.", "usage": {}}
    got = label_contract("edgar_1", TEXT, big_outline(), TOPICS, "m", runner, Ledger(tmp_path / "l.jsonl", key="key"), "a")
    assert all(v["error"] and not v["found"] for v in got.values())


def test_label_all_rows_items_and_resume(tmp_path, deals_conn):
    # deals_conn: an index built with build_index({"edgar_1": TEXT}) (fixture in this file)
    from evals.tmachine import PASSES, TOPICS
    runner = FakeRunner(QUOTES, ids=CHUNK_IDS)
    rows, summary = label_all(deals_conn, {"edgar_1": TEXT}, [("edgar_1", "Acme Software, Inc.")], TOPICS, PASSES,
                              runner, tmp_path / "l.jsonl", workers=2)
    assert summary["kept"] == 3 and summary["complete"] == 1 and summary["fallback_contracts"] == 1
    assert sorted(set(runner.calls)) == sorted(m for _, m in PASSES)
    items = items_from_rows(rows)
    assert {i.item_id for i in items} == {f"edgar_1|{f}" for f in QUOTES}
    ea = next(i for i in items if i.category == "equity_awards")
    assert ea.query == TEMPLATES["equity_awards"].format(target="Acme Software, Inc.")
    assert TEXT[ea.gold[0][0]:ea.gold[0][1]].startswith("Each Company Option shall be cancelled")
    n = len(runner.calls)
    label_all(deals_conn, {"edgar_1": TEXT}, [("edgar_1", "Acme Software, Inc.")], TOPICS, PASSES, runner,
              tmp_path / "l.jsonl")
    assert len(runner.calls) == n


def test_max_new_bounds_the_run(tmp_path, deals_conn_two):
    from evals.tmachine import PASSES, TOPICS
    conn, texts = deals_conn_two  # two contracts, edgar_1 and edgar_2, both TEXT
    runner = FakeRunner(QUOTES, ids=CHUNK_IDS)
    rows, summary = label_all(conn, texts, [("edgar_1", "A"), ("edgar_2", "B")], TOPICS, PASSES, runner,
                              tmp_path / "l.jsonl", max_new=1)
    assert summary["complete"] == 1 and {r["contract_id"] for r in rows} == {"edgar_1"}


def test_topics_by_contract(tmp_path, deals_conn_two):
    from evals.tmachine import PASSES, TOPICS
    conn, texts = deals_conn_two
    runner = FakeRunner(QUOTES, ids=CHUNK_IDS)
    per = {"edgar_2": {"equity_awards": TOPICS["equity_awards"]}}
    rows, summary = label_all(conn, texts, [("edgar_1", "A"), ("edgar_2", "B")], TOPICS, PASSES, runner,
                              tmp_path / "l.jsonl", topics_by_contract=per)
    assert sorted((r["contract_id"], r["family"]) for r in rows) == sorted(
        [("edgar_1", f) for f in QUOTES] + [("edgar_2", "equity_awards")])
```

Fixtures in the same file:

```python
@pytest.fixture
def deals_conn(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    build_index(tmp_path / "d.db", {"edgar_1": TEXT})
    return sqlite3.connect(tmp_path / "d.db", check_same_thread=False)


@pytest.fixture
def deals_conn_two(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    texts = {"edgar_1": TEXT, "edgar_2": TEXT}
    build_index(tmp_path / "d.db", texts)
    return sqlite3.connect(tmp_path / "d.db", check_same_thread=False), texts
```

Append to `tests/test_cli.py`: `dtd m3 label` with `cli.run_claude` monkeypatched to a fake runner, on a fixture `EDGAR` and `DEALS_INDEX` (patch `cli.EDGAR`, `cli.DEALS_INDEX`, `cli.DATA`). It writes `m3/tmachine.jsonl` and `m3/tmachine_summary.json`. A second run with a runner that raises makes no call and exits 0.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tmachine.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`evals/tmachine.py`:

```python
import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from evals.bootstrap import split_of
from evals.items import Item, _merged
from pipeline.ledger import Ledger
from pipeline.m0 import CANDIDATE_SPECS, LEAD_TOPICS, _json_object
from pipeline.normalise import squash

FAMILIES = ("equity_awards", "termination_fee", "employee_benefits")
TOPICS = {"equity_awards": LEAD_TOPICS["equity_awards"], "termination_fee": LEAD_TOPICS["termination_fee"],
          "employee_benefits": next(sp.topic for sp in CANDIDATE_SPECS if sp.name == "employee_benefits")}
TEMPLATES = {"equity_awards": "What happens to {target} employees' stock options and RSUs in the merger?",
             "termination_fee": "How much does {target} have to pay if the merger agreement is terminated?",
             "employee_benefits": "Will {target} employees keep their pay and benefits after the merger?"}
PASSES = (("a", "claude-opus-5-5"), ("b", "claude-sonnet-5-5"))
MIN_SECTIONS = 10
CHUNK = 6000
STEP2_CAP = 60000
MAX_SECTIONS = 3
MIN_QUOTE = 20
INPUT_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
FOLD = str.maketrans({chr(0x201C): '"', chr(0x201D): '"', chr(0x2018): "'", chr(0x2019): "'",
                      chr(0x2013): "-", chr(0x2014): "-"})
ELLIPSIS = ("...", chr(0x2026))

STEP1 = """Below is the outline of one merger agreement: one line per section, its id first. For each topic, list the ids of up to 3 sections most likely to contain the provision that governs it, best first. Use [] if no section fits.

Topics:
{topics}

Reply with one JSON object and nothing else, mapping each topic name to a list of ids, for example {example}

Outline:
{outline}"""

STEP2 = """Below are sections of one merger agreement, each headed by its id in square brackets. For each topic, decide whether these sections contain the provision that governs it. If they do, copy up to 3 short passages that state it, each one sentence or clause of 40 to 400 characters, exactly as written in the agreement, and answer the topic in one plain sentence.

Topics:
{topics}

Reply with one JSON object and nothing else, for example {example}

Sections:
{sections}"""


@dataclass(frozen=True)
class Outline:
    lines: tuple[str, ...]
    sections: dict
    fallback: bool


def outline(passages: list[tuple[str, str, int, int]], text: str) -> Outline:
    runs: list[list] = []
    for sid, title, s, e in passages:
        if not sid:
            continue
        if runs and runs[-1][0] == sid:
            runs[-1][3] = max(runs[-1][3], e)
        else:
            runs.append([sid, title, s, e])
    sections, lines, seen = {}, [], {}
    for sid, title, s, e in runs:
        seen[sid] = seen.get(sid, 0) + 1
        key = sid if seen[sid] == 1 else f"{sid}#{seen[sid]}"
        sections[key] = (s, e)
        lines.append(f"{key} {title}".strip())
    if len(sections) >= MIN_SECTIONS:
        return Outline(tuple(lines), sections, False)
    sections, lines = {}, []
    for i, s in enumerate(range(0, len(text), CHUNK), start=1):
        sections[f"C{i}"] = (s, min(len(text), s + CHUNK))
        lines.append(f"C{i}: " + " ".join(text[s:s + 300].split())[:100])
    return Outline(tuple(lines), sections, True)


def locate(quote: str, text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces = [quote]
    for e in ELLIPSIS:
        pieces = [p for q in pieces for p in q.split(e)]
    out = []
    for piece in pieces:
        q = "".join(piece.translate(FOLD).split())
        if len(q) < MIN_QUOTE:
            continue
        for s, e in spans:
            sq, idx = squash(text[s:e].translate(FOLD))
            i = sq.find(q)
            if i >= 0:
                out.append((s + idx[i], s + idx[i + len(q) - 1] + 1))
                break
    return out


def _topics_block(topics: dict[str, str]) -> str:
    return "\n".join(f"- {t}: {d}" for t, d in topics.items())


def _ask(ledger, lock, key, prompt, model, runner) -> str:
    with lock:
        rec = ledger.get(key)
    if rec is None:
        resp = runner(prompt, model)
        usage = resp.get("usage", {})
        rec = {"key": key, "model": model, "result": resp["result"],
               "input_tokens": sum(usage.get(k, 0) for k in INPUT_KEYS), "output_tokens": usage.get("output_tokens", 0)}
        with lock:
            ledger.put(rec)
    return rec["result"]


def _parse(reply: str, keys) -> dict | None:
    try:
        return _json_object(reply, tuple(keys))
    except RuntimeError:
        return None


def label_contract(cid, text, ol: Outline, topics: dict[str, str], model, runner, ledger, pass_name, group=6,
                   lock=None) -> dict[str, dict]:
    lock = lock or threading.Lock()
    base = f"{pass_name}|{model}|{cid}"
    example1 = json.dumps({t: [] for t in topics})
    reply = _ask(ledger, lock, f"{base}|outline", STEP1.format(topics=_topics_block(topics), example=example1,
                                                              outline="\n".join(ol.lines)), model, runner)
    picked = _parse(reply, topics)
    out = {t: {"found": False, "sections": [], "spans": [], "answer": "", "unlocated": 0, "truncated": False,
               "error": picked is None} for t in topics}
    if picked is None:
        return out
    for t in topics:
        ids = picked.get(t) if isinstance(picked.get(t), list) else []
        out[t]["sections"] = [i for i in dict.fromkeys(str(x) for x in ids) if i in ol.sections][:MAX_SECTIONS]
    names = list(topics)
    for g, start in enumerate(range(0, len(names), group)):
        chunk = names[start:start + group]
        shown_ids = sorted({i for t in chunk for i in out[t]["sections"]}, key=lambda i: ol.sections[i][0])
        if not shown_ids:
            continue
        parts, used, truncated, shown = [], 0, False, []
        for i in shown_ids:
            s, e = ol.sections[i]
            room = STEP2_CAP - used
            if room <= 0:
                truncated = True
                break
            if e - s > room:
                e, truncated = s + room, True
            parts.append(f"[{i}]\n{text[s:e]}")
            shown.append((s, e))
            used += e - s
        example2 = json.dumps({t: {"found": True, "quotes": ["..."], "answer": "..."} for t in chunk})
        prompt = STEP2.format(topics=_topics_block({t: topics[t] for t in chunk}), example=example2,
                              sections="\n\n".join(parts))
        got = _parse(_ask(ledger, lock, f"{base}|sections|{g}", prompt, model, runner), chunk)
        for t in chunk:
            out[t]["truncated"] = truncated
            if got is None:
                out[t]["error"] = True
                continue
            r = got.get(t) if isinstance(got.get(t), dict) else {}
            quotes = [q for q in r.get("quotes", []) if isinstance(q, str)][:3]
            located = [locate(q, text, shown) for q in quotes]
            out[t].update(found=bool(r.get("found")), spans=[list(sp) for got in located for sp in got],
                          answer=str(r.get("answer", "")), unlocated=sum(1 for got in located if not got))
    return out


def status(a: dict, b: dict, section_at) -> str:
    if a.get("error") or b.get("error"):
        return "error"
    fa, fb = a["found"] and bool(a["spans"]), b["found"] and bool(b["spans"])
    if not a["found"] and not b["found"]:
        return "absent"
    if not (fa and fb):
        return "one_found"
    if any(s1 < e2 and s2 < e1 for s1, e1 in a["spans"] for s2, e2 in b["spans"]):
        return "kept"
    sa = {section_at(s) for s, _ in a["spans"]} - {""}
    sb = {section_at(s) for s, _ in b["spans"]} - {""}
    return "kept" if sa & sb else "disagree"


class _NeedsCall(Exception):
    pass


def _cached_only(prompt, model):
    raise _NeedsCall


def _passages(conn, cid) -> list[tuple[str, str, int, int]]:
    return conn.execute("SELECT section_id, section_title, start_char, end_char FROM passages"
                        " WHERE contract_id = ? AND kind != 'toc' ORDER BY start_char", (cid,)).fetchall()


def _section_at(passages):
    def at(pos: int) -> str:
        for sid, _, s, e in passages:
            if s <= pos < e:
                return sid
        return ""
    return at


STATUSES = ("kept", "absent", "disagree", "one_found", "error")


def label_all(conn, texts, contracts, topics, passes, runner, ledger_path, workers=4, max_new=None,
              topics_by_contract=None):
    tps = {cid: (topics_by_contract or {}).get(cid, topics) for cid, _ in contracts}
    ledger, lock = Ledger(Path(ledger_path), key="key"), threading.Lock()
    passages = {cid: _passages(conn, cid) for cid, _ in contracts}
    outlines = {cid: outline(passages[cid], texts[cid]) for cid, _ in contracts}
    calls: list[str] = []

    def counted(prompt, model):
        resp = runner(prompt, model)
        with lock:
            calls.append(model)
        return resp

    def run_one(cid, call):
        return {p: label_contract(cid, texts[cid], outlines[cid], tps[cid], m, call, ledger, p, lock=lock)
                for p, m in passes}

    def cached(cid):
        """The contract's labels if every call it needs is in the ledger, else None (and no call is made)."""
        try:
            return run_one(cid, _cached_only)
        except _NeedsCall:
            return None

    results = {cid: r for cid, _ in contracts if (r := cached(cid)) is not None}
    todo = [cid for cid, _ in contracts if cid not in results]
    if max_new is not None:
        todo = todo[:max_new]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, cid, counted): cid for cid in todo}
        for fut in as_completed(futures):
            results[futures[fut]] = fut.result()  # a failed call raises here; finished calls are already ledgered
    (pa, _), (pb, _) = passes
    rows = []
    for cid, target in contracts:
        if cid not in results:
            continue
        at = _section_at(passages[cid])
        for t in tps[cid]:
            a, b = results[cid][pa][t], results[cid][pb][t]
            st = status(a, b, at)
            gold = [list(g) for g in _merged([tuple(s) for s in a["spans"] + b["spans"]])] if st == "kept" else []
            rows.append({"contract_id": cid, "family": t, "target": target, "split": split_of(cid), "status": st,
                         "gold": gold, "fallback": outlines[cid].fallback, "a": a, "b": b})
    done = {r["contract_id"] for r in rows}
    summary = {"contracts": len(contracts), "complete": len(done), "calls_made": len(calls),
               "fallback_contracts": sum(1 for cid in done if outlines[cid].fallback)}
    summary |= {st: sum(1 for r in rows if r["status"] == st) for st in STATUSES}
    summary["by_family"] = {t: {st: sum(1 for r in rows if r["family"] == t and r["status"] == st) for st in STATUSES}
                            for t in dict.fromkeys(t for cid in done for t in tps[cid])}
    return rows, summary


def items_from_rows(rows: list[dict]) -> list[Item]:
    return [Item(f"{r['contract_id']}|{r['family']}", r["contract_id"], r["family"], r["family"],
                 TEMPLATES[r["family"]].format(target=r["target"]), tuple(tuple(g) for g in r["gold"]))
            for r in rows if r["status"] == "kept"]
```

A reviewer should check that `cached` makes no model call and that a contract counts as complete exactly when replaying it from the ledger needs no call. The `FakeRunner` call counts in the tests pin both.

`pipeline/cli.py`: `m3` gains the sub-command `label` with `--workers` (default 4) and `--max-new` (default none). It needs `DEALS_INDEX` and `EDGAR/deals.jsonl`; otherwise exit 2, naming the missing step. It reads texts with `load_contract` from `EDGAR/contracts`. `contracts = [(d["contract_id"], d["target"] or d["aliases"][0]) for d in deals]`, sorted by contract id. It calls `label_all(sqlite3.connect(DEALS_INDEX), texts, contracts, TOPICS, PASSES, run_claude, DATA / "m3" / "tmachine_ledger.jsonl", …)`, then writes the rows and summary atomically and prints the summary. A `RuntimeError` from the runner prints its message and exits 2. Everything already cached stays cached.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add evals/tmachine.py pipeline/cli.py tests/test_tmachine.py tests/test_cli.py
git commit -m "m3: T-machine — two independent passes (outline, then sections), quotes located in the chosen sections

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 7: The ladder on T-machine, and R7 against R6 corpus-wide

**Files:**
- Modify: `evals/tmachine.py`, `pipeline/cli.py`
- Test: `tests/test_tmachine.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `items_from_rows` (Task 6); `Resolver`, `DEAL_RUNGS` (Task 5); `_deals_texts` and `add_deals` (Task 4); `evaluate`, `Context`, `with_passages` from `evals/run_rung.py`.
- Produces: `evals.tmachine.scope_report(items: list[Item], resolver) -> dict`. Per item it records `{"item_id", "split", "outcome", "alias", "candidates"}`, where `outcome` is `"right"` (resolved to the item's own deal), `"wrong"` (resolved to another deal), `"ambiguous"` or `"none"`. It also gives `"by_split": {split: {outcome: count}}`.
- Produces: `dtd embed --deals`, which embeds and builds vectors for `DEALS_INDEX`. MAUD's passages are already in `data/cache/embeddings.db`, so only the tech passages are new.
- Produces: `dtd m3 eval`, which writes into `OUT / "m3"`:
  - `t_r1.json` … `t_r6.json` and their `_items.jsonl`: R1–R6 within-agreement on the T-machine items over the deals index.
  - `t_r6_corpus.json` and `t_r7_corpus.json`: corpus-wide over the deals index (MAUD plus tech), k = 10. A hit from another agreement counts as a miss, via `isolate_foreign` inside `evaluate`.
  - `r7_scope.json`: from `scope_report`.

R7 is compared with R6 corpus-wide, because R7 is R6 with the deal found from the question. Within one agreement R7 equals R6 by construction, so that comparison would show nothing.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_tmachine.py`:

```python
def test_scope_report_outcomes():
    import sqlite3
    from evals.items import Item
    from evals.tmachine import scope_report
    from retrieval.scope import Resolver
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", [
        ("acme software", "edgar_1", "target"), ("polycom", "edgar_2", "target"), ("polycom", "edgar_3", "target"),
        ("zeta labs", "edgar_4", "target")])
    items = [Item("edgar_1|equity_awards", "edgar_1", "equity_awards", "equity_awards", "Acme Software options?", ((0, 5),)),
             Item("edgar_2|termination_fee", "edgar_2", "termination_fee", "termination_fee", "Polycom fee?", ((0, 5),)),
             Item("edgar_5|termination_fee", "edgar_5", "termination_fee", "termination_fee", "Zeta Labs fee?", ((0, 5),)),
             Item("edgar_6|termination_fee", "edgar_6", "termination_fee", "termination_fee", "Unknown Co fee?", ((0, 5),))]
    got = scope_report(items, Resolver(conn))
    assert [r["outcome"] for r in got["items"]] == ["right", "ambiguous", "wrong", "none"]
    assert sum(sum(c.values()) for c in got["by_split"].values()) == 4
```

Append to `tests/test_cli.py` a chain test on the fixture data, with `cli.run_claude` and `cli._models` faked as the existing M2 tests do, and `cli.EDGAR`, `cli.DEALS_INDEX`, `cli.DATA` and `cli.OUT` patched into `tmp_path`. The chain is `m3 corpus` → `build --deals` → `embed --deals` → `lexicon` → `m3 label` → `m3 eval`, all exiting 0. The test then asserts that `OUT/m3` holds `t_r1.json` … `t_r6.json`, `t_r6_corpus.json`, `t_r7_corpus.json` and `r7_scope.json`, and that `t_r7_corpus.json`'s `scope` is `"corpus-wide"`. A second test: `m3 eval` before `embed --deals` exits 2 and names `dtd embed --deals`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tmachine.py tests/test_cli.py -q`
Expected: FAIL (`scope_report` missing, no `m3 eval`).

- [ ] **Step 3: Implement**

Append to `evals/tmachine.py`:

```python
from collections import Counter, defaultdict


def scope_report(items: list[Item], resolver) -> dict:
    rows, by_split = [], defaultdict(Counter)
    for i in items:
        s = resolver.resolve(i.query)
        outcome = ("right" if s.contract_id == i.contract_id else "wrong" if s.contract_id
                   else "ambiguous" if s.candidates else "none")
        split = split_of(i.contract_id)
        rows.append({"item_id": i.item_id, "split": split, "outcome": outcome, "alias": s.alias,
                     "candidates": list(s.candidates)})
        by_split[split][outcome] += 1
    return {"items": rows, "by_split": {k: dict(v) for k, v in sorted(by_split.items())}}
```

(Move the two imports to the top of the module.)

`pipeline/cli.py`:
- `embed` gains `--deals`: `db = DEALS_INDEX if args.deals else INDEX_FIXED if args.fixed else INDEX`. The "missing" message names `dtd build --deals`.
- `_deals_ladder(contracts, amendment_texts) -> Ladder` is `_ladder`'s body on `DEALS_INDEX`, plus `amendment_texts` and `resolver=Resolver(conn)`.
- `m3 eval` refuses with exit 2, naming the step to run, if `DEALS_INDEX` has no vectors, `DATA/m3/tmachine.jsonl` is missing, or the lexicon is missing. Then:

```python
    contracts, amendment_texts = _deals_texts()
    rows = [json.loads(l) for l in (DATA / "m3" / "tmachine.jsonl").read_text(encoding="utf-8").splitlines() if l]
    items = items_from_rows(rows)
    ctx = with_passages(Context(items, {"source": "T-machine (machine-built)", "items": len(items)}, contracts, {}),
                        DEALS_INDEX)
    ladder = _deals_ladder(contracts, amendment_texts)
    out, kw = OUT / "m3", {"count_tokens": ladder.embedder.count_tokens,
                           "extra": {"settings": asdict(ladder.settings)}}
    for rung in RUNGS:
        evaluate(ctx, f"T-{rung}", lambda q, c, k, r=rung: ladder.run(r, q, c, k), out, **kw)
    evaluate(ctx, "T-R6-corpus", lambda q, c, k: ladder.run("R6", q, None, k), out, scope="corpus-wide", **kw)
    evaluate(ctx, "T-R7-corpus", lambda q, c, k: ladder.run("R7", q, None, k), out, scope="corpus-wide", **kw)
    _write_atomic(out / "r7_scope.json", json.dumps(scope_report(items, ladder.resolver), indent=2, sort_keys=True))
```

It prints `{"items": n, "written": [file names]}`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add evals/tmachine.py pipeline/cli.py tests/
git commit -m "m3: ladder on T-machine over the deals index; R7 against R6 corpus-wide with scope outcomes

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 8: Tier agreement on MAUD — machine key against the lawyers, and Kendall's tau

**Files:**
- Create: `evals/tier.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_tier.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: `label_all`, `PASSES` (Task 6); M2's per-item files `OUT/r1_items.jsonl` … `OUT/r6_items.jsonl` (rows with `item_id`, `contract_id`, `split`, `query`, `gold`, `recall@5`, `top_passage_ids`); `maud.db`'s `passages`; `evals.metrics.recall_at_k`; `evals.bootstrap.cluster_bootstrap`.
- Produces, in `evals/tier.py`:
  - `TIER_CONTRACTS = 30`, `SEED = 0`.
  - `tier_sample(r1_rows: dict[str, dict], n=TIER_CONTRACTS, seed=SEED) -> list[str]`: n report-split MAUD contracts, sampled with `random.Random(seed)` from the sorted list, returned sorted.
  - `tier_topics(r1_rows, cid) -> tuple[dict[str, str], dict[str, str]]`: `({"T1": query, …}, {"T1": item_id, …})`, one short key per MAUD item of that contract, in item-id order. The short keys keep JSON replies robust: MAUD's deal-point names contain quotes and colons.
  - `tau_b(x: list[float], y: list[float]) -> float | None`: Kendall's tau-b, None when either side is all ties.
  - `tier_report(rows: list[dict], keymap: dict[tuple[str, str], str], rung_rows: dict[str, dict[str, dict]], spans: dict[int, tuple[int, int]], n_boot=2000) -> dict`. `rows` are `label_all` rows, `keymap` maps `(cid, "T3")` to the MAUD item id, `rung_rows` holds M2's items per rung `"R1"`…`"R6"`, and `spans` maps passage id to `(start, end)`.
- Produces: `dtd m3 tier [--workers 4]`. It writes `DATA/m3/tier_rows.jsonl` and `OUT/m3/tier.json` from the ledger `DATA/m3/tier_ledger.jsonl`.

What `tier_report` computes, on the items the machine procedure kept (both passes agreed):
- **Match rate:** the share of kept items whose machine gold overlaps the lawyers' gold by at least one character. Cluster bootstrap by contract.
- **Rung means under each key:** the human key is M2's stored `recall@5`. The machine key is recall@5 recomputed from M2's stored `top_passage_ids` against the machine gold. Both use the same items, and no retrieval is rerun. Task 3's parity check guarantees those passage ids still mean the same spans in the rebuilt `maud.db`.
- **Tau:** `tau_b` between the six human means and the six machine means. Interval: 2,000 resamples of the contracts with replacement, taking the 2.5th and 97.5th percentiles of the defined taus.
- **Status counts and kept rate**, as in T-machine.

With only six rungs, tau moves in steps of about 0.07 to 0.13 and its interval will be wide. The report says so and shows both orderings, so a reader can see where they differ.

- [ ] **Step 1: Write the failing tests**

`tests/test_tier.py`:

```python
import pytest

from evals.tier import tau_b, tier_report, tier_sample, tier_topics


def test_tau_b_known_values():
    assert tau_b([1, 2, 3], [1, 2, 3]) == 1.0
    assert tau_b([1, 2, 3], [3, 2, 1]) == -1.0
    assert tau_b([1, 2, 2, 3], [1, 3, 2, 4]) == pytest.approx(0.9129, abs=1e-4)  # scipy.stats.kendalltau
    assert tau_b([1, 1, 1], [1, 2, 3]) is None


def rows_for(cids, split="report"):
    out = {}
    for c in cids:
        for t in ("Type A", "Type B"):
            out[f"{c}|{t}"] = {"item_id": f"{c}|{t}", "contract_id": c, "split": split, "query": f"{t} question",
                               "gold": [[100, 200]], "recall@5": 1.0, "top_passage_ids": [1, 2, 3, 4, 5]}
    return out


def test_sample_is_seeded_sorted_and_report_only():
    rows = rows_for([f"contract_{i}" for i in range(50)]) | rows_for(["contract_t"], split="tune")
    a, b = tier_sample(rows, n=10), tier_sample(rows, n=10)
    assert a == b == sorted(a) and len(a) == 10 and "contract_t" not in a


def test_topics_use_short_keys():
    topics, keymap = tier_topics(rows_for(["contract_1"]), "contract_1")
    assert topics == {"T1": "Type A question", "T2": "Type B question"}
    assert keymap == {"T1": "contract_1|Type A", "T2": "contract_1|Type B"}


def test_report_match_rate_and_tau():
    cids = ["contract_1", "contract_2"]
    base = rows_for(cids)
    spans = {1: (100, 200), 2: (300, 400), 3: (500, 600), 4: (700, 800), 5: (900, 1000)}
    # Machine gold: Type A agrees with the lawyers (100-200); Type B points elsewhere (300-400).
    label_rows, keymap = [], {}
    for c in cids:
        for key, t, gold in (("T1", "Type A", [[120, 180]]), ("T2", "Type B", [[300, 350]])):
            label_rows.append({"contract_id": c, "family": key, "status": "kept", "gold": gold})
            keymap[(c, key)] = f"{c}|{t}"
    rung_rows = {}
    for n, r in enumerate(("R1", "R2", "R3", "R4", "R5", "R6")):
        rows = {}
        for i, row in base.items():
            hit_human = n >= 3          # later rungs find the lawyers' span ...
            hit_machine_b = n >= 3      # ... and, for Type B, the machine's span too
            top = ([1] if hit_human else [9]) + ([2] if hit_machine_b and row["item_id"].endswith("B") else [8]) + [7, 6, 5]
            rows[i] = row | {"recall@5": 1.0 if hit_human else 0.0, "top_passage_ids": top}
        rung_rows[r] = rows
    spans |= {6: (1100, 1200), 7: (1300, 1400), 8: (1500, 1600), 9: (1700, 1800)}
    got = tier_report(label_rows, keymap, rung_rows, spans, n_boot=200)
    assert got["kept"] == 4 and got["match"]["mean"] == 0.5
    assert got["rungs"]["R1"]["human"] == 0.0 and got["rungs"]["R6"]["machine"] == 1.0
    assert got["tau"] == pytest.approx(1.0)
```

Append to `tests/test_cli.py`: `dtd m3 tier` on the M2 fixture chain with a fake `run_claude` writes `OUT/m3/tier.json` with keys `match`, `tau`, `rungs`. Run without M2's `r6_items.jsonl`, it exits 2 and names `dtd eval --rung R6`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_tier.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`evals/tier.py`:

```python
import math
import random
from collections import defaultdict
from types import SimpleNamespace

from evals.bootstrap import CI_HIGH, CI_LOW, cluster_bootstrap
from evals.metrics import recall_at_k

TIER_CONTRACTS = 30
SEED = 0
RUNG_NAMES = ("R1", "R2", "R3", "R4", "R5", "R6")
STATUSES = ("kept", "absent", "disagree", "one_found", "error")


def tier_sample(r1_rows: dict[str, dict], n: int = TIER_CONTRACTS, seed: int = SEED) -> list[str]:
    report = sorted({r["contract_id"] for r in r1_rows.values() if r["split"] == "report"})
    return sorted(random.Random(seed).sample(report, min(n, len(report))))


def tier_topics(r1_rows: dict[str, dict], cid: str) -> tuple[dict[str, str], dict[str, str]]:
    ids = sorted(i for i, r in r1_rows.items() if r["contract_id"] == cid)
    return ({f"T{n}": r1_rows[i]["query"] for n, i in enumerate(ids, start=1)},
            {f"T{n}": i for n, i in enumerate(ids, start=1)})


def tau_b(x: list[float], y: list[float]) -> float | None:
    conc = disc = tx = ty = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            dx = (x[i] > x[j]) - (x[i] < x[j])
            dy = (y[i] > y[j]) - (y[i] < y[j])
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx == dy:
                conc += 1
            else:
                disc += 1
    denom = math.sqrt((conc + disc + tx) * (conc + disc + ty))
    return (conc - disc) / denom if denom else None


def _overlaps(a, b) -> bool:
    return any(s1 < e2 and s2 < e1 for s1, e1 in a for s2, e2 in b)


def _means(per_contract: dict[str, list[tuple[list[float], list[float]]]], cids: list[str]):
    h, m, n = [0.0] * len(RUNG_NAMES), [0.0] * len(RUNG_NAMES), 0
    for c in cids:
        for hv, mv in per_contract[c]:
            h = [a + b for a, b in zip(h, hv)]
            m = [a + b for a, b in zip(m, mv)]
            n += 1
    return [v / n for v in h], [v / n for v in m]


def tier_report(rows, keymap, rung_rows, spans, n_boot: int = 2000, seed: int = 0) -> dict:
    status = {st: sum(1 for r in rows if r["status"] == st) for st in STATUSES}
    kept = [r for r in rows if r["status"] == "kept"]
    match_by_contract: dict[str, list[float]] = defaultdict(list)
    per_contract: dict[str, list] = defaultdict(list)
    for r in kept:
        item_id = keymap[(r["contract_id"], r["family"])]
        human_gold = [tuple(g) for g in rung_rows["R1"][item_id]["gold"]]
        machine_gold = [tuple(g) for g in r["gold"]]
        match_by_contract[r["contract_id"]].append(1.0 if _overlaps(machine_gold, human_gold) else 0.0)
        hv, mv = [], []
        for rung in RUNG_NAMES:
            row = rung_rows[rung][item_id]
            hits = [SimpleNamespace(start=spans[p][0], end=spans[p][1]) for p in row["top_passage_ids"][:5]]
            hv.append(row["recall@5"])
            mv.append(recall_at_k(hits, machine_gold, 5))
        per_contract[r["contract_id"]].append((hv, mv))
    cids = sorted(per_contract)
    human, machine = _means(per_contract, cids)
    rng, taus = random.Random(seed), []
    for _ in range(n_boot):
        t = tau_b(*_means(per_contract, [cids[rng.randrange(len(cids))] for _ in cids]))
        if t is not None:
            taus.append(t)
    taus.sort()
    return {
        "contracts": len({r["contract_id"] for r in rows}), "items": len(rows), **status,
        "kept_rate": status["kept"] / len(rows) if rows else None,
        "match": cluster_bootstrap(match_by_contract, n_boot=n_boot, seed=seed),
        "rungs": {r: {"human": h, "machine": m} for r, h, m in zip(RUNG_NAMES, human, machine)},
        "tau": tau_b(human, machine),
        "tau_lo": taus[int(CI_LOW * len(taus))] if taus else None,
        "tau_hi": taus[min(len(taus) - 1, int(CI_HIGH * len(taus)))] if taus else None,
        "tau_defined": len(taus), "n_boot": n_boot,
        "human_order": [r for _, r in sorted(zip(human, RUNG_NAMES), key=lambda p: (-p[0], p[1]))],
        "machine_order": [r for _, r in sorted(zip(machine, RUNG_NAMES), key=lambda p: (-p[0], p[1]))],
    }
```

`pipeline/cli.py`: `m3 tier`, which:
1. Requires `INDEX` and `OUT/r{1..6}_items.jsonl`, exiting 2 and naming the missing `dtd eval --rung Rn`.
2. Loads `rung_rows = {R: load_items(OUT / f"{R.lower()}_items.jsonl")}` and picks `cids = tier_sample(rung_rows["R1"])`.
3. Builds `topics_by_contract = {cid: tier_topics(rung_rows["R1"], cid)[0]}` and the keymap `{(cid, key): item_id}`. It then makes one `label_all(sqlite3.connect(INDEX), texts, [(cid, cid) for cid in cids], {}, PASSES, run_claude, DATA / "m3" / "tier_ledger.jsonl", workers=args.workers, topics_by_contract=topics_by_contract)` call.
4. Reads texts with `load_contract(RAW / "contracts" / f"{cid}.txt")`. `spans` comes from `SELECT passage_id, start_char, end_char FROM passages` on `INDEX`.
5. Writes `DATA/m3/tier_rows.jsonl` and `OUT/m3/tier.json` (`tier_report(...)`) atomically, and prints the report's `match`, `tau`, `tau_lo` and `tau_hi`.

Ledger: `DATA/m3/tier_ledger.jsonl`. Keys include the pass, model and contract, so T-machine's and the tier's caches never collide even though both use `label_contract`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add evals/tier.py pipeline/cli.py tests/test_tier.py tests/test_cli.py
git commit -m "m3: tier agreement — machine key vs lawyers' spans on 30 MAUD agreements, Kendall's tau over R1–R6

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 9: The LLM-rewrite append variant (M2 carry-over)

**Files:**
- Modify: `pipeline/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: the cached rewrites `CACHE/llm_rewrites.jsonl` (M2) and `_refuse_new_calls`.
- Produces: `dtd eval --rung R5-llm-append`, which writes `OUT/r5_llm_append.json` and `OUT/r5_llm_append_items.jsonl`. It is R5 with `rewritten = f"{query} {rewrite}"`: the model's rewrite appended to the question, as the lexicon appends its terms. It makes no model call.

M2 compared the lexicon (which appends) with an LLM rewrite that replaced the query, so the two differed in two ways at once. This run separates them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_cli.py`, next to `test_r5_llm_runs_after_rewrite` and using the same fixture and fake runner:

```python
def test_r5_llm_append_appends_the_cached_rewrite_and_makes_no_call(data, monkeypatch):
    monkeypatch.setattr(cli, "run_claude", fake_rewrite_runner)  # the runner the R5-llm test uses
    assert cli.entry(["rewrite"]) == 0
    monkeypatch.setattr(cli, "run_claude", lambda *a, **k: pytest.fail("no model call allowed"))
    seen = []
    real_run = cli.Ladder.run
    monkeypatch.setattr(cli.Ladder, "run", lambda self, rung, q, c=None, k=10, rewritten=None:
                        seen.append((q, rewritten)) or real_run(self, rung, q, c, k, rewritten))
    assert cli.entry(["eval", "--rung", "R5-llm-append"]) == 0
    assert seen and all(r.startswith(q + " ") and len(r) > len(q) + 1 for q, r in seen)
    assert (cli.OUT / "r5_llm_append.json").exists()
```

(If the existing R5-llm test names its fake runner differently, use that name.)

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k append -q`
Expected: FAIL (`unknown rung R5-llm-append`, exit 2).

- [ ] **Step 3: Implement**

In `_cmd_eval`, accept `"R5-llm-append"` alongside `"R5-llm"`, and run both through the same branch:

```python
    if rung in ("R5-llm", "R5-llm-append"):
        ...
        def retrieve(q, c, k):
            r = rewrites[q]
            text = r["rewrite"] if rung == "R5-llm" else f"{q} {r['rewrite']}"
            got = ladder.run("R5", q, c, k, rewritten=text)
            return Retrieved(got.hits, got.ms + r["api_ms"], got.context)
        ...
        result = evaluate(ctx, rung, retrieve, out, ...)
```

The `extra` block is unchanged, so both runs record the rewrite model and token means.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/cli.py tests/test_cli.py
git commit -m "m3: R5-llm-append — the cached LLM rewrite appended, not substituted (no model calls)

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 10: M3 facts and `docs/m3/REPORT.md`

**Files:**
- Create: `facts/m3.py`, `facts/report_m3.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_facts_m3.py`, `tests/test_report_m3.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes the M3 outputs:
  - `EDGAR/summary.json`, written by `dtd m3 corpus` (Task 2).
  - `DATA/m3/deals_summary.json`, written by `dtd build --deals` (Task 4).
  - `DATA/m3/tmachine_summary.json` and `tmachine_ledger.jsonl`.
  - `OUT/m3/t_r*.json` and their items files, `r7_scope.json` and `tier.json`.
  - `OUT/r5_llm_append*`, `OUT/r5_items.jsonl` and `OUT/r5_llm_items.jsonl`.
- Produces: `facts.m3.present_m3(out_m3) -> bool` and `build_m3(out_m3, out_dir, data_m3, edgar_dir, deals_db, n_boot=2000) -> dict` of `m3_*` facts. It raises `FileNotFoundError` naming every missing input.
- Produces: `facts.report_m3.render_m3(f) -> str`. `dtd report` writes `docs/m3/REPORT.md` when `m3_t_r1_report_recall_at_5` is in the facts.
- `pipeline/cli.py`: `REPORT_M3 = Path("docs/m3/REPORT.md")`. `_all_facts` adds `build_m3(...)` when `present_m3(OUT / "m3")`. **The CLI test fixture must patch `cli.REPORT_M3` into `tmp_path`, as it already does for `REPORT_M0` and `REPORT_M2`.** M0's run showed what happens otherwise: a test wrote the real report. Extend the existing guard test to `docs/m3/REPORT.md`.

Fact names. Every `_ci` fact has `_lo` and `_hi` siblings, and every `_delta` fact has `_lo` and `_hi`:
- Corpus: `m3_corpus_{deals,kept,excluded_not_merger,amendments,aliases}`, `m3_deals_{deals,maud_deals,aliases,schedule_tagged,amendments_linked,amendments_unlinked,passages_superseded}`, `m3_deals_passages`, `m3_tech_passages`, `m3_deals_index_bytes` (unstable).
- T-machine (machine-built):
  - Counts: `m3_tm_{contracts,complete,fallback_contracts}`, `m3_tm_{kept,absent,disagree,one_found,error}`, `m3_tm_calls` (ledger rows).
  - Models: `m3_tm_model_a` and `m3_tm_model_b`, read from the ledger records.
  - Per family `fam` in `FAMILIES`: `m3_tm_{fam}_{status}` and `m3_tm_{fam}_agreement_rate`.
- Ladder on T-machine, report split, for `r` in `t_r1`…`t_r6`, `t_r6_corpus`, `t_r7_corpus`:
  - `_ci` facts `m3_{r}_report_recall_at_5` and `m3_{r}_report_mrr_at_10`.
  - `m3_{r}_latency_ms_p95` (unstable).
  - `m3_{r}_{fam}_recall_at_5`.
  - Deltas: `m3_cmp_{r}_vs_t_r1_recall_at_5`, `m3_cmp_{r}_vs_prev_recall_at_5` and `m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5`.
  - Item counts: `m3_t_report_items` and `m3_t_report_contracts`.
- R7 scope, report split: `m3_r7_{right,wrong,ambiguous,none}`.
- Tier:
  - Counts: `m3_tier_{contracts,items,kept}`.
  - `_ci` fact `m3_tier_match_rate`.
  - `m3_tier_tau`, `m3_tier_tau_lo` and `m3_tier_tau_hi`.
  - Per rung: `m3_tier_{r}_{human,machine}_recall_at_5` for `r` in `r1`…`r6`.
  - Orderings: `m3_tier_human_order` and `m3_tier_machine_order`, as strings like "R5 > R6 > …".
- Append variant: the `_ci` fact `m3_r5_llm_append_report_recall_at_5`, and the deltas `m3_cmp_r5_llm_append_vs_r5_recall_at_5` and `m3_cmp_r5_llm_append_vs_r5_llm_recall_at_5`.

- [ ] **Step 1: Write the failing tests**

`tests/test_report_m3.py`:

```python
import re

from facts.report_m3 import render_m3

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


ALLOWED = re.compile(r"\bM\d\b|\bR\d\b|@\d+|\bp95\b|§\d+(?:\.\d+)?")


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m3(Every()).replace(str(SENTINEL), "")
    lines = [l for l in text.splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_machine_built_numbers_are_labelled_and_the_disclaimer_is_there():
    text = render_m3(Every())
    for heading in ("## T-machine labels", "## The ladder on T-machine", "## Tier agreement"):
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
        assert "machine-built" in section, heading
    assert "This is not legal advice." in text


def test_missing_values_print_as_na():
    text = render_m3(Every(m3_tm_equity_awards_agreement_rate=None, m3_tier_tau=None))
    assert "n/a" in text
```

`tests/test_facts_m3.py` builds a minimal tree in `tmp_path`: every input file `build_m3` reads, with two tech contracts (`edgar_a` on the report split, `edgar_b` on the tune split; check with `split_of` and pick ids that land there), two items each, and rung results written by calling `evals.run_rung.evaluate` with a fake retriever. That avoids hand-writing result JSON. It asserts:

```python
def test_build_m3_reads_every_input(m3_tree):
    f = build_m3(*m3_tree)
    assert f["m3_corpus_kept"] == 2 and f["m3_tm_kept"] == 4
    assert f["m3_tm_equity_awards_agreement_rate"] == 1.0
    assert f["m3_tm_model_a"] == "claude-opus-5-5"
    assert {"m3_t_r1_report_recall_at_5", "m3_t_r7_corpus_report_recall_at_5", "m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5_delta",
            "m3_tier_tau", "m3_tier_match_rate", "m3_r5_llm_append_report_recall_at_5", "m3_r7_right"} <= set(f)


def test_missing_inputs_are_named(m3_tree):
    (m3_tree[0] / "tier.json").unlink()
    with pytest.raises(FileNotFoundError, match="tier.json"):
        build_m3(*m3_tree)


def test_unstable_facts_are_recognised():
    from facts.m2 import is_unstable
    assert is_unstable("m3_t_r1_latency_ms_p95") and is_unstable("m3_deals_index_bytes")
    assert not is_unstable("m3_t_r1_report_recall_at_5")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_facts_m3.py tests/test_report_m3.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`facts/m3.py`:

```python
import sqlite3
from pathlib import Path

from evals.compare import load_items, paired_bootstrap
from evals.run_rung import _percentile
from evals.tmachine import FAMILIES
from facts.m0 import _rows
from facts.m2 import _ci, _delta, _json

T_LADDER = ("t_r1", "t_r2", "t_r3", "t_r4", "t_r5", "t_r6")
T_CORPUS = ("t_r6_corpus", "t_r7_corpus")
STATUSES = ("kept", "absent", "disagree", "one_found", "error")
SCOPE_OUTCOMES = ("right", "wrong", "ambiguous", "none")


def present_m3(out_m3: Path) -> bool:
    return (Path(out_m3) / "t_r1.json").exists()


def _model(ledger_rows: list[dict], pass_name: str) -> str | None:
    models = sorted({r["model"] for r in ledger_rows if r["key"].startswith(pass_name + "|")})
    return ", ".join(models) or None


def build_m3(out_m3, out_dir, data_m3, edgar_dir, deals_db, n_boot: int = 2000) -> dict:
    out_m3, out_dir, data_m3, edgar_dir, deals_db = map(Path, (out_m3, out_dir, data_m3, edgar_dir, deals_db))
    needed = ([out_m3 / f"{r}.json" for r in T_LADDER + T_CORPUS]
              + [out_m3 / f"{r}_items.jsonl" for r in T_LADDER + T_CORPUS]
              + [out_m3 / "r7_scope.json", out_m3 / "tier.json", out_dir / "r5_items.jsonl",
                 out_dir / "r5_llm_items.jsonl", out_dir / "r5_llm_append.json", out_dir / "r5_llm_append_items.jsonl",
                 data_m3 / "tmachine_summary.json", data_m3 / "tmachine_ledger.jsonl", data_m3 / "deals_summary.json",
                 edgar_dir / "summary.json", deals_db])
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        raise FileNotFoundError("M3 inputs missing: " + ", ".join(missing))
    f: dict = {}

    corpus = _json(edgar_dir / "summary.json")
    for k in ("deals", "kept", "excluded_not_merger", "amendments", "aliases"):
        f[f"m3_corpus_{k}"] = corpus[k]
    deals = _json(data_m3 / "deals_summary.json")
    for k in ("deals", "maud_deals", "aliases", "schedule_tagged", "amendments_linked", "amendments_unlinked",
              "passages_superseded"):
        f[f"m3_deals_{k}"] = deals[k]
    conn = sqlite3.connect(deals_db)
    f["m3_deals_passages"] = conn.execute("SELECT COUNT(*) FROM passages WHERE kind != 'toc'").fetchone()[0]
    f["m3_tech_passages"] = conn.execute("SELECT COUNT(*) FROM passages WHERE kind != 'toc'"
                                         " AND contract_id >= 'edgar_' AND contract_id < 'edgar`'").fetchone()[0]
    conn.close()
    f["m3_deals_index_bytes"] = deals_db.stat().st_size

    tm = _json(data_m3 / "tmachine_summary.json")
    for k in ("contracts", "complete", "fallback_contracts") + STATUSES:
        f[f"m3_tm_{k}"] = tm[k]
    ledger = _rows(data_m3 / "tmachine_ledger.jsonl")
    f["m3_tm_calls"] = len({r["key"] for r in ledger})
    f["m3_tm_model_a"], f["m3_tm_model_b"] = _model(ledger, "a"), _model(ledger, "b")
    for fam in FAMILIES:
        c = tm["by_family"].get(fam, dict.fromkeys(STATUSES, 0))
        for st in STATUSES:
            f[f"m3_tm_{fam}_{st}"] = c[st]
        decided = c["kept"] + c["disagree"] + c["one_found"]
        f[f"m3_tm_{fam}_agreement_rate"] = round(c["kept"] / decided, 4) if decided else None

    res = {r: _json(out_m3 / f"{r}.json") for r in T_LADDER + T_CORPUS}
    items = {r: load_items(out_m3 / f"{r}_items.jsonl") for r in T_LADDER + T_CORPUS}
    f["m3_t_report_items"] = res["t_r1"]["by_split"]["report"]["recall@5"]["n_items"]
    f["m3_t_report_contracts"] = res["t_r1"]["by_split"]["report"]["recall@5"]["n_clusters"]
    for r in T_LADDER + T_CORPUS:
        report = res[r]["by_split"]["report"]
        _ci(f, f"m3_{r}_report_recall_at_5", report["recall@5"])
        _ci(f, f"m3_{r}_report_mrr_at_10", report["mrr@10"])
        rows = [row for row in items[r].values() if row["split"] == "report"]
        f[f"m3_{r}_latency_ms_p95"] = round(_percentile(sorted(row["latency_ms"] for row in rows), 0.95), 2)
        for fam in FAMILIES:
            fr = [row["recall@5"] for row in rows if row["category"] == fam]
            f[f"m3_{r}_{fam}_recall_at_5"] = round(sum(fr) / len(fr), 4) if fr else None
    for i, r in enumerate(T_LADDER[1:], start=1):
        _delta(f, f"m3_cmp_{r}_vs_t_r1_recall_at_5", paired_bootstrap(items["t_r1"], items[r], "recall@5", n_boot=n_boot))
        if i > 1:
            _delta(f, f"m3_cmp_{r}_vs_prev_recall_at_5",
                   paired_bootstrap(items[T_LADDER[i - 1]], items[r], "recall@5", n_boot=n_boot))
    _delta(f, "m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5",
           paired_bootstrap(items["t_r6_corpus"], items["t_r7_corpus"], "recall@5", n_boot=n_boot))
    scope = _json(out_m3 / "r7_scope.json")["by_split"].get("report", {})
    for o in SCOPE_OUTCOMES:
        f[f"m3_r7_{o}"] = scope.get(o, 0)

    tier = _json(out_m3 / "tier.json")
    for k in ("contracts", "items", "kept"):
        f[f"m3_tier_{k}"] = tier[k]
    _ci(f, "m3_tier_match_rate", tier["match"])
    for k in ("tau", "tau_lo", "tau_hi"):
        f[f"m3_tier_{k}"] = round(tier[k], 4) if tier[k] is not None else None
    for rung, v in tier["rungs"].items():
        f[f"m3_tier_{rung.lower()}_human_recall_at_5"] = round(v["human"], 4)
        f[f"m3_tier_{rung.lower()}_machine_recall_at_5"] = round(v["machine"], 4)
    f["m3_tier_human_order"] = " > ".join(tier["human_order"])
    f["m3_tier_machine_order"] = " > ".join(tier["machine_order"])

    append = load_items(out_dir / "r5_llm_append_items.jsonl")
    _ci(f, "m3_r5_llm_append_report_recall_at_5", _json(out_dir / "r5_llm_append.json")["by_split"]["report"]["recall@5"])
    _delta(f, "m3_cmp_r5_llm_append_vs_r5_recall_at_5",
           paired_bootstrap(load_items(out_dir / "r5_items.jsonl"), append, "recall@5", n_boot=n_boot))
    _delta(f, "m3_cmp_r5_llm_append_vs_r5_llm_recall_at_5",
           paired_bootstrap(load_items(out_dir / "r5_llm_items.jsonl"), append, "recall@5", n_boot=n_boot))
    return f
```

`facts/report_m3.py`:

```python
from evals.tmachine import FAMILIES

LABELS = {"equity_awards": "Employee equity awards", "termination_fee": "Termination (break-up) fee",
          "employee_benefits": "Employees' pay and benefits after the deal"}
RUNGS = (("t_r1", "R1 keyword"), ("t_r2", "R2 dense"), ("t_r3", "R3 hybrid"), ("t_r4", "R4 rerank"),
         ("t_r5", "R5 lexicon rewrite"), ("t_r6", "R6 definitions"))


def _v(x) -> str:
    return "n/a" if x is None else str(x)


def _ci(f, name) -> str:
    return f"{_v(f[name])} ({_v(f[name + '_lo'])} to {_v(f[name + '_hi'])})"


def _d(f, name) -> str:
    lo, hi = f[name + "_lo"], f[name + "_hi"]
    verdict = "helps" if lo > 0 else "hurts" if hi < 0 else "no measurable change"
    return f"{_v(f[name + '_delta'])} ({_v(lo)} to {_v(hi)}; {verdict})"


def _corpus(f) -> str:
    return (f"## Corpus\n\nOf the {f['m3_corpus_deals']} tech deals M0 found, {f['m3_corpus_kept']} agreements were "
            f"ingested. Left out because the document's own title is not a merger agreement: "
            f"{f['m3_corpus_excluded_not_merger']}. The deals index holds {f['m3_deals_deals']} agreements ({f['m3_deals_maud_deals']} from MAUD) "
            f"and {f['m3_deals_passages']} passages, {f['m3_tech_passages']} of them from the tech agreements, in "
            f"{f['m3_deals_index_bytes']} bytes.\n\n"
            f"{f['m3_corpus_amendments']} amendments are linked to their deals. {f['m3_deals_amendments_linked']} name "
            f"the sections they change in the explicit form (\"Section … is hereby amended\") and mark "
            f"{f['m3_deals_passages_superseded']} passages as superseded; an answer drawn from one of them shows the "
            f"amended text beside it. The other {f['m3_deals_amendments_unlinked']} are recorded but not linked to "
            f"sections, because nothing in them says which section they change in a form a program can trust. "
            f"{f['m3_deals_schedule_tagged']} passages refer to a disclosure letter or schedule, which is never filed.\n")


def _tmachine(f) -> str:
    rows = "\n".join(f"| {LABELS[fam]} | {f[f'm3_tm_{fam}_kept']} | {f[f'm3_tm_{fam}_absent']} | "
                     f"{f[f'm3_tm_{fam}_disagree']} | {f[f'm3_tm_{fam}_one_found']} | "
                     f"{_v(f[f'm3_tm_{fam}_agreement_rate'])} |" for fam in FAMILIES)
    return (f"## T-machine labels (machine-built)\n\nTwo independent passes ({f['m3_tm_model_a']} and "
            f"{f['m3_tm_model_b']}) each read the agreement's section outline, chose the sections to read, then quoted "
            f"the governing clause and answered. Neither pass sees a retrieval result, so the labels do not favour "
            f"any rung. An item is kept only when both passes found the clause and their quotes overlap or sit in the "
            f"same section. {f['m3_tm_complete']} of {f['m3_tm_contracts']} agreements are labelled, in "
            f"{f['m3_tm_calls']} model calls; {f['m3_tm_fallback_contracts']} had no usable section numbering and "
            f"were shown fixed-size chunks instead.\n\n"
            "| Family | Kept | Both passes: absent | Passes disagree | One pass only | Agreement rate (machine-built) |\n"
            "|---|---|---|---|---|---|\n" + rows + "\n\nItems both passes found absent are held for M4's "
            "abstention questions; they are not retrieval items.\n")


def _ladder(f) -> str:
    rows = "\n".join(
        f"| {label} | {_ci(f, f'm3_{r}_report_recall_at_5')} | "
        f"{'' if r == 't_r1' else _d(f, f'm3_cmp_{r}_vs_t_r1_recall_at_5')} | "
        f"{_d(f, f'm3_cmp_{r}_vs_prev_recall_at_5') if r not in ('t_r1', 't_r2') else ''} | "
        f"{f[f'm3_{r}_latency_ms_p95']} |" for r, label in RUNGS)
    fam_rows = "\n".join(f"| {label} | " + " | ".join(_v(f[f'm3_{r}_{fam}_recall_at_5']) for fam in FAMILIES) + " |"
                         for r, label in RUNGS)
    return (f"## The ladder on T-machine (machine-built)\n\nReport split: {f['m3_t_report_items']} machine-built "
            f"items from {f['m3_t_report_contracts']} tech agreements, each asked as a lay question naming the target. "
            f"Recall@5 with a bootstrap interval clustered by agreement; differences are paired.\n\n"
            "| Rung | recall@5 | vs R1 | vs previous rung | p95 latency (ms) |\n|---|---|---|---|---|\n" + rows +
            "\n\n| Rung | " + " | ".join(LABELS[fam] for fam in FAMILIES) + " |\n|---|---|---|---|\n" + fam_rows + "\n")


def _r7(f) -> str:
    return (f"## R7: finding the deal from the question\n\nCorpus-wide, over every agreement in the deals index, with "
            f"a hit from another agreement counted as a miss (machine-built items): R6 "
            f"{_ci(f, 'm3_t_r6_corpus_report_recall_at_5')}, R7 {_ci(f, 'm3_t_r7_corpus_report_recall_at_5')}; "
            f"difference {_d(f, 'm3_cmp_t_r7_vs_t_r6_corpus_recall_at_5')}. On the report split R7 resolved "
            f"{f['m3_r7_right']} questions to the right deal and {f['m3_r7_wrong']} to a wrong one. "
            f"{f['m3_r7_ambiguous']} named a company shared by several deals, so R7 searched everything rather than "
            f"guess, and {f['m3_r7_none']} named no company it knew.\n")


def _tier(f) -> str:
    rows = "\n".join(f"| {label} | {_v(f[f'm3_tier_{r[2:]}_human_recall_at_5'])} | "
                     f"{_v(f[f'm3_tier_{r[2:]}_machine_recall_at_5'])} |" for r, label in RUNGS)
    return (f"## Tier agreement (machine-built key against MAUD's lawyers)\n\nThe same two-pass procedure was run on "
            f"MAUD's own deal points in {f['m3_tier_contracts']} agreements from the report split "
            f"({f['m3_tier_items']} items), so those questions have two answer keys. Both passes agreed on "
            f"{f['m3_tier_kept']}. Of those, the machine-built span overlaps the lawyers' span in "
            f"{_ci(f, 'm3_tier_match_rate')} of items. Kendall's tau between the rung ordering under the lawyers' key "
            f"and under the machine-built key is {_v(f['m3_tier_tau'])} ({_v(f['m3_tier_tau_lo'])} to "
            f"{_v(f['m3_tier_tau_hi'])}). With six rungs, tau moves in coarse steps and its interval is wide, so both "
            f"orderings are shown: lawyers' key {f['m3_tier_human_order']}; machine-built key "
            f"{f['m3_tier_machine_order']}. This is evidence for or against trusting T-machine, not proof.\n\n"
            "| Rung | recall@5, lawyers' key | recall@5, machine-built key |\n|---|---|---|\n" + rows + "\n")


def _append(f) -> str:
    return (f"## The LLM rewrite, appended\n\nM2 compared the lexicon, which appends terms to the question, with an "
            f"LLM rewrite that replaced the question. Appending the same cached rewrite instead gives recall@5 "
            f"{_ci(f, 'm3_r5_llm_append_report_recall_at_5')} on T-human's report split: against R5 "
            f"{_d(f, 'm3_cmp_r5_llm_append_vs_r5_recall_at_5')}; against the replacing rewrite "
            f"{_d(f, 'm3_cmp_r5_llm_append_vs_r5_llm_recall_at_5')}.\n")


def render_m3(f) -> str:
    head = ("# M3: tech deals, deal scoping and the machine-built tier\n\nGenerated from `facts.json` by `dtd report`; "
            "do not edit by hand. Numbers marked machine-built come from model passes, not lawyers.\n")
    return "\n".join([head, _corpus(f), _tmachine(f), _ladder(f), _r7(f), _tier(f), _append(f),
                      "This is not legal advice.\n"])
```

`pipeline/cli.py`:
- `_all_facts` adds `if present_m3(OUT / "m3"): facts |= build_m3(OUT / "m3", OUT, DATA / "m3", EDGAR, DEALS_INDEX)`.
- `_cmd_report` writes `REPORT_M3` when `"m3_t_r1_report_recall_at_5" in facts`.
- The test fixture patches `cli.REPORT_M3`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass, including the guard that no test writes the real `docs/m*/REPORT.md`.

- [ ] **Step 5: Commit**

```bash
git add facts/m3.py facts/report_m3.py pipeline/cli.py tests/
git commit -m "m3: M3 facts and generated report (machine-built numbers labelled)

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

---

### Task 11: The real run, with kill-and-resume tests

**Files:**
- Produces (committed): `facts.json`, `docs/m3/REPORT.md`
- Produces (git-ignored): `data/raw/edgar/`, `data/index/deals.db`, `data/m3/`, `data/out/m3/`, `data/out/r5_llm_append*`

No sec.gov request is made in this task. Run the stages in this order, in one terminal, one at a time. Any stage projected past 100 minutes (the background limit is 2 hours) is handed to Michael to run in his own terminal, as M2's tuning was. Record wall time and load average for each stage in the ledger.

- [ ] **Step 1: Corpus and index**

```bash
uv run dtd m3 corpus
uv run dtd build --deals
```

Expected: the corpus summary matches the dry run in "Numbers this plan starts from" (`kept` 318, `excluded_not_merger` 1, `amendments` 31). If not, find out why before continuing. `build --deals` reports about 89k passages (MAUD's plus the tech agreements').

- [ ] **Step 2: Embedding, with a kill test**

Run `uv run dtd embed --deals 2>&1 | tee data/m3/embed.log` in the background. When the log shows `embedded 2000/`, kill the process with `kill -9`. Note the denominator in the log. Rerun the same command to completion.

Expected: the rerun's first progress line has a denominator smaller by at least 2,000. The final summary has `vectors` equal to the number of indexed passages, and `embedded + cached` equal to the distinct passage texts. If the first 2,000 show a rate that projects the whole run past 100 minutes, stop after the kill test and hand the rerun to Michael.

- [ ] **Step 3: T-machine labelling — measure, then run in bounded chunks, with a kill test**

1. `uv run dtd m3 label --max-new 8 --workers 4`. Record the wall time, the calls made and the token means from the ledger. Project the remaining 310 contracts at the same rate. Report the projection in the ledger. If it exceeds 100 minutes, continue in `--max-new` chunks that each fit, or hand chunks to Michael.
2. Kill test: start `uv run dtd m3 label --max-new 16 --workers 4` in the background. Once `data/m3/tmachine_ledger.jsonl` has grown by at least 10 lines, `kill -9` the Python process. The `claude -p` children it started run on to their own timeout and are discarded; do not hunt for them with a broad `pkill`, which could hit Michael's own sessions. Rerun the same command, then verify:
   - the ledger's keys are unique: `python3 -c "import json;k=[json.loads(l)['key'] for l in open('data/m3/tmachine_ledger.jsonl') if l.strip()];print(len(k),len(set(k)))"` prints two equal numbers;
   - the rerun's `calls_made` is less than 16 × 2 × 2 (contracts × passes × calls per pass);
   - a further rerun with `--max-new 0` reports `calls_made` 0.
3. Run the remaining chunks until `complete` equals `contracts`.
4. Eyeball check: print 10 kept items picked with `random.Random(0)` (query, family, the first 300 characters of the gold text). Read them, and record each verdict ("the gold is the governing clause" yes or no) in the ledger. Fewer than 8 of 10 means stop and tell Michael before evaluating: the labels would not be good enough to report.

- [ ] **Step 4: Evaluations**

```bash
uv run dtd m3 eval
uv run dtd eval --rung R5-llm-append
```

- [ ] **Step 5: Tier agreement, with a kill test**

Run `uv run dtd m3 tier --workers 4` in the background. `kill -9` it once `data/m3/tier_ledger.jsonl` has 10 lines, then rerun to completion. Check that the ledger keys are unique, as in Step 3.

- [ ] **Step 6: Facts, report, checks**

```bash
uv run dtd facts && uv run dtd report && uv run dtd facts --check && uv run pytest -q
git diff --stat facts.json docs/
```

Expected:
- `facts --check` exits 0.
- Every `m1_*`/`m2_*`/`m0_*` fact other than the unstable ones is unchanged. Check with `git diff facts.json`: only `m3_*` lines are added, and only unstable facts change.
- The tests pass.

Read `docs/m3/REPORT.md` end to end. Every sentence must match its numbers, especially the helps/hurts wording.

- [ ] **Step 7: Commit**

```bash
git add facts.json docs/m3/REPORT.md
git commit -m "m3: real run — tech corpus, deals index, T-machine, R7, tier agreement, append variant

<one line per stage: wall time, and the kill-test result>

Assisted-by: Claude
Co-Authored-By: <model> <noreply@anthropic.com>"
```

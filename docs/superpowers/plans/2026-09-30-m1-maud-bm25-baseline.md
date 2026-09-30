# M1: MAUD Ingest, BM25 Baseline and Human-Labelled Eval Harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce the first command-backed retrieval numbers for Deal Terms Desk: BM25 over section-aware passages of the MAUD merger agreements, scored against lawyers' annotated excerpts, with confidence intervals.

**Architecture:** A resumable fetch pulls MAUD at a pinned revision. A build stage turns each contract into section-aware passages and a defined-term list and writes one SQLite file (metadata + FTS5). An eval stage aligns MAUD's annotated excerpts back to character spans in the contracts, runs BM25 within each agreement, and reports recall@k, MRR and nDCG@10 with contract-clustered bootstrap intervals. A facts stage writes every reportable number to `facts.json`.

**Tech Stack:** Python 3.12, `uv`, `pytest`, standard library only (`sqlite3` with FTS5, `csv`, `urllib`, `hashlib`, `random`). No third-party runtime dependency in M1.

**Spec:** `docs/PRD.md` (this plan implements milestone M1 of §9; M0 and M2–M6 get their own plans).

## Global Constraints

- $0 cash. M1 uses only free data and local compute.
- Every number the site or README prints comes from `facts.json`, produced by a named query in `facts/`. Never hard-code a digit in page copy or in a report.
- Every stage is idempotent and resumable from its ledger. Resume is tested by killing the stage, not by reasoning.
- M1 touches MAUD only. Nothing in M1 may request `sec.gov`, `data.sec.gov` or `efts.sec.gov`.
- MAUD is CC BY 4.0: attribution lives in `NOTICE.md`. The README and the launch post are written by Michael by hand; never create or edit `README.md`.
- No personal email address in any request header or any committed file.
- Commits end with these two trailer lines:
  `Assisted-by: Claude`
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- Python `>=3.12,<3.13`. All character offsets refer to the canonical text returned by `pipeline.normalise.load_contract`.

## Facts measured while writing this plan (2026-09-30, MAUD revision `37d5c3b95d18dcd8404cc5ce3fd5069be062392f`)

These shaped the design. They are seeds, not published numbers; Task 9 re-derives everything.

- Files: `MAUD_v1/MAUD_train.csv` (81.3 MB), `MAUD_dev.csv` (21.2 MB), `MAUD_test.csv` (20.6 MB), `MAUD_v1/contracts/contract_N.txt`.
- CSV columns: `data_type, contract_name, text, answer, label, question, subquestion, text_type, id, category`. `data_type` is `main`, `abridged` or `rare_answers`. Only `main` rows are real excerpts. `contract_name` can be `<RARE_ANSWERS>`, which has no contract file.
- The dev CSV alone names 152 contracts, so the CSV splits are splits of rows, not of contracts.
- **Only 100 of the 152 named contracts have a text file at this revision.** The other 52 return 404. Their label rows exist but cannot be scored. The spec's "152 agreements" is the label count, not the text count.
- **`text` is not a verbatim substring of the contract.** It is stitched from non-contiguous pieces joined by `<omitted>`, ends with a marker like `(Pages 81-82)`, and differs in whitespace. On 6 contracts, splitting on `<omitted>`, stripping page markers and comparing with all whitespace removed aligned 116 of 157 pieces exactly; a head-and-tail anchor fallback aligned 36 more (152 of 157).
- Contract formatting varies: some have one heading per paragraph, some have headings inline after two or more spaces, and the table of contents repeats every heading. A prototype of the Task 3 segmenter gave 208–563 passages per contract on those 6, with a median passage of about 1,500–1,770 characters. In 1 of the 6 the early sections were not detected and fell into unsectioned "front" passages; they are still indexed. Task 9 publishes the share of passages that carry a section id.

## Dry run (2026-09-30)

Every code block in this plan was extracted into a scratch project and run: the 81 tests pass,
and the full chain (`fetch`, `build`, `eval`, `facts`, `facts --check`, `report`) ran on real
MAUD data in under a minute after a 23-second download. The dry run saw 100 agreements, 22,789
indexed passages, 97% of excerpt pieces aligned, 96% of indexed passages carrying a section id,
and BM25 recall@5 near 0.48 on the report split. These are orientation only. Nothing from the
dry run is committed; Task 9 produces the numbers of record in the repo.

## Review Focus

1. **A download interrupted mid-file.** A partial file must never be treated as complete; the next run must fetch it again. (Test in Task 1.)
2. **A contract with no detectable section headings.** The segmenter must still return bounded passages that cover the whole text. (Test in Task 3.)
3. **A query made of punctuation, FTS5 operators or nothing** (`"AND OR"`, `what's the "fee"?`, `""`). Search must return results or an empty list, never raise. (Test in Task 5.)
4. **An annotated excerpt that cannot be aligned to the contract.** The item must be excluded from scoring and counted, not scored as a retrieval miss. (Test in Task 7.)
5. **A contract named in the CSV with no file** (`<RARE_ANSWERS>`, or a 404). It must be skipped and counted, not crash the run. (Tests in Tasks 1, 6 and 7.)

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml`, `.github/workflows/ci.yml`, `NOTICE.md` | Project, CI, MAUD attribution |
| `pipeline/paths.py` | Default data locations and the pinned MAUD revision |
| `pipeline/ledger.py` | Append-only JSONL ledger keyed by URL |
| `pipeline/fetch_maud.py` | Resumable, atomic download of CSVs and contracts |
| `pipeline/normalise.py` | Canonical contract text; whitespace-free view with offset map |
| `pipeline/segment.py` | Section-aware passages |
| `pipeline/terms.py` | Defined-term extraction |
| `pipeline/cli.py` | `dtd fetch / build / eval / facts / report` |
| `retrieval/index.py` | Build the SQLite file (metadata + FTS5), atomically |
| `retrieval/bm25.py` | R1 search |
| `evals/maud_labels.py` | Load `main` rows from the MAUD CSVs |
| `evals/align.py` | Excerpt pieces → character spans in the contract |
| `evals/items.py` | Eval items (query + gold spans) and the alignment report |
| `evals/metrics.py` | Relevance, recall@k, MRR, nDCG@k |
| `evals/bootstrap.py` | Contract-clustered bootstrap; tune/report split |
| `evals/run_r1.py` | Run R1 over all items, write results JSON |
| `facts/queries.py`, `facts/build.py`, `facts/report.py` | Named queries → `facts.json` → `docs/m1/REPORT.md` |
| `tests/…` | One test file per module, synthetic fixtures only, no network |

---

### Task 1: Project scaffold, ledger and resumable MAUD fetch

**Files:**
- Create: `pyproject.toml`, `NOTICE.md`, `.github/workflows/ci.yml`
- Create: `pipeline/__init__.py`, `pipeline/paths.py`, `pipeline/ledger.py`, `pipeline/fetch_maud.py`
- Create: `retrieval/__init__.py`, `evals/__init__.py`, `facts/__init__.py` (all empty)
- Test: `tests/test_ledger.py`, `tests/test_fetch_maud.py`

**Interfaces:**
- Produces: `pipeline.paths.MAUD_REV: str`, `RAW: Path`, `INDEX: Path`, `OUT: Path`, `CSV_NAMES: tuple[str, ...]`
- Produces: `pipeline.ledger.Ledger(path: Path)` with `.get(url) -> dict | None`, `.put(rec: dict) -> None`
- Produces: `pipeline.fetch_maud.fetch(url: str, dest: Path, ledger: Ledger, opener=urllib.request.urlopen) -> dict` (record has `status` of `"ok"` or `"missing"`)
- Produces: `pipeline.fetch_maud.contract_names(csv_paths: list[Path]) -> list[str]`
- Produces: `pipeline.fetch_maud.fetch_all(raw_dir: Path, opener=urllib.request.urlopen) -> dict` with keys `ok`, `missing`

- [ ] **Step 1: Write the project files**

`pyproject.toml`:

```toml
[project]
name = "deal-terms-desk"
version = "0.1.0"
description = "Deal Terms Desk pipeline, retrieval and evals"
requires-python = ">=3.12,<3.13"
dependencies = []

[project.scripts]
dtd = "pipeline.cli:entry"

[dependency-groups]
dev = ["pytest>=8"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["pipeline", "retrieval", "evals", "facts"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

`NOTICE.md`:

```markdown
# Third-party data

This project uses the Merger Agreement Understanding Dataset (MAUD), by The Atticus Project,
licensed under CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/).
Source: https://huggingface.co/datasets/theatticusproject/maud

MAUD files are downloaded at build time and are not redistributed in this repository.
```

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
  pull_request:

jobs:
  tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v6
      - name: Install
        run: uv sync --frozen
      - name: Tests
        run: uv run pytest -q
```

`pipeline/paths.py`:

```python
import os
from pathlib import Path

MAUD_REV = "37d5c3b95d18dcd8404cc5ce3fd5069be062392f"
MAUD_BASE = f"https://huggingface.co/datasets/theatticusproject/maud/resolve/{MAUD_REV}/MAUD_v1"
CSV_NAMES = ("MAUD_train.csv", "MAUD_dev.csv", "MAUD_test.csv")

DATA = Path(os.environ.get("DTD_DATA", "data"))
RAW = DATA / "raw" / "maud"
INDEX = DATA / "index" / "maud.db"
OUT = DATA / "out"
```

Create the four empty `__init__.py` files, then run `uv sync` (this writes `uv.lock`).

- [ ] **Step 2: Write the failing ledger test**

`tests/test_ledger.py`:

```python
from pipeline.ledger import Ledger


def test_put_then_get_survives_reopen(tmp_path):
    p = tmp_path / "ledger.jsonl"
    Ledger(p).put({"url": "u1", "status": "ok", "bytes": 3})
    assert Ledger(p).get("u1") == {"url": "u1", "status": "ok", "bytes": 3}
    assert Ledger(p).get("absent") is None


def test_later_record_wins(tmp_path):
    p = tmp_path / "ledger.jsonl"
    led = Ledger(p)
    led.put({"url": "u1", "status": "missing"})
    led.put({"url": "u1", "status": "ok", "bytes": 9})
    assert Ledger(p).get("u1")["status"] == "ok"


def test_unterminated_last_line_is_ignored(tmp_path):
    p = tmp_path / "ledger.jsonl"
    p.write_text('{"url": "u1", "status": "ok", "bytes": 1}\n{"url": "u2", "sta')
    led = Ledger(p)
    assert led.get("u1") is not None
    assert led.get("u2") is None
```

- [ ] **Step 3: Run it to verify it fails**

Run: `uv run pytest tests/test_ledger.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.ledger'`

- [ ] **Step 4: Implement the ledger**

`pipeline/ledger.py`:

```python
import json
import os
from pathlib import Path


class Ledger:
    """Append-only JSONL keyed by url. A torn last line (a kill mid-write) is ignored."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._recs: dict[str, dict] = {}
        if self.path.exists():
            data = self.path.read_text(encoding="utf-8")
            lines = data.split("\n")
            if not data.endswith("\n"):
                lines = lines[:-1]
            for line in lines:
                if line.strip():
                    rec = json.loads(line)
                    self._recs[rec["url"]] = rec

    def get(self, url: str) -> dict | None:
        return self._recs.get(url)

    def put(self, rec: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, sort_keys=True) + "\n")
            f.flush()
            os.fsync(f.fileno())
        self._recs[rec["url"]] = rec
```

- [ ] **Step 5: Run the ledger test**

Run: `uv run pytest tests/test_ledger.py -q`
Expected: 3 passed

- [ ] **Step 6: Write the failing fetch test**

`tests/test_fetch_maud.py`:

```python
import io
import urllib.error

import pytest

from pipeline.fetch_maud import contract_names, fetch, fetch_all
from pipeline.ledger import Ledger


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class BrokenResponse(FakeResponse):
    """Yields some bytes, then the connection dies."""

    def __init__(self, data):
        super().__init__(data)
        self.calls = 0

    def read(self, n=-1):
        self.calls += 1
        if self.calls > 1:
            raise ConnectionError("killed mid-download")
        return super().read(4)


def opener_for(files, calls=None):
    def opener(req):
        url = req.full_url
        if calls is not None:
            calls.append(url)
        if url not in files:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return FakeResponse(files[url])
    return opener


def test_fetch_writes_file_and_ledger(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    rec = fetch("http://x/a.txt", tmp_path / "a.txt", led, opener_for({"http://x/a.txt": b"hello"}))
    assert rec["status"] == "ok" and rec["bytes"] == 5
    assert (tmp_path / "a.txt").read_bytes() == b"hello"


def test_fetch_is_skipped_when_already_done(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    calls = []
    op = opener_for({"http://x/a.txt": b"hello"}, calls)
    fetch("http://x/a.txt", tmp_path / "a.txt", led, op)
    fetch("http://x/a.txt", tmp_path / "a.txt", Ledger(tmp_path / "l.jsonl"), op)
    assert calls == ["http://x/a.txt"]


def test_interrupted_download_is_not_treated_as_complete(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    dest = tmp_path / "a.txt"
    with pytest.raises(ConnectionError):
        fetch("http://x/a.txt", dest, led, lambda req: BrokenResponse(b"hello world"))
    assert not dest.exists()
    assert Ledger(tmp_path / "l.jsonl").get("http://x/a.txt") is None
    rec = fetch("http://x/a.txt", dest, Ledger(tmp_path / "l.jsonl"), opener_for({"http://x/a.txt": b"hello world"}))
    assert rec["status"] == "ok" and dest.read_bytes() == b"hello world"


def test_missing_file_is_recorded_not_raised(tmp_path):
    led = Ledger(tmp_path / "l.jsonl")
    rec = fetch("http://x/gone.txt", tmp_path / "gone.txt", led, opener_for({}))
    assert rec["status"] == "missing"
    assert not (tmp_path / "gone.txt").exists()


def test_contract_names_skips_pseudo_contract(tmp_path):
    p = tmp_path / "MAUD_dev.csv"
    p.write_text(
        "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
        "main,contract_2,t,a,0,q,<NONE>,tt,1,c\n"
        "rare_answers,<RARE_ANSWERS>,t,a,0,q,<NONE>,tt,2,c\n"
        "main,contract_10,t,a,0,q,<NONE>,tt,3,c\n",
        encoding="utf-8",
    )
    assert contract_names([p]) == ["contract_10", "contract_2"]


def test_fetch_all_counts_missing_contracts(tmp_path, monkeypatch):
    import pipeline.fetch_maud as fm

    monkeypatch.setattr(fm, "CSV_NAMES", ("MAUD_dev.csv",))
    monkeypatch.setattr(fm, "MAUD_BASE", "http://x")
    csv = (
        "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
        "main,contract_1,t,a,0,q,<NONE>,tt,1,c\n"
        "main,contract_2,t,a,0,q,<NONE>,tt,2,c\n"
    ).encode()
    files = {"http://x/MAUD_dev.csv": csv, "http://x/contracts/contract_1.txt": b"AGREEMENT"}
    summary = fetch_all(tmp_path, opener_for(files))
    assert summary == {"ok": 2, "missing": 1}
    assert (tmp_path / "contracts" / "contract_1.txt").exists()
```

- [ ] **Step 7: Run it to verify it fails**

Run: `uv run pytest tests/test_fetch_maud.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.fetch_maud'`

- [ ] **Step 8: Implement the fetch**

`pipeline/fetch_maud.py`:

```python
import csv
import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.ledger import Ledger
from pipeline.paths import CSV_NAMES, MAUD_BASE

USER_AGENT = "deal-terms-desk/0.1 (+https://github.com/MichaelFornal)"
PSEUDO_CONTRACT = "<RARE_ANSWERS>"


def fetch(url: str, dest: Path, ledger: Ledger, opener=urllib.request.urlopen) -> dict:
    """Download url to dest atomically. Skips work already recorded in the ledger."""
    done = ledger.get(url)
    if done and done["status"] == "missing":
        return done
    if done and dest.exists() and dest.stat().st_size == done["bytes"]:
        return done
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(req) as resp, open(part, "wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            rec = {"url": url, "status": "missing"}
            ledger.put(rec)
            return rec
        raise
    os.replace(part, dest)
    rec = {"url": url, "status": "ok", "bytes": size, "sha256": digest.hexdigest()}
    ledger.put(rec)
    return rec


def contract_names(csv_paths: list[Path]) -> list[str]:
    csv.field_size_limit(10**9)
    names: set[str] = set()
    for p in csv_paths:
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if row["contract_name"] != PSEUDO_CONTRACT:
                    names.add(row["contract_name"])
    return sorted(names)


def fetch_all(raw_dir: Path, opener=urllib.request.urlopen) -> dict:
    raw_dir = Path(raw_dir)
    ledger = Ledger(raw_dir / "ledger.jsonl")
    summary = {"ok": 0, "missing": 0}
    csv_paths = []
    for name in CSV_NAMES:
        dest = raw_dir / name
        rec = fetch(f"{MAUD_BASE}/{name}", dest, ledger, opener)
        summary[rec["status"]] += 1
        if rec["status"] == "ok":
            csv_paths.append(dest)
    for name in contract_names(csv_paths):
        rec = fetch(f"{MAUD_BASE}/contracts/{name}.txt", raw_dir / "contracts" / f"{name}.txt", ledger, opener)
        summary[rec["status"]] += 1
    return summary
```

- [ ] **Step 9: Run all tests**

Run: `uv run pytest -q`
Expected: 9 passed

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock NOTICE.md .github pipeline retrieval evals facts tests
git commit -m "m1: scaffold, ledger and resumable MAUD fetch

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Canonical contract text and the whitespace-free view

**Files:**
- Create: `pipeline/normalise.py`
- Test: `tests/test_normalise.py`

**Interfaces:**
- Produces: `pipeline.normalise.canonical(raw: str) -> str` (drops a leading BOM, converts `\r\n` and `\r` to `\n`; nothing else)
- Produces: `pipeline.normalise.load_contract(path: Path) -> str`
- Produces: `pipeline.normalise.squash(text: str) -> tuple[str, list[int]]` (the text with every whitespace character removed, and for each kept character its offset in `text`)

- [ ] **Step 1: Write the failing test**

`tests/test_normalise.py`:

```python
from pipeline.normalise import canonical, load_contract, squash


def test_canonical_strips_bom_and_normalises_newlines():
    assert canonical("﻿A\r\nB\rC") == "A\nB\nC"


def test_canonical_keeps_inner_whitespace():
    assert canonical("2.6           Conversion") == "2.6           Conversion"


def test_load_contract_reads_utf8_with_bad_bytes(tmp_path):
    p = tmp_path / "c.txt"
    p.write_bytes(b"\xef\xbb\xbfSection 1.1 \xff Closing")
    text = load_contract(p)
    assert text.startswith("Section 1.1") and text.endswith("Closing")


def test_squash_maps_back_to_original_offsets():
    text = "a \n b\tc"
    squashed, index = squash(text)
    assert squashed == "abc"
    assert [text[i] for i in index] == ["a", "b", "c"]


def test_squash_of_whitespace_only_is_empty():
    assert squash(" \n\t") == ("", [])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_normalise.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.normalise'`

- [ ] **Step 3: Implement**

`pipeline/normalise.py`:

```python
from pathlib import Path


def canonical(raw: str) -> str:
    """The text every character offset in this project refers to."""
    if raw.startswith("﻿"):
        raw = raw[1:]
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def load_contract(path: Path) -> str:
    return canonical(Path(path).read_bytes().decode("utf-8", errors="replace"))


def squash(text: str) -> tuple[str, list[int]]:
    """Remove all whitespace; index[i] is the offset in text of squashed[i]."""
    chars: list[str] = []
    index: list[int] = []
    for i, ch in enumerate(text):
        if not ch.isspace():
            chars.append(ch)
            index.append(i)
    return "".join(chars), index
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_normalise.py -q`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/normalise.py tests/test_normalise.py
git commit -m "m1: canonical contract text and whitespace-free view with offset map

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Section-aware segmenter

**Files:**
- Create: `pipeline/segment.py`
- Test: `tests/test_segment.py`

**Interfaces:**
- Produces: `pipeline.segment.Passage` — frozen dataclass with `contract_id: str, ordinal: int, start: int, end: int, section_id: str, section_title: str, kind: str`. `kind` is `"section"`, `"front"` or `"toc"`.
- Produces: `pipeline.segment.segment(contract_id: str, text: str, max_chars: int = 2400) -> list[Passage]`
- Guarantees: passages are in order, contiguous and non-overlapping, the first starts at 0, the last ends at `len(text)`, and none is longer than `max_chars`. Empty text returns `[]`.

How it works, for the implementer: a heading is a section number like `7.2`, optionally preceded by `Section`, that sits at the start of a line or after two or more whitespace characters, and is followed by a capitalised title. Cross-references such as "pursuant to Section 2.9" have a single space before them and do not match. The table of contents lists every heading once before the body does, so the body starts at the *second* occurrence of the first heading's number when there is one. Everything before the body is "front" matter (title page, table of contents, preamble, recitals); front chunks that contain five or more section numbers are marked `toc` and are not indexed later. Long sections are cut at the best available boundary: blank line, then sub-clause marker such as `(a)`, then sentence end, then a hard cut.

- [ ] **Step 1: Write the failing test**

`tests/test_segment.py`:

```python
from pipeline.segment import segment

TOC = "TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 The Merger 6  Section 2.1 Effect on Stock 9  Section 2.2 Options 9  Section 3.1 Fees 12\n\n"
PREAMBLE = "AGREEMENT AND PLAN OF MERGER dated as of May 1 among Parent, Merger Sub and the Company.\n\nWHEREAS, the parties intend to merge.\n\n"
BODY = (
    "Section 1.1 Closing. The closing shall take place at 10:00 a.m.\n\n"
    "Section 1.2 The Merger. Merger Sub shall be merged into the Company pursuant to Section 1.1 hereof.\n\n"
    "Section 2.1 Effect on Stock. Each share shall be converted.\n\n"
    "Section 2.2 Options. Each Company Option shall vest in full.\n\n"
    "Section 3.1 Fees. The Company shall pay the Termination Fee.\n"
)
DOC = TOC + PREAMBLE + BODY


def check_cover(text, ps, max_chars):
    assert ps[0].start == 0 and ps[-1].end == len(text)
    assert all(a.end == b.start for a, b in zip(ps, ps[1:]))
    assert all(0 < p.end - p.start <= max_chars for p in ps)
    assert [p.ordinal for p in ps] == list(range(len(ps)))


def test_sections_come_from_the_body_not_the_table_of_contents():
    ps = segment("c1", DOC)
    check_cover(DOC, ps, 2400)
    sections = [p for p in ps if p.kind == "section"]
    assert [p.section_id for p in sections] == ["1.1", "1.2", "2.1", "2.2", "3.1"]
    assert sections[0].section_title == "Closing"
    assert DOC[sections[3].start:sections[3].end].startswith("Section 2.2 Options.")


def test_table_of_contents_is_marked_toc_and_preamble_is_front():
    ps = segment("c1", DOC, max_chars=160)
    kinds = {DOC[p.start:p.end][:17]: p.kind for p in ps if p.kind != "section"}
    assert kinds["TABLE OF CONTENTS"] == "toc"
    assert any(p.kind == "front" and "WHEREAS" in DOC[p.start:p.end] for p in ps)


def test_cross_reference_is_not_a_heading():
    ps = segment("c1", DOC)
    assert sum(1 for p in ps if p.section_id == "1.1") == 1


def test_inline_headings_after_wide_spaces_are_found():
    text = "The officers shall remain.   2.6           Conversion of Securities. At the Effective Time each share converts.   2.7   Exchange. The agent shall pay."
    ps = segment("c2", text)
    check_cover(text, ps, 2400)
    assert [p.section_id for p in ps if p.kind == "section"] == ["2.6", "2.7"]
    assert ps[0].kind == "front"


def test_long_section_is_split_at_subclause_boundaries():
    clause = "the Company shall comply with each of its obligations under this Agreement in all respects "
    text = "Section 5.1 Covenants. " + "".join(f"({c}) {clause * 3}" for c in "abcdefgh")
    ps = segment("c3", text, max_chars=600)
    check_cover(text, ps, 600)
    assert len(ps) > 1
    assert all(p.section_id == "5.1" for p in ps)
    assert all(text[p.start:p.end].lstrip().startswith("(") for p in ps[1:])


def test_text_with_no_headings_is_still_covered_and_bounded():
    text = "lorem ipsum dolor sit amet " * 400
    ps = segment("c4", text, max_chars=500)
    check_cover(text, ps, 500)
    assert {p.kind for p in ps} == {"front"}
    assert {p.section_id for p in ps} == {""}


def test_empty_text_gives_no_passages():
    assert segment("c5", "") == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_segment.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.segment'`

- [ ] **Step 3: Implement**

`pipeline/segment.py`:

```python
import re
from dataclasses import dataclass

HEAD = re.compile(
    r"(?:(?<=\n)|(?<=\s\s)|\A)(?:Section\s+|SECTION\s+)?(\d{1,2}\.\d{1,2})\.?[ \t\xa0]+(?=[A-Z])"
)
SECTION_NUMBER = re.compile(r"\b\d{1,2}\.\d{1,2}\b")
TITLE = re.compile(r"([^.\n]{2,100})\.")
# Tried in order: blank line, sub-clause marker, sentence end.
BREAKS = (
    re.compile(r"\n\s*\n"),
    re.compile(r"\s(?=\((?:[a-z]|[ivx]{1,4}|[A-Z])\)\s)"),
    re.compile(r"(?<=[.;:])\s"),
)
TOC_MIN_SECTION_NUMBERS = 5


@dataclass(frozen=True)
class Passage:
    contract_id: str
    ordinal: int
    start: int
    end: int
    section_id: str
    section_title: str
    kind: str


def _title(text: str, pos: int) -> str:
    m = TITLE.match(text[pos:pos + 110])
    return m.group(1).strip() if m else ""


def _cut(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    out = []
    while end - start > max_chars:
        window = text[start:start + max_chars]
        cut = None
        for rx in BREAKS:
            ends = [m.end() for m in rx.finditer(window) if m.end() >= max_chars // 4]
            if ends:
                cut = ends[-1]
                break
        if cut is None:
            cut = max_chars
        out.append((start, start + cut))
        start += cut
    out.append((start, end))
    return out


def segment(contract_id: str, text: str, max_chars: int = 2400) -> list[Passage]:
    if not text:
        return []
    cands = [(m.start(), m.group(1), m.end()) for m in HEAD.finditer(text)]
    heads = []
    if cands:
        first_id = cands[0][1]
        occurrences = [i for i, c in enumerate(cands) if c[1] == first_id]
        heads = cands[occurrences[1] if len(occurrences) > 1 else occurrences[0]:]
    pieces = []
    body_start = heads[0][0] if heads else len(text)
    if body_start > 0:
        pieces.append((0, body_start, "", "", "front"))
    for i, (pos, section_id, title_pos) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        pieces.append((pos, nxt, section_id, _title(text, title_pos), "section"))
    out: list[Passage] = []
    for s, e, section_id, title, kind in pieces:
        for a, b in _cut(text, s, e, max_chars):
            k = kind
            if kind == "front" and len(SECTION_NUMBER.findall(text[a:b])) >= TOC_MIN_SECTION_NUMBERS:
                k = "toc"
            out.append(Passage(contract_id, len(out), a, b, section_id, title, k))
    return out
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_segment.py -q`
Expected: 7 passed

If `test_table_of_contents_is_marked_toc_and_preamble_is_front` fails because a cut landed inside the table of contents and left fewer than five section numbers in one chunk, the fixture is at fault, not the rule: raise `max_chars` in that test to `200` and re-run. Do not lower `TOC_MIN_SECTION_NUMBERS`.

- [ ] **Step 5: Commit**

```bash
git add pipeline/segment.py tests/test_segment.py
git commit -m "m1: section-aware segmenter with contiguous bounded passages

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Defined-term extraction

**Files:**
- Create: `pipeline/terms.py`
- Test: `tests/test_terms.py`

**Interfaces:**
- Produces: `pipeline.terms.Term` — frozen dataclass with `term: str, start: int, end: int, style: str`. `style` is `"means"` or `"paren"`. `start`/`end` bound the match in the canonical text.
- Produces: `pipeline.terms.extract_terms(text: str) -> list[Term]`, sorted by `start`.

M1 only extracts and counts terms. Attaching definitions to passages is rung R6, in the M2 plan.

- [ ] **Step 1: Write the failing test**

`tests/test_terms.py`:

```python
from pipeline.terms import extract_terms


def test_means_style_with_curly_quotes():
    text = "“Company Equity Awards” means the Company Options and the Company RSUs."
    terms = extract_terms(text)
    assert [(t.term, t.style) for t in terms] == [("Company Equity Awards", "means")]
    assert text[terms[0].start:terms[0].end].startswith("“Company Equity Awards” means")


def test_shall_mean_and_has_the_meaning_with_straight_quotes():
    text = '"Effective Time" shall mean the time of filing. "Parent Board" has the meaning set forth in Section 1.1.'
    assert [t.term for t in extract_terms(text)] == ["Effective Time", "Parent Board"]


def test_parenthetical_definition():
    text = "equal to fourteen dollars ($14.00) (the “Per Share Merger Consideration”) payable to the holder"
    terms = extract_terms(text)
    assert [(t.term, t.style) for t in terms] == [("Per Share Merger Consideration", "paren")]


def test_each_an_parenthetical():
    text = "become an option (each, an “Assumed Stock Option”) to purchase shares"
    assert [t.term for t in extract_terms(text)] == ["Assumed Stock Option"]


def test_quoted_phrase_that_is_not_a_definition_is_ignored():
    text = "The word “including” is not limiting. He said “Yes” to the offer."
    assert extract_terms(text) == []


def test_results_are_sorted_by_position():
    text = "(the “B Term”) and later “A Term” means something."
    assert [t.term for t in extract_terms(text)] == ["B Term", "A Term"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_terms.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.terms'`

- [ ] **Step 3: Implement**

`pipeline/terms.py`:

```python
import re
from dataclasses import dataclass

_QUOTED = r"[“\"]([A-Z][^”\"\n]{1,80})[”\"]"
MEANS = re.compile(_QUOTED + r"\s+(?:means|shall mean|has the meaning|shall have the meaning)\b")
PAREN = re.compile(r"\((?:the|each,? an?|collectively,? the|together,? the)?\s*" + _QUOTED + r"\)")


@dataclass(frozen=True)
class Term:
    term: str
    start: int
    end: int
    style: str


def extract_terms(text: str) -> list[Term]:
    out = [Term(m.group(1).strip(), m.start(), m.end(), "means") for m in MEANS.finditer(text)]
    out += [Term(m.group(1).strip(), m.start(), m.end(), "paren") for m in PAREN.finditer(text)]
    return sorted(out, key=lambda t: t.start)
```

- [ ] **Step 4: Run the test**

Run: `uv run pytest tests/test_terms.py -q`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add pipeline/terms.py tests/test_terms.py
git commit -m "m1: defined-term extraction (means and parenthetical styles)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: SQLite index build and BM25 search (rung R1)

**Files:**
- Create: `retrieval/index.py`, `retrieval/bm25.py`
- Test: `tests/test_index.py`, `tests/test_bm25.py`

**Interfaces:**
- Consumes: `pipeline.segment.segment`, `pipeline.terms.extract_terms`
- Produces: `retrieval.index.build_index(db_path: Path, contracts: dict[str, str]) -> dict` — `contracts` maps contract id to canonical text; returns `{"contracts": n, "passages": n, "indexed": n, "terms": n}`. Writes to `db_path` atomically; rerunning replaces the file.
- Produces tables: `contracts(contract_id, n_chars)`; `passages(passage_id, contract_id, ordinal, start_char, end_char, section_id, section_title, kind)`; `terms(contract_id, term, start_char, end_char, style)`; FTS5 `passages_fts(text)` whose `rowid` is `passage_id`. Passages of kind `toc` are in `passages` but not in `passages_fts`.
- Produces: `retrieval.bm25.Hit` — frozen dataclass `passage_id: int, contract_id: str, start: int, end: int, score: float`
- Produces: `retrieval.bm25.fts_query(q: str) -> str`
- Produces: `retrieval.bm25.search(conn: sqlite3.Connection, query: str, contract_id: str | None = None, k: int = 10) -> list[Hit]` — best first; higher score is better.

- [ ] **Step 1: Write the failing index test**

`tests/test_index.py`:

```python
import sqlite3

from retrieval.index import build_index

DOC_A = (
    "TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 Merger 6  Section 2.1 Stock 9  Section 2.2 Options 9  Section 3.1 Fees 12\n\n"
    "Section 1.1 Closing. The closing shall occur.\n\n"
    "Section 1.2 Merger. “Effective Time” means the time of filing.\n\n"
    "Section 2.2 Options. Each Company Option shall vest in full at the Effective Time.\n"
)
DOC_B = "Section 1.1 Fees. The Company shall pay the Termination Fee of $50,000,000 to Parent.\n"


def test_build_writes_all_tables(tmp_path):
    db = tmp_path / "idx" / "maud.db"
    summary = build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    conn = sqlite3.connect(db)
    assert summary["contracts"] == conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 2
    assert summary["passages"] == conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    assert summary["indexed"] == conn.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]
    assert summary["terms"] == conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 1
    toc = conn.execute("SELECT COUNT(*) FROM passages WHERE kind = 'toc'").fetchone()[0]
    assert toc >= 1 and summary["indexed"] == summary["passages"] - toc


def test_stored_offsets_recover_the_indexed_text(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_b": DOC_B})
    conn = sqlite3.connect(db)
    pid, s, e = conn.execute("SELECT passage_id, start_char, end_char FROM passages").fetchone()
    assert conn.execute("SELECT text FROM passages_fts WHERE rowid = ?", (pid,)).fetchone()[0] == DOC_B[s:e]


def test_rebuild_is_idempotent_and_leaves_no_temp_file(tmp_path):
    db = tmp_path / "maud.db"
    first = build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    second = build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    assert first == second
    assert sorted(p.name for p in tmp_path.iterdir()) == ["maud.db"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_index.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval.index'`

- [ ] **Step 3: Implement the index build**

`retrieval/index.py`:

```python
import os
import sqlite3
from pathlib import Path

from pipeline.segment import segment
from pipeline.terms import extract_terms

SCHEMA = """
CREATE TABLE contracts(contract_id TEXT PRIMARY KEY, n_chars INTEGER NOT NULL);
CREATE TABLE passages(
    passage_id INTEGER PRIMARY KEY,
    contract_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    section_id TEXT NOT NULL,
    section_title TEXT NOT NULL,
    kind TEXT NOT NULL
);
CREATE INDEX passages_contract ON passages(contract_id);
CREATE TABLE terms(
    contract_id TEXT NOT NULL,
    term TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    style TEXT NOT NULL
);
CREATE VIRTUAL TABLE passages_fts USING fts5(text, tokenize='porter unicode61');
"""


def build_index(db_path: Path, contracts: dict[str, str]) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    summary = {"contracts": 0, "passages": 0, "indexed": 0, "terms": 0}
    for contract_id in sorted(contracts):
        text = contracts[contract_id]
        conn.execute("INSERT INTO contracts VALUES (?, ?)", (contract_id, len(text)))
        summary["contracts"] += 1
        for p in segment(contract_id, text):
            cur = conn.execute(
                "INSERT INTO passages(contract_id, ordinal, start_char, end_char, section_id, section_title, kind)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (p.contract_id, p.ordinal, p.start, p.end, p.section_id, p.section_title, p.kind),
            )
            summary["passages"] += 1
            if p.kind != "toc":
                conn.execute(
                    "INSERT INTO passages_fts(rowid, text) VALUES (?, ?)",
                    (cur.lastrowid, text[p.start:p.end]),
                )
                summary["indexed"] += 1
        for t in extract_terms(text):
            conn.execute("INSERT INTO terms VALUES (?, ?, ?, ?, ?)", (contract_id, t.term, t.start, t.end, t.style))
            summary["terms"] += 1
    conn.commit()
    conn.close()
    os.replace(tmp, db_path)
    return summary
```

- [ ] **Step 4: Run the index test**

Run: `uv run pytest tests/test_index.py -q`
Expected: 3 passed

- [ ] **Step 5: Write the failing search test**

`tests/test_bm25.py`:

```python
import sqlite3

import pytest

from retrieval.bm25 import fts_query, search
from retrieval.index import build_index

DOC_A = (
    "Section 1.1 Closing. The closing shall occur at the offices of counsel.\n\n"
    "Section 2.2 Options. Each Company Option shall vest in full at the Effective Time.\n\n"
    "Section 3.1 Fees. The Company shall pay the Termination Fee to Parent.\n"
)
DOC_B = "Section 1.1 Options. Each option shall be cancelled for no consideration.\n"


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    return sqlite3.connect(db)


def test_best_hit_is_the_matching_section(conn):
    hits = search(conn, "do options vest", contract_id="contract_a", k=3)
    assert DOC_A[hits[0].start:hits[0].end].startswith("Section 2.2 Options.")
    assert all(h.contract_id == "contract_a" for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_without_a_contract_filter_all_contracts_are_searched(conn):
    assert {h.contract_id for h in search(conn, "option", k=10)} == {"contract_a", "contract_b"}


def test_k_limits_the_result_count(conn):
    assert len(search(conn, "the shall", k=2)) == 2


def test_fts_query_quotes_tokens_and_drops_punctuation():
    assert fts_query('what\'s the "fee"?') == '"what" OR "the" OR "fee"'
    assert fts_query("AND OR") == '"and" OR "or"'


@pytest.mark.parametrize("q", ["", "   ", "?!\"'()*:^", "AND OR NOT NEAR", 'what\'s the "fee"?', "a"])
def test_hostile_queries_never_raise(conn, q):
    assert isinstance(search(conn, q, contract_id="contract_a"), list)


def test_empty_query_returns_no_hits(conn):
    assert search(conn, "?!") == []
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_bm25.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'retrieval.bm25'`

- [ ] **Step 7: Implement search**

`retrieval/bm25.py`:

```python
import re
import sqlite3
from dataclasses import dataclass

TOKEN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class Hit:
    passage_id: int
    contract_id: str
    start: int
    end: int
    score: float


def fts_query(q: str) -> str:
    """Every token quoted and OR-joined, so FTS5 operators in user text are inert."""
    tokens = [t for t in dict.fromkeys(TOKEN.findall(q.lower())) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in tokens)


def search(conn: sqlite3.Connection, query: str, contract_id: str | None = None, k: int = 10) -> list[Hit]:
    match = fts_query(query)
    if not match:
        return []
    sql = (
        "SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, -bm25(passages_fts)"
        " FROM passages_fts JOIN passages p ON p.passage_id = passages_fts.rowid"
        " WHERE passages_fts MATCH ?"
    )
    params: list = [match]
    if contract_id is not None:
        sql += " AND p.contract_id = ?"
        params.append(contract_id)
    sql += " ORDER BY bm25(passages_fts) LIMIT ?"
    params.append(k)
    return [Hit(*row) for row in conn.execute(sql, params)]
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -q`
Expected: all pass (41 tests)

- [ ] **Step 9: Commit**

```bash
git add retrieval tests/test_index.py tests/test_bm25.py
git commit -m "m1: SQLite index build and BM25 search (rung R1)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: MAUD label loading and excerpt alignment

**Files:**
- Create: `evals/maud_labels.py`, `evals/align.py`
- Test: `tests/test_maud_labels.py`, `tests/test_align.py`

**Interfaces:**
- Consumes: `pipeline.normalise.squash`
- Produces: `evals.maud_labels.LabelRow` — frozen dataclass `contract_id: str, text: str, question: str, subquestion: str, answer: str, text_type: str, category: str`
- Produces: `evals.maud_labels.load_rows(csv_paths: list[Path]) -> list[LabelRow]` — only rows with `data_type == "main"` and a real contract name; exact duplicate rows across the three CSVs are removed.
- Produces: `evals.align.pieces_of(excerpt: str) -> list[str]` — the excerpt split on `<omitted>` with page markers removed; pieces shorter than `MIN_PIECE` (40) non-whitespace characters are dropped.
- Produces: `evals.align.align_piece(piece: str, squashed: str, index: list[int]) -> tuple[str, int, int]` — `(status, start, end)` in canonical-text offsets; status is `"exact"`, `"anchored"` or `"none"` (then `start == end == -1`).

Why alignment is needed: MAUD's `text` column is not a substring of the contract. It is stitched from pieces joined by `<omitted>`, ends with `(Page N)` or `(Pages N-M)`, and its whitespace differs. Comparing with all whitespace removed finds most pieces exactly. For the rest, the first 40 and last 40 characters of the piece are located separately and the span between them is taken, provided it is not more than about twice the piece's length.

- [ ] **Step 1: Write the failing label test**

`tests/test_maud_labels.py`:

```python
from evals.maud_labels import load_rows

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"


def write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def test_only_main_rows_with_real_contracts_are_loaded(tmp_path):
    p = write(
        tmp_path, "a.csv",
        'main,contract_1,"Section 2.6 text",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,1,General Information\n'
        "abridged,contract_1,short,All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,2,General Information\n"
        "rare_answers,<RARE_ANSWERS>,made up,Other,3,Type of Consideration-Answer,<NONE>,Type of Consideration,3,General Information\n",
    )
    rows = load_rows([p])
    assert len(rows) == 1
    r = rows[0]
    assert (r.contract_id, r.text, r.answer, r.text_type, r.category) == (
        "contract_1", "Section 2.6 text", "All Cash", "Type of Consideration", "General Information")


def test_duplicate_rows_across_files_are_removed(tmp_path):
    line = "main,contract_1,t,a,0,q,<NONE>,tt,1,c\n"
    rows = load_rows([write(tmp_path, "a.csv", line), write(tmp_path, "b.csv", line)])
    assert len(rows) == 1


def test_very_long_text_field_is_read(tmp_path):
    big = "x" * 300_000
    rows = load_rows([write(tmp_path, "a.csv", f"main,contract_1,{big},a,0,q,<NONE>,tt,1,c\n")])
    assert len(rows[0].text) == 300_000
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_maud_labels.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.maud_labels'`

- [ ] **Step 3: Implement label loading**

`evals/maud_labels.py`:

```python
import csv
from dataclasses import dataclass
from pathlib import Path

PSEUDO_CONTRACT = "<RARE_ANSWERS>"


@dataclass(frozen=True)
class LabelRow:
    contract_id: str
    text: str
    question: str
    subquestion: str
    answer: str
    text_type: str
    category: str


def load_rows(csv_paths: list[Path]) -> list[LabelRow]:
    csv.field_size_limit(10**9)
    seen: dict[LabelRow, None] = {}
    for p in csv_paths:
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if row["data_type"] != "main" or row["contract_name"] == PSEUDO_CONTRACT:
                    continue
                seen[LabelRow(
                    contract_id=row["contract_name"],
                    text=row["text"],
                    question=row["question"],
                    subquestion=row["subquestion"],
                    answer=row["answer"],
                    text_type=row["text_type"],
                    category=row["category"],
                )] = None
    return list(seen)
```

- [ ] **Step 4: Run the label test**

Run: `uv run pytest tests/test_maud_labels.py -q`
Expected: 3 passed

- [ ] **Step 5: Write the failing alignment test**

`tests/test_align.py`:

```python
from evals.align import align_piece, pieces_of
from pipeline.normalise import squash

CONTRACT = (
    "Section 7.2   Conditions to Obligations of Parent and Merger Sub.\n\n"
    "The obligations of Parent and Merger Sub to consummate the Closing are subject to the\n"
    "satisfaction of the following conditions: (a) the representations shall be true; "
    "(b) Performance of Obligations of the Company. The Company shall have performed in all "
    "material respects its covenants and obligations under this Agreement.\n"
)
SQ, IDX = squash(CONTRACT)


def test_pieces_split_on_omitted_and_drop_page_markers_and_short_pieces():
    excerpt = ("Section 7.2 Conditions. <omitted> The Company shall have performed in all material respects "
               "its covenants and obligations under this Agreement. (Pages 81-82)")
    pieces = pieces_of(excerpt)
    assert len(pieces) == 1
    assert pieces[0].startswith("The Company shall have performed")
    assert "(Pages" not in pieces[0]


def test_single_page_marker_is_removed():
    assert "(Page" not in pieces_of("x" * 60 + " (Page 12)")[0]


def test_exact_alignment_ignores_whitespace_differences():
    piece = "The obligations of Parent and Merger Sub to consummate the  Closing are subject to the satisfaction of the following conditions"
    status, s, e = align_piece(piece, SQ, IDX)
    assert status == "exact"
    assert CONTRACT[s:e].startswith("The obligations of Parent")
    assert CONTRACT[s:e].endswith("following conditions")


def test_anchored_alignment_survives_a_changed_middle():
    piece = ("The obligations of Parent and Merger Sub to consummate the Closing are subject to the "
             "satisfaction of the following conditions: (a) the representations 76 shall be true; "
             "(b) Performance of Obligations of the Company. The Company shall have performed in all "
             "material respects its covenants and obligations under this Agreement.")
    status, s, e = align_piece(piece, SQ, IDX)
    assert status == "anchored"
    assert CONTRACT[s:e].startswith("The obligations of Parent")
    assert CONTRACT[s:e].endswith("under this Agreement.")


def test_text_not_in_the_contract_is_unaligned():
    piece = "Each holder of Company Warrants shall receive the Black-Scholes value of such warrant in cash."
    assert align_piece(piece, SQ, IDX) == ("none", -1, -1)


def test_anchors_too_far_apart_are_rejected():
    far = "A" * 40 + " filler " * 2000 + "B" * 40
    sq, idx = squash(far)
    piece = "A" * 40 + " x " + "B" * 40
    assert align_piece(piece, sq, idx)[0] == "none"
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_align.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.align'`

- [ ] **Step 7: Implement alignment**

`evals/align.py`:

```python
import re

PAGE_MARKER = re.compile(r"\(Pages?\s*[\d\-–, ]+\)")
WHITESPACE = re.compile(r"\s+")
MIN_PIECE = 40
ANCHOR = 40
MAX_ANCHOR_TRIES = 4


def _squash(s: str) -> str:
    return WHITESPACE.sub("", s)


def pieces_of(excerpt: str) -> list[str]:
    parts = PAGE_MARKER.sub("", excerpt).split("<omitted>")
    return [p.strip() for p in parts if len(_squash(p)) >= MIN_PIECE]


def _locate(p: str, squashed: str) -> tuple[str, int, int]:
    i = squashed.find(p)
    if i >= 0:
        return "exact", i, i + len(p)
    n = len(p)
    limit = 2 * n + 200
    for head_at in range(0, min(n - ANCHOR, MAX_ANCHOR_TRIES * ANCHOR) + 1, ANCHOR):
        h = squashed.find(p[head_at:head_at + ANCHOR])
        if h < 0:
            continue
        for tail_end in range(n, max(ANCHOR, n - MAX_ANCHOR_TRIES * ANCHOR) - 1, -ANCHOR):
            t = squashed.find(p[tail_end - ANCHOR:tail_end], h)
            if t >= 0 and t + ANCHOR - h <= limit:
                return "anchored", h, t + ANCHOR
    return "none", -1, -1


def align_piece(piece: str, squashed: str, index: list[int]) -> tuple[str, int, int]:
    status, s, e = _locate(_squash(piece), squashed)
    if status == "none":
        return "none", -1, -1
    return status, index[s], index[e - 1] + 1
```

- [ ] **Step 8: Run the alignment test**

Run: `uv run pytest tests/test_align.py -q`
Expected: 6 passed

- [ ] **Step 9: Commit**

```bash
git add evals/maud_labels.py evals/align.py tests/test_maud_labels.py tests/test_align.py
git commit -m "m1: MAUD label loading and excerpt-to-span alignment

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Eval items and retrieval metrics

**Files:**
- Create: `evals/items.py`, `evals/metrics.py`
- Test: `tests/test_items.py`, `tests/test_metrics.py`

**Interfaces:**
- Consumes: `evals.maud_labels.LabelRow`, `evals.align.pieces_of`, `evals.align.align_piece`, `pipeline.normalise.squash`, `retrieval.bm25.Hit`
- Produces: `evals.items.Item` — frozen dataclass `item_id: str, contract_id: str, text_type: str, category: str, query: str, gold: tuple[tuple[int, int], ...]`
- Produces: `evals.items.build_items(rows: list[LabelRow], texts: dict[str, str]) -> tuple[list[Item], dict]` — one item per `(contract_id, text_type)`; only items with at least one aligned gold span are returned. The report dict has integer keys `rows, items, items_scored, items_no_gold, items_missing_contract, pieces, pieces_exact, pieces_anchored, pieces_unaligned`.
- Produces: `evals.metrics.is_relevant(start: int, end: int, gold) -> bool`, `recall_at_k(hits, gold, k) -> float`, `mrr(hits, gold, k=10) -> float`, `ndcg_at_k(hits, gold, n_relevant, k=10) -> float`

Definitions, for the implementer:
- The **query** for an item is the MAUD deal-point name (`text_type`) followed by the distinct MAUD question names under it, with a trailing `-Answer` removed. These are MAUD's own label names used verbatim, not natural questions; M2's query rewriting is measured against this baseline.
- A passage is **relevant** to a gold span when they overlap by at least 20 characters, or by the whole span if the span is shorter than 20.
- **recall@k** is the share of an item's gold spans touched by at least one of the top k passages.
- **nDCG@k** uses gain 1 for a relevant passage; the ideal ranking has `min(k, n_relevant)` relevant passages, where `n_relevant` is how many indexed passages of that contract are relevant.

- [ ] **Step 1: Write the failing items test**

`tests/test_items.py`:

```python
from evals.items import build_items
from evals.maud_labels import LabelRow

TEXT = (
    "Section 2.6 Conversion of Securities. Each Company Share shall be converted into the right to receive cash.\n\n"
    "Section 7.2 Conditions. The Company shall have performed in all material respects its covenants hereunder.\n"
)
EX_26 = "Section 2.6 Conversion of Securities. Each Company Share shall be converted into the right to receive cash. (Page 9)"
EX_72 = "Section 7.2 Conditions. The Company shall have performed in all material respects its covenants hereunder. (Page 80)"


def row(contract, text, text_type, question, category="General Information"):
    return LabelRow(contract, text, question, "<NONE>", "answer", text_type, category)


def test_one_item_per_contract_and_text_type_with_combined_query():
    rows = [
        row("contract_1", EX_26, "Type of Consideration", "Type of Consideration-Answer"),
        row("contract_1", EX_26, "Type of Consideration", "Stock Deal-Answer"),
        row("contract_1", EX_72, "Compliance with Covenant Closing Condition", "Compliance-Answer", "Conditions to Closing"),
    ]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert [i.item_id for i in items] == [
        "contract_1|Compliance with Covenant Closing Condition", "contract_1|Type of Consideration"]
    toc = items[1]
    assert toc.query == "Type of Consideration. Stock Deal"
    assert len(toc.gold) == 1
    s, e = toc.gold[0]
    assert TEXT[s:e].startswith("Section 2.6") and TEXT[s:e].endswith("receive cash.")
    assert report["items"] == 2 and report["items_scored"] == 2 and report["pieces_exact"] == 2


def test_identical_excerpts_give_one_gold_span():
    rows = [row("contract_1", EX_26, "Type of Consideration", q) for q in ("A-Answer", "B-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert len(items[0].gold) == 1 and report["pieces"] == 1


def test_unalignable_excerpt_excludes_the_item_and_is_counted():
    bad = "Each holder of Company Warrants shall receive the Black-Scholes value of such warrant in cash at closing."
    rows = [row("contract_1", bad, "Warrants", "Warrants-Answer"),
            row("contract_1", EX_26, "Type of Consideration", "Type of Consideration-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert [i.text_type for i in items] == ["Type of Consideration"]
    assert report["items"] == 2 and report["items_scored"] == 1 and report["items_no_gold"] == 1
    assert report["pieces_unaligned"] == 1


def test_contract_without_a_file_is_counted_not_raised():
    rows = [row("contract_404", EX_26, "Type of Consideration", "Type of Consideration-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert items == []
    assert report["items_missing_contract"] == 1 and report["items_scored"] == 0
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_items.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.items'`

- [ ] **Step 3: Implement items**

`evals/items.py`:

```python
from collections import defaultdict
from dataclasses import dataclass

from evals.align import align_piece, pieces_of
from evals.maud_labels import LabelRow
from pipeline.normalise import squash

ANSWER_SUFFIX = "-Answer"


@dataclass(frozen=True)
class Item:
    item_id: str
    contract_id: str
    text_type: str
    category: str
    query: str
    gold: tuple[tuple[int, int], ...]


def _query(text_type: str, questions: list[str]) -> str:
    stems = []
    for q in questions:
        stem = q[: -len(ANSWER_SUFFIX)] if q.endswith(ANSWER_SUFFIX) else q
        if stem != text_type and stem not in stems:
            stems.append(stem)
    return ". ".join([text_type] + sorted(stems))


def build_items(rows: list[LabelRow], texts: dict[str, str]) -> tuple[list[Item], dict]:
    report = dict.fromkeys(
        ("rows", "items", "items_scored", "items_no_gold", "items_missing_contract",
         "pieces", "pieces_exact", "pieces_anchored", "pieces_unaligned"), 0)
    report["rows"] = len(rows)
    groups: dict[tuple[str, str], list[LabelRow]] = defaultdict(list)
    for r in rows:
        groups[(r.contract_id, r.text_type)].append(r)
    squashed_cache: dict[str, tuple[str, list[int]]] = {}
    items: list[Item] = []
    for (contract_id, text_type) in sorted(groups):
        group = groups[(contract_id, text_type)]
        report["items"] += 1
        if contract_id not in texts:
            report["items_missing_contract"] += 1
            continue
        if contract_id not in squashed_cache:
            squashed_cache[contract_id] = squash(texts[contract_id])
        squashed, index = squashed_cache[contract_id]
        gold: list[tuple[int, int]] = []
        for excerpt in dict.fromkeys(r.text for r in group):
            for piece in pieces_of(excerpt):
                report["pieces"] += 1
                status, s, e = align_piece(piece, squashed, index)
                if status == "none":
                    report["pieces_unaligned"] += 1
                    continue
                report[f"pieces_{status}"] += 1
                if (s, e) not in gold:
                    gold.append((s, e))
        if not gold:
            report["items_no_gold"] += 1
            continue
        report["items_scored"] += 1
        items.append(Item(
            item_id=f"{contract_id}|{text_type}",
            contract_id=contract_id,
            text_type=text_type,
            category=group[0].category,
            query=_query(text_type, [r.question for r in group]),
            gold=tuple(sorted(gold)),
        ))
    return items, report
```

- [ ] **Step 4: Run the items test**

Run: `uv run pytest tests/test_items.py -q`
Expected: 4 passed

- [ ] **Step 5: Write the failing metrics test**

`tests/test_metrics.py`:

```python
import math

import pytest

from evals.metrics import is_relevant, mrr, ndcg_at_k, recall_at_k
from retrieval.bm25 import Hit


def hit(start, end, pid=1):
    return Hit(pid, "c", start, end, 1.0)


GOLD = ((100, 200), (500, 510))


def test_relevance_needs_twenty_characters_of_overlap():
    assert is_relevant(180, 300, GOLD)
    assert not is_relevant(190, 300, GOLD)
    assert not is_relevant(200, 300, GOLD)


def test_a_span_shorter_than_twenty_needs_full_overlap():
    assert is_relevant(495, 520, GOLD)
    assert not is_relevant(505, 520, GOLD)


def test_recall_counts_gold_spans_touched_in_top_k():
    hits = [hit(0, 50), hit(90, 210), hit(480, 520)]
    assert recall_at_k(hits, GOLD, 1) == 0.0
    assert recall_at_k(hits, GOLD, 2) == 0.5
    assert recall_at_k(hits, GOLD, 3) == 1.0


def test_recall_with_no_hits_is_zero():
    assert recall_at_k([], GOLD, 5) == 0.0


def test_mrr_is_reciprocal_rank_of_first_relevant_hit():
    assert mrr([hit(0, 50), hit(90, 210)], GOLD) == 0.5
    assert mrr([hit(0, 50)], GOLD) == 0.0


def test_mrr_ignores_hits_beyond_k():
    hits = [hit(0, 50)] * 10 + [hit(90, 210)]
    assert mrr(hits, GOLD, k=10) == 0.0


def test_ndcg_is_one_for_an_ideal_ranking():
    assert ndcg_at_k([hit(90, 210), hit(480, 520), hit(0, 50)], GOLD, n_relevant=2) == pytest.approx(1.0)


def test_ndcg_discounts_a_late_relevant_hit():
    got = ndcg_at_k([hit(0, 50), hit(90, 210)], GOLD, n_relevant=1)
    assert got == pytest.approx((1 / math.log2(3)) / 1.0)


def test_ndcg_is_zero_when_nothing_is_relevant_in_the_corpus():
    assert ndcg_at_k([hit(0, 50)], GOLD, n_relevant=0) == 0.0
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_metrics.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.metrics'`

- [ ] **Step 7: Implement metrics**

`evals/metrics.py`:

```python
import math

MIN_OVERLAP = 20


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def _touches(start: int, end: int, g0: int, g1: int) -> bool:
    return _overlap(start, end, g0, g1) >= min(MIN_OVERLAP, g1 - g0)


def is_relevant(start: int, end: int, gold) -> bool:
    return any(_touches(start, end, g0, g1) for g0, g1 in gold)


def recall_at_k(hits, gold, k: int) -> float:
    top = hits[:k]
    found = sum(1 for g0, g1 in gold if any(_touches(h.start, h.end, g0, g1) for h in top))
    return found / len(gold)


def mrr(hits, gold, k: int = 10) -> float:
    for rank, h in enumerate(hits[:k], start=1):
        if is_relevant(h.start, h.end, gold):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(hits, gold, n_relevant: int, k: int = 10) -> float:
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, n_relevant) + 1))
    if ideal == 0:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, h in enumerate(hits[:k], start=1)
        if is_relevant(h.start, h.end, gold)
    )
    return dcg / ideal
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -q`
Expected: all pass (63 tests)

- [ ] **Step 9: Commit**

```bash
git add evals/items.py evals/metrics.py tests/test_items.py tests/test_metrics.py
git commit -m "m1: eval items from MAUD labels and span-overlap retrieval metrics

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Clustered bootstrap, tune/report split and the R1 run

**Files:**
- Create: `evals/bootstrap.py`, `evals/run_r1.py`
- Test: `tests/test_bootstrap.py`, `tests/test_run_r1.py`

**Interfaces:**
- Consumes: `retrieval.index.build_index`, `retrieval.bm25.search`, `evals.maud_labels.load_rows`, `evals.items.build_items`, `evals.metrics.*`, `pipeline.normalise.load_contract`
- Produces: `evals.bootstrap.split_of(contract_id: str) -> str` — `"tune"` for about 30% of contracts, `"report"` for the rest, fixed by a hash of the id
- Produces: `evals.bootstrap.cluster_bootstrap(values_by_cluster: dict[str, list[float]], n_boot: int = 2000, seed: int = 0) -> dict` with keys `mean, lo, hi, n_items, n_clusters` (a 95% interval; clusters are resampled with replacement)
- Produces: `evals.run_r1.METRICS: tuple[str, ...]` = `("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")`
- Produces: `evals.run_r1.run(db_path: Path, csv_paths: list[Path], contracts_dir: Path, out_dir: Path, n_boot: int = 2000) -> dict` — writes `out_dir/r1.json` and `out_dir/alignment.json` and returns the r1 dict:

```json
{
  "rung": "R1",
  "scope": "within-agreement",
  "alignment": {"rows": 0, "items": 0, "items_scored": 0, "...": 0},
  "overall": {"recall@1": {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n_items": 0, "n_clusters": 0}, "...": {}},
  "by_split": {"tune": {"recall@1": {}}, "report": {"recall@1": {}}},
  "by_category": {"<category>": {"recall@1": {}}},
  "latency_ms": {"p50": 0.0, "p95": 0.0}
}
```

Why the split exists: M2 tunes rungs (fusion weights, reranker depth). Tuning happens on `tune` contracts and headline numbers are read from `report` contracts. The split is fixed now so that M1's baseline and M2's rungs are compared on the same contracts.

Why the interval is clustered: several items come from the same agreement and are not independent. Resampling whole contracts gives an honest interval.

- [ ] **Step 1: Write the failing bootstrap test**

`tests/test_bootstrap.py`:

```python
import pytest

from evals.bootstrap import cluster_bootstrap, split_of


def test_split_is_stable_and_roughly_thirty_seventy():
    ids = [f"contract_{i}" for i in range(152)]
    splits = [split_of(i) for i in ids]
    assert splits == [split_of(i) for i in ids]
    assert set(splits) == {"tune", "report"}
    assert 25 <= splits.count("tune") <= 70


def test_mean_is_over_all_items_not_over_clusters():
    got = cluster_bootstrap({"a": [1.0, 1.0, 1.0], "b": [0.0]}, n_boot=200)
    assert got["mean"] == 0.75
    assert got["n_items"] == 4 and got["n_clusters"] == 2


def test_interval_brackets_the_mean_and_is_reproducible():
    data = {f"c{i}": [float(i % 2)] * 3 for i in range(20)}
    a = cluster_bootstrap(data, n_boot=500, seed=7)
    b = cluster_bootstrap(data, n_boot=500, seed=7)
    assert a == b
    assert a["lo"] <= a["mean"] <= a["hi"]
    assert a["lo"] < a["hi"]


def test_identical_values_give_a_zero_width_interval():
    got = cluster_bootstrap({"a": [0.5, 0.5], "b": [0.5]}, n_boot=100)
    assert got["lo"] == got["hi"] == got["mean"] == 0.5


def test_single_cluster_still_returns_an_interval():
    got = cluster_bootstrap({"a": [0.0, 1.0]}, n_boot=50)
    assert got["mean"] == got["lo"] == got["hi"] == 0.5


def test_no_values_raises():
    with pytest.raises(ValueError):
        cluster_bootstrap({})
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_bootstrap.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.bootstrap'`

- [ ] **Step 3: Implement the bootstrap**

`evals/bootstrap.py`:

```python
import hashlib
import random

TUNE_TENTHS = 3


def split_of(contract_id: str) -> str:
    bucket = hashlib.sha1(contract_id.encode("utf-8")).digest()[0] % 10
    return "tune" if bucket < TUNE_TENTHS else "report"


def cluster_bootstrap(values_by_cluster: dict[str, list[float]], n_boot: int = 2000, seed: int = 0) -> dict:
    clusters = sorted(c for c, vs in values_by_cluster.items() if vs)
    if not clusters:
        raise ValueError("no values to bootstrap")
    sums = [sum(values_by_cluster[c]) for c in clusters]
    counts = [len(values_by_cluster[c]) for c in clusters]
    mean = sum(sums) / sum(counts)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        total = 0.0
        n = 0
        for _ in clusters:
            j = rng.randrange(len(clusters))
            total += sums[j]
            n += counts[j]
        stats.append(total / n)
    stats.sort()
    lo = stats[int(0.025 * n_boot)]
    hi = stats[min(n_boot - 1, int(0.975 * n_boot))]
    return {"mean": mean, "lo": lo, "hi": hi, "n_items": sum(counts), "n_clusters": len(clusters)}
```

- [ ] **Step 4: Run the bootstrap test**

Run: `uv run pytest tests/test_bootstrap.py -q`
Expected: 6 passed

- [ ] **Step 5: Write the failing run test**

`tests/test_run_r1.py`:

```python
import json

from evals.run_r1 import METRICS, run
from retrieval.index import build_index

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
        consideration = t.split("\n\n")[1]
        fee = t.split("\n\n")[2].strip()
        body += f'main,{cid},"{consideration} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,{i},General Information\n'
        body += f'main,{cid},"{fee} (Page 70)",Yes,1,Termination Fee-Answer,<NONE>,Termination Fee,{i + 100},Deal Protection and Related Provisions\n'
    body += 'main,contract_404,"Section 2.6 Type of Consideration. Each Company Share shall be converted. (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,999,General Information\n'
    csv_path = tmp_path / "raw" / "MAUD_dev.csv"
    csv_path.write_text(HEADER + body, encoding="utf-8")
    db = tmp_path / "index" / "maud.db"
    build_index(db, texts)
    return db, [csv_path], cdir, tmp_path / "out"


def test_run_writes_results_with_every_metric(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    assert json.loads((out / "r1.json").read_text()) == result
    assert result["rung"] == "R1" and result["scope"] == "within-agreement"
    assert set(result["overall"]) == set(METRICS)
    assert result["overall"]["recall@10"]["n_items"] == 8
    assert result["overall"]["recall@10"]["n_clusters"] == 4
    assert result["overall"]["recall@5"]["mean"] == 1.0
    assert result["latency_ms"]["p50"] >= 0 and result["latency_ms"]["p95"] >= result["latency_ms"]["p50"]


def test_run_reports_the_missing_contract(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    assert result["alignment"]["items_missing_contract"] == 1
    assert result["alignment"]["items_scored"] == 8
    assert json.loads((out / "alignment.json").read_text()) == result["alignment"]


def test_run_breaks_results_down_by_category_and_split(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    assert set(result["by_category"]) == {"General Information", "Deal Protection and Related Provisions"}
    assert result["by_category"]["General Information"]["recall@10"]["n_items"] == 4
    total = sum(result["by_split"][s]["recall@10"]["n_items"] for s in result["by_split"])
    assert total == 8


def test_run_is_deterministic(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    a = run(db, csvs, cdir, out, n_boot=100)
    b = run(db, csvs, cdir, out, n_boot=100)
    a.pop("latency_ms"); b.pop("latency_ms")
    assert a == b
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_run_r1.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.run_r1'`

- [ ] **Step 7: Implement the run**

`evals/run_r1.py`:

```python
import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap, split_of
from evals.items import build_items
from evals.maud_labels import load_rows
from evals.metrics import is_relevant, mrr, ndcg_at_k, recall_at_k
from pipeline.normalise import load_contract
from retrieval.bm25 import search

METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")
K = 10


def _summarise(per_item: list[dict], n_boot: int) -> dict:
    out = {}
    for metric in METRICS:
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


def run(db_path: Path, csv_paths: list[Path], contracts_dir: Path, out_dir: Path, n_boot: int = 2000) -> dict:
    conn = sqlite3.connect(db_path)
    contract_ids = [r[0] for r in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id")]
    texts = {cid: load_contract(Path(contracts_dir) / f"{cid}.txt") for cid in contract_ids}
    items, alignment = build_items(load_rows(csv_paths), texts)

    passages: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cid, s, e in conn.execute("SELECT contract_id, start_char, end_char FROM passages WHERE kind != 'toc'"):
        passages[cid].append((s, e))

    per_item = []
    latencies = []
    for item in items:
        t0 = time.perf_counter()
        hits = search(conn, item.query, contract_id=item.contract_id, k=K)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        n_relevant = sum(1 for s, e in passages[item.contract_id] if is_relevant(s, e, item.gold))
        per_item.append({
            "item_id": item.item_id,
            "contract_id": item.contract_id,
            "category": item.category,
            "split": split_of(item.contract_id),
            "recall@1": recall_at_k(hits, item.gold, 1),
            "recall@5": recall_at_k(hits, item.gold, 5),
            "recall@10": recall_at_k(hits, item.gold, 10),
            "mrr@10": mrr(hits, item.gold, K),
            "ndcg@10": ndcg_at_k(hits, item.gold, n_relevant, K),
        })
    if not per_item:
        raise ValueError("no scorable eval items: check that the index and the label CSVs describe the same contracts")

    latencies.sort()
    result = {
        "rung": "R1",
        "scope": "within-agreement",
        "alignment": alignment,
        "overall": _summarise(per_item, n_boot),
        "by_split": {
            split: _summarise([r for r in per_item if r["split"] == split], n_boot)
            for split in sorted({r["split"] for r in per_item})
        },
        "by_category": {
            cat: _summarise([r for r in per_item if r["category"] == cat], n_boot)
            for cat in sorted({r["category"] for r in per_item})
        },
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
    }
    out_dir = Path(out_dir)
    _write_json(out_dir / "alignment.json", alignment)
    _write_json(out_dir / "r1.json", result)
    return result
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -q`
Expected: all pass (73 tests)

- [ ] **Step 9: Commit**

```bash
git add evals/bootstrap.py evals/run_r1.py tests/test_bootstrap.py tests/test_run_r1.py
git commit -m "m1: contract-clustered bootstrap, tune/report split and the R1 eval run

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: CLI, facts, the real run and the M1 report

**Files:**
- Create: `pipeline/cli.py`, `facts/queries.py`, `facts/build.py`, `facts/report.py`
- Create (generated by commands, then committed): `facts.json`, `docs/m1/REPORT.md`
- Test: `tests/test_facts.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `facts.queries.QUERIES: dict[str, Callable[[sqlite3.Connection, dict], int | float]]` — each query takes the index connection and the loaded `r1.json` dict.
- Produces: `facts.build.build(db_path: Path, r1_path: Path) -> dict` and `facts.build.check(db_path: Path, r1_path: Path, facts_path: Path) -> list[str]` (names whose stored value differs; empty means in sync)
- Produces: `facts.report.render(facts: dict) -> str` (markdown; every number comes from `facts`)
- Produces: commands `dtd fetch`, `dtd build`, `dtd eval`, `dtd facts [--check]`, `dtd report`

- [ ] **Step 1: Write the failing facts test**

`tests/test_facts.py`:

```python
import json
import sqlite3

from facts.build import build, check
from facts.queries import QUERIES
from facts.report import render
from retrieval.index import build_index

R1 = {
    "alignment": {"rows": 10, "items": 6, "items_scored": 5, "items_no_gold": 1, "items_missing_contract": 0,
                  "pieces": 8, "pieces_exact": 5, "pieces_anchored": 2, "pieces_unaligned": 1},
    "overall": {m: {"mean": 0.123456, "lo": 0.1, "hi": 0.2, "n_items": 5, "n_clusters": 2}
                for m in ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")},
    "by_split": {"report": {m: {"mean": 0.5, "lo": 0.4, "hi": 0.6, "n_items": 3, "n_clusters": 1}
                            for m in ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")}},
    "latency_ms": {"p50": 1.23456, "p95": 4.56789},
}
DOC = "Section 1.1 Closing. “Closing Date” means the date of closing.\n\nSection 1.2 Merger. The merger occurs.\n"


def make(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_a": DOC, "contract_b": "no headings here at all"})
    r1 = tmp_path / "r1.json"
    r1.write_text(json.dumps(R1))
    return db, r1


def test_build_runs_every_named_query(tmp_path):
    db, r1 = make(tmp_path)
    facts = build(db, r1)
    assert set(facts) == set(QUERIES)
    assert facts["maud_contracts"] == 2
    assert facts["maud_terms"] == 1
    assert facts["eval_items_scored"] == 5
    assert facts["align_piece_rate"] == 0.875
    assert facts["r1_recall_at_5"] == 0.1235
    assert facts["r1_report_recall_at_5"] == 0.5
    assert 0 < facts["maud_passages_with_section_share"] < 1


def test_check_reports_stale_facts(tmp_path):
    db, r1 = make(tmp_path)
    path = tmp_path / "facts.json"
    facts = build(db, r1)
    path.write_text(json.dumps(facts))
    assert check(db, r1, path) == []
    facts["maud_contracts"] = 999
    path.write_text(json.dumps(facts))
    assert check(db, r1, path) == ["maud_contracts"]


def test_check_reports_a_missing_facts_file(tmp_path):
    db, r1 = make(tmp_path)
    assert check(db, r1, tmp_path / "absent.json") == sorted(QUERIES)


def test_report_prints_only_values_from_facts(tmp_path):
    db, r1 = make(tmp_path)
    facts = build(db, r1)
    text = render(facts)
    assert "machine" not in text.lower()
    assert "human-labelled (MAUD)" in text
    for name in ("maud_contracts", "r1_report_recall_at_5", "align_piece_rate"):
        assert str(facts[name]) in text


def test_committed_facts_file_has_exactly_the_named_queries():
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "facts.json"
    if path.exists():
        assert set(json.loads(path.read_text())) == set(QUERIES)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_facts.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'facts.build'`

- [ ] **Step 3: Implement facts**

`facts/queries.py`:

```python
import sqlite3
from typing import Callable


def _scalar(sql: str):
    return lambda conn, r1: conn.execute(sql).fetchone()[0]


def _metric(metric: str, field: str = "mean", split: str | None = None):
    def q(conn, r1):
        block = r1["by_split"][split] if split else r1["overall"]
        return round(block[metric][field], 4)
    return q


def _align_rate(conn, r1):
    a = r1["alignment"]
    return round((a["pieces_exact"] + a["pieces_anchored"]) / a["pieces"], 4)


def _section_share(conn, r1):
    total, with_id = conn.execute(
        "SELECT COUNT(*), SUM(section_id != '') FROM passages WHERE kind != 'toc'").fetchone()
    return round(with_id / total, 4)


QUERIES: dict[str, Callable[[sqlite3.Connection, dict], int | float]] = {
    "maud_contracts": _scalar("SELECT COUNT(*) FROM contracts"),
    "maud_chars": _scalar("SELECT SUM(n_chars) FROM contracts"),
    "maud_passages": _scalar("SELECT COUNT(*) FROM passages"),
    "maud_passages_indexed": _scalar("SELECT COUNT(*) FROM passages_fts"),
    "maud_passages_with_section_share": _section_share,
    "maud_terms": _scalar("SELECT COUNT(*) FROM terms"),
    "maud_label_rows_main": lambda conn, r1: r1["alignment"]["rows"],
    "eval_items": lambda conn, r1: r1["alignment"]["items"],
    "eval_items_scored": lambda conn, r1: r1["alignment"]["items_scored"],
    "eval_items_no_gold": lambda conn, r1: r1["alignment"]["items_no_gold"],
    "eval_items_missing_contract": lambda conn, r1: r1["alignment"]["items_missing_contract"],
    "align_pieces": lambda conn, r1: r1["alignment"]["pieces"],
    "align_piece_rate": _align_rate,
    "r1_recall_at_1": _metric("recall@1"),
    "r1_recall_at_5": _metric("recall@5"),
    "r1_recall_at_10": _metric("recall@10"),
    "r1_mrr_at_10": _metric("mrr@10"),
    "r1_ndcg_at_10": _metric("ndcg@10"),
    "r1_report_items": lambda conn, r1: r1["by_split"]["report"]["recall@5"]["n_items"],
    "r1_report_contracts": lambda conn, r1: r1["by_split"]["report"]["recall@5"]["n_clusters"],
    "r1_report_recall_at_1": _metric("recall@1", split="report"),
    "r1_report_recall_at_5": _metric("recall@5", split="report"),
    "r1_report_recall_at_5_lo": _metric("recall@5", "lo", split="report"),
    "r1_report_recall_at_5_hi": _metric("recall@5", "hi", split="report"),
    "r1_report_recall_at_10": _metric("recall@10", split="report"),
    "r1_report_mrr_at_10": _metric("mrr@10", split="report"),
    "r1_report_ndcg_at_10": _metric("ndcg@10", split="report"),
    "r1_latency_ms_p50": lambda conn, r1: round(r1["latency_ms"]["p50"], 2),
    "r1_latency_ms_p95": lambda conn, r1: round(r1["latency_ms"]["p95"], 2),
}
```

`facts/build.py`:

```python
import json
import sqlite3
from pathlib import Path

from facts.queries import QUERIES

# Wall-clock measurements differ between runs, so --check does not compare them.
UNSTABLE = {"r1_latency_ms_p50", "r1_latency_ms_p95"}


def build(db_path: Path, r1_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    r1 = json.loads(Path(r1_path).read_text(encoding="utf-8"))
    return {name: QUERIES[name](conn, r1) for name in sorted(QUERIES)}


def check(db_path: Path, r1_path: Path, facts_path: Path) -> list[str]:
    facts_path = Path(facts_path)
    if not facts_path.exists():
        return sorted(QUERIES)
    stored = json.loads(facts_path.read_text(encoding="utf-8"))
    fresh = build(db_path, r1_path)
    return sorted(n for n in fresh if n not in UNSTABLE and stored.get(n) != fresh[n])
```

`facts/report.py`:

```python
def render(f: dict) -> str:
    return f"""# M1 report: BM25 baseline on MAUD

Generated by `dtd report` from `facts.json`. Do not edit by hand.

## Corpus

| Fact | Value |
|---|---|
| Agreements | {f['maud_contracts']} |
| Characters | {f['maud_chars']} |
| Passages | {f['maud_passages']} |
| Passages indexed (table-of-contents chunks excluded) | {f['maud_passages_indexed']} |
| Share of indexed passages carrying a section id | {f['maud_passages_with_section_share']} |
| Defined terms found | {f['maud_terms']} |

## Eval set: human-labelled (MAUD)

| Fact | Value |
|---|---|
| Label rows (`main`) | {f['maud_label_rows_main']} |
| Eval items (agreement x deal point) | {f['eval_items']} |
| Items scored | {f['eval_items_scored']} |
| Items dropped: no excerpt piece could be aligned | {f['eval_items_no_gold']} |
| Items dropped: agreement file missing | {f['eval_items_missing_contract']} |
| Excerpt pieces | {f['align_pieces']} |
| Share of pieces aligned to a character span | {f['align_piece_rate']} |

## Rung R1: BM25, retrieval within the agreement

Queries are MAUD's deal-point and question names, verbatim. Headline numbers are on the report
split ({f['r1_report_contracts']} agreements, {f['r1_report_items']} items); the tune split is
held back for choosing settings in later rungs. Intervals are 95%, bootstrapped over agreements.

| Metric | Report split | All agreements |
|---|---|---|
| recall@1 | {f['r1_report_recall_at_1']} | {f['r1_recall_at_1']} |
| recall@5 | {f['r1_report_recall_at_5']} ({f['r1_report_recall_at_5_lo']} to {f['r1_report_recall_at_5_hi']}) | {f['r1_recall_at_5']} |
| recall@10 | {f['r1_report_recall_at_10']} | {f['r1_recall_at_10']} |
| MRR@10 | {f['r1_report_mrr_at_10']} | {f['r1_mrr_at_10']} |
| nDCG@10 | {f['r1_report_ndcg_at_10']} | {f['r1_ndcg_at_10']} |

Latency per query: p50 {f['r1_latency_ms_p50']} ms, p95 {f['r1_latency_ms_p95']} ms.
"""
```

- [ ] **Step 4: Run the facts test**

Run: `uv run pytest tests/test_facts.py -q`
Expected: 5 passed

- [ ] **Step 5: Write the failing CLI test**

`tests/test_cli.py`:

```python
import json

import pytest

from pipeline import cli

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
DOC = (
    "Section 1.1 Closing. The closing shall occur at the offices of counsel on the Closing Date.\n\n"
    "Section 2.6 Type of Consideration. Each Company Share shall be converted into the right to receive cash.\n"
)


@pytest.fixture
def data(tmp_path, monkeypatch):
    raw = tmp_path / "raw" / "maud"
    (raw / "contracts").mkdir(parents=True)
    for i in range(3):
        (raw / "contracts" / f"contract_{i}.txt").write_text(DOC, encoding="utf-8")
    body = "".join(
        f'main,contract_{i},"{DOC.split(chr(10) * 2)[1].strip()} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,{i},General Information\n'
        for i in range(3))
    (raw / "MAUD_dev.csv").write_text(HEADER + body, encoding="utf-8")
    monkeypatch.setattr(cli, "RAW", raw)
    monkeypatch.setattr(cli, "INDEX", tmp_path / "index" / "maud.db")
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "FACTS", tmp_path / "facts.json")
    monkeypatch.setattr(cli, "REPORT", tmp_path / "docs" / "REPORT.md")
    monkeypatch.setattr(cli, "CSV_NAMES", ("MAUD_dev.csv",))
    return tmp_path


def test_build_eval_facts_report_chain(data, capsys):
    assert cli.entry(["build"]) == 0
    assert cli.entry(["eval"]) == 0
    assert cli.entry(["facts"]) == 0
    assert cli.entry(["facts", "--check"]) == 0
    assert cli.entry(["report"]) == 0
    facts = json.loads((data / "facts.json").read_text())
    assert facts["maud_contracts"] == 3 and facts["eval_items_scored"] == 3
    assert str(facts["maud_contracts"]) in (data / "docs" / "REPORT.md").read_text()


def test_facts_check_fails_when_facts_are_stale(data):
    cli.entry(["build"]); cli.entry(["eval"]); cli.entry(["facts"])
    stale = json.loads((data / "facts.json").read_text())
    stale["maud_contracts"] = 0
    (data / "facts.json").write_text(json.dumps(stale))
    assert cli.entry(["facts", "--check"]) == 1


def test_build_without_fetched_contracts_fails_clearly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RAW", tmp_path / "nothing")
    monkeypatch.setattr(cli, "INDEX", tmp_path / "maud.db")
    assert cli.entry(["build"]) == 2
    assert "dtd fetch" in capsys.readouterr().err
```

- [ ] **Step 6: Run it to verify it fails**

Run: `uv run pytest tests/test_cli.py -q`
Expected: FAIL with `ImportError: cannot import name 'cli' from 'pipeline'`

- [ ] **Step 7: Implement the CLI**

`pipeline/cli.py`:

```python
import argparse
import json
import sys
from pathlib import Path

from evals.run_r1 import run as run_r1
from facts.build import build as build_facts
from facts.build import check as check_facts
from facts.report import render
from pipeline.fetch_maud import fetch_all
from pipeline.normalise import load_contract
from pipeline.paths import CSV_NAMES, INDEX, OUT, RAW
from retrieval.index import build_index

FACTS = Path("facts.json")
REPORT = Path("docs/m1/REPORT.md")


def _csv_paths() -> list[Path]:
    return [RAW / n for n in CSV_NAMES if (RAW / n).exists()]


def _cmd_fetch(args) -> int:
    print(json.dumps(fetch_all(RAW)))
    return 0


def _cmd_build(args) -> int:
    files = sorted((RAW / "contracts").glob("*.txt")) if (RAW / "contracts").exists() else []
    if not files:
        print(f"no contracts under {RAW / 'contracts'}; run `dtd fetch` first", file=sys.stderr)
        return 2
    print(json.dumps(build_index(INDEX, {p.stem: load_contract(p) for p in files})))
    return 0


def _cmd_eval(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    result = run_r1(INDEX, _csv_paths(), RAW / "contracts", OUT)
    print(json.dumps(result["overall"], indent=2))
    return 0


def _cmd_facts(args) -> int:
    r1 = OUT / "r1.json"
    if not INDEX.exists() or not r1.exists():
        print("index or r1.json missing; run `dtd build` then `dtd eval` first", file=sys.stderr)
        return 2
    if args.check:
        stale = check_facts(INDEX, r1, FACTS)
        if stale:
            print("stale facts: " + ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    FACTS.write_text(json.dumps(build_facts(INDEX, r1), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _cmd_report(args) -> int:
    if not FACTS.exists():
        print("facts.json missing; run `dtd facts` first", file=sys.stderr)
        return 2
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(json.loads(FACTS.read_text(encoding="utf-8"))), encoding="utf-8")
    return 0


def entry(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dtd")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(fn=_cmd_fetch)
    sub.add_parser("build").set_defaults(fn=_cmd_build)
    sub.add_parser("eval").set_defaults(fn=_cmd_eval)
    facts = sub.add_parser("facts")
    facts.add_argument("--check", action="store_true")
    facts.set_defaults(fn=_cmd_facts)
    sub.add_parser("report").set_defaults(fn=_cmd_report)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(entry())
```

- [ ] **Step 8: Run all tests**

Run: `uv run pytest -q`
Expected: all pass (81 tests)

- [ ] **Step 9: Commit the code**

```bash
git add pipeline/cli.py facts tests/test_facts.py tests/test_cli.py
git commit -m "m1: dtd CLI, named-query facts and the generated M1 report

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 10: Fetch MAUD for real**

Run: `uv run dtd fetch`
Expected: `{"ok": 103, "missing": 52}` (3 CSVs plus 100 contract files; 52 contracts named in the CSVs have no file at this revision). About 160 MB lands under `data/raw/maud/`, which is git-ignored. If the counts differ, report them to Michael with the names (`grep missing data/raw/maud/ledger.jsonl`); it does not block the run.

- [ ] **Step 11: Prove the fetch resumes after a kill**

```bash
rm data/raw/maud/contracts/contract_10.txt data/raw/maud/contracts/contract_13.txt
uv run dtd fetch & sleep 1; kill -9 $!
ls data/raw/maud/contracts/*.part 2>/dev/null; uv run dtd fetch
ls data/raw/maud/contracts/contract_10.txt data/raw/maud/contracts/contract_13.txt
```

Expected: the second `dtd fetch` prints the same `ok` count as Step 10, and both files exist. If the kill landed before either file started, that is still a pass; the point is that the rerun completes and re-downloads only what is absent.

- [ ] **Step 12: Build, evaluate, write facts and the report**

```bash
uv run dtd build && uv run dtd eval && uv run dtd facts && uv run dtd facts --check && uv run dtd report
cat docs/m1/REPORT.md
```

Expected: `dtd build` prints counts with `contracts` equal to the number of contract files; `dtd facts --check` exits 0; the report renders with every cell filled.

- [ ] **Step 13: Sanity-check the numbers before committing them**

Read `facts.json` and stop to report to Michael, without committing, if any of these hold:
- `align_piece_rate` is below 0.85 (the prototype reached 0.97 on 6 contracts; a much lower rate means the aligner is mis-handling a format it did not see).
- `maud_contracts` is below 100 (files that fetched in the dry run are now missing).
- `maud_passages_with_section_share` is below 0.6 (the segmenter is missing headings in many agreements).
- `r1_report_recall_at_10` is exactly 0 or exactly 1 (a wiring error, not a result).

Otherwise the numbers stand as measured, whatever they are. A low BM25 score is a valid baseline.

- [ ] **Step 14: Commit the measured facts and report**

```bash
git add facts.json docs/m1/REPORT.md
git commit -m "m1: first measured numbers, BM25 on MAUD against lawyers' excerpts

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

## What M1 deliberately leaves for later plans

- Dense, hybrid, reranking, query rewriting, defined-term expansion and the chunking comparison (M2). Failure classification and paired rung comparisons start there, since they need more than one rung.
- Answer accuracy against MAUD's answer labels (M4; `LabelRow.answer` is loaded now so the data path exists).
- Anything that touches EDGAR (M0, M3).
- Comparison against LegalBench-RAG's published MAUD baselines (M2, once there is a rung worth comparing).

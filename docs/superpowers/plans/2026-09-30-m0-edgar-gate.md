# M0: The EDGAR Gate — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure, with one slow polite process, whether EDGAR holds enough technology-target merger agreements for the tech half of Deal Terms Desk, and write the M0 report whose numbers gate M3 (PRD §9).

**Architecture:** One module, `pipeline/sec_client.py`, is the only code that talks to sec.gov. It enforces the access rules: one process (file lock), at most 2 requests per second, a persistent response cache so a rerun fetches nothing twice, a User-Agent built from `SEC_CONTACT`, and on a 403 or 429 it stops and refuses all requests for an hour. The stages are search, candidates, fetch and measure. Each reads the previous stage's output file and writes its own atomically, so a kill loses at most one response. A measure stage turns the fetched agreements into counts, a facts builder names them, and a generated report states the gate.

**Tech Stack:** Python 3.12, `uv`, `pytest`, standard library only (`urllib`, `html.parser`, `fcntl`, `gzip`, `json`, `re`), `claude -p` for one quote-gated model pass on a sample of 30.

**Spec:** `docs/PRD.md` (milestone M0 of §9; selection rule and access rules in §2.2; §5.2 break-up fee cross-check; §10 fallback).

## Global Constraints

- **sec.gov access rules (hard):** one process, never parallel; at most 2 requests per second; a persistent ledger so a rerun fetches nothing twice; the User-Agent carries `SEC_CONTACT`; on a 403 the fetcher stops and waits, and does not retry or change identity. Never fan agents out against sec.gov. No subagent, test or CI job makes a real request to sec.gov: tests use recorded fixtures and an injected opener.
- `SEC_CONTACT` is read from the environment or the gitignored `.env`. It is never written to the repo, to a cache file, to a ledger, to a log line or to an output file.
- Only these hosts are ever requested: `www.sec.gov`, `efts.sec.gov`, `data.sec.gov`.
- The repo ships accession numbers and the fetch script, not EDGAR documents. Everything fetched lives under `data/` (gitignored).
- Every number the report prints comes from `facts.json`, produced by a named query in `facts/`. No digit is hard-coded in report copy. Model-built numbers carry "machine-built".
- Every stage is idempotent and resumable. Resume is tested by killing the real run (Task 8), not by reasoning.
- The README and the launch post are written by Michael by hand; never create or edit `README.md`.
- Commits end with these two trailer lines:
  `Assisted-by: Claude`
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`
- Python `>=3.12,<3.13`.

## What is known before M0 runs

Nothing about the tech half has been measured (PRD §2.2). sec.gov blocked the development machine for 40+ minutes on 2026-09-30 after parallel agents hit it. This plan was written without any request to sec.gov, so the response shapes below come from public knowledge of EDGAR's endpoints, not from a probe. **Task 2 is a probe:** four requests (a search page, a submissions JSON, an exhibit and its filing index), recorded as test fixtures. Every later task codes against those recorded fixtures. If a recorded shape differs from what this plan assumes, the implementer adapts the parser to the fixture and says so.

Assumed shapes (to be confirmed by Task 2):
- **Full-text search:** `https://efts.sec.gov/LATEST/search-index?q="agreement and plan of merger"&forms=8-K&dateRange=custom&startdt=YYYY-MM-DD&enddt=YYYY-MM-DD&from=N`. JSON `hits.total.value` and `hits.total.relation` (`"gte"` at the 10,000 cap), and `hits.hits[]` with `_id` = `"<accession>:<filename>"` and `_source` with `ciks`, `display_names`, `file_type`, `file_date`, `form`, `adsh`, `sics`. Pages of 100.
- **Submissions:** `https://data.sec.gov/submissions/CIK##########.json` with `name`, `sic`, `sicDescription`.
- **Archive document:** `https://www.sec.gov/Archives/edgar/data/<cik>/<accession without dashes>/<filename>`, and the filing index `…/<accession>-index.htm` listing each document's type.

## Dry run (2026-09-30)

The code blocks of Tasks 1 and 3–7 (except the CLI wiring) were extracted into a scratch project and run against their own tests, with no network: 53 pass. Three plan bugs were found and fixed that way: the party-name pattern swallowed preamble prose, the fake EDGAR routed the press release wrongly, and the fake served plain text as HTML. Nothing about sec.gov's real responses is verified until Task 2.

## The gate (PRD §9)

The gate **passes** when both hold:
1. At least 100 tech agreements: canonical (one per deal), not amendments, signed on or after 2015-01-01, with a target resolved to an EDGAR registrant whose SIC is in 3570–3579, 3661–3679 or 7370–7379.
2. Each lead family (employee equity awards, termination fee, earn-out or other contingent consideration) is present in at least half of a seeded random sample of 30 of those agreements, by the quote-gated machine pass.

If it fails, PRD §10's fallback applies before M3 is planned: index whatever tech deals exist, lead the demo with the most recognisable, and drop the startup framing. The report states which condition failed, and the facts carry `m0_gate_pass`.

## Review Focus

1. **A 403 or 429 in the middle of a stage.** The process must stop at once, with no further request and no retry. A rerun within the hour must refuse without touching the network, and the cache written so far must survive. (Test in Task 2; real behaviour observed in Task 8.)
2. **A second M0 process started while one runs.** It must refuse before any request. (Test in Task 2.)
3. **A search window over the 10,000-result cap.** It must be split until every window is under the cap. It must never silently truncate. (Test in Task 3.)
4. **An agreement whose preamble names no "Company", or names one that matches no filer.** It must be counted as unresolved, never guessed or dropped silently. (Test in Task 5.)
5. **`SEC_CONTACT` unset, or the contact appearing in any written file.** The first must refuse to start. The second must never happen, and a test scans every file the stages write. (Test in Task 2.)

## File Structure

| File | Responsibility |
|---|---|
| `pipeline/env.py` | Read `SEC_CONTACT` from the environment or `.env` |
| `pipeline/sec_client.py` | The only sec.gov client: lock, rate limit, cache, block handling |
| `pipeline/edgar_search.py` | Full-text search windows, splitting at the cap, paging |
| `pipeline/html_text.py` | HTML or plain-text exhibit → canonical text |
| `pipeline/target.py` | Preamble → parties, signing date, amendment flag; name → CIK |
| `pipeline/m0.py` | The stages: search, candidates, fetch, measure; `dtd m0 …` |
| `pipeline/claude.py` | `claude -p` runner (shared with M2; created here if M2 is not merged yet) |
| `facts/m0.py`, `facts/report_m0.py` | M0 named facts; `docs/m0/REPORT.md` |
| `tests/fixtures/sec/` | The four recorded probe responses, trimmed |
| `tests/conftest.py` | An autouse guard: any real request to a sec.gov host in tests fails |

Branch: `m0`, cut from `main` when execution starts. If M2 has merged by then, `pipeline/claude.py` and the generalised `Ledger(key=...)` already exist, so reuse them. If not, Task 2 adds `Ledger(key=...)` exactly as M2's Task 8 specifies, and Task 6 adds `pipeline/claude.py` as M2's Task 7 specifies, so the two branches merge cleanly.

---
## When each task runs

Tasks 1 and 3–7 make no request to sec.gov. Their tests use synthetic fixtures shaped like the assumed responses, so they can be built at any time, through subagents as usual. **Task 2 (the probe) and Task 8 (the real run) wait until Michael says sec.gov has unblocked this machine.** The controller runs them itself, as one process, never a subagent. After the probe, the controller compares the recorded fixtures with the assumed shapes. Any parser that disagrees is fixed through a normal fix dispatch before Task 8.

---

### Task 1: The contact and the only sec.gov client

**Files:**
- Create: `pipeline/env.py`, `pipeline/sec_client.py`, `tests/conftest.py`
- Modify: `pipeline/ledger.py` (only if M2's `key` parameter is not on this branch yet; apply M2 Task 8's change verbatim)
- Test: `tests/test_env.py`, `tests/test_sec_client.py`

**Interfaces:**
- Produces: `pipeline.env.sec_contact(env_file: Path = Path(".env")) -> str`. It reads `SEC_CONTACT` from the environment first, then from `.env`, and raises `RuntimeError` if the value has no `@`. Its return value is never logged or written.
- Produces: `pipeline.sec_client.HOSTS`, `MIN_INTERVAL = 0.5`, `COOLDOWN_S = 3600`, `STOP_CODES = {403, 429}`, the exception `Blocked(RuntimeError)`, and `SecClient(root: Path, contact: str, opener=None, clock=time.monotonic, wall=time.time, sleep=time.sleep)` with `.get(url) -> bytes | None` (None for a 404), `.get_json(url) -> dict | None`, `.requests: int` (network requests made by this instance) and `.close()`.
- `root` is `data/sec`. Responses are cached at `root/cache/<sha1(url)>` and the ledger is at `root/ledger.jsonl`. The block marker `root/blocked.json` holds only time, status and URL, and the lock is `root/.lock`.

What it enforces:
1. **One process.** An exclusive non-blocking `flock` on `root/.lock`. A second client in any process raises before any request.
2. **At most 2 per second.** At least `MIN_INTERVAL` between the starts of consecutive network requests. Cache hits do not wait and are not counted.
3. **Nothing fetched twice.** A URL in the ledger with its cached file is served from disk. A recorded 404 is not asked again.
4. **Stop on refusal.** On a 403 or 429 it writes the marker and raises `Blocked`. Any later `get` that needs the network within `COOLDOWN_S` of the marker raises `Blocked` without a request. There is no retry, and no change of identity.
5. **Allowed hosts only.** Any other host raises `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/conftest.py`:

```python
import urllib.request
from urllib.parse import urlparse

import pytest

SEC_HOSTS = {"www.sec.gov", "efts.sec.gov", "data.sec.gov"}


@pytest.fixture(autouse=True)
def no_real_sec_requests(monkeypatch):
    """No test may reach sec.gov: the access rules forbid it and CI would hammer it."""
    real = urllib.request.urlopen

    def guarded(req, *args, **kwargs):
        url = req.full_url if hasattr(req, "full_url") else req
        if urlparse(url).hostname in SEC_HOSTS:
            raise AssertionError(f"test tried to reach sec.gov: {url}")
        return real(req, *args, **kwargs)
    monkeypatch.setattr(urllib.request, "urlopen", guarded)
```

`tests/test_env.py`:

```python
import pytest

from pipeline.env import sec_contact


def test_contact_comes_from_the_environment_first(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("SEC_CONTACT=file@example.com\n")
    monkeypatch.setenv("SEC_CONTACT", "env@example.com")
    assert sec_contact(tmp_path / ".env") == "env@example.com"


def test_contact_falls_back_to_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    (tmp_path / ".env").write_text('# comment\nOTHER=x\nSEC_CONTACT="file@example.com"\n')
    assert sec_contact(tmp_path / ".env") == "file@example.com"


def test_missing_contact_refuses(tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    with pytest.raises(RuntimeError, match="SEC_CONTACT"):
        sec_contact(tmp_path / ".env")
```

`tests/test_sec_client.py`:

```python
import json
import urllib.error

import pytest

from pipeline.sec_client import COOLDOWN_S, MIN_INTERVAL, Blocked, SecClient

CONTACT = "tester@example.com"


class Resp:
    def __init__(self, body: bytes):
        self.body = body
        self.headers = {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


class Net:
    """A fake opener; `script` maps URL to a body or an HTTP status."""

    def __init__(self, script):
        self.script = script
        self.seen = []

    def __call__(self, req, timeout=None):
        self.seen.append((req.full_url, req.get_header("User-agent")))
        out = self.script[req.full_url]
        if isinstance(out, int):
            raise urllib.error.HTTPError(req.full_url, out, "x", {}, None)
        return Resp(out)


class Clock:
    def __init__(self):
        self.t = 1000.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.slept.append(s)
        self.t += s


def client(tmp_path, net, clock=None):
    clock = clock or Clock()
    return SecClient(tmp_path / "sec", CONTACT, opener=net, clock=clock.now, wall=clock.now, sleep=clock.sleep), clock


A = "https://www.sec.gov/a"
B = "https://www.sec.gov/b"


def test_requests_are_spaced_and_carry_the_contact(tmp_path):
    net = Net({A: b"a", B: b"b"})
    c, clock = client(tmp_path, net)
    assert c.get(A) == b"a" and c.get(B) == b"b"
    assert clock.slept == [MIN_INTERVAL]
    assert all(CONTACT in ua for _, ua in net.seen)


def test_cached_responses_are_never_fetched_again(tmp_path):
    net = Net({A: b"a"})
    c, _ = client(tmp_path, net)
    c.get(A)
    c.close()
    c2, clock = client(tmp_path, net)
    assert c2.get(A) == b"a"
    assert len(net.seen) == 1 and c2.requests == 0 and clock.slept == []


def test_a_404_is_recorded_and_not_asked_again(tmp_path):
    net = Net({A: 404})
    c, _ = client(tmp_path, net)
    assert c.get(A) is None and c.get(A) is None
    assert len(net.seen) == 1


@pytest.mark.parametrize("code", [403, 429])
def test_refusal_stops_and_blocks_further_requests(tmp_path, code):
    net = Net({A: code, B: b"b"})
    c, clock = client(tmp_path, net)
    with pytest.raises(Blocked):
        c.get(A)
    with pytest.raises(Blocked):
        c.get(B)
    assert [u for u, _ in net.seen] == [A]
    marker = json.loads((tmp_path / "sec" / "blocked.json").read_text())
    assert marker["status"] == code and CONTACT not in json.dumps(marker)
    clock.t += COOLDOWN_S + 1
    assert c.get(B) == b"b"


def test_a_second_client_is_refused_while_one_is_open(tmp_path):
    c, _ = client(tmp_path, Net({}))
    with pytest.raises(RuntimeError, match="one process"):
        client(tmp_path, Net({}))
    c.close()
    client(tmp_path, Net({}))[0].close()


def test_other_hosts_are_refused(tmp_path):
    c, _ = client(tmp_path, Net({}))
    with pytest.raises(ValueError, match="host"):
        c.get("https://example.com/x")


def test_the_contact_is_never_written_to_disk(tmp_path):
    net = Net({A: b"a", B: 404})
    c, _ = client(tmp_path, net)
    c.get(A)
    c.get(B)
    for p in (tmp_path / "sec").rglob("*"):
        if p.is_file():
            assert CONTACT.encode() not in p.read_bytes(), p


def test_the_guard_stops_a_real_request(tmp_path):
    c = SecClient(tmp_path / "sec", CONTACT)
    with pytest.raises(AssertionError, match="sec.gov"):
        c.get(A)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_env.py tests/test_sec_client.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.env'`

- [ ] **Step 3: Implement**

`pipeline/env.py`:

```python
import os
from pathlib import Path


def sec_contact(env_file: Path = Path(".env")) -> str:
    value = os.environ.get("SEC_CONTACT", "").strip()
    if not value and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == "SEC_CONTACT":
                value = val.strip().strip('"').strip("'")
    if "@" not in value:
        raise RuntimeError("SEC_CONTACT is not set: export it, or put SEC_CONTACT=<email> in the gitignored .env")
    return value
```

`pipeline/sec_client.py`:

```python
import fcntl
import gzip
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

from pipeline.ledger import Ledger

HOSTS = {"www.sec.gov", "efts.sec.gov", "data.sec.gov"}
MIN_INTERVAL = 0.5
COOLDOWN_S = 3600
STOP_CODES = {403, 429}


class Blocked(RuntimeError):
    pass


class SecClient:
    """The only code that talks to sec.gov. One process, at most 2 requests per second, nothing twice,
    and a full stop on a refusal."""

    def __init__(self, root: Path, contact: str, opener=None, clock=time.monotonic, wall=time.time,
                 sleep=time.sleep):
        self.root = Path(root)
        (self.root / "cache").mkdir(parents=True, exist_ok=True)
        self._lock = open(self.root / ".lock", "w")
        try:
            fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._lock.close()
            raise RuntimeError("another sec.gov client holds data/sec/.lock; M0 runs as one process")
        self.ledger = Ledger(self.root / "ledger.jsonl")
        self._ua = f"deal-terms-desk/0.1 {contact}"
        self._opener = opener or urllib.request.urlopen
        self._clock, self._wall, self._sleep = clock, wall, sleep
        self._last: float | None = None
        self.requests = 0

    def close(self) -> None:
        fcntl.flock(self._lock, fcntl.LOCK_UN)
        self._lock.close()

    def _cached(self, url: str) -> Path:
        return self.root / "cache" / hashlib.sha1(url.encode("utf-8")).hexdigest()

    def _refuse_if_blocked(self) -> None:
        marker = self.root / "blocked.json"
        if marker.exists():
            age = self._wall() - json.loads(marker.read_text(encoding="utf-8"))["at"]
            if age < COOLDOWN_S:
                raise Blocked(f"sec.gov refused a request {int(age)} s ago; waiting out the {COOLDOWN_S} s cooldown")

    def get(self, url: str) -> bytes | None:
        if urlparse(url).hostname not in HOSTS:
            raise ValueError(f"host not allowed: {url}")
        rec = self.ledger.get(url)
        if rec and rec["status"] == "missing":
            return None
        path = self._cached(url)
        if rec and path.exists():
            return path.read_bytes()
        self._refuse_if_blocked()
        if self._last is not None:
            wait = self._last + MIN_INTERVAL - self._clock()
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        self.requests += 1
        req = urllib.request.Request(url, headers={"User-Agent": self._ua, "Accept-Encoding": "gzip"})
        try:
            with self._opener(req, timeout=60) as resp:
                body = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
        except urllib.error.HTTPError as e:
            if e.code in STOP_CODES:
                (self.root / "blocked.json").write_text(
                    json.dumps({"at": self._wall(), "status": e.code, "url": url}), encoding="utf-8")
                raise Blocked(f"sec.gov answered {e.code} for {url}; stopped, no retry") from e
            if e.code == 404:
                self.ledger.put({"url": url, "status": "missing"})
                return None
            raise
        part = path.with_name(path.name + ".part")
        part.write_bytes(body)
        os.replace(part, path)
        self.ledger.put({"url": url, "status": "ok", "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()})
        return body

    def get_json(self, url: str) -> dict | None:
        body = self.get(url)
        return None if body is None else json.loads(body)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. The guard must not break M1's fetch tests, which inject their own opener.

- [ ] **Step 5: Commit**

```bash
git add pipeline/env.py pipeline/sec_client.py tests/conftest.py tests/test_env.py tests/test_sec_client.py
git commit -m "m0: the only sec.gov client: one process, 2 per second, cached, stops on a refusal

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The probe (controller only, after the SEC unblocks)

**Files:**
- Create: `tests/fixtures/sec/fts.json`, `tests/fixtures/sec/submissions.json`, `tests/fixtures/sec/ex21.htm`, `tests/fixtures/sec/index.htm`
- Create: `pipeline/m0_probe.py`

**Interfaces:**
- Produces: `uv run python -m pipeline.m0_probe`. It makes exactly four requests through `SecClient`: one full-text search page for January 2016, the submissions JSON of the filer of its first EX-2.1 hit, that EX-2.1 document, and its filing index. It writes trimmed copies to `tests/fixtures/sec/`: the search JSON with only its first five hits, the submissions JSON with only `cik`, `name`, `sic` and `sicDescription`, and the first 40,000 characters of the document and of the index.

The probe exists so that every later parser can be checked against what sec.gov actually returns, at the cost of four requests.

- [ ] **Step 1: Preconditions**

Michael has confirmed that sec.gov loads in his browser from this machine, `uv run python -c "from pipeline.env import sec_contact; sec_contact(); print('ok')"` prints `ok`, and no `data/sec/blocked.json` younger than an hour exists.

- [ ] **Step 2: Write the probe**

`pipeline/m0_probe.py`:

```python
import json
from pathlib import Path

from pipeline.edgar_search import doc_url, index_url, is_ex21, row, search_url
from pipeline.env import sec_contact
from pipeline.sec_client import SecClient
from datetime import date

FIX = Path("tests/fixtures/sec")


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    c = SecClient(Path("data/sec"), sec_contact())
    try:
        page = c.get_json(search_url(date(2016, 1, 1), date(2016, 1, 31), 0))
        hits = page["hits"]["hits"]
        first = next(row(h) for h in hits if is_ex21(h["_source"].get("file_type", "")))
        cik = int(first["ciks"][0])
        sub = c.get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
        doc = c.get(doc_url(first))
        idx = c.get(index_url(first))
        trimmed = {**page, "hits": {**page["hits"], "hits": hits[:5]}}
        (FIX / "fts.json").write_text(json.dumps(trimmed, indent=1), encoding="utf-8")
        (FIX / "submissions.json").write_text(
            json.dumps({k: sub.get(k) for k in ("cik", "name", "sic", "sicDescription")}, indent=1), encoding="utf-8")
        (FIX / "ex21.htm").write_bytes(doc[:40000])
        (FIX / "index.htm").write_bytes(idx[:40000])
        print(json.dumps({"requests": c.requests, "total": page["hits"]["total"], "first": first["adsh"]}))
    finally:
        c.close()


if __name__ == "__main__":
    main()
```

(It imports from Task 3. If Task 3 has not been built when the SEC unblocks, build Task 3 first.)

- [ ] **Step 3: Run it once**

Run: `uv run python -m pipeline.m0_probe`
Expected: `requests` is 4. If it raises `Blocked`, stop and tell Michael. Do not rerun within the hour.

- [ ] **Step 4: Compare the shapes**

Open the four fixtures. Check each assumption listed under "What is known before M0 runs": the field names in `_source`, the `total.relation` value, the page size, `_id`'s form, the submissions fields, and whether the index page lists document types. Write the differences into the ledger. For each parser that disagrees, dispatch a fix against its task, whose tests then use the real fixture.

- [ ] **Step 5: Commit**

Check that `grep -r "$(uv run python -c 'from pipeline.env import sec_contact; print(sec_contact())')" tests/fixtures/sec` prints nothing. Then:

```bash
git add tests/fixtures/sec pipeline/m0_probe.py
git commit -m "m0: probe, four recorded sec.gov responses as fixtures

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Full-text search, windowed under the cap

**Files:**
- Create: `pipeline/edgar_search.py`
- Test: `tests/test_edgar_search.py`

**Interfaces:**
- Produces: `FTS`, `PHRASE = '"agreement and plan of merger"'`, `PAGE = 100`, `CAP = 10000`, `START = date(2015, 1, 1)`.
- Produces: `search_url(start: date, end: date, offset: int) -> str`, `months(start: date, end: date) -> list[tuple[date, date]]`, `row(hit: dict) -> dict` (keys `adsh, filename, file_type, file_date, form, ciks, names, sics`), `is_ex21(file_type: str) -> bool`, `doc_url(r: dict) -> str`, `index_url(r: dict) -> str`.
- Produces: `search_window(client, start: date, end: date) -> list[dict]`. Every row of the window. A window whose total is at the cap, or whose relation is not `"eq"`, is split in half and both halves are searched. A single day over the cap raises `ValueError` rather than truncating.

- [ ] **Step 1: Write the failing tests**

`tests/test_edgar_search.py`:

```python
from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from pipeline.edgar_search import (CAP, PAGE, doc_url, index_url, is_ex21, months, row, search_url,
                                   search_window)


def hit(i, file_type="EX-2.1"):
    return {"_id": f"0001193125-16-{i:06d}:d{i}dex21.htm",
            "_source": {"ciks": ["0000012345"], "display_names": ["Acme Software Inc  (ACME)  (CIK 0000012345)"],
                        "file_type": file_type, "file_date": "2016-01-05", "form": "8-K",
                        "adsh": f"0001193125-16-{i:06d}", "sics": ["7372"]}}


class FakeClient:
    """Serves search pages from a function of (start, end) -> total hits in that window."""

    def __init__(self, total_of):
        self.total_of = total_of
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        start, end, offset = date.fromisoformat(q["startdt"]), date.fromisoformat(q["enddt"]), int(q["from"])
        total = self.total_of(start, end)
        relation = "gte" if total >= CAP else "eq"
        n = min(PAGE, max(0, min(total, CAP) - offset))
        base = (start.toordinal() % 1000) * 100000
        return {"hits": {"total": {"value": min(total, CAP), "relation": relation},
                         "hits": [hit(base + offset + i) for i in range(n)]}}


def test_search_url_carries_phrase_form_window_and_offset():
    q = parse_qs(urlparse(search_url(date(2016, 1, 1), date(2016, 1, 31), 200)).query)
    assert q["q"] == ['"agreement and plan of merger"'] and q["forms"] == ["8-K"]
    assert q["startdt"] == ["2016-01-01"] and q["enddt"] == ["2016-01-31"] and q["from"] == ["200"]


def test_months_cover_the_range_without_gaps():
    ms = months(date(2015, 1, 1), date(2015, 3, 10))
    assert ms == [(date(2015, 1, 1), date(2015, 1, 31)), (date(2015, 2, 1), date(2015, 2, 28)),
                  (date(2015, 3, 1), date(2015, 3, 10))]


def test_a_window_is_paged_to_its_total():
    c = FakeClient(lambda s, e: 250)
    rows = search_window(c, date(2016, 1, 1), date(2016, 1, 31))
    assert len(rows) == 250 and len(c.urls) == 3


def test_a_window_at_the_cap_is_split_until_each_part_is_under_it():
    c = FakeClient(lambda s, e: 30 * ((e - s).days + 1) * (500 if (e - s).days > 20 else 1))
    rows = search_window(c, date(2016, 1, 1), date(2016, 1, 31))
    assert len(rows) == 30 * 31
    assert len(c.urls) > 1  # the month was split, not read as one capped window


def test_a_single_day_over_the_cap_raises_instead_of_truncating():
    with pytest.raises(ValueError, match="cap"):
        search_window(FakeClient(lambda s, e: CAP), date(2016, 1, 1), date(2016, 1, 1))


def test_row_and_urls():
    r = row(hit(7))
    assert r["adsh"] == "0001193125-16-000007" and r["filename"] == "d7dex21.htm" and r["sics"] == ["7372"]
    assert doc_url(r) == "https://www.sec.gov/Archives/edgar/data/12345/000119312516000007/d7dex21.htm"
    assert index_url(r) == "https://www.sec.gov/Archives/edgar/data/12345/000119312516000007/0001193125-16-000007-index.htm"


@pytest.mark.parametrize("t,ok", [("EX-2.1", True), ("ex-2.1", True), ("EX-2.01", True), ("EX-2.2", False),
                                  ("EX-99.1", False), ("", False)])
def test_is_ex21(t, ok):
    assert is_ex21(t) is ok
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_edgar_search.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`pipeline/edgar_search.py`:

```python
import calendar
from datetime import date, timedelta
from urllib.parse import urlencode

FTS = "https://efts.sec.gov/LATEST/search-index"
PHRASE = '"agreement and plan of merger"'
PAGE = 100
CAP = 10000
START = date(2015, 1, 1)


def search_url(start: date, end: date, offset: int) -> str:
    return FTS + "?" + urlencode({"q": PHRASE, "forms": "8-K", "dateRange": "custom",
                                  "startdt": start.isoformat(), "enddt": end.isoformat(), "from": offset})


def months(start: date, end: date) -> list[tuple[date, date]]:
    out = []
    cur = start
    while cur <= end:
        last = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        out.append((cur, min(last, end)))
        cur = last + timedelta(days=1)
    return out


def row(hit: dict) -> dict:
    accession, _, filename = hit["_id"].partition(":")
    s = hit["_source"]
    return {"adsh": s.get("adsh", accession), "filename": filename, "file_type": s.get("file_type", ""),
            "file_date": s.get("file_date", ""), "form": s.get("form", ""), "ciks": s.get("ciks", []),
            "names": s.get("display_names", []), "sics": s.get("sics", [])}


def is_ex21(file_type: str) -> bool:
    return file_type.strip().upper() in ("EX-2.1", "EX-2.01")


def _folder(r: dict) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(r['ciks'][0])}/{r['adsh'].replace('-', '')}"


def doc_url(r: dict) -> str:
    return f"{_folder(r)}/{r['filename']}"


def index_url(r: dict) -> str:
    return f"{_folder(r)}/{r['adsh']}-index.htm"


def search_window(client, start: date, end: date) -> list[dict]:
    first = client.get_json(search_url(start, end, 0))
    total = first["hits"]["total"]
    over = total["relation"] != "eq" or total["value"] >= CAP
    if over and start < end:
        mid = start + (end - start) // 2
        return search_window(client, start, mid) + search_window(client, mid + timedelta(days=1), end)
    if over:
        raise ValueError(f"{start} alone reaches the {CAP}-result cap; narrow the query")
    hits = list(first["hits"]["hits"])
    for offset in range(PAGE, total["value"], PAGE):
        hits += client.get_json(search_url(start, end, offset))["hits"]["hits"]
    return [row(h) for h in hits]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/edgar_search.py tests/test_edgar_search.py
git commit -m "m0: EDGAR full-text search by window, split below the result cap, paged

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 4: Exhibit text

**Files:**
- Create: `pipeline/html_text.py`
- Test: `tests/test_html_text.py`

**Interfaces:**
- Produces: `pipeline.html_text.to_text(raw: bytes, filename: str) -> str`. HTML (by extension, or by an `<html` or `<body` tag near the top) is converted with the standard library's `HTMLParser`: block tags become line breaks, `script` and `style` are dropped, entities are unescaped, and non-breaking spaces become spaces. Plain text passes through. Both then go through `pipeline.normalise.canonical`. Runs of spaces collapse, three or more newlines become two, and lines holding only a page number (`7`, `- 7 -`, `Page 7`) are removed.

M0 needs the text only to count and parse it. Offsets back to the source, and running-header removal, are M3's normaliser (PRD §2.3); this one does not keep offsets.

- [ ] **Step 1: Write the failing tests**

`tests/test_html_text.py`:

```python
from pipeline.html_text import to_text

HTML = b"""<html><head><style>p{color:red}</style><script>var x=1;</script></head><body>
<p align="center"><b>AGREEMENT AND PLAN OF MERGER</b></p>
<p>This AGREEMENT AND PLAN OF MERGER, dated as of March&nbsp;1, 2016, by and among
Parent&#160;Inc., a Delaware corporation (&#8220;Parent&#8221;), and Acme Software, Inc. (the &ldquo;Company&rdquo;).</p>
<p style="text-align:center">- 2 -</p>
<div>ARTICLE I</div><table><tr><td>Section&nbsp;1.1</td><td>The Merger.</td></tr></table>
</body></html>"""


def test_html_becomes_lines_without_markup_scripts_or_page_numbers():
    text = to_text(HTML, "d1dex21.htm")
    assert "AGREEMENT AND PLAN OF MERGER\n" in text
    assert "dated as of March 1, 2016" in text
    assert "(“Parent”)" in text and "(the “Company”)" in text
    assert "color" not in text and "var x" not in text
    assert "- 2 -" not in text
    assert "\n\n\n" not in text and "  " not in text


def test_plain_text_passes_through_canonicalised():
    raw = "﻿AGREEMENT AND PLAN OF MERGER\r\n\r\n\r\n\r\nPage 3\r\nSection 1.1 The Merger.\r\n".encode()
    assert to_text(raw, "ex2-1.txt") == "AGREEMENT AND PLAN OF MERGER\n\nSection 1.1 The Merger.\n"


def test_html_detected_by_content_when_the_extension_is_txt():
    assert to_text(b"<HTML><BODY><P>Hello</P><P>World</P></BODY></HTML>", "x.txt").split() == ["Hello", "World"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_html_text.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`pipeline/html_text.py`:

```python
import re
from html.parser import HTMLParser

from pipeline.normalise import canonical

BLOCK = {"p", "div", "br", "tr", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6", "center", "title", "hr"}
SKIP = {"script", "style"}
PAGE_LINE = re.compile(r"(?m)^[ \t]*(?:-\s*\d{1,3}\s*-|\d{1,3}|Page\s+\d{1,3}(?:\s+of\s+\d{1,3})?)[ \t]*\n")
SPACES = re.compile(r"[ \t\xa0]+")


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP:
            self.skipping += 1
        elif tag in BLOCK:
            self.out.append("\n")
        elif tag == "td":
            self.out.append(" ")

    def handle_endtag(self, tag):
        if tag in SKIP:
            self.skipping = max(0, self.skipping - 1)
        elif tag in BLOCK:
            self.out.append("\n")

    def handle_data(self, data):
        if not self.skipping:
            self.out.append(data.replace("\n", " "))


def _is_html(s: str, filename: str) -> bool:
    head = s[:2000].lower()
    return filename.lower().endswith((".htm", ".html")) or "<html" in head or "<body" in head


def to_text(raw: bytes, filename: str) -> str:
    s = raw.decode("utf-8", errors="replace")
    if _is_html(s, filename):
        p = _Text()
        p.feed(s)
        p.close()
        s = "".join(p.out)
    s = canonical(s)
    s = "\n".join(SPACES.sub(" ", line).strip() for line in s.split("\n"))
    s = PAGE_LINE.sub("", s + "\n")
    s = re.sub(r"\n{3,}", "\n\n", s).strip("\n")
    return s + "\n"
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add pipeline/html_text.py tests/test_html_text.py
git commit -m "m0: exhibit HTML or text to canonical plain text

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Preamble, deal identity and target resolution

**Files:**
- Create: `pipeline/target.py`
- Test: `tests/test_target.py`

**Interfaces:**
- Produces: `TECH_SIC = ((3570, 3579), (3661, 3679), (7370, 7379))` and `is_tech(sic) -> bool` (accepts a str or int; empty or non-numeric is False).
- Produces: the frozen dataclass `Preamble(company: str | None, parent: str | None, signed: date | None, amendment: bool)` and `preamble(text: str) -> Preamble`, read from the first 6,000 characters.
- Produces: `norm(name: str) -> str`, which lowercases, turns `&` into `and`, drops punctuation and corporate suffixes (inc, incorporated, corp, corporation, co, company, ltd, limited, llc, plc, nv, holdings, holding, group, the), and collapses spaces.
- Produces: `deal_key(p: Preamble) -> tuple[str, str, str] | None`, which is `(norm(company), norm(parent), signed ISO)`, or None if any part is missing.
- Produces: `resolve(company: str, ciks: list[str], names: list[str]) -> str | None`. It matches the company to one of the filing's own filers, where display names look like `Acme Software Inc  (ACME)  (CIK 0000012345)`. A filer matches when the normalised names are equal, or one is the other followed by more words. Otherwise None, counted as unresolved and never guessed.

The rules, and why:
- **Target.** The target is the party defined as "Company" (or "Target"), and the acquirer is the party defined as "Parent" (or Acquiror, Acquirer, Buyer, Purchaser). That is how US public merger agreements name them. If the pattern finds no "Company", the agreement counts as unparsed.
- **Signing date.** It comes from "dated as of <Month> <day>, <year>", "dated <Month> …", or "… day of <Month>, <year>" in the preamble.
- **Amendment.** An agreement is an amendment if "Amendment No.", "First Amendment" (or Second, Third), or "Amendment to (the) Agreement and Plan of Merger" appears in its first 1,500 characters.
- **Resolution.** Resolution is attempted only against the filing's own filers. A target that is a registrant files its own 8-K with the agreement (Item 1.01), so its copy resolves even when the acquirer's copy does not. The report states this assumption, together with the measured share of deals seen in two or more copies.

- [ ] **Step 1: Write the failing tests**

`tests/test_target.py`:

```python
from datetime import date

import pytest

from pipeline.target import deal_key, is_tech, norm, preamble, resolve

PRE = ("AGREEMENT AND PLAN OF MERGER\n\nThis AGREEMENT AND PLAN OF MERGER (this “Agreement”), dated as of "
       "March 1, 2016, is entered into by and among Big Buyer Corp., a Delaware corporation (“Parent”), "
       "Buyer Sub, Inc., a Delaware corporation and a wholly owned subsidiary of Parent (“Merger Sub”), "
       "and Acme Software, Inc., a Delaware corporation (the “Company”).\n")


def test_preamble_reads_target_acquirer_date():
    p = preamble(PRE)
    assert p.company == "Acme Software, Inc." and p.parent == "Big Buyer Corp."
    assert p.signed == date(2016, 3, 1) and p.amendment is False


def test_day_of_dates_and_amendments():
    text = ("AMENDMENT NO. 1 TO AGREEMENT AND PLAN OF MERGER\n\nThis Amendment is made this 5th day of June, 2017, "
            "by and among Parent Co, a Nevada corporation (“Parent”), and Target Labs LLC, a Delaware limited "
            "liability company (the “Company”).")
    p = preamble(text)
    assert p.amendment is True and p.signed == date(2017, 6, 5) and p.company == "Target Labs LLC"


def test_no_company_is_unparsed_not_guessed():
    p = preamble("ASSET PURCHASE AGREEMENT between Seller (“Seller”) and Buyer (“Buyer”), dated May 2, 2018.")
    assert p.company is None and deal_key(p) is None


def test_norm_drops_suffixes_and_punctuation():
    assert norm("Acme Software, Inc.") == norm("ACME SOFTWARE INC") == "acme software"
    assert norm("Smith & Jones Holdings, Ltd.") == "smith and jones"


def test_resolve_matches_only_the_filings_own_filers():
    names = ["Big Buyer Corp  (BBC)  (CIK 0000000001)", "ACME SOFTWARE INC  (ACME)  (CIK 0000012345)"]
    assert resolve("Acme Software, Inc.", ["0000000001", "0000012345"], names) == "0000012345"
    assert resolve("Other Target, Inc.", ["0000000001", "0000012345"], names) is None


@pytest.mark.parametrize("sic,ok", [("7372", True), (3576, True), ("3661", True), ("3679", True), ("3680", False),
                                    ("2834", False), ("", False), (None, False), ("n/a", False)])
def test_is_tech(sic, ok):
    assert is_tech(sic) is ok
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_target.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

`pipeline/target.py`:

```python
import re
from dataclasses import dataclass
from datetime import date

TECH_SIC = ((3570, 3579), (3661, 3679), (7370, 7379))
PREAMBLE_CHARS = 6000
MONTHS = ("January February March April May June July August September October November December").split()
_Q = "[“\"]"
_QE = "[”\"]"
# A party name is a run of capitalised words (with "of", "and", "de", "la", "the" inside), so a match cannot
# start back in the preamble's prose ("dated as of March 1, 2016, ... among Big Buyer Corp.").
NAME = r"(?P<name>[A-Z0-9][\w.&'’\-]*(?:,?\s+(?:[A-Z0-9&][\w.&'’\-]*|of|and|de|la|the))*)"
PARTY = re.compile(
    NAME + r",?\s+(?:a|an)\s+[A-Za-z .’'\-]{0,80}?"
    r"(?:corporation|company|partnership|N\.V\.|B\.V\.|S\.A\.|plc|Ltd\.?|limited)\b[^()“”\"]{0,120}?"
    r"\(\s*(?:the\s+)?" + _Q + r"(?P<role>[A-Z][A-Za-z ]{1,40})" + _QE + r"\s*\)", re.S)
COMPANY_ROLES = ("Company", "Target")
PARENT_ROLES = ("Parent", "Acquiror", "Acquirer", "Buyer", "Purchaser")
MONTH = "(" + "|".join(MONTHS) + ")"
DATED = re.compile(r"dated\s+(?:as\s+of\s+)?" + MONTH + r"\s+(\d{1,2}),?\s+(\d{4})")
DAY_OF = re.compile(r"(\d{1,2})(?:st|nd|rd|th)?\s+day\s+of\s+" + MONTH + r",?\s+(\d{4})")
AMENDMENT = re.compile(r"\bAmendment\s+No\.?\s*\d|\b(?:First|Second|Third)\s+Amendment\b|"
                       r"\bAmendment\s+to\s+(?:the\s+)?Agreement\s+and\s+Plan\s+of\s+Merger", re.I)
SUFFIX = re.compile(r"\b(?:incorporated|inc|corporation|corp|company|co|ltd|limited|llc|plc|nv|holdings|holding|"
                    r"group|the)\b")


@dataclass(frozen=True)
class Preamble:
    company: str | None
    parent: str | None
    signed: date | None
    amendment: bool


def is_tech(sic) -> bool:
    try:
        n = int(str(sic).strip())
    except (TypeError, ValueError):
        return False
    return any(lo <= n <= hi for lo, hi in TECH_SIC)


def _signed(head: str) -> date | None:
    m = DATED.search(head)
    if m:
        return _date(int(m.group(3)), m.group(1), int(m.group(2)))
    m = DAY_OF.search(head)
    if m:
        return _date(int(m.group(3)), m.group(2), int(m.group(1)))
    return None


def _date(year: int, month: str, day: int) -> date | None:
    try:
        return date(year, MONTHS.index(month) + 1, day)
    except ValueError:
        return None


def preamble(text: str) -> Preamble:
    head = text[:PREAMBLE_CHARS]
    roles: dict[str, str] = {}
    for m in PARTY.finditer(head):
        roles.setdefault(m.group("role").strip(), m.group("name").strip(" ,"))
    company = next((roles[r] for r in COMPANY_ROLES if r in roles), None)
    parent = next((roles[r] for r in PARENT_ROLES if r in roles), None)
    return Preamble(company, parent, _signed(head), bool(AMENDMENT.search(head[:1500])))


def norm(name: str) -> str:
    s = name.lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = SUFFIX.sub(" ", s)
    return " ".join(s.split())


def deal_key(p: Preamble) -> tuple[str, str, str] | None:
    if not (p.company and p.parent and p.signed):
        return None
    return norm(p.company), norm(p.parent), p.signed.isoformat()


def resolve(company: str, ciks: list[str], names: list[str]) -> str | None:
    target = norm(company)
    if not target:
        return None
    for cik, display in zip(ciks, names):
        n = norm(re.sub(r"\(.*?\)", " ", display))
        if n and (n == target or n.startswith(target + " ") or target.startswith(n + " ")):
            return cik
    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. (This code was dry-run against these tests while the plan was written.)

- [ ] **Step 5: Commit**

```bash
git add pipeline/target.py tests/test_target.py
git commit -m "m0: preamble parties, signing date, amendments, deal identity and target resolution

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 6: The stages

**Files:**
- Create: `pipeline/m0.py`
- Create if absent: `pipeline/claude.py` (verbatim from M2 Task 7)
- Test: `tests/test_m0.py`

**Interfaces:**
- Consumes: `SecClient` (Task 1), `edgar_search` (Task 3), `html_text.to_text` (Task 4), `target` (Task 5), `pipeline.segment.segment`, `pipeline.normalise.squash`, `pipeline.ledger.Ledger(path, key=...)`, `pipeline.claude.run_claude`.
- Produces: `pipeline.m0.M0_DIR = Path("data/m0")`, `SAMPLE = 30`, `SEED = 0`, `FAMILIES = ("equity_awards", "termination_fee", "contingent_consideration")`, `LEAD_MODEL = "claude-opus-5-5"`.
- Produces the stage functions. Each reads the previous stage's file and writes its own atomically, and each is safe to rerun:

| Function | Reads | Writes | sec.gov |
|---|---|---|---|
| `stage_search(client, out, today=None) -> dict` | (none) | `search.jsonl` | search pages |
| `stage_candidates(client, out) -> dict` | `search.jsonl` | `candidates.jsonl` | submissions, only for hits without SICs |
| `stage_fetch(client, out) -> dict` | `candidates.jsonl` | `docs.jsonl`, `text/*.txt` | one exhibit per candidate |
| `stage_deals(client, out) -> dict` | `docs.jsonl` | `deals.jsonl` | one submissions JSON per resolved target |
| `stage_sample(out, runner=run_claude, model=LEAD_MODEL) -> dict` | `deals.jsonl` | `sample.jsonl` (+ ledger) | none (`claude -p`) |
| `stage_press(client, out) -> dict` | `sample.jsonl`, `deals.jsonl` | `press.jsonl` | filing index and EX-99.1 per sampled deal |
| `stage_measure(out) -> dict` | all of the above | `measure.json` | none |

- Produces: `hint_passages(text) -> dict[str, list[str]]`, `lead_families(text, runner, model) -> dict`, `fee_amounts(text) -> set[float]`, `restates(press_text, fees) -> bool`, `press_release_url(index_html) -> str | None`.

The rules, and why:
- **Candidates.** EX-2.1 hits whose filers include one with a tech SIC. A tech target that is a registrant files its own copy, so filtering on filers misses only targets that never filed. The share of tech deals seen in two or more copies, measured here, is the evidence for that.
- **Deals.** Non-amendment copies are grouped by `deal_key` (target, acquirer, signing date). The canonical copy is the earliest filed. An amendment attaches to the deal with the same target and acquirer. A deal is resolved if any copy resolves its target among that filing's filers, and it is tech if the resolved target's SIC (from its submissions JSON) is in range.
- **Lead families, machine-built and quote-gated.** For each family, a broad pattern picks out up to 12 passages that could hold it. A family with no such passage is absent without a model call. Otherwise one `claude -p` call reads those passages (at most 40,000 characters). It counts a family present only if it says so **and** its quote occurs verbatim, ignoring whitespace, in the passages it was shown. The pattern's own verdict is kept too, as `regex`, for the report.
- **Fee restatement.** The fee amount comes from the agreement: a dollar figure within 300 characters after "Termination Fee", at least $100,000. The press release is the filing's EX-99.1, found on the filing index page. "Restated" means a dollar figure in the release within 0.5% of the fee.

- [ ] **Step 1: Write the failing test**

`tests/test_m0.py`:

```python
import json
from datetime import date
from urllib.parse import parse_qs, urlparse

from pipeline.m0 import (fee_amounts, lead_families, press_release_url, restates, stage_candidates, stage_deals,
                         stage_fetch, stage_measure, stage_press, stage_sample, stage_search)
from tests.fakes import fake_claude

PRE = ("AGREEMENT AND PLAN OF MERGER\n\nThis AGREEMENT AND PLAN OF MERGER, dated as of {d}, by and among "
       "{p}, a Delaware corporation (“Parent”), and {c}, a Delaware corporation (the “Company”).\n\n"
       "Section 2.3 Company Options. Each Company Option shall be cancelled and converted into cash.\n\n"
       "Section 8.3 Termination Fee. The Company shall pay Parent a termination fee of $45,000,000 in cash.\n")
DOCS = {
    # accession: (filer cik, filer display name, filer sic, text)
    "0000000001-16-000001": ("0000000011", "ACME SOFTWARE INC  (ACME)  (CIK 0000000011)", "7372",
                             PRE.format(d="March 1, 2016", p="Big Buyer Corp.", c="Acme Software, Inc.")),
    "0000000002-16-000002": ("0000000022", "BIG BUYER CORP  (BBC)  (CIK 0000000022)", "7372",
                             PRE.format(d="March 1, 2016", p="Big Buyer Corp.", c="Acme Software, Inc.")),
    "0000000003-16-000003": ("0000000033", "DRUGCO INC  (DRG)  (CIK 0000000033)", "2834",
                             PRE.format(d="March 9, 2016", p="Pharma Parent Inc.", c="DrugCo, Inc.")),
}
PRESS = b"<html><body><p>Acme to be acquired. A termination fee of $45 million may be payable.</p></body></html>"


def hit(adsh, cik, name, sic):
    return {"_id": f"{adsh}:ex21.htm", "_source": {"ciks": [cik], "display_names": [name], "file_type": "EX-2.1",
                                                   "file_date": "2016-03-02", "form": "8-K", "adsh": adsh, "sics": [sic]}}


class FakeEdgar:
    def __init__(self):
        self.urls = []

    def _route(self, url):
        u = urlparse(url)
        if u.hostname == "efts.sec.gov":
            q = parse_qs(u.query)
            in_march = q["startdt"][0] <= "2016-03-02" <= q["enddt"][0]
            hits = [hit(a, c, n, s) for a, (c, n, s, _) in DOCS.items()] if in_march and q["from"][0] == "0" else []
            return json.dumps({"hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": hits}}).encode()
        if u.hostname == "data.sec.gov":
            cik = u.path.split("CIK")[1].split(".")[0]
            sic = next(s for c, _, s, _ in DOCS.values() if int(c) == int(cik))
            return json.dumps({"cik": cik, "name": "x", "sic": sic}).encode()
        if url.endswith("pr.htm"):
            return PRESS
        folder = u.path.split("/")[5]
        adsh = next(a for a in DOCS if a.replace("-", "") == folder)
        if url.endswith("ex21.htm"):
            # Real exhibits are HTML: a newline in the source is only whitespace, paragraphs are tags.
            paras = "".join(f"<p>{p}</p>" for p in DOCS[adsh][3].split("\n\n"))
            return f"<html><body>{paras}</body></html>".encode()
        if url.endswith("-index.htm"):
            return (b'<table><tr><td>1</td><td><a href="/Archives/edgar/data/11/x/ex21.htm">ex21.htm</a></td>'
                    b'<td>EX-2.1</td></tr><tr><td>2</td><td><a href="/Archives/edgar/data/11/x/pr.htm">pr.htm</a>'
                    b'</td><td>EX-99.1</td></tr></table>')
        return None

    def get(self, url):
        self.urls.append(url)
        return self._route(url)

    def get_json(self, url):
        body = self.get(url)
        return None if body is None else json.loads(body)


ANSWER = json.dumps({"equity_awards": {"present": True, "quote": "Each Company Option shall be cancelled"},
                     "termination_fee": {"present": True, "quote": "a termination fee of $45,000,000"},
                     "contingent_consideration": {"present": True, "quote": "an earn-out"}})


def test_the_stages_measure_a_small_fake_edgar(tmp_path):
    edgar = FakeEdgar()
    assert stage_search(edgar, tmp_path, today=date(2016, 4, 30))["ex21"] == 3
    assert stage_candidates(edgar, tmp_path)["candidates"] == 2
    assert stage_fetch(edgar, tmp_path)["fetched"] == 2
    deals = stage_deals(edgar, tmp_path)
    assert deals == {"deals": 1, "resolved": 1, "tech": 1}
    runner = fake_claude(ANSWER)
    assert stage_sample(tmp_path, runner=runner, model="m")["sample"] == 1
    assert stage_press(edgar, tmp_path)["restated"] == 1
    m = stage_measure(tmp_path)
    assert m["tech_deals"] == 1 and m["tech_multi_copy"] == 1
    assert m["family_present"] == {"equity_awards": 1, "termination_fee": 1, "contingent_consideration": 0}
    assert m["family_regex"]["contingent_consideration"] == 0
    assert m["passages_total"] >= 2
    assert len(runner.calls) == 1
    before = len(edgar.urls)
    stage_sample(tmp_path, runner=fake_claude("unused"), model="m")
    assert len(edgar.urls) == before


def test_a_family_with_no_hint_is_absent_without_a_call():
    runner = fake_claude(ANSWER)
    out = lead_families("Section 1.1 Closing. The closing occurs.\n", runner, "m")
    assert all(not v["present"] for v in out.values()) and runner.calls == []


def test_an_unverifiable_quote_does_not_count():
    runner = fake_claude(json.dumps({"termination_fee": {"present": True, "quote": "a fee of one billion"}}))
    out = lead_families("Section 8.3 Fees. The Company shall pay a termination fee of $5,000,000.\n", runner, "m")
    assert out["termination_fee"]["present"] is False and out["termination_fee"]["regex"] is True


def test_fee_amounts_and_restatement():
    fees = fee_amounts("“Termination Fee” means an amount equal to $1,250,000,000.")
    assert fees == {1_250_000_000.0}
    assert restates("a breakup fee of $1.25 billion", fees)
    assert not restates("a fee of $1.5 billion", fees)
    assert fee_amounts("the Termination Fee shall be reduced by $1.00") == set()


def test_press_release_url_reads_the_index_row_typed_ex_99_1():
    html = ('<tr><td><a href="/Archives/edgar/data/1/2/a.htm">a.htm</a></td><td>EX-2.1</td></tr>'
            '<tr><td><a href="/ix?doc=/Archives/edgar/data/1/2/pr.htm">pr.htm</a></td><td>EX-99.1</td></tr>')
    assert press_release_url(html) == "https://www.sec.gov/Archives/edgar/data/1/2/pr.htm"
    assert press_release_url("<tr><td>EX-2.1</td></tr>") is None
```

(The fake answer claims an earn-out with the quote "an earn-out". That phrase is not in the passages shown, and no passage matched the earn-out pattern, so the family stays absent. This is the quote gate and the hint gate working together.)

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_m0.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'pipeline.m0'`.

- [ ] **Step 3: Implement**

`pipeline/m0.py`:

```python
import json
import random
import re
from datetime import date
from pathlib import Path
from statistics import median

from pipeline.claude import run_claude
from pipeline.edgar_search import START, doc_url, index_url, is_ex21, months, search_window
from pipeline.html_text import to_text
from pipeline.ledger import Ledger
from pipeline.normalise import squash
from pipeline.segment import segment
from pipeline.target import deal_key, is_tech, norm, preamble, resolve

M0_DIR = Path("data/m0")
SAMPLE = 30
SEED = 0
FAMILIES = ("equity_awards", "termination_fee", "contingent_consideration")
LEAD_MODEL = "claude-opus-5-5"
MAX_HINT_PASSAGES = 12
MAX_PROMPT_CHARS = 40000
MIN_FEE = 100_000
FEE_TOLERANCE = 0.005
HINTS = {
    "equity_awards": re.compile(r"\b(?:Stock\s+Options?|Company\s+Options?|RSUs?|Restricted\s+Stock(?:\s+Units?)?|"
                                r"PSUs?|Equity\s+Awards?|Stock\s+Awards?)\b", re.I),
    "termination_fee": re.compile(r"\b(?:termination\s+fee|break-?up\s+fee)\b", re.I),
    "contingent_consideration": re.compile(r"\b(?:earn-?outs?|contingent\s+value\s+rights?|CVRs?|"
                                           r"milestone\s+payments?|contingent\s+consideration)\b", re.I),
}
PROMPT = """Below are passages from one merger agreement, separated by ---. For each topic, decide whether these passages contain a provision on it, and quote the shortest verbatim fragment (at most 300 characters) that shows it.

Topics:
- equity_awards: how employee stock options, restricted stock units or other equity awards are treated in the merger
- termination_fee: a fee one party must pay the other if the agreement is terminated
- contingent_consideration: an earn-out, contingent value right, milestone payment or other consideration paid later depending on future events

Reply with one JSON object and nothing else: {{"equity_awards": {{"present": true or false, "quote": "..."}}, "termination_fee": {{"present": true or false, "quote": "..."}}, "contingent_consideration": {{"present": true or false, "quote": "..."}}}}

Passages:
{excerpt}"""
FEE = re.compile(r"termination\s+fee[^;]{0,300}?\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion)?", re.I | re.S)
DOLLARS = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion)?", re.I)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def stage_search(client, out: Path = M0_DIR, today: date | None = None) -> dict:
    rows: dict[tuple[str, str], dict] = {}
    for start, end in months(START, today or date.today()):
        for r in search_window(client, start, end):
            rows[(r["adsh"], r["filename"])] = r
    _write_jsonl(Path(out) / "search.jsonl", [rows[k] for k in sorted(rows)])
    return {"docs": len(rows), "ex21": sum(is_ex21(r["file_type"]) for r in rows.values())}


def _filer_sics(client, r: dict) -> list[str]:
    if r["sics"]:
        return [str(s) for s in r["sics"]]
    out = []
    for cik in r["ciks"]:
        sub = client.get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        if sub:
            out.append(str(sub.get("sic", "")))
    return out


def stage_candidates(client, out: Path = M0_DIR) -> dict:
    ex21 = [r for r in _read_jsonl(Path(out) / "search.jsonl") if is_ex21(r["file_type"])]
    cands = [r for r in ex21 if any(is_tech(s) for s in _filer_sics(client, r))]
    _write_jsonl(Path(out) / "candidates.jsonl", cands)
    return {"ex21": len(ex21), "candidates": len(cands)}


def stage_fetch(client, out: Path = M0_DIR) -> dict:
    out = Path(out)
    (out / "text").mkdir(parents=True, exist_ok=True)
    docs = []
    for r in _read_jsonl(out / "candidates.jsonl"):
        raw = client.get(doc_url(r))
        if raw is None:
            docs.append({**r, "missing": True})
            continue
        text = to_text(raw, r["filename"])
        path = out / "text" / f"{r['adsh']}_{r['filename']}.txt"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        p = preamble(text)
        key = deal_key(p)
        docs.append({**r, "missing": False, "chars": len(text), "text": str(path), "company": p.company,
                     "parent": p.parent, "signed": p.signed.isoformat() if p.signed else None,
                     "amendment": p.amendment, "key": list(key) if key else None,
                     "target_cik": resolve(p.company, r["ciks"], r["names"]) if p.company else None})
    _write_jsonl(out / "docs.jsonl", docs)
    return {"candidates": len(docs), "fetched": sum(not d["missing"] for d in docs)}


def stage_deals(client, out: Path = M0_DIR) -> dict:
    docs = [d for d in _read_jsonl(Path(out) / "docs.jsonl") if not d["missing"]]
    groups: dict[tuple, list[dict]] = {}
    for d in docs:
        if d["key"] and not d["amendment"]:
            groups.setdefault(tuple(d["key"]), []).append(d)
    amended = [(norm(d["company"]), norm(d["parent"])) for d in docs
               if d["amendment"] and d["company"] and d["parent"]]
    rows = []
    for key, copies in sorted(groups.items()):
        cik = next((c["target_cik"] for c in copies if c["target_cik"]), None)
        sub = client.get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json") if cik else None
        sic = str(sub.get("sic", "")) if sub else None
        canonical = min(copies, key=lambda c: (c["file_date"], c["adsh"]))
        rows.append({"key": list(key), "signed": key[2], "target_cik": cik, "target_sic": sic,
                     "tech": bool(cik) and is_tech(sic), "copies": len(copies),
                     "amendments": sum(1 for a in amended if a == key[:2]),
                     "canonical": {k: canonical[k] for k in ("adsh", "filename", "ciks", "file_date", "text")}})
    _write_jsonl(Path(out) / "deals.jsonl", rows)
    return {"deals": len(rows), "resolved": sum(bool(r["target_cik"]) for r in rows),
            "tech": sum(r["tech"] for r in rows)}


def _gate_deals(out: Path) -> list[dict]:
    return [d for d in _read_jsonl(Path(out) / "deals.jsonl") if d["tech"] and d["signed"] >= START.isoformat()]


def hint_passages(text: str) -> dict[str, list[str]]:
    chunks = [text[p.start:p.end] for p in segment("m0", text)]
    return {f: [c for c in chunks if HINTS[f].search(c)][:MAX_HINT_PASSAGES] for f in FAMILIES}


def _json_object(s: str) -> dict:
    m = re.search(r"\{.*\}", s, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def lead_families(text: str, runner, model: str) -> dict:
    hints = hint_passages(text)
    out = {f: {"present": False, "regex": bool(hints[f]), "quote": ""} for f in FAMILIES}
    asked = [f for f in FAMILIES if hints[f]]
    if not asked:
        return out
    excerpt = "\n\n---\n\n".join(dict.fromkeys(c for f in asked for c in hints[f]))[:MAX_PROMPT_CHARS]
    answer = _json_object(runner(PROMPT.format(excerpt=excerpt), model)["result"])
    shown = squash(excerpt)[0]
    for f in asked:
        got = answer.get(f) if isinstance(answer.get(f), dict) else {}
        quote = str(got.get("quote", "")).strip()
        out[f] = {"present": got.get("present") is True and bool(quote) and squash(quote)[0] in shown,
                  "regex": True, "quote": quote[:300]}
    return out


def stage_sample(out: Path = M0_DIR, runner=run_claude, model: str = LEAD_MODEL) -> dict:
    deals = sorted(_gate_deals(out), key=lambda d: d["key"])
    picked = random.Random(SEED).sample(deals, min(SAMPLE, len(deals)))
    ledger = Ledger(Path(out) / "sample_ledger.jsonl", key="adsh")
    rows = []
    for d in sorted(picked, key=lambda d: d["key"]):
        adsh = d["canonical"]["adsh"]
        rec = ledger.get(adsh)
        if rec is None:
            text = Path(d["canonical"]["text"]).read_text(encoding="utf-8")
            rec = {"adsh": adsh, "model": model, **lead_families(text, runner, model)}
            ledger.put(rec)
        rows.append({**rec, "key": d["key"]})
    _write_jsonl(Path(out) / "sample.jsonl", rows)
    return {"sample": len(rows), "of": len(deals)}


def _amount(num: str, scale: str | None) -> float:
    return float(num.replace(",", "")) * {"million": 1e6, "billion": 1e9}.get((scale or "").lower(), 1.0)


def fee_amounts(text: str) -> set[float]:
    return {v for v in (_amount(*m.groups()) for m in FEE.finditer(text)) if v >= MIN_FEE}


def restates(press_text: str, fees: set[float]) -> bool:
    found = [_amount(*m.groups()) for m in DOLLARS.finditer(press_text)]
    return any(abs(v - f) <= FEE_TOLERANCE * f for v in found for f in fees)


def press_release_url(index_html: str) -> str | None:
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", index_html, re.S | re.I):
        if re.search(r">\s*EX-99\.1\s*<", tr, re.I):
            m = re.search(r'href="([^"]+)"', tr)
            if m:
                href = m.group(1).replace("/ix?doc=", "")
                return href if href.startswith("http") else "https://www.sec.gov" + href
    return None


def stage_press(client, out: Path = M0_DIR) -> dict:
    deals = {d["canonical"]["adsh"]: d for d in _read_jsonl(Path(out) / "deals.jsonl")}
    rows = []
    for s in _read_jsonl(Path(out) / "sample.jsonl"):
        c = deals[s["adsh"]]["canonical"]
        fees = fee_amounts(Path(c["text"]).read_text(encoding="utf-8"))
        index = client.get(index_url(c))
        url = press_release_url(index.decode("utf-8", errors="replace")) if index else None
        raw = client.get(url) if url else None
        release = to_text(raw, url) if raw else None
        rows.append({"adsh": s["adsh"], "fee": bool(fees), "release": release is not None,
                     "restated": bool(fees) and release is not None and restates(release, fees)})
    _write_jsonl(Path(out) / "press.jsonl", rows)
    return {"sample": len(rows), "restated": sum(r["restated"] for r in rows)}


def stage_measure(out: Path = M0_DIR) -> dict:
    out = Path(out)
    search = _read_jsonl(out / "search.jsonl")
    docs = _read_jsonl(out / "docs.jsonl")
    fetched = [d for d in docs if not d["missing"]]
    deals = _read_jsonl(out / "deals.jsonl")
    gate = _gate_deals(out)
    sample = _read_jsonl(out / "sample.jsonl")
    press = _read_jsonl(out / "press.jsonl")
    passages = [len(segment("m0", Path(d["canonical"]["text"]).read_text(encoding="utf-8"))) for d in gate]
    m = {
        "search_docs": len(search),
        "ex21_docs": sum(is_ex21(r["file_type"]) for r in search),
        "candidates": len(docs),
        "fetched": len(fetched),
        "missing": len(docs) - len(fetched),
        "company_parsed": sum(1 for d in fetched if d["company"]),
        "amendment_docs": sum(1 for d in fetched if d["amendment"]),
        "deals": len(deals),
        "deals_resolved": sum(1 for d in deals if d["target_cik"]),
        "tech_deals": len(gate),
        "tech_multi_copy": sum(1 for d in gate if d["copies"] > 1),
        "tech_amended": sum(1 for d in gate if d["amendments"] > 0),
        "sample": len(sample),
        "family_present": {f: sum(1 for r in sample if r[f]["present"]) for f in FAMILIES},
        "family_regex": {f: sum(1 for r in sample if r[f]["regex"]) for f in FAMILIES},
        "press_fee": sum(r["fee"] for r in press),
        "press_release": sum(r["release"] for r in press),
        "press_both": sum(1 for r in press if r["fee"] and r["release"]),
        "press_restated": sum(r["restated"] for r in press),
        "passages_total": sum(passages),
        "passages_mean": round(sum(passages) / len(passages), 1) if passages else 0.0,
        "passages_median": median(passages) if passages else 0,
        "lead_model": sample[0]["model"] if sample else LEAD_MODEL,
    }
    (out / "measure.json").write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    return m
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. The test fixture's filer CIKs (`0000000011`, `0000000022`) are what the fake submissions endpoint resolves; nothing reaches the network (the conftest guard would fail the test).

- [ ] **Step 5: Commit**

```bash
git add pipeline/m0.py pipeline/claude.py tests/test_m0.py
git commit -m "m0: stages from search to measure, quote-gated lead-family sample, fee restatement

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---
### Task 7: `dtd m0`, the M0 facts and `docs/m0/REPORT.md`

**Files:**
- Create: `facts/m0.py`, `facts/report_m0.py`
- Modify: `pipeline/cli.py`
- Test: `tests/test_facts_m0.py`, `tests/test_report_m0.py`, `tests/test_cli.py`

**Interfaces:**
- Produces: `dtd m0 {search,candidates,fetch,deals,sample,press,measure,all}`. Stages that need sec.gov open one `SecClient(DATA / "sec", sec_contact())` for the whole invocation, and `all` runs every stage in order in that one process. On `Blocked` it prints the reason and returns 3, and on a missing contact it returns 2. Each stage prints its summary line as JSON.
- Produces: `facts.m0.GATE_AGREEMENTS = 100`, `GATE_FAMILY_SHARE = 0.5`, `build_m0(m0_dir: Path, facts: dict | None = None) -> dict`. Every fact name starts with `m0_`. `m0_gate_pass` is true only if `m0_gate_count_ok` and `m0_gate_families_ok` are both true. If M2's `m2_index_bytes` and `m2_vec_passages` are present, `m0_estimate_index_bytes` estimates the tech index from M2's measured bytes per passage. It ends in `index_bytes`, so M2's `is_unstable` already skips it in `--check`.
- Produces: `facts.report_m0.render_m0(f) -> str`.
- `dtd facts` adds the M0 facts when `data/m0/measure.json` exists. That happens in M2's `_all_facts` if M2 has merged, and in `_cmd_facts` otherwise. `dtd report` writes `docs/m0/REPORT.md` when they exist.

- [ ] **Step 1: Write the failing tests**

`tests/test_facts_m0.py`:

```python
import json

from facts.m0 import GATE_AGREEMENTS, build_m0

FAM = ("equity_awards", "termination_fee", "contingent_consideration")


def measure(tmp_path, tech=150, present=(30, 29, 4), sample=30):
    m = {"search_docs": 9000, "ex21_docs": 4000, "candidates": 600, "fetched": 590, "missing": 10,
         "company_parsed": 560, "amendment_docs": 40, "deals": 300, "deals_resolved": 240, "tech_deals": tech,
         "tech_multi_copy": 90, "tech_amended": 12, "sample": sample,
         "family_present": dict(zip(FAM, present)), "family_regex": dict(zip(FAM, (30, 30, 9))),
         "press_fee": 28, "press_release": 27, "press_both": 26, "press_restated": 13,
         "passages_total": 40000, "passages_mean": 266.7, "passages_median": 250, "lead_model": "m"}
    (tmp_path / "measure.json").write_text(json.dumps(m))
    return tmp_path


def test_rates_and_the_gate(tmp_path):
    f = build_m0(measure(tmp_path))
    assert f["m0_target_resolved_rate"] == 0.8 and f["m0_duplicate_rate"] == 0.6
    assert f["m0_press_restated_share"] == 0.5
    assert f["m0_gate_count_ok"] is True and f["m0_gate_families_ok"] is False and f["m0_gate_pass"] is False
    assert f["m0_gate_agreements_min"] == GATE_AGREEMENTS
    assert all(k.startswith("m0_") for k in f)


def test_gate_passes_when_both_conditions_hold(tmp_path):
    f = build_m0(measure(tmp_path, present=(30, 29, 15)))
    assert f["m0_gate_pass"] is True


def test_too_few_agreements_fail_the_gate(tmp_path):
    f = build_m0(measure(tmp_path, tech=GATE_AGREEMENTS - 1, present=(30, 30, 30)))
    assert f["m0_gate_count_ok"] is False and f["m0_gate_pass"] is False


def test_empty_sample_fails_families_without_dividing_by_zero(tmp_path):
    f = build_m0(measure(tmp_path, tech=0, present=(0, 0, 0), sample=0))
    assert f["m0_gate_families_ok"] is False and f["m0_sample_equity_awards_share"] is None


def test_index_estimate_uses_m2_bytes_per_passage(tmp_path):
    f = build_m0(measure(tmp_path), {"m2_index_bytes": 1000, "m2_vec_passages": 10})
    assert f["m0_estimate_index_bytes"] == 40000 * 100
```

`tests/test_report_m0.py`:

```python
import re

from facts.report_m0 import render_m0

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


ALLOWED = re.compile(r"\bM\d\b|§\d+(?:\.\d+)?|EX-2\.1|EX-99\.1|\b8-K\b")


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m0(Every()).replace(str(SENTINEL), "")
    lines = [l for l in text.splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_the_report_states_the_gate_and_its_labels():
    text = render_m0(Every())
    assert "machine-built" in text and "Gate" in text and "This is not legal advice." in text
```

Append to `tests/test_cli.py`:

```python
def test_m0_without_a_contact_refuses_before_any_request(data, monkeypatch, capsys):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    monkeypatch.chdir(data)
    assert cli.entry(["m0", "search"]) == 2
    assert "SEC_CONTACT" in capsys.readouterr().err


def test_m0_stops_with_exit_3_when_blocked(data, monkeypatch, capsys):
    from pipeline.sec_client import Blocked
    monkeypatch.setenv("SEC_CONTACT", "tester@example.com")
    monkeypatch.setattr(cli, "DATA", data)

    def blocked(client, out, today=None):
        raise Blocked("sec.gov answered 403; stopped, no retry")
    monkeypatch.setattr(cli.m0, "stage_search", blocked)
    assert cli.entry(["m0", "search"]) == 3
    assert "403" in capsys.readouterr().err
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_facts_m0.py tests/test_report_m0.py tests/test_cli.py -q`
Expected: FAIL (no `facts.m0`, no `m0` command).

- [ ] **Step 3: Implement the facts**

`facts/m0.py`:

```python
import json
from pathlib import Path

from pipeline.edgar_search import START
from pipeline.m0 import FAMILIES, SAMPLE
from pipeline.target import TECH_SIC

GATE_AGREEMENTS = 100
GATE_FAMILY_SHARE = 0.5
COPIED = ("search_docs", "ex21_docs", "candidates", "fetched", "missing", "company_parsed", "amendment_docs",
          "deals", "deals_resolved", "tech_deals", "tech_multi_copy", "tech_amended", "sample", "press_fee",
          "press_release", "press_both", "press_restated", "passages_total", "passages_mean", "passages_median",
          "lead_model")


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def build_m0(m0_dir: Path, facts: dict | None = None) -> dict:
    m = json.loads((Path(m0_dir) / "measure.json").read_text(encoding="utf-8"))
    f = {f"m0_{k}": m[k] for k in COPIED}
    f["m0_company_parsed_rate"] = _rate(m["company_parsed"], m["fetched"])
    f["m0_target_resolved_rate"] = _rate(m["deals_resolved"], m["deals"])
    f["m0_duplicate_rate"] = _rate(m["tech_multi_copy"], m["tech_deals"])
    f["m0_amendment_rate"] = _rate(m["tech_amended"], m["tech_deals"])
    f["m0_press_restated_share"] = _rate(m["press_restated"], m["press_both"])
    for fam in FAMILIES:
        f[f"m0_sample_{fam}_present"] = m["family_present"][fam]
        f[f"m0_sample_{fam}_share"] = _rate(m["family_present"][fam], m["sample"])
        f[f"m0_sample_{fam}_regex"] = m["family_regex"][fam]
    f["m0_sample_target"] = SAMPLE
    f["m0_start"] = START.isoformat()
    f["m0_sic_ranges"] = ", ".join(f"{lo}–{hi}" for lo, hi in TECH_SIC)
    f["m0_gate_agreements_min"] = GATE_AGREEMENTS
    f["m0_gate_family_share_min"] = GATE_FAMILY_SHARE
    f["m0_gate_count_ok"] = m["tech_deals"] >= GATE_AGREEMENTS
    f["m0_gate_families_ok"] = m["sample"] > 0 and all(
        m["family_present"][fam] / m["sample"] >= GATE_FAMILY_SHARE for fam in FAMILIES)
    f["m0_gate_pass"] = f["m0_gate_count_ok"] and f["m0_gate_families_ok"]
    if facts and facts.get("m2_index_bytes") and facts.get("m2_vec_passages"):
        f["m0_estimate_index_bytes"] = round(m["passages_total"] * facts["m2_index_bytes"] / facts["m2_vec_passages"])
    return dict(sorted(f.items()))
```

- [ ] **Step 4: Implement the report**

`facts/report_m0.py`:

```python
from pipeline.m0 import FAMILIES

LABELS = {"equity_awards": "Employee equity awards", "termination_fee": "Termination (break-up) fee",
          "contingent_consideration": "Earn-out or other contingent consideration"}


def _ok(v) -> str:
    return "Met" if v else "Not met"


def _families(f) -> str:
    return "\n".join(
        f"| {LABELS[fam]} | {f[f'm0_sample_{fam}_present']} | {f[f'm0_sample_{fam}_share']} "
        f"| {f[f'm0_sample_{fam}_regex']} |" for fam in FAMILIES)


def render_m0(f) -> str:
    verdict = "PASS" if f["m0_gate_pass"] else "FAIL"
    estimate = (f"Estimated index size from M2's bytes per passage: {f['m0_estimate_index_bytes']} bytes."
                if "m0_estimate_index_bytes" in f else "No index-size estimate: M2's index measurements are not in the facts.")
    return f"""# M0 report: the EDGAR gate

Generated by `dtd report` from `facts.json`. Do not edit by hand. This is not legal advice.

## Gate: {verdict}

- Tech agreements: {f['m0_tech_deals']}; the gate needs at least {f['m0_gate_agreements_min']}. {_ok(f['m0_gate_count_ok'])}.
- Each lead family in at least {f['m0_gate_family_share_min']} of a sample of {f['m0_sample']} tech agreements. {_ok(f['m0_gate_families_ok'])}.

If the gate failed, PRD §10's fallback applies before M3 is planned: index the tech deals that exist, lead the demo with the most recognisable, and describe the corpus as public acquisition agreements without the startup framing.

## Lead families in the sample (machine-built)

Presence is judged by `{f['m0_lead_model']}` on passages a broad pattern picked out, and counts only when its supporting quote occurs verbatim in those passages. The pattern's own count is beside it.

| Family | Present | Share | Pattern matched |
|---|---|---|---|
{_families(f)}

## How the corpus was found

Selection rule (PRD §2.2): an EX-2.1 exhibit to an 8-K whose text is an agreement and plan of merger, signed on or after {f['m0_start']}, whose target is an EDGAR registrant with SIC in {f['m0_sic_ranges']}. Every request followed the access rules of PRD §2.2.

| Step | Count |
|---|---|
| Documents found by full-text search for "agreement and plan of merger" in 8-K filings | {f['m0_search_docs']} |
| Of those, EX-2.1 exhibits | {f['m0_ex21_docs']} |
| Filed by a company with a tech SIC (candidates) | {f['m0_candidates']} |
| Fetched (the rest were missing) | {f['m0_fetched']} ({f['m0_missing']} missing) |
| Preamble names a "Company" | {f['m0_company_parsed']} (rate {f['m0_company_parsed_rate']}) |
| Amendments among them | {f['m0_amendment_docs']} |
| Distinct deals (target, acquirer, signing date) | {f['m0_deals']} |
| Deals whose target resolved to a filer | {f['m0_deals_resolved']} (rate {f['m0_target_resolved_rate']}) |
| Tech agreements: resolved target with a tech SIC, signed in range | {f['m0_tech_deals']} |

The target is resolved only against the filing's own filers, on the assumption that a target which is a registrant files its own copy. Tech deals seen in more than one copy: {f['m0_tech_multi_copy']} (rate {f['m0_duplicate_rate']}). Tech deals with an amendment: {f['m0_tech_amended']} (rate {f['m0_amendment_rate']}).

## The fee in the press release (PRD §5.2 cross-check)

Of the sampled deals, {f['m0_press_fee']} state a fee amount in the agreement and {f['m0_press_release']} have an EX-99.1 press release; of the {f['m0_press_both']} with both, {f['m0_press_restated']} restate the amount (share {f['m0_press_restated_share']}). M4 includes the cross-check only if this share is usable.

## Size for M3

Passages in the tech agreements, cut by the same section-aware segmenter as MAUD: {f['m0_passages_total']} in all, {f['m0_passages_mean']} per agreement on average, median {f['m0_passages_median']}. {estimate}
"""
```

- [ ] **Step 5: Wire the CLI**

In `pipeline/cli.py`:

```python
from pipeline import m0
from pipeline.paths import DATA

M0_STAGES = ("search", "candidates", "fetch", "deals", "sample", "press", "measure")
NEEDS_SEC = {"search", "candidates", "fetch", "deals", "press"}


def _cmd_m0(args) -> int:
    from pipeline.env import sec_contact
    from pipeline.sec_client import Blocked, SecClient
    stages = M0_STAGES if args.stage == "all" else (args.stage,)
    client = None
    try:
        if NEEDS_SEC & set(stages):
            client = SecClient(DATA / "sec", sec_contact())
        out = DATA / "m0"
        for stage in stages:
            fn = getattr(m0, f"stage_{stage}")
            summary = fn(out) if stage in ("sample", "measure") else fn(client, out)
            print(json.dumps({stage: summary}), flush=True)
        return 0
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 3 if isinstance(e, Blocked) else 2
    finally:
        if client is not None:
            client.close()
```

Register:

```python
    m0p = sub.add_parser("m0")
    m0p.add_argument("stage", choices=M0_STAGES + ("all",))
    m0p.set_defaults(fn=_cmd_m0)
```

In the facts builder (`_all_facts` if M2 is merged, else `_cmd_facts`), after the other facts:

```python
    if (DATA / "m0" / "measure.json").exists():
        facts |= build_m0(DATA / "m0", facts)
```

and in `_cmd_report`:

```python
    if "m0_gate_pass" in facts:
        REPORT_M0.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M0.write_text(render_m0(facts), encoding="utf-8")
```

with `REPORT_M0 = Path("docs/m0/REPORT.md")` and the imports `from facts.m0 import build_m0` and `from facts.report_m0 import render_m0`. (The `data` fixture in `tests/test_cli.py` does not patch `DATA`; the blocked test does, so the lock file lands in the test's directory.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest -q`
Expected: all pass. If the digit test fails, it lists the offending lines. Move each number into a fact; never widen `ALLOWED` for a number.

- [ ] **Step 7: Commit**

```bash
git add facts/m0.py facts/report_m0.py pipeline/cli.py tests/test_facts_m0.py tests/test_report_m0.py tests/test_cli.py
git commit -m "m0: dtd m0 stages, named M0 facts with the gate, and the generated M0 report

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The real run (controller only, one process, after the SEC unblocks)

**Files:**
- Modify (generated): `facts.json`, `docs/m0/REPORT.md`
- Nothing under `data/` is committed.

- [ ] **Step 1: Preconditions**

- Task 2's probe is done and every parser agrees with the recorded fixtures.
- No other process is touching sec.gov: no agent, no browser automation, no second terminal. `dtd m0` takes the lock, but a process outside this repo would not see it.
- Michael knows the run is starting.

- [ ] **Step 2: Search, with a kill**

Run `uv run dtd m0 search` in the background. After about 50 lines in `data/sec/ledger.jsonl`, `kill -9` it. Rerun it to completion.
Expected: the rerun's first requests are cache hits (the ledger grows only past the kill point), and `search.jsonl` is written once at the end. At 2 per second, a page count of P takes about P/2 seconds. Note P in the ledger.

If any stage exits with code 3 (blocked), stop everything and tell Michael. Do not rerun within the hour, and never from another identity or machine.

The search records its end date in `data/m0/search_meta.json`, and `dtd m0 search` reuses it, so the rerun asks exactly the same windows.

**Stall A: `search_window` raises "expected N hits, paged M" for a window.** Stop. The message names the window's start and end dates (it may be a part-month window from the cap split). With no `dtd` process running, delete that window's cache files and ledger rows: the rows are those in `data/sec/ledger.jsonl` whose `url` contains both `startdt=<start>` and `enddt=<end>`, and each row's cache file is `data/sec/cache/<sha1 of the url>`. For example:

```python
# uv run python clear_window.py, with <start> and <end> filled in
import hashlib, json, pathlib
root, start, end = pathlib.Path("data/sec"), "<start>", "<end>"
led, keep = root / "ledger.jsonl", []
for line in led.read_text(encoding="utf-8").splitlines():
    url = json.loads(line)["url"]
    if f"startdt={start}" in url and f"enddt={end}" in url:
        (root / "cache" / hashlib.sha1(url.encode("utf-8")).hexdigest()).unlink(missing_ok=True)
    else:
        keep.append(line)
led.write_text("".join(l + "\n" for l in keep), encoding="utf-8")
```

Then rerun `uv run dtd m0 search` once. If the same window fails again, do not retry: record the window as unreadable in the run's ledger notes (start, end, the expected and paged counts) and tell Michael.

**Stall B: one URL is refused again after the hour's cooldown.** If a single URL answers 403 again once the cooldown has passed, while www.sec.gov still loads in a browser, stop the run and tell Michael. Never retry in a loop, and never change the User-Agent, the contact, the machine or the network. `data/sec/blocked_events.jsonl` keeps every refusal with its time and URL.

- [ ] **Step 3: Candidates, fetch and deals, with a kill on fetch**

Run: `uv run dtd m0 candidates`, then `uv run dtd m0 fetch` in the background. `kill -9` it after about 30 exhibits and rerun it to completion. Then `uv run dtd m0 deals`.
Expected: the rerun re-requests nothing already in the ledger.

- [ ] **Step 4: Sample, press release and measure**

Run: `uv run dtd m0 sample && uv run dtd m0 press && uv run dtd m0 measure`
Expected: at most 30 `claude -p` calls (none for agreements whose hints are empty), and two sec.gov requests per sampled deal at most.

- [ ] **Step 5: Look before publishing**

Read 10 rows of `data/m0/deals.jsonl` at random, and check by eye that the target, acquirer and date match the agreement text. Read the sampled quotes in `data/m0/sample.jsonl`. If the parse is badly wrong (more than 2 of 10 targets wrong), stop and report to Michael rather than publish a gate built on it.

- [ ] **Step 6: Facts, report, commit**

Run: `uv run dtd facts && uv run dtd facts --check && uv run dtd report`

```bash
git add facts.json docs/m0/REPORT.md
git commit -m "m0: measured EDGAR gate, <PASS or FAIL> (<tech agreements> tech agreements)

Resume tested by kill -9 on search and fetch: <one line each>.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Show Michael the gate verdict. M3's plan is written only after this commit, and uses these numbers (PRD §9).

---

## What M0 deliberately leaves for later plans

- **The full EDGAR ingestion** (M3): the offset-keeping normaliser with running-header removal, amendment linking with `superseded_by`, deal scoping (R7), and the T-machine questions.
- **The press-release cross-check** (M4), if this report shows a usable share.
- **Targets that never filed their own copy.** Filtering on the filers' SICs misses them, and the report states that assumption.

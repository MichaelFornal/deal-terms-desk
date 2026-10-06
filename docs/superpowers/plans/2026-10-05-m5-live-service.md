# M5 — Live service, cost controls, site, deployment: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** a visitor at `deals.forn.al` asks what a merger agreement says and gets a cited answer from the same code
the evals measured, under a $10/month cap that trips in a test.

**Architecture:**
- **Live index:** one read-only SQLite bundle (`data/live/live.db`, built from `deals.db`) holds the index, the
  contract texts and the links.
- **Service:** a FastAPI service (`service/`) wraps a `Desk` object. The `Desk` runs R7n retrieval, the M4
  `Answerer` with an Anthropic API runner, a spend ledger with month and day caps, an answer cache keyed by prompt
  hash, and request limits.
- **Site:** four static pages rendered in Python from `facts.json` (`facts/site.py`). Caddy serves them and
  proxies `/api/*` to uvicorn on one Hetzner box.
- **Release gate:** `deploy/push.sh` ships a release only after tests and `dtd facts --check` pass, then asserts
  that the running service's shas match the repo.

**Tech Stack:**
- Python 3.12, uv, pytest;
- SQLite (FTS5, sqlite-vec), fastembed (bge-small);
- anthropic (Python SDK 1.x), fastapi, uvicorn;
- vanilla JS, Caddy, systemd.

**Spec:** `docs/superpowers/specs/2026-10-05-m5-live-design.md` (approved 2026-10-05). The roadmap with Michael's
steps is `~/.claude/plans/plan-out-every-step-soft-hearth.md`.

## Global Constraints

- Every number on a page, in a report or in the README comes from `facts.json` via a named builder. No digit in
  page copy, `site/examples.json` or user-visible `app.js` strings. Machine-built numbers say "machine-built";
  T-human ones say "human-labelled (MAUD)".
- sec.gov is never touched.
- The default suite (`uv run pytest`) makes no network or model call. A real call is marked `@pytest.mark.model`.
- Every stage is idempotent and resumable. Resume is tested by killing the stage, not by reasoning.
- `SEC_CONTACT` and `ANTHROPIC_API_KEY` are never written into the repo or into commit metadata. The repo-local
  `user.email` is the GitHub noreply address; check it before the first commit in any clone.
- README and launch post are Michael's; never generate them.
- Commits:
  - start with `m5: ` (plan and spec commits `m5 plan:` / `m5 spec:`);
  - end with `Assisted-by: Claude` then `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`;
  - land on branch `m5`.
- The live model is `claude-haiku-4-5-20251001`. API spend outside the service (calibration, smoke, the real-call
  test) uses the `dtd-dev` key, after Michael approves the estimate.
- The M4 measured path must not move: re-preparing M4's answer items gives the same `prompt_sha` as their ledgers.

## Deviations from the spec, decided while planning

1. **The answer path is enforced, not just read.** `Answerer` reads `answer_path` from settings and refuses
   anything but `R7n`: it always scopes the question, then retrieves with R6n inside the deal. A settings change
   can no longer drift silently from the code.
2. **The cache and `dtd warm` live behind a `Desk` object,** not the FastAPI app. `warm` calls `Desk.ask`
   directly, so warming uses the exact service path without going through HTTP rate limits.
3. **`dtd m5 calibrate` reuses `evals.run_answers.answer_all`** with the API runner and its own ledger, one per
   (model, output cap). Kill and resume behaviour is the existing, tested one.
4. **API failures:**
   - A truncated, refused or failed API call raises `RunnerError(kind, message, usage)`, a `RuntimeError`, so
     `answer_all` records it as `runner: …` like a CLI failure.
   - Truncated and refused replies are permanent in that ledger, because a retry would pay for the same reply.
5. **The price table moves to Task 5,** because calibration is its first consumer.
6. **Spend booking:**
   - A timeout or lost connection with no usage is booked at its worst case.
   - A reservation left open by a crash counts at worst case at once, and is settled at worst case only once it is
     older than `STALE_S` (600 s). A second process on the same ledger (`dtd warm`) must never close the service's
     in-flight call.
7. **`/api/health` shows no spend amounts.** The cap-trip check on the box reads the ledger over ssh
   (`deploy/smoke.py --ssh`).
8. **`dtd m5 measure` runs from the development machine.** Server-side times come from each payload's `ms`, so
   they exclude the network, and the embedding-parity reference runs locally over the same bundle.
9. **`Buckets(0, …)` and `Slots(0)` are closed limits.** Config never produces them; tests use them to reach `busy`.

## Review Focus

1. **Overspend:**
   - concurrent `/ask` requests, or a launch spike, push spend past the month or day cap;
   - and a crash between reserve and settle under-counts.
   - Pinned by: the 50-thread and two-connection reservation tests and the crash-reconciliation test (Task 6), the
     global fresh-call bucket (Task 8), and the cap-trip, concurrency and kill tests through `Desk` (Task 9).
2. **A picked deal is dropped:** R7n re-resolves and ignores `contract_id`. Pinned by Task 2's tests, the golden
   prompt hashes, and `dtd m5 parity`.
3. **Untrusted text rendered as HTML:** contract quotes or visitor input reach the page as markup. Pinned by Task
   10's `innerHTML` ban, `textContent` rendering, escaped server-rendered copy, and Task 12's CSP test.
4. **Rate limits keyed on the wrong address:** a spoofed `X-Forwarded-For`, or IPv6 rotation inside one /64.
   Pinned by Task 8's `client_key` tests, Task 9's /64 bucket test, and Task 15's smoke check on the real box.
5. **The live service drifts from the facts:** it serves a bundle, code or facts other than the ones the site
   describes. Pinned by Task 9's `/api/health` shas, Task 12's `push.sh` assertion, and smoke.

## File structure

| File | Responsibility | Task |
|---|---|---|
| `tests/test_cli.py` (modify) | the `data` fixture redirects every `REPORT*` path | 1 |
| `pipeline/cli.py` `_cmd_facts` (modify) | atomic write; `--check` flags keys no longer built | 1 |
| `service/__init__.py` (new), `pyproject.toml` (modify) | the `service` package | 1 |
| `retrieval/scope.py` (modify) | `scope_question`: the one resolve-and-strip | 2 |
| `retrieval/ladder.py` (modify) | R7/R7n use `scope_question` and honour `contract_id`; `RETRIEVAL_FOR`; `_stages` | 2, 3 |
| `answer/answerer.py` (modify) | answer path from settings, enforced; `scope_question` | 2 |
| `retrieval/result.py` (modify) | `Retrieved.stages` | 3 |
| `evals/live_parity.py` (new) | `prompt_parity` (vs M4 ledgers), `r7n_parity` (bundle vs deals.db) | 2, 4 |
| `pipeline/bundle.py` (new) | `build_bundle`, `bundle_is_current`, `MANIFEST`, `maud_url` | 4 |
| `retrieval/live.py` (new) | `open_bundle`, `bundle_meta`, `links_for`, `build_live_ladder` | 4 |
| `pipeline/env.py` (modify) | `anthropic_key` beside `sec_contact` | 5 |
| `answer/api_runner.py` (new) | `RunnerError`, `KINDS`, `make_api_runner` | 5 |
| `service/prices.json`, `service/prices.py` (new) | `Prices`, `load_prices`, `cost_usd`, `worst_case_usd` | 5 |
| `evals/run_answers.py` (modify) | truncated and refused API replies are permanent | 5 |
| `evals/calibrate.py` (new) | `calibration_sample`, `ledger_path`, `run_calibration`, `summarise` | 5 |
| `service/budget.py` (new) | `Budget`, `STALE_S` | 6 |
| `service/cache.py` (new) | `AnswerCache`, `normalise_question`, `CACHEABLE` | 7 |
| `service/limits.py`, `service/config.py` (new) | `client_key`, `Buckets`, `Slots`; `Config`, `from_env` | 8 |
| `service/desk.py`, `service/app.py`, `service/warm.py` (new) | `Desk`; `build_desk`, `create_app`; `warm` | 9 |
| `facts/labels.py`, `facts/site.py` (new) | label classification; `render_site` and the page content | 10 |
| `site/templates/*.html`, `site/static/app.js`, `site/static/style.css`, `site/examples.json` (new) | the pages | 10 |
| `.gitignore`, `.github/workflows/ci.yml` (modify) | ignore `site/dist/`; the CI "Facts check" step | 10 |
| `facts/m5.py`, `facts/report_m5.py` (new); `facts/m2.py` (modify) | M5 facts, `docs/m5/REPORT.md`; `rss_mb` is unstable | 11 |
| `evals/measure.py` (new) | `measure`, `reference_hits` | 11 |
| `deploy/Caddyfile`, `dtd.service`, `env.example`, `hosting.json`, `provision.sh`, `push.sh`, `smoke.py` (new) | the box | 12 |
| `pipeline/cli.py` (modify) | `dtd bundle`, `dtd m5 parity\|recall\|calibrate\|measure`, `dtd warm`, `dtd site`, facts/report wiring | 1, 2, 4, 5, 9, 10, 11 |
| `tests/test_*.py` | one test file per new module | all |

## Interfaces (the contract every task codes against)

```python
# retrieval/scope.py (Task 2)
def scope_question(resolver: "Resolver | None", question: str,
                   contract_id: str | None = None) -> tuple[Scope, str]:
    """contract_id given: (Scope(contract_id, None, ()), question minus every alias of that deal, longest first;
    unchanged when resolver is None). Otherwise resolver required (ValueError if None):
    (resolver.resolve(question), question minus the resolved alias when one deal resolved, else unchanged)."""

# retrieval/ladder.py (Task 2) — unchanged run() signature; R7/R7n now call scope_question(self.resolver, query, contract_id)
RETRIEVAL_FOR = {"R7n": "R6n"}   # answer path -> rung run inside the scoped deal

# answer/answerer.py (Task 2)
class Answerer:
    def __init__(self, ladder, runner, model: str, answer_path: str | None = None): ...
        # answer_path None -> load_answer_path(); not in RETRIEVAL_FOR -> ValueError; kept as .answer_path

# retrieval/result.py (Task 3)
@dataclass(frozen=True)
class Retrieved:
    hits: list[Hit]; ms: float; context: list[str]; amended: tuple[str, ...] = (); scope: object = None
    stages: dict = field(default_factory=dict)
    # {passage_id: {"bm25": {"rank": int, "score": float} | None, "dense": {"rank": int, "score": float} | None}}
    # filled for hybrid rungs (R3-R6, R6n, and R7/R7n through them) for every returned hit; {} for R1 and R2

# evals/live_parity.py (Tasks 2, 4)
def prompt_parity(items, answerer, records: dict[str, dict]) -> dict   # {"checked", "same", "differ": [item_id, …]}
def r7n_parity(questions: list[tuple[str, str | None]], a, b, k: int = 10) -> dict
    # {"checked", "same", "differ": [{"question", "contract_id"}, …]}

# pipeline/bundle.py (Task 4)
MANIFEST = "bundle.json"                                 # written next to the bundle
def maud_url(contract_id: str) -> str
def build_bundle(deals_db: Path, out: Path, *, texts: dict[str, str], amendment_texts: dict[str, str],
                 deals_jsonl: Path, settings_path: Path, lexicon_path: Path) -> dict:
    """-> {"sha256", "bytes", "contracts", "passages", "rebuilt": bool}; skips the build when the bundle matches
    its manifest and the inputs' hashes are unchanged."""
def bundle_is_current(out: Path) -> bool

# retrieval/live.py (Task 4)
def open_bundle(path: Path) -> sqlite3.Connection        # read-only, immutable, check_same_thread=False, sqlite-vec
def bundle_meta(conn) -> dict[str, str]                  # the meta table
def links_for(conn, contract_id: str) -> dict            # {"filing": url | None, "amendments": {int: url}}
def build_live_ladder(path: Path, embedder, lexicon: dict, settings: Settings) -> Ladder   # reranker None

# pipeline/env.py (Task 5)
def anthropic_key(env_file: Path = Path(".env")) -> str  # environment first, then the gitignored .env

# answer/api_runner.py (Task 5)
KINDS = ("rate_limited", "overloaded", "timeout", "connection", "bad_request", "billing", "refusal", "truncated")
class RunnerError(RuntimeError):
    def __init__(self, kind: str, message: str, usage: dict | None = None): ...   # .kind, .usage ({} if None)
def make_api_runner(max_tokens: int, client=None, timeout: float = 30.0):
    """-> runner(prompt: str, model: str) -> {"result": str, "usage": {input_tokens, output_tokens,
    cache_creation_input_tokens, cache_read_input_tokens}, "stop_reason": str}; nulls become 0."""

# service/prices.py (Task 5)
CHARS_PER_TOKEN = 3
@dataclass(frozen=True)
class Prices:
    model: str; input: float; output: float; cache_write: float; cache_read: float; source: str; checked: str
def load_prices(path) -> Prices
def cost_usd(p: Prices, usage: dict | None) -> float
def worst_case_usd(p: Prices, prompt_chars: int, max_tokens: int) -> float     # prompt_chars / 3 tokens in

# evals/calibrate.py (Task 5)
def ledger_path(root: Path, model: str, max_tokens: int) -> Path   # root / f"calibration_{model}_mt{max_tokens}.jsonl"
def calibration_sample(items, n: int) -> list           # n//2 tune T-human + n//2 tune T-machine, stable by sha1(item_id)
def run_calibration(jobs, ledger: Path, workers: int = 3, max_new: int | None = None) -> dict
    # jobs: [(items, answerer), …] into one ledger -> {"items", "done", "new_calls", "errors"}
def summarise(items, api: dict, cli: dict, prompt_chars: dict, prices, max_tokens: int) -> dict
    # {"n", "called", "errors", "missing", "truncated", "refused", "api_tokens_in_mean", "api_tokens_in_p95",
    #  "api_tokens_out_mean", "api_tokens_out_p95", "api_tokens_out_p99", "cost_usd_total", "cost_per_answer_mean",
    #  "cost_per_answer_p95", "worst_case_ok", "worst_case_min_margin_usd", "paired", "gate_pass_rate": {api, cli},
    #  "state_agreement", "thuman_accuracy": {api, cli, diff, n},
    #  "stop_rule": {"state_agreement_min", "accuracy_diff_max", "verdict": "go" | "stop", "reasons"}}

# service/budget.py (Task 6)
STALE_S = 600.0
class Budget:
    def __init__(self, db: Path, month_cap: float, day_cap: float, prices: Prices, clock=time.time): ...
    def reserve(self, prompt_chars: int, max_tokens: int) -> int | None   # reservation id, None = over a cap
    def settle(self, rid: int, usage: dict | None) -> float               # actual USD; None books the worst case
    def release(self, rid: int) -> None                                   # nothing billed
    def spent(self) -> dict                                               # {"month", "day"} USD, open rows at worst
    def state(self, min_call_usd: float) -> str                           # "reached" when < min_call_usd is left

# service/cache.py (Task 7)
CACHEABLE = ("answered", "not_stated", "unfiled_schedule")
def normalise_question(q: str) -> str                                     # whitespace collapsed, stripped
class AnswerCache:
    def __init__(self, db: Path): ...
    def get(self, model: str, prompt_sha: str) -> dict | None
    def put(self, model: str, prompt_sha: str, payload: dict) -> None     # ignores non-CACHEABLE states

# service/limits.py (Task 8)
def client_key(host: str) -> str             # IPv4 as is; IPv6 -> its /64; IPv4-mapped -> the IPv4; else unchanged
class Buckets:
    def __init__(self, per_window: int, window_s: float, clock=time.monotonic): ...   # per_window 0: never allows
    def allow(self, key: str) -> float                                    # 0.0 allowed, else seconds to wait
class Slots:
    def __init__(self, n: int): ...                                       # n 0: never acquires
    def try_acquire(self) -> bool
    def release(self) -> None

# service/config.py (Task 8)
@dataclass(frozen=True)
class Config:
    bundle: Path; state_dir: Path; prices_path: Path; facts_path: Path; model: str; max_tokens: int
    month_cap_usd: float; day_cap_usd: float; question_max_chars: int; ask_per_hour: int; search_per_minute: int
    fresh_per_hour: int; ask_slots: int; git_sha: str
def from_env(env=os.environ) -> Config
    # DTD_* variables; the month cap is required; git_sha = DTD_GIT_SHA, else the GIT_SHA file push.sh writes
    # into each release (read from the working directory), else "unknown"

# service/desk.py (Task 9)
STATES = ("answered", "not_stated", "unfiled_schedule", "which_deal", "budget_cached", "budget_reached",
          "busy", "error")
class Desk:
    def __init__(self, ladder, runner, config: Config, budget: Budget, cache: AnswerCache,
                 fresh: Buckets, slots: Slots): ...          # .answerer, .budget, .config
    def ask(self, question: str, deal: str | None = None) -> dict
        # {"state", "question", "deal", "claims", "amended", "candidates", "served_from", "budget", "tokens", "ms"}
        # (+ "cached_state" on a cache hit); an unknown deal id raises ValueError
    def search(self, q: str, deal: str | None = None) -> dict   # {"query", "scope", "hits", "ms"}
    def deals(self) -> list[dict]
    def health(self) -> dict
        # {"ok", "git_sha", "bundle_sha", "facts_sha", "template_sha", "model", "budget", "rss_mb", "bundle_meta"}
        # never spend amounts

# service/app.py, service/warm.py (Task 9)
def build_desk(config: Config) -> Desk
def create_app(config: Config | None = None, desk: Desk | None = None) -> FastAPI   # zero args: from_env()
def warm(desk: Desk, examples: list[dict]) -> dict      # {"asked", "cached", "states": {...}}

# facts/labels.py (Task 10)
MACHINE = "machine-built"; HUMAN = "human-labelled (MAUD)"
MACHINE_BUILT_PREFIXES: tuple[str, ...]
def is_machine_built(key: str) -> bool
def tier_label(key: str) -> str | None          # MACHINE | HUMAN | None

# facts/site.py (Task 10)
def render_site(facts: dict, out: Path, examples: list[dict], strict: bool = False) -> list[Path]
    # missing m5_* facts render "pending" unless strict; any other missing fact raises KeyError

# facts/m5.py, facts/report_m5.py (Task 11)
def present_m5(data_m5: Path) -> bool           # data_m5.parent / "live" / "bundle.json" exists
def build_m5(data_m5: Path, live_dir: Path, out_m4: Path, out_m5: Path, prices_path: Path,
             hosting_path: Path) -> dict        # each section once its input exists
def render_m5(f) -> str

# evals/measure.py (Task 11)
def measure(base_url: str, questions: list[str], fresh: list[str], reference: dict | None = None,
            cached=()) -> dict
def reference_hits(ladder, questions: list[str]) -> dict[str, list[int]]

# deploy/smoke.py (Task 12)
def check_health(base, want: dict) -> list[str]  # and check_pages, check_deals, check_search, check_ask,
                                                 # check_invalid, check_burst: each a list of problems
def ledger_over_ssh(target: str)                 # -> a function returning the box's ledger as "rows|usd"
def cap_trip(base, fresh_q, cached_q, ledger) -> dict
    # {"budget_reached", "budget_cached", "ledger_unchanged", "health_budget"}

# pipeline/cli.py (Tasks 1, 2, 4, 5, 9, 10, 11)
M5_STAGES = {"parity": _m5_parity, "recall": _m5_recall, "calibrate": _m5_calibrate, "measure": _m5_measure}
# helpers _out_m5() (OUT/"m5"), _data_m5() (DATA/"m5"), _live_db() (DATA/"live"/"live.db");
# constants ENV_FILE, PRICES, HOSTING, REPORT_M5, EXAMPLES, SITE_DIST;
# commands dtd bundle, dtd m5 <stage>, dtd warm [--examples], dtd site [--strict]
```

---

## Before you start

- **Tasks 1–12** need nothing external: no data download, no key, no server. Their real-data steps (Task 2 Step 10,
  Task 4 Steps 9–10) need the local `data/` from M0–M4, which is already on the development machine.
- **Task 13** needs the `dtd-dev` key in local `.env` as `ANTHROPIC_API_KEY`, and Michael's approval of the
  calibration estimate.
- **Tasks 14–16** need roadmap steps 0.3–0.5:
  - the private GitHub repo;
  - the `dtd-live` Console workspace and key;
  - the Hetzner account with his SSH key, and the DNS host for `forn.al`.
- The plan runs on branch `m5`, which already exists; commit `086185c` holds the spec and the PRD note. Check
  `git config user.email` is the GitHub noreply address before the first commit.

---

### Task 1: Facts-tool gaps, test hazards, the `service` package

**Files:**
- Modify: `tests/test_cli.py:15-43` (the `data` fixture), and add tests at the end
- Modify: `pipeline/cli.py:346-369` (`_cmd_facts`)
- Modify: `tests/test_facts.py` (imports; M1 digit scan at the end)
- Modify: `tests/test_report_m0.py` (imports; M0 committed-render test at the end)
- Create: `service/__init__.py`
- Modify: `pyproject.toml:19` (hatch `packages`)
- Create: `tests/test_packaging.py`

**Interfaces:**
- Consumes: `cli._write_atomic(path, text)` (`pipeline/cli.py:67`), `facts.build.UNSTABLE`, `facts.m2.is_unstable`, `facts.report.render`, `facts.report_m0.render_m0`.
- Produces:
  - `dtd facts --check` exits 1 and prints `facts no longer built: <names>` for stored stable keys a fresh build no longer makes;
  - `facts.json` is always written atomically;
  - the importable package `service`;
  - the `data` fixture redirects every `cli.REPORT*` path, including the `REPORT_M5` added in Task 11, so Task 11 needs no fixture edit.

- [ ] **Step 1: Write the failing tests.**

  In `tests/test_cli.py`, append:

```python
def test_the_data_fixture_redirects_every_report_path(data):
    for name in [n for n in dir(cli) if n.startswith("REPORT")]:
        assert Path(getattr(cli, name)).is_relative_to(data), name


def test_facts_check_fails_on_stored_facts_no_longer_built(data, capsys):
    cli.entry(["build"]); cli.entry(["eval"]); cli.entry(["facts"])
    stored = json.loads((data / "facts.json").read_text())
    stored["m9_leftover"] = 1
    (data / "facts.json").write_text(json.dumps(stored))
    capsys.readouterr()
    assert cli.entry(["facts", "--check"]) == 1
    assert "facts no longer built: m9_leftover" in capsys.readouterr().err


def test_facts_are_written_atomically(data, monkeypatch):
    cli.entry(["build"]); cli.entry(["eval"]); cli.entry(["facts"])
    path = data / "facts.json"
    path.write_text('{"kept": 1}')
    real = Path.replace

    def fail_on_facts(self, target):
        if Path(target).name == "facts.json":
            raise OSError("disk full")
        return real(self, target)
    monkeypatch.setattr(Path, "replace", fail_on_facts)
    with pytest.raises(OSError, match="disk full"):
        cli.entry(["facts"])
    assert path.read_text() == '{"kept": 1}' and not (data / "facts.json.tmp").exists()
```

  Create `tests/test_packaging.py`:

```python
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_service_is_a_packaged_module():
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "service" in cfg["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    import service  # noqa: F401
```

- [ ] **Step 2: Run them and confirm they fail.**

  Run: `uv run pytest tests/test_cli.py::test_the_data_fixture_redirects_every_report_path tests/test_cli.py::test_facts_check_fails_on_stored_facts_no_longer_built tests/test_cli.py::test_facts_are_written_atomically tests/test_packaging.py -v`

  Expected, all FAIL:
  - the fixture test: `REPORT_M4` is the relative `docs/m4/REPORT.md`;
  - the check test returns 0;
  - the atomic test: `DID NOT RAISE`, because `write_text` never calls `replace`;
  - the packaging test: `AssertionError` / `ModuleNotFoundError: service`.

- [ ] **Step 3: Redirect every report path in the fixture.**

  In `tests/test_cli.py`'s `data` fixture, replace these three lines:

```python
    monkeypatch.setattr(cli, "REPORT_M0", tmp_path / "docs" / "m0" / "REPORT.md")
    monkeypatch.setattr(cli, "REPORT_M2", tmp_path / "docs" / "m2" / "REPORT.md")
    monkeypatch.setattr(cli, "REPORT_M3", tmp_path / "docs" / "m3" / "REPORT.md")
```

  with:

```python
    # Every report path, present and future, lands under tmp_path (docs/mN/REPORT.md keeps its shape), so no
    # test can overwrite a committed report. REPORT itself keeps its older flat location below.
    for name in [n for n in dir(cli) if n.startswith("REPORT")]:
        monkeypatch.setattr(cli, name, tmp_path / getattr(cli, name))
```

  Keep the existing `monkeypatch.setattr(cli, "REPORT", tmp_path / "docs" / "REPORT.md")` line, and make sure it runs *after* the loop: move it to just below the loop. M0, M2 and M3 get the same paths as before, and M4 (plus M5 later) is now redirected too.

- [ ] **Step 4: Atomic write and stale-key check in `_cmd_facts`.**

  In `pipeline/cli.py`, replace the block from `if args.check:` to the end of `_cmd_facts` with:

```python
    if args.check:
        stored = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.exists() else {}

        def stable(n: str) -> bool:
            return n not in UNSTABLE and not is_unstable(n)
        stale = sorted(n for n in fresh if stable(n) and stored.get(n) != fresh[n])
        gone = sorted(n for n in stored if n not in fresh and stable(n))
        if stale:
            print("stale facts: " + ", ".join(stale), file=sys.stderr)
        if gone:
            print("facts no longer built: " + ", ".join(gone), file=sys.stderr)
        return 1 if stale or gone else 0
    _write_atomic(FACTS, json.dumps(fresh, indent=2, sort_keys=True) + "\n")
    return 0
```

- [ ] **Step 5: Add the `service` package.**

  Create `service/__init__.py`:

```python
"""The live service (M5): the Desk behind /api, its spend ledger, answer cache and request limits."""
```

  In `pyproject.toml`, change the hatch packages line to:

```toml
packages = ["pipeline", "retrieval", "evals", "facts", "answer", "service"]
```

- [ ] **Step 6: Add the two missing report guards.**

  Both pass today, checked on 2026-10-05:
  - M2's allowlist, which already allows the CI level "95%", clears every digit in the M1 report;
  - `docs/m0/REPORT.md` equals `render_m0` of the committed facts.

  They are regression guards, so no copy change is needed.

  In `tests/test_facts.py`, add `import re` to the imports, then append:

```python
class _Every(dict):
    """Any fact renders as a sentinel number, so the template is checked, not the data."""
    def __missing__(self, key):
        return 7777.0


# Identifiers and the pinned CI level, not figures (the CI level is pinned by
# test_bootstrap_quantiles_match_the_reports_95_percent; same allowlist as tests/test_report_m2.py).
M1_ALLOWED = re.compile(r"BM25|recall@\d+|MRR@\d+|nDCG@\d+|\bR\d\b|\bM\d\b|p50|p95|95%")


def test_every_digit_in_the_m1_report_comes_from_facts():
    text = render(_Every()).replace("7777.0", "")
    stray = [line for line in text.splitlines() if re.search(r"\d", M1_ALLOWED.sub("", line))]
    assert stray == []
```

  In `tests/test_report_m0.py`, add the imports `import json`, `from pathlib import Path` and `import pytest`, then append:

```python
def test_committed_m0_report_is_rendered_from_committed_facts():
    root = Path(__file__).resolve().parent.parent
    f = json.loads((root / "facts.json").read_text(encoding="utf-8"))
    if "m0_gate_pass" not in f:
        pytest.skip("M0 facts not committed")
    assert (root / "docs" / "m0" / "REPORT.md").read_text(encoding="utf-8") == render_m0(f)
```

- [ ] **Step 7: Run the new tests and the suite.**

  Run: `uv run pytest tests/test_cli.py tests/test_facts.py tests/test_report_m0.py tests/test_packaging.py -v`

  Expected: PASS.

  Then run `uv run pytest -q`. Expected: all pass.

- [ ] **Step 8: Real-data check of the stricter `--check`.**

  Run: `uv run dtd facts --check; echo exit=$?`

  Expected: `exit=0`. If it prints `facts no longer built: …`, those keys are leftovers in the committed `facts.json`:
  1. run `uv run dtd facts && uv run dtd report`;
  2. confirm `git diff --stat facts.json docs/` shows only `facts.json` changing;
  3. confirm `git diff facts.json` only removes the listed keys;
  4. re-run `uv run dtd facts --check` and expect `exit=0`.

- [ ] **Step 9: Commit.**

```bash
git add tests/test_cli.py pipeline/cli.py tests/test_facts.py tests/test_report_m0.py service/__init__.py pyproject.toml tests/test_packaging.py
git add facts.json  # only if Step 8 removed leftover keys
git commit -q -F - <<'EOF'
m5: facts --check flags keys no longer built, facts.json written atomically, tests cannot overwrite any report, M1/M0 report guards, service package

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 2: One live answer path

**Files:**
- Modify: `retrieval/scope.py` (append `scope_question`)
- Modify: `retrieval/ladder.py:11` (import), `:15` (add `RETRIEVAL_FOR`), `:81-90` (R7/R7n block)
- Modify: `answer/answerer.py:11-12` (imports), `:128-155` (`Answerer.__init__`, `prepare`)
- Create: `evals/live_parity.py`
- Modify: `pipeline/cli.py` (imports; `_out_m5`, `_data_m5`, `_no_model_call`, `_m5_parity`, `M5_STAGES`, `_cmd_m5`; the `m5` subparser)
- Test: `tests/test_scope.py`, `tests/test_ladder.py`, `tests/test_answerer.py`, `tests/test_live_parity.py` (new), `tests/test_cli.py`

**Interfaces:**
- Consumes: `Resolver.resolve`, `Resolver.conn`, `strip_alias`, `Scope`, `load_answer_path`, `evals.run_answers.load_answers(ledger_path, model, items)`, `evals.answer_sets.read_items`, `cli._ladder`, `cli._deals_ladder`, `cli._deals_texts`, `cli.HAIKU`.
- Produces:
  - `scope_question(resolver, question, contract_id=None) -> tuple[Scope, str]` and `RETRIEVAL_FOR = {"R7n": "R6n"}`;
  - `Answerer(ladder, runner, model, answer_path=None)` with `.answer_path`;
  - `Ladder.run("R7"|"R7n", q, contract_id)` honours `contract_id`;
  - `prompt_parity(items, answerer, records) -> {"checked", "same", "differ": [item_id, …]}`;
  - `cli._out_m5()` (`OUT/"m5"`) and `cli._data_m5()` (`DATA/"m5"`);
  - the `M5_STAGES` dict and the `dtd m5 <stage>` subparser.
  - Task 4 adds `"recall"`, Task 5 `"calibrate"` (with `--n`, `--max-tokens`), and Task 11 `"measure"` (with `--base`). Each inserts its `_m5_*` function above `M5_STAGES` and adds its entry to the dict literal. `choices=tuple(M5_STAGES)` picks them up.

- [ ] **Step 1: Write the failing scope tests.**

  In `tests/test_scope.py`, change the imports to:

```python
import sqlite3

import pytest

from retrieval.index import build_index
from retrieval.scope import Resolver, Scope, scope_question, strip_alias
```

  Append:

```python
def test_scope_question_keeps_a_picked_deal_and_drops_every_name_of_it_longest_first():
    r = make([("acme software", "edgar_1", "target"), ("acme", "edgar_1", "target"),
              ("big parent", "edgar_1", "parent"), ("zeta", "edgar_2", "target")])
    assert scope_question(r, "Acme Software and Big Parent fee", "edgar_1") == (Scope("edgar_1", None, ()), "and fee")
    # another deal's name is left alone: the visitor picked edgar_1
    assert scope_question(r, "Zeta fee", "edgar_1") == (Scope("edgar_1", None, ()), "Zeta fee")


def test_scope_question_without_a_resolver_keeps_a_picked_question_as_is():
    assert scope_question(None, "Acme fee", "contract_1") == (Scope("contract_1", None, ()), "Acme fee")


def test_scope_question_resolves_and_strips_only_when_one_deal_is_found():
    r = make([("acme software", "edgar_1", "target"), ("oracle", "edgar_2", "parent"), ("oracle", "edgar_3", "parent")])
    assert scope_question(r, "Acme Software fee") == (Scope("edgar_1", "acme software", ("edgar_1",)), "fee")
    assert scope_question(r, "Oracle fee") == (Scope(None, "oracle", ("edgar_2", "edgar_3")), "Oracle fee")
    assert scope_question(r, "fee") == (Scope(None, None, ()), "fee")


def test_scope_question_needs_a_resolver_when_no_deal_is_picked():
    with pytest.raises(ValueError, match="resolver"):
        scope_question(None, "fee")
```

- [ ] **Step 2: Write the failing ladder and answerer tests.**

  In `tests/test_ladder.py`, replace `_spy_r6` with a version that takes the rung (existing callers keep working):

```python
def _spy_r6(ladder, rung="R6"):
    seen, real = [], ladder.run

    def run(rung_, query, contract_id=None, k=10, rewritten=None):
        if rung_ == rung:
            seen.append((query, contract_id))
        return real(rung_, query, contract_id, k, rewritten)
    ladder.run = run
    return seen
```

  Then append:

```python
def test_r7n_keeps_a_picked_deal_and_drops_only_its_own_names(deals_ladder):
    seen = _spy_r6(deals_ladder, "R6n")
    got = deals_ladder.run("R7n", "Acme Software outside date", "contract_1", k=5)
    assert got.scope == Scope("contract_1", None, ())
    assert got.hits and all(h.contract_id == "contract_1" for h in got.hits)
    assert seen == [("Acme Software outside date", "contract_1")]
    seen.clear()
    deals_ladder.run("R7n", "What is the Acme Software outside date?", "edgar_0001", k=5)
    assert seen == [("What is the outside date", "edgar_0001")]
```

  In `tests/test_answerer.py`, append:

```python
def _spy_r6n(ladder):
    seen, real = [], ladder.run

    def run(rung, query, contract_id=None, k=10, rewritten=None):
        if rung == "R6n":
            seen.append((query, contract_id))
        return real(rung, query, contract_id, k, rewritten)
    ladder.run = run
    return seen


@pytest.mark.parametrize("question,picked", [("What is the Acme Software outside date?", None),
                                             ("What is the Acme Software outside date?", "edgar_0001"),
                                             ("Acme Software outside date", "contract_1")])
def test_the_answerer_and_r7n_search_the_same_words_in_the_same_deal(deals_ladder, question, picked):
    seen = _spy_r6n(deals_ladder)
    deals_ladder.run("R7n", question, picked, k=5)
    via_ladder = list(seen)
    seen.clear()
    Answerer(deals_ladder, fake_claude(""), "m").prepare(question, picked)
    assert seen == via_ladder and len(seen) == 1


def test_the_answer_path_comes_from_settings_and_only_r7n_is_accepted(ladder, monkeypatch):
    import answer.answerer as A
    assert Answerer(ladder, fake_claude(""), "m").answer_path == "R7n"
    with pytest.raises(ValueError, match="'R6n'"):
        Answerer(ladder, fake_claude(""), "m", answer_path="R6n")
    monkeypatch.setattr(A, "load_answer_path", lambda: "R4")
    with pytest.raises(ValueError, match="'R4'"):
        Answerer(ladder, fake_claude(""), "m")


# prompt_sha from the M4 code (main a92fcfd, before this task) on these fixtures: the refactor must not move them.
GOLDEN = [
    ("deals", "What is the Acme Software outside date?", None, "5419b0b3f91d", ("edgar_0001",)),
    ("deals", "termination fee", "edgar_0001", "c814656a0121", ()),
    ("deals", "What is the Acme Software outside date?", "edgar_0001", "5419b0b3f91d", ()),
    ("deals", "Acme Software outside date", "contract_1", "2a2f69169918", ()),
    ("maud", "termination fee", "big", "d9e95ed716b4", ()),
    ("maud", "Who pays the walk-away payment?", "big", "2f0d4bff5bdf", ()),
    ("maud", "closing", "tiny", "c06935ff3a20", ()),
]


@pytest.mark.parametrize("which,question,picked,sha,candidates", GOLDEN)
def test_prompts_are_byte_identical_to_m4s(request, which, question, picked, sha, candidates):
    lad = request.getfixturevalue("deals_ladder" if which == "deals" else "ladder")
    p = Answerer(lad, fake_claude(""), "m").prepare(question, picked)
    assert isinstance(p, Prepared) and p.prompt_sha == sha and p.candidates == candidates
```

  Create `tests/test_live_parity.py`:

```python
from answer.answerer import Answerer
from evals.answer_sets import AnswerItem
from evals.live_parity import prompt_parity
from tests.fakes import fake_claude
from tests.test_ladder import deals_ladder  # noqa: F401


def item(i, question, cid=None):
    return AnswerItem(f"i{i}", "tmachine", "termination_fee", "test", cid, question)


def test_prompt_parity_compares_recorded_hashes_and_skips_failed_calls(deals_ladder):
    run = fake_claude("")
    ans = Answerer(deals_ladder, run, "m")
    items = [item(1, "What is the Acme Software outside date?"), item(2, "termination fee", "edgar_0001"),
             item(3, "outside date", "edgar_0001"), item(4, "What is the outside date for Zeta Labs?"),
             item(5, "closing", "contract_1")]
    sha = {i.item_id: ans.prepare(i.question, i.contract_id).prompt_sha for i in items}
    records = {"i1": {"answer": {"prompt_sha": sha["i1"]}},
               "i2": {"answer": {"prompt_sha": "stale0000000"}},
               "i3": {"answer": None, "error": "runner: timeout"},  # a failed call has no answer: skipped
               "i4": {"answer": {"prompt_sha": None}}}               # which_deal: no prompt, as recorded
    assert prompt_parity(items, ans, records) == {"checked": 3, "same": 2, "differ": ["i2"]}
    assert run.calls == []
```

  In `tests/test_cli.py`, append:

```python
def test_m5_parity_refuses_without_m4_inputs(data, capsys):
    assert cli.entry(["m5", "parity"]) == 2
    assert "dtd m4 sets" in capsys.readouterr().err
```

- [ ] **Step 3: Run them and confirm they fail.**

  Run: `uv run pytest tests/test_scope.py tests/test_ladder.py tests/test_answerer.py tests/test_live_parity.py tests/test_cli.py::test_m5_parity_refuses_without_m4_inputs -q`

  Expected FAIL:
  - `ImportError: cannot import name 'scope_question'` (test_scope);
  - the R7n picked-deal test (scope resolves to `edgar_0001`);
  - the `contract_1` case of the same-words test;
  - the answer-path test (`TypeError: unexpected keyword 'answer_path'`);
  - `ModuleNotFoundError: evals.live_parity`;
  - the CLI test (`invalid choice: 'm5'`, SystemExit 2 from argparse; this may show as PASS for the wrong reason, so check the message).

  The GOLDEN cases PASS already. That is intended: they pin today's prompts.

- [ ] **Step 4: Implement `scope_question`.**

  Append to `retrieval/scope.py`:

```python
def scope_question(resolver: "Resolver | None", question: str,
                   contract_id: str | None = None) -> tuple[Scope, str]:
    """The deal a question is about, and the question to search it with. Inside one agreement the company's own
    name is everywhere, so it only misleads the search and is dropped.

    A picked deal (contract_id) is taken as given: every alias of it is dropped, longest first, and the question is
    unchanged when there is no resolver (the MAUD index has no aliases). Otherwise the resolver decides, and the
    alias it matched is dropped only when it found exactly one deal."""
    if contract_id is not None:
        q = question
        if resolver is not None:
            rows = resolver.conn.execute("SELECT alias FROM aliases WHERE contract_id = ?", (contract_id,))
            for (alias,) in sorted(rows, key=lambda r: -len(r[0])):
                q = strip_alias(q, alias)
        return Scope(contract_id, None, ()), q
    if resolver is None:
        raise ValueError("a question with no picked deal needs a resolver over the deals index")
    scope = resolver.resolve(question)
    return scope, (strip_alias(question, scope.alias) if scope.contract_id else question)
```

- [ ] **Step 5: R7/R7n use it and honour a picked deal.**

  In `retrieval/ladder.py`, replace `from retrieval.scope import strip_alias` with `from retrieval.scope import scope_question`. Below `ANSWER_RUNGS`, add:

```python
# The answer path settings.json names -> the rung run inside the deal once the Answerer has scoped the question.
RETRIEVAL_FOR = {"R7n": "R6n"}
```

  Replace the `if rung in ("R7", "R7n"):` block with:

```python
        if rung in ("R7", "R7n"):
            if self.resolver is None:
                raise ValueError(f"{rung} needs a resolver over the deals index")
            t0 = time.perf_counter()
            # A picked deal is kept; otherwise the resolver finds one. Either way the deal's own name is dropped.
            scope, q = scope_question(self.resolver, query, contract_id)
            resolve_ms = (time.perf_counter() - t0) * 1000.0
            got = self.run("R6" if rung == "R7" else "R6n", q, scope.contract_id, k, rewritten)
            return replace(got, scope=scope, ms=got.ms + resolve_ms)
```

- [ ] **Step 6: The Answerer reads its path from settings and uses `scope_question`.**

  In `answer/answerer.py`, replace the import `from retrieval.scope import strip_alias` with:

```python
from retrieval.ladder import RETRIEVAL_FOR, load_answer_path
from retrieval.scope import scope_question
```

  Replace the class docstring, `__init__` and the body of `prepare` up to and including the `got = self.ladder.run(...)` line with:

```python
class Answerer:
    """The answer path named in settings (`answer_path`; only R7n): the question is scoped to one deal, picked or
    resolved from the name it gives, with the deal's own name dropped; then R6n retrieves inside that deal."""

    def __init__(self, ladder, runner, model: str, answer_path: str | None = None):
        path = answer_path if answer_path is not None else load_answer_path()
        if path not in RETRIEVAL_FOR:
            raise ValueError(f"answer path {path!r} is not supported; expected one of {sorted(RETRIEVAL_FOR)}")
        self.ladder, self.runner, self.model, self.answer_path = ladder, runner, model, path

    def prepare(self, question: str, contract_id: str | None = None, choices: tuple[str, ...] = ()) -> Prepared | Answer:
        t0 = time.perf_counter()
        if contract_id is None and self.ladder.resolver is None:
            return Answer("which_deal", retrieval_ms=(time.perf_counter() - t0) * 1000.0)
        scope, q = scope_question(self.ladder.resolver, question, contract_id)
        if scope.contract_id is None:
            return Answer("which_deal", candidates=scope.candidates,
                          retrieval_ms=(time.perf_counter() - t0) * 1000.0)
        contract_id, candidates = scope.contract_id, scope.candidates
        got = self.ladder.run(RETRIEVAL_FOR[self.answer_path], q, contract_id, CONTEXT_K)
```

  The rest of `prepare` (from `ms = …` on), and `finish` and `ask`, are unchanged.

- [ ] **Step 7: The parity helper.**

  Create `evals/live_parity.py`:

```python
"""Checks that the live path is the measured one: prompts M4 answered, and R7n over the live bundle."""


def prompt_parity(items, answerer, records: dict[str, dict]) -> dict:
    """Re-prepare every item that has an answer record and compare its prompt's hash with the recorded one. A
    preparation that ends without a model call (which_deal, not_stated) has no hash, as its record has none. A
    record without an answer (a failed call) is skipped. Never calls the model."""
    checked, same, differ = 0, 0, []
    for item in items:
        rec = records.get(item.item_id)
        if not rec or rec.get("answer") is None:
            continue
        now = answerer.prepare(item.question, item.contract_id, item.choices).prompt_sha
        checked += 1
        if now == rec["answer"].get("prompt_sha"):
            same += 1
        else:
            differ.append(item.item_id)
    return {"checked": checked, "same": same, "differ": differ}
```

- [ ] **Step 8: `dtd m5 parity`.**

  In `pipeline/cli.py`, add `from evals.live_parity import prompt_parity` to the imports. After `_cmd_m4`, add:

```python
def _out_m5() -> Path:
    return OUT / "m5"


def _data_m5() -> Path:
    return DATA / "m5"


def _no_model_call(prompt, model):
    raise RuntimeError("this stage only prepares prompts; it never calls a model")


def _m5_parity(args) -> int:
    """Re-prepare every M4 answer item with the ladder M4 used and compare each prompt's hash with the ledgered
    one, so the live answer path is provably the measured one. Exit 1 if any differ."""
    sets = ("thuman", "tmachine", "abstain")
    needed = ([INDEX, DEALS_INDEX] + [_data_m4() / f"{s}_items.jsonl" for s in sets]
              + [_data_m4() / f"answers_{s}_{HAIKU}.jsonl" for s in sets])
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        print("missing: " + ", ".join(missing) + "; run M3, `dtd m4 sets` and `dtd m4 answer` first",
              file=sys.stderr)
        return 2
    out, deals = {}, None
    for s in sets:
        items = read_items(_data_m4() / f"{s}_items.jsonl")
        records = load_answers(_data_m4() / f"answers_{s}_{HAIKU}.jsonl", HAIKU, items)
        if s == "thuman":  # as `dtd m4 answer`: T-human on maud.db, the other sets on deals.db
            ladder = _ladder(INDEX, {p.stem: load_contract(p) for p in sorted((RAW / "contracts").glob("*.txt"))})
        else:
            deals = deals or _deals_ladder(*_deals_texts())
            ladder = deals
        out[s] = prompt_parity(items, Answerer(ladder, _no_model_call, HAIKU), records)
        print(json.dumps({s: {"checked": out[s]["checked"], "same": out[s]["same"]}}), file=sys.stderr, flush=True)
    _out_m5().mkdir(parents=True, exist_ok=True)
    _write_atomic(_out_m5() / "parity.json", json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({s: {"checked": v["checked"], "same": v["same"]} for s, v in out.items()}))
    return 1 if any(v["differ"] for v in out.values()) else 0


M5_STAGES = {"parity": _m5_parity}  # Tasks 4, 5 and 11 add recall, calibrate and measure


def _cmd_m5(args) -> int:
    return M5_STAGES[args.stage](args)
```

  In `entry`, after the `m4p` block, add:

```python
    m5p = sub.add_parser("m5")
    m5p.add_argument("stage", choices=tuple(M5_STAGES))
    m5p.set_defaults(fn=_cmd_m5)
```

- [ ] **Step 9: Run the tests.**

  Run: `uv run pytest tests/test_scope.py tests/test_ladder.py tests/test_answerer.py tests/test_live_parity.py tests/test_cli.py -q`

  Expected: PASS. The existing R7 tests (`_spy_r6`, the ambiguous resolver, resolver latency) are unchanged in behaviour.

  Then run `uv run pytest -q`. Expected: all pass.

- [ ] **Step 10: Real-data parity (free, about 10–15 minutes).**

  Run: `uv run dtd m5 parity; echo exit=$?`

  Expected:
  - `exit=0`;
  - `data/out/m5/parity.json` has `"differ": []` for `thuman`, `tmachine` and `abstain`;
  - `checked` close to the ledger counts (about 8.4k, 0.9k and 0.2k answered records);
  - `same == checked` for each.

  If anything differs, stop. The refactor changed the measured path. Fix it in `scope_question` or `prepare` until parity holds; never by editing the ledgers.

- [ ] **Step 11: Commit.**

```bash
git add retrieval/scope.py retrieval/ladder.py answer/answerer.py evals/live_parity.py pipeline/cli.py tests/test_scope.py tests/test_ladder.py tests/test_answerer.py tests/test_live_parity.py tests/test_cli.py
git commit -q -F - <<'EOF'
m5: one live answer path — scope_question shared by R7n and the Answerer, R7n honours a picked deal, answer path enforced from settings; dtd m5 parity proves M4 prompts unchanged

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 3: Per-stage scores for Search

**Files:**
- Modify: `retrieval/result.py` (the `Retrieved` dataclass)
- Modify: `retrieval/ladder.py` (`Ladder.run` below the R7 block; new module function `_stages`)
- Test: `tests/test_ladder.py`

**Interfaces:**
- Consumes: the `legs` list in `Ladder.run` (`ladder.py:105`): `[bm25.search(...), self._dense(...)]`. BM25 hit scores are `-bm25` (higher is better); dense scores are `1 - cosine distance`.
- Produces: `Retrieved.stages: dict[int, dict]`, `{passage_id: {"bm25": {"rank", "score"} | None, "dense": {"rank", "score"} | None}}`.
  - Filled for every returned hit of R3–R6, R6n, and R7/R7n through them; `{}` for R1 and R2.
  - Task 9's `/api/search` reads it.

- [ ] **Step 1: Write the failing tests.**

  Append to `tests/test_ladder.py`:

```python
def test_hybrid_rungs_record_each_legs_rank_and_score(ladder):
    from retrieval import bm25
    got = ladder.run("R3", "counsel", "big", k=5)
    assert set(got.stages) == {h.passage_id for h in got.hits}
    lex = bm25.search(ladder.conn, "counsel", "big", 10)  # R3's BM25 leg at depth 10
    top = lex[0]
    assert got.stages[top.passage_id]["bm25"] == {"rank": 1, "score": top.score}
    assert got.stages[top.passage_id]["dense"]["rank"] >= 1
    dense_only = [s for pid, s in got.stages.items() if pid not in {h.passage_id for h in lex}]
    assert dense_only and all(s["bm25"] is None and s["dense"] is not None for s in dense_only)


def test_stages_leave_the_fused_order_untouched(ladder):
    from retrieval import bm25
    from retrieval.hybrid import rrf
    from retrieval.lexicon import rewrite
    q = "termination fee amount in cash"
    got = ladder.run("R6n", q, "big", k=5)
    rq, depth = rewrite(q, ladder.lexicon), max(5, ladder.settings.depth)
    legs = [bm25.search(ladder.conn, rq, "big", depth, table="passages_x_fts"), ladder._dense(rq, "big", depth)]
    assert got.hits == rrf(legs, ladder.settings.rrf_k0, 2 * depth)[:5]


def test_single_leg_rungs_have_no_stages_and_r7n_and_rerank_keep_them(ladder, deals_ladder):
    assert ladder.run("R1", "termination fee", "big", k=5).stages == {}
    assert ladder.run("R2", "termination fee", "big", k=5).stages == {}
    reranked = ladder.run("R4", "termination fee", "big", k=5)
    assert set(reranked.stages) == {h.passage_id for h in reranked.hits}
    got = deals_ladder.run("R7n", "What is the Acme Software outside date?", k=5)
    assert got.hits and set(got.stages) == {h.passage_id for h in got.hits}
```

- [ ] **Step 2: Run them and confirm they fail.**

  Run: `uv run pytest tests/test_ladder.py -q -k "stages or each_legs"`

  Expected: FAIL with `AttributeError: 'Retrieved' object has no attribute 'stages'`. `test_stages_leave_the_fused_order_untouched` passes already; it guards the order.

- [ ] **Step 3: Add the field.**

  Replace `retrieval/result.py` with:

```python
from dataclasses import dataclass, field

from retrieval.bm25 import Hit

CONTEXT_K = 5


@dataclass(frozen=True)
class Retrieved:
    hits: list[Hit]
    ms: float
    context: list[str]
    amended: tuple[str, ...] = ()
    scope: object = None  # retrieval.scope.Scope | None; set by R7 only (object avoids an import cycle)
    # passage_id -> {"bm25": {"rank", "score"} | None, "dense": {"rank", "score"} | None}: where each returned hit
    # stood in each leg before fusion. Filled for the hybrid rungs (R3-R6, R6n, R7/R7n through them); {} otherwise.
    stages: dict = field(default_factory=dict)
```

- [ ] **Step 4: Record the legs in `Ladder.run`.**

  In `retrieval/ladder.py`, add above `class Ladder`:

```python
def _stages(hits, legs) -> dict:
    """Where each returned hit stood in each leg before fusion: 1-based rank and the leg's own score (BM25: -bm25,
    higher is better; dense: 1 - cosine distance). None where the leg did not return the passage."""
    pos = [{h.passage_id: (rank, h.score) for rank, h in enumerate(leg, start=1)} for leg in legs]
    return {h.passage_id: {name: ({"rank": p[h.passage_id][0], "score": p[h.passage_id][1]}
                                  if h.passage_id in p else None)
                           for name, p in zip(("bm25", "dense"), pos)}
            for h in hits}
```

  In `Ladder.run`, replace everything from `t0 = time.perf_counter()` (the one after the `n >= 5` lexicon check) to the end of the method with the code below. The timing still covers exactly the retrieval it did before; `_stages` runs after `ms` is taken.

```python
        t0 = time.perf_counter()
        adjust = 0.0
        legs = None
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
            if n == 3 or not rerank:
                hits = fused[:k]
            else:
                head = fused[:self.settings.rerank_depth]
                t1 = time.perf_counter()
                scores, compute_ms = self.reranker.score(query, [self._passage(h) for h in head])
                adjust += compute_ms - (time.perf_counter() - t1) * 1000.0
                order = sorted(range(len(head)), key=lambda i: (-scores[i], head[i].passage_id))
                hits = ([replace(head[i], score=scores[i]) for i in order] + fused[len(head):])[:k]
        ms = (time.perf_counter() - t0) * 1000.0 + adjust
        amended = tuple(dict.fromkeys(a[0] for h in hits[:CONTEXT_K] for a in self._amendments(h)))
        return Retrieved(hits, ms, [self._shown(h, n == 6) for h in hits[:CONTEXT_K]], amended,
                         stages=_stages(hits, legs) if legs else {})
```

- [ ] **Step 5: Run the tests.**

  Run: `uv run pytest tests/test_ladder.py tests/test_answerer.py tests/test_run_rung.py -q`

  Expected: PASS. Then run `uv run pytest -q`; expected: all pass.

- [ ] **Step 6: Commit.**

```bash
git add retrieval/result.py retrieval/ladder.py tests/test_ladder.py
git commit -q -F - <<'EOF'
m5: Retrieved.stages records each hit's BM25 and dense rank and score before fusion (fused order unchanged)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 4: Live bundle and live ladder

**Files:**
- Create: `pipeline/bundle.py`
- Create: `retrieval/live.py`
- Modify: `evals/live_parity.py` (append `r7n_parity`)
- Modify: `pipeline/cli.py`:
  - imports;
  - `_live_db`, `_cmd_bundle`, `_m5_recall`, `PARITY_N`;
  - the `M5_STAGES` literal;
  - the `bundle` subparser.
- Test: `tests/test_bundle.py` (new), `tests/test_live.py` (new), `tests/test_live_parity.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes:
  - `deals.db` tables (`contracts`, `passages`, `passages_fts`, `passages_x_fts`, `passages_vec`, `passage_defs`, `deals`, `aliases`, `passage_tags`, `superseded`, `terms`);
  - `pipeline.paths.MAUD_BASE`;
  - `answer.prompt.TEMPLATE_SHA`;
  - `Ladder`, `Settings`, `Resolver`;
  - `evals.run_rung.load_context`, `with_passages`, `evaluate`;
  - `cli._deals_texts`, `cli._deals_ladder`, `cli._models`;
  - Task 2's `M5_STAGES`, `_out_m5`.
- Produces:
  - `build_bundle(deals_db, out, *, texts, amendment_texts, deals_jsonl, settings_path, lexicon_path) -> {"sha256", "bytes", "contracts", "passages", "rebuilt"}`;
  - `bundle_is_current(out) -> bool`, plus `MANIFEST = "bundle.json"` (next to `out`) and `maud_url(cid)`;
  - `open_bundle(path)` (read-only, immutable, any thread);
  - `bundle_meta(conn) -> dict`;
  - `links_for(conn, cid) -> {"filing": url | None, "amendments": {no: url}}`;
  - `build_live_ladder(path, embedder, lexicon, settings) -> Ladder` (reranker None, resolver over the bundle);
  - `r7n_parity(questions, a, b, k=10) -> {"checked", "same", "differ": [{"question", "contract_id"}]}`;
  - `cli._live_db()` (`DATA/"live"/"live.db"`);
  - `dtd bundle`;
  - `dtd m5 recall`, which writes `data/out/m5/bundle_r6n.json`, `bundle_r6n_items.jsonl` and `bundle_parity.json` (Task 11 reads them).
- Bundle tables, beyond `deals.db`'s minus `terms`:
  - `texts(contract_id PK, text)`;
  - `amendment_texts(amendment_id PK, text)`;
  - `links(contract_id, kind 'filing'|'amendment', amendment_no, url)`;
  - `meta(key PK, value)`, whose keys are `deals_db_sha256`, `texts_sha256`, `amendment_texts_sha256`, `deals_jsonl_sha256`, `settings_sha256`, `lexicon_sha256` and `template_sha`.

**Mechanics checked on 2026-10-05 against a fixture:**
- `VACUUM INTO` from a plain connection copies the vec0 and FTS5 tables;
- dense and BM25 results are identical before and after `VACUUM INTO` plus `VACUUM`;
- `file:…?mode=ro&immutable=1` reads with no `-wal`, `-shm` or journal files and refuses writes;
- SQLite is 3.53.1.

- [ ] **Step 1: Write the failing bundle tests.**

  Create `tests/test_bundle.py`:

```python
import json
import sqlite3

import pytest

from answer.prompt import TEMPLATE_SHA
from pipeline.bundle import MANIFEST, build_bundle, bundle_is_current, maud_url
from pipeline.normalise import load_contract
from retrieval.deals import add_deals
from retrieval.index import build_index
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder
from tests.test_amendments import AMEND
from tests.test_deals import deals_inputs

LEXICON = {"walk-away payment": ["Termination Fee"]}


@pytest.fixture
def src(tmp_path):
    deals, texts, amends = deals_inputs(tmp_path)
    db = tmp_path / "src" / "deals.db"
    build_index(db, texts)
    add_deals(db, deals, texts, amends)
    conn, cache, emb = connect(db), open_cache(tmp_path / "src" / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    conn.close()
    jsonl = tmp_path / "src" / "deals.jsonl"
    jsonl.write_text("".join(json.dumps(d) + "\n" for d in deals), encoding="utf-8")
    settings = tmp_path / "src" / "settings.json"
    settings.write_text(json.dumps({"settings": {"depth": 10, "rrf_k0": 60, "reranker": "fake-reranker",
                                                 "rerank_depth": 3}, "answer_path": "R7n"}))
    lexicon = tmp_path / "src" / "lexicon.json"
    lexicon.write_text(json.dumps({"entries": LEXICON}))
    return {"db": db, "texts": texts, "amendment_texts": amends, "deals_jsonl": jsonl, "settings": settings,
            "lexicon": lexicon}


def bundle(src, out):
    return build_bundle(src["db"], out, texts=src["texts"], amendment_texts=src["amendment_texts"],
                        deals_jsonl=src["deals_jsonl"], settings_path=src["settings"], lexicon_path=src["lexicon"])


def test_the_bundle_holds_the_index_texts_and_links_but_not_terms(src, tmp_path):
    out = tmp_path / "live" / "live.db"
    s = bundle(src, out)
    assert s["rebuilt"] and s["contracts"] == 2 and s["passages"] > 0 and bundle_is_current(out)
    conn = sqlite3.connect(out)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "terms" not in names
    assert {"passages_fts", "passages_x_fts", "passages_vec", "deals", "aliases", "superseded", "texts",
            "amendment_texts", "links", "meta"} <= names
    assert dict(conn.execute("SELECT contract_id, text FROM texts")) == src["texts"]
    assert dict(conn.execute("SELECT amendment_id, text FROM amendment_texts")) == {"edgar_0002": AMEND}
    assert sorted(conn.execute("SELECT contract_id, kind, amendment_no, url FROM links")) == sorted([
        ("contract_1", "filing", None, maud_url("contract_1")),
        ("edgar_0001", "filing", None, "https://example.test/a"),
        ("edgar_0001", "amendment", 2, "https://example.test/b")])
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    assert meta["template_sha"] == TEMPLATE_SHA and len(meta["deals_db_sha256"]) == 64
    assert json.loads(out.with_name(MANIFEST).read_text())["sha256"] == s["sha256"]


def test_maud_links_are_the_fetched_contract_urls():
    from pipeline.paths import MAUD_BASE
    assert maud_url("contract_7") == f"{MAUD_BASE}/contracts/contract_7.txt"  # as pipeline/fetch_maud.py fetches


def test_texts_round_trip_load_contract(src, tmp_path):
    d = tmp_path / "files"
    d.mkdir()
    for cid, text in src["texts"].items():
        (d / f"{cid}.txt").write_bytes(("﻿" + text.replace("\n", "\r\n")).encode("utf-8"))
    loaded = {p.stem: load_contract(p) for p in d.glob("*.txt")}
    assert loaded == src["texts"]  # the canonical form undoes the BOM and CRLF
    out = tmp_path / "live.db"
    bundle(dict(src, texts=loaded), out)
    assert dict(sqlite3.connect(out).execute("SELECT contract_id, text FROM texts")) == loaded


def test_a_rerun_with_the_same_inputs_rebuilds_nothing(src, tmp_path):
    out = tmp_path / "live.db"
    first = bundle(src, out)
    mtime = out.stat().st_mtime_ns
    assert bundle(src, out) == first | {"rebuilt": False}
    assert out.stat().st_mtime_ns == mtime


def test_a_changed_input_rebuilds(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    src["lexicon"].write_text(json.dumps({"entries": {"walk-away payment": ["Company Termination Fee"]}}))
    assert bundle(src, out)["rebuilt"] is True


def _no_bundle_files(d):
    return not any((d / n).exists() for n in ("live.db", "live.db.building", MANIFEST, MANIFEST + ".tmp"))


def test_a_kill_mid_build_leaves_no_bundle_and_keeps_an_old_one(src, tmp_path, monkeypatch):
    import pipeline.bundle as B
    out = tmp_path / "live.db"

    def die(*a, **k):  # the process dies after VACUUM INTO, before anything is renamed into place
        raise KeyboardInterrupt
    monkeypatch.setattr(B, "_fill", die)
    with pytest.raises(KeyboardInterrupt):
        bundle(src, out)
    assert _no_bundle_files(tmp_path)
    monkeypatch.undo()
    good = bundle(src, out)
    src["lexicon"].write_text(json.dumps({"entries": {}}))
    monkeypatch.setattr(B, "_fill", die)
    with pytest.raises(KeyboardInterrupt):
        bundle(src, out)
    assert bundle_is_current(out) and json.loads(out.with_name(MANIFEST).read_text())["sha256"] == good["sha256"]
    assert not out.with_name("live.db.building").exists()


def test_a_kill_between_the_two_renames_is_caught_and_rebuilt(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    man = out.with_name(MANIFEST)
    doc = json.loads(man.read_text())
    doc["sha256"] = "0" * 64  # the new db landed, the old manifest did not move
    man.write_text(json.dumps(doc))
    assert not bundle_is_current(out)
    assert bundle(src, out)["rebuilt"] is True and bundle_is_current(out)


def test_an_indexed_contract_without_text_is_refused(src, tmp_path):
    with pytest.raises(ValueError, match="no text"):
        bundle(dict(src, texts={"edgar_0001": src["texts"]["edgar_0001"]}), tmp_path / "live.db")
    assert _no_bundle_files(tmp_path)
```

- [ ] **Step 2: Write the failing live-ladder and parity tests.**

  Create `tests/test_live.py`:

```python
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from answer.prompt import TEMPLATE_SHA
from evals.live_parity import r7n_parity
from pipeline.bundle import maud_url
from retrieval.ladder import Ladder, Settings
from retrieval.live import build_live_ladder, bundle_meta, links_for, open_bundle
from retrieval.scope import Resolver
from retrieval.vectors import connect
from tests.fakes import FakeEmbedder
from tests.test_bundle import LEXICON, bundle, src  # noqa: F401

SETTINGS = Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3)
QUESTIONS = [("What is the Acme Software outside date?", None), ("termination fee", "edgar_0001"),
             ("Acme Software outside date", "contract_1"), ("outside date", None), ("closing date", "contract_1")]


def source_ladder(src):
    conn = connect(src["db"])
    return Ladder(conn, src["texts"], FakeEmbedder(), None, LEXICON, SETTINGS,
                  amendment_texts=src["amendment_texts"], resolver=Resolver(conn))


def test_r7n_over_the_bundle_equals_r7n_over_the_source(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    live, ref = build_live_ladder(out, FakeEmbedder(), LEXICON, SETTINGS), source_ladder(src)
    for q, cid in QUESTIONS:
        a, b = live.run("R7n", q, cid, 5), ref.run("R7n", q, cid, 5)
        assert [h.passage_id for h in a.hits] == [h.passage_id for h in b.hits]
        assert a.context == b.context and a.scope == b.scope and a.amended == b.amended
    assert r7n_parity(QUESTIONS, live, ref, k=5) == {"checked": 5, "same": 5, "differ": []}


def test_the_bundle_is_read_only_and_reading_it_writes_no_files(src, tmp_path):
    out = tmp_path / "live" / "live.db"
    bundle(src, out)
    before = sorted(p.name for p in out.parent.iterdir())
    ladder = build_live_ladder(out, FakeEmbedder(), LEXICON, SETTINGS)
    assert ladder.reranker is None
    assert ladder.run("R7n", "What is the Acme Software outside date?", None, 5).hits
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ladder.conn.execute("CREATE TABLE x(a)")
    assert sorted(p.name for p in out.parent.iterdir()) == before


def test_open_bundle_works_from_another_thread_and_a_path_with_spaces(src, tmp_path):
    out = tmp_path / "a dir" / "live.db"
    bundle(src, out)
    conn = open_bundle(out)
    with ThreadPoolExecutor(1) as ex:
        n = ex.submit(lambda: conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]).result()
    assert n > 0


def test_meta_and_links(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    conn = open_bundle(out)
    assert bundle_meta(conn)["template_sha"] == TEMPLATE_SHA
    assert links_for(conn, "edgar_0001") == {"filing": "https://example.test/a",
                                             "amendments": {2: "https://example.test/b"}}
    assert links_for(conn, "contract_1") == {"filing": maud_url("contract_1"), "amendments": {}}
    assert links_for(conn, "nope") == {"filing": None, "amendments": {}}


def test_open_bundle_without_a_file_names_the_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="dtd bundle"):
        open_bundle(tmp_path / "missing.db")
```

  In `tests/test_live_parity.py`, change the import `from evals.live_parity import prompt_parity` to
  `from evals.live_parity import prompt_parity, r7n_parity`, then append:

```python
def test_r7n_parity_names_the_questions_that_differ():
    from retrieval.bm25 import Hit
    from retrieval.result import Retrieved

    class L:
        def __init__(self, ids):
            self.ids = ids

        def run(self, rung, q, cid, k):
            assert rung == "R7n"
            return Retrieved([Hit(i, "c", 0, 1, 1.0) for i in self.ids[q]], 1.0, [], ())
    a, b = L({"x": [1, 2], "y": [3]}), L({"x": [1, 2], "y": [4]})
    assert r7n_parity([("x", None), ("y", "c")], a, b) == {
        "checked": 2, "same": 1, "differ": [{"question": "y", "contract_id": "c"}]}
```

  Append to `tests/test_cli.py`:

```python
def test_bundle_builds_the_live_file_and_skips_an_unchanged_rerun(data, monkeypatch, capsys):
    _m3_setup(data, monkeypatch)
    assert cli.entry(["embed", "--deals"]) == 0
    (data / "settings.json").write_text(json.dumps({"settings": {}, "answer_path": "R7n"}))
    (data / "lexicon.json").write_text(json.dumps({"entries": {}}))
    capsys.readouterr()
    assert cli.entry(["bundle"]) == 0
    first = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert first["rebuilt"] and (data / "data" / "live" / "live.db").exists()
    assert (data / "data" / "live" / "bundle.json").exists()
    assert cli.entry(["bundle"]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == first | {"rebuilt": False}


def test_bundle_before_embed_deals_names_the_command(data, capsys):
    assert cli.entry(["bundle"]) == 2
    assert "dtd embed --deals" in capsys.readouterr().err
    assert not (data / "index" / "deals.db").exists()  # the check did not create an empty index


def test_m5_recall_refuses_without_a_current_bundle(data, capsys):
    assert cli.entry(["m5", "recall"]) == 2
    assert "dtd bundle" in capsys.readouterr().err
```

- [ ] **Step 3: Run them and confirm they fail.**

  Run: `uv run pytest tests/test_bundle.py tests/test_live.py tests/test_live_parity.py tests/test_cli.py -q -k "bundle or live or parity or recall"`

  Expected FAIL:
  - `ModuleNotFoundError: pipeline.bundle` and `retrieval.live`;
  - `ImportError: r7n_parity`;
  - argparse `invalid choice: 'bundle'` and `'recall'`.

- [ ] **Step 4: Implement `pipeline/bundle.py`.**

```python
"""The live bundle: one read-only SQLite file the server loads. It is deals.db (the index the evals measured)
plus the contract texts, the amendment texts and the links a visitor follows, minus the `terms` table, which
nothing reads at query time. It is built through a temp file, then renamed into place with its manifest, so a kill
leaves either the previous bundle or none."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from answer.prompt import TEMPLATE_SHA
from pipeline.paths import MAUD_BASE

MANIFEST = "bundle.json"
EXTRA = """
CREATE TABLE texts(contract_id TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE amendment_texts(amendment_id TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE links(contract_id TEXT NOT NULL, kind TEXT NOT NULL, amendment_no INTEGER, url TEXT NOT NULL);
CREATE INDEX links_contract ON links(contract_id);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def maud_url(contract_id: str) -> str:
    """Where pipeline/fetch_maud.py fetched the agreement text (MAUD on Hugging Face, pinned revision)."""
    return f"{MAUD_BASE}/contracts/{contract_id}.txt"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _sha256_texts(texts: dict[str, str]) -> str:
    h = hashlib.sha256()
    for cid in sorted(texts):
        h.update(cid.encode("utf-8") + b"\0" + texts[cid].encode("utf-8") + b"\0")
    return h.hexdigest()


def _inputs(deals_db: Path, texts, amendment_texts, deals_jsonl: Path, settings_path: Path,
            lexicon_path: Path) -> dict[str, str]:
    return {"deals_db_sha256": _sha256_file(deals_db), "texts_sha256": _sha256_texts(texts),
            "amendment_texts_sha256": _sha256_texts(amendment_texts),
            "deals_jsonl_sha256": _sha256_file(deals_jsonl), "settings_sha256": _sha256_file(settings_path),
            "lexicon_sha256": _sha256_file(lexicon_path), "template_sha": TEMPLATE_SHA}


def bundle_is_current(out: Path) -> bool:
    """The bundle matches the sha its manifest records. Both are renamed into place, the db first, so a kill
    between the renames leaves a mismatch (rebuilt next run), never a false match."""
    out = Path(out)
    man = out.with_name(MANIFEST)
    if not (out.exists() and man.exists()):
        return False
    try:
        doc = json.loads(man.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return doc.get("sha256") == _sha256_file(out)


def _fill(conn: sqlite3.Connection, texts: dict[str, str], amendment_texts: dict[str, str], deals_jsonl: Path,
          meta: dict[str, str]) -> None:
    conn.execute("DROP TABLE IF EXISTS terms")
    conn.executescript(EXTRA)
    cids = [r[0] for r in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id")]
    missing = [c for c in cids if c not in texts]
    if missing:
        raise ValueError(f"{len(missing)} indexed contracts have no text, e.g. {missing[0]}")
    conn.executemany("INSERT INTO texts VALUES (?, ?)", [(c, texts[c]) for c in cids])
    linked = conn.execute("SELECT DISTINCT amendment_id, amendment_no FROM superseded ORDER BY amendment_id").fetchall()
    gone = sorted({a for a, _ in linked if a not in amendment_texts})
    if gone:
        raise ValueError(f"{len(gone)} linked amendments have no text, e.g. {gone[0]}")
    conn.executemany("INSERT OR IGNORE INTO amendment_texts VALUES (?, ?)",
                     [(a, amendment_texts[a]) for a, _ in linked])
    for cid, source, url in conn.execute("SELECT contract_id, source, url FROM deals ORDER BY contract_id").fetchall():
        filing = url if source == "edgar" else maud_url(cid)
        if filing:
            conn.execute("INSERT INTO links VALUES (?, 'filing', NULL, ?)", (cid, filing))
    urls: dict[str, tuple[str, str]] = {}
    for line in Path(deals_jsonl).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            for am in d.get("amendments", []):
                if am.get("url"):
                    urls[am["contract_id"]] = (d["contract_id"], am["url"])
    for aid, no in linked:
        if aid in urls:
            cid, url = urls[aid]
            conn.execute("INSERT INTO links VALUES (?, 'amendment', ?, ?)", (cid, no, url))
    conn.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))


def build_bundle(deals_db: Path, out: Path, *, texts: dict[str, str], amendment_texts: dict[str, str],
                 deals_jsonl: Path, settings_path: Path, lexicon_path: Path) -> dict:
    deals_db, out = Path(deals_db), Path(out)
    man = out.with_name(MANIFEST)
    meta = _inputs(deals_db, texts, amendment_texts, Path(deals_jsonl), Path(settings_path), Path(lexicon_path))
    keys = ("sha256", "bytes", "contracts", "passages")
    if bundle_is_current(out):
        doc = json.loads(man.read_text(encoding="utf-8"))
        if doc.get("meta") == meta:
            return {k: doc[k] for k in keys} | {"rebuilt": False}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".building")
    part = man.with_name(man.name + ".tmp")
    tmp.unlink(missing_ok=True)  # a SIGKILLed earlier build leaves this behind; VACUUM INTO refuses an existing file
    try:
        src = sqlite3.connect(deals_db)
        try:
            src.execute("VACUUM INTO ?", (str(tmp),))
        finally:
            src.close()
        conn = sqlite3.connect(tmp)
        try:
            _fill(conn, texts, amendment_texts, Path(deals_jsonl), meta)
            conn.commit()
            conn.execute("VACUUM")
            counts = {"contracts": conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0],
                      "passages": conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]}
        finally:
            conn.close()
        doc = {"sha256": _sha256_file(tmp), "bytes": tmp.stat().st_size, **counts, "meta": meta}
        part.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, out)
        os.replace(part, man)
    finally:
        tmp.unlink(missing_ok=True)
        part.unlink(missing_ok=True)
    return {k: doc[k] for k in keys} | {"rebuilt": True}
```

- [ ] **Step 5: Implement `retrieval/live.py`.**

```python
"""The live index: the bundle opened read-only, and the R7n ladder over it (no reranker model is loaded)."""
import sqlite3
import urllib.parse
from pathlib import Path

import sqlite_vec

from retrieval.ladder import Ladder, Settings
from retrieval.scope import Resolver


def open_bundle(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: no journal, no lock or -wal/-shm files, and every write is refused. Usable from any
    thread; callers serialise access (the service holds one lock around retrieval)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `dtd bundle` first")
    uri = f"file:{urllib.parse.quote(str(path.resolve()))}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def bundle_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM meta"))


def links_for(conn: sqlite3.Connection, contract_id: str) -> dict:
    """The filing a visitor can open for an agreement, and the filing of each amendment by its number."""
    out: dict = {"filing": None, "amendments": {}}
    for kind, no, url in conn.execute("SELECT kind, amendment_no, url FROM links WHERE contract_id = ?"
                                      " ORDER BY kind, amendment_no", (contract_id,)):
        if kind == "filing":
            out["filing"] = url
        else:
            out["amendments"][no] = url
    return out


def build_live_ladder(path: Path, embedder, lexicon: dict, settings: Settings) -> Ladder:
    conn = open_bundle(path)
    texts = dict(conn.execute("SELECT contract_id, text FROM texts"))
    amendment_texts = dict(conn.execute("SELECT amendment_id, text FROM amendment_texts"))
    return Ladder(conn, texts, embedder, None, lexicon, settings, amendment_texts=amendment_texts,
                  resolver=Resolver(conn))
```

- [ ] **Step 6: Add `r7n_parity`.**

  Append to `evals/live_parity.py`:

```python
def r7n_parity(questions: list[tuple[str, str | None]], a, b, k: int = 10) -> dict:
    """R7n through two ladders (the live bundle and the deals.db the evals used): same hits in the same order, same
    shown context and same scope for every question, or the questions where they differ."""
    checked, same, differ = 0, 0, []
    for q, cid in questions:
        ra, rb = a.run("R7n", q, cid, k), b.run("R7n", q, cid, k)
        checked += 1
        if ([h.passage_id for h in ra.hits] == [h.passage_id for h in rb.hits] and ra.context == rb.context
                and ra.scope == rb.scope):
            same += 1
        else:
            differ.append({"question": q, "contract_id": cid})
    return {"checked": checked, "same": same, "differ": differ}
```

- [ ] **Step 7: `dtd bundle` and `dtd m5 recall`.**

  In `pipeline/cli.py`, add `import hashlib` to the stdlib imports and these to the project imports:

```python
from evals.live_parity import prompt_parity, r7n_parity
from pipeline.bundle import MANIFEST, build_bundle, bundle_is_current
from retrieval.live import build_live_ladder
```

  This replaces Task 2's single `prompt_parity` import line. Add after `_build_deals`:

```python
def _live_db() -> Path:
    return DATA / "live" / "live.db"


def _cmd_bundle(args) -> int:
    if not DEALS_INDEX.exists() or not _has_vectors(DEALS_INDEX):
        print("deals index missing or has no vectors; run `dtd build --deals` then `dtd embed --deals` first",
              file=sys.stderr)
        return 2
    if not (EDGAR / "deals.jsonl").exists():
        print(f"{EDGAR / 'deals.jsonl'} missing; run `dtd m3 corpus` first", file=sys.stderr)
        return 2
    if not (SETTINGS_PATH.exists() and LEXICON_PATH.exists()):
        print("retrieval settings or lexicon missing; run `dtd tune` and `dtd lexicon` first", file=sys.stderr)
        return 2
    contracts, amendment_texts = _deals_texts()
    try:
        summary = build_bundle(DEALS_INDEX, _live_db(), texts=contracts, amendment_texts=amendment_texts,
                               deals_jsonl=EDGAR / "deals.jsonl", settings_path=SETTINGS_PATH,
                               lexicon_path=LEXICON_PATH)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(summary))
    return 0
```

  Above `M5_STAGES`, add:

```python
PARITY_N = 200  # questions sampled for R7n bundle-vs-deals.db parity


def _m5_recall(args) -> int:
    """T-human R6n recall over the live bundle's MAUD agreements (the evals ran on maud.db; this measures the index
    visitors get), and R7n parity between the bundle and deals.db on a stable sample of M4's questions."""
    live = _live_db()
    if not bundle_is_current(live):
        print(f"{live} missing or not matching its manifest; run `dtd bundle` first", file=sys.stderr)
        return 2
    sets = [_data_m4() / f"{s}_items.jsonl" for s in ("tmachine", "abstain")]
    if not (INDEX.exists() and _csv_paths() and LEXICON_PATH.exists() and all(p.exists() for p in sets)):
        print("need maud.db, the label CSVs, the lexicon and M4's item sets; run M2 and `dtd m4 sets` first",
              file=sys.stderr)
        return 2
    embedder, _ = _models()
    settings = load_settings(SETTINGS_PATH)
    ladder = build_live_ladder(live, embedder, load_lexicon(LEXICON_PATH), settings)
    sha = json.loads(live.with_name(MANIFEST).read_text(encoding="utf-8"))["sha256"]
    maud_ids = {r[0] for r in ladder.conn.execute("SELECT contract_id FROM deals WHERE source = 'maud'")}
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    ctx = with_passages(replace(ctx, items=[i for i in ctx.items if i.contract_id in maud_ids]), live)
    evaluate(ctx, "bundle-R6n", lambda q, c, k: ladder.run("R6n", q, c, k), _out_m5(),
             count_tokens=embedder.count_tokens, extra={"settings": asdict(settings), "bundle_sha256": sha})
    items = [i for p in sets for i in read_items(p)]
    sample = sorted(items, key=lambda i: hashlib.sha1(i.item_id.encode()).hexdigest())[:PARITY_N]
    par = r7n_parity([(i.question, i.contract_id) for i in sample], ladder, _deals_ladder(*_deals_texts()))
    _write_atomic(_out_m5() / "bundle_parity.json",
                  json.dumps(par | {"bundle_sha256": sha}, indent=2, sort_keys=True))
    print(json.dumps({"bundle_r6n": str(_out_m5() / "bundle_r6n.json"),
                      "parity": {"checked": par["checked"], "same": par["same"]}}))
    return 1 if par["differ"] else 0
```

  Change the `M5_STAGES` literal to:

```python
M5_STAGES = {"parity": _m5_parity, "recall": _m5_recall}  # Tasks 5 and 11 add calibrate and measure
```

  In `entry`, after `sub.add_parser("report")…`, add:

```python
    sub.add_parser("bundle").set_defaults(fn=_cmd_bundle)
```

- [ ] **Step 8: Run the tests.**

  Run: `uv run pytest tests/test_bundle.py tests/test_live.py tests/test_live_parity.py tests/test_cli.py -q`

  Expected: PASS. Then run `uv run pytest -q`; expected: all pass.

- [ ] **Step 9: Real bundle, with a real kill.**

  Kill it mid-build. `pkill -f` matches both `uv` and the Python process it starts; killing only `uv` could leave the
  build running.

```bash
mkdir -p data/live
(uv run dtd bundle > data/live/bundle_kill.log 2>&1 &) ; sleep 15 ; pkill -9 -f "dtd bundle" ; sleep 1 ; ls -la data/live/
```

  Expected: no `live.db` on the first ever build (a stale `live.db.building` may remain, which is fine). If a previous bundle existed, it stays, with a matching `bundle.json`.

  Then run it to completion, twice:

```bash
uv run dtd bundle | tee data/live/bundle.log
uv run dtd bundle
ls -la data/live/
```

  Expected:
  - the first finishing run prints `"rebuilt": true`, with `contracts` 406 and `passages` 88628 (the M3/M4 `deals.db` counts);
  - `bytes` is roughly 0.6 GB: `deals.db` (505 MB) plus about 137 MB of texts, minus about 4 MB of `terms`;
  - the second prints the same summary with `"rebuilt": false`;
  - no `.building` or `.tmp` file remains.

- [ ] **Step 10: Real recall and parity (free, a few minutes).**

  Run: `uv run dtd m5 recall | tee data/out/m5/recall.log; echo exit=$?`

  Expected:
  - `exit=0`, with `"parity": {"checked": 200, "same": 200}`;
  - `data/out/m5/bundle_parity.json` has `"differ": []`;
  - `data/out/m5/bundle_r6n.json` exists. Its `by_split.report["recall@5"]` mean is the M5 fact, reported beside `m4_r6n_report_recall_at_5` in Task 11. No equality is expected: BM25 statistics differ between corpora, and the bundle holds 88 of the 100 MAUD agreements.

  If parity differs, stop. The bundle is not the measured index. Inspect the listed questions; never accept a non-empty `differ`.

- [ ] **Step 11: Commit.**

```bash
git add pipeline/bundle.py retrieval/live.py evals/live_parity.py pipeline/cli.py tests/test_bundle.py tests/test_live.py tests/test_live_parity.py tests/test_cli.py
git commit -q -F - <<'EOF'
m5: live bundle (deals.db + texts + links, built atomically, read-only immutable open) and the R7n live ladder; dtd bundle, dtd m5 recall (bundle T-human recall, R7n parity)

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
```

---

### Task 5: API runner, prices and calibration command

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (dependency `anthropic`)
- Modify: `pipeline/env.py` (`anthropic_key`)
- Create: `answer/api_runner.py`
- Create: `service/prices.json`, `service/prices.py`. These move here from Task 6 because calibration is their first consumer; Task 6 imports them.
- Modify: `evals/run_answers.py` (a truncated or refused API reply is permanent in the ledger)
- Create: `evals/calibrate.py`
- Modify: `pipeline/cli.py` (stage `calibrate` of the `m5` command Task 2 created; constants `ENV_FILE`, `PRICES`)
- Test: `tests/test_env.py` (extend), `tests/test_api_runner.py`, `tests/test_prices.py`, `tests/test_run_answers.py` (extend), `tests/test_calibrate.py`

**Interfaces:**
- Consumes:
  - `Answerer(ladder, runner, model, answer_path=None)` and `Prepared` (Task 2)
  - `answer_all(items, answerer, ledger_path, workers, max_new, max_error_rate)`, `load_answers(ledger_path, model, items)` (`evals/run_answers.py`)
  - `match_choice` (`evals/answer_score.py`), `normalise` (`answer/gate.py`)
  - `AnswerItem`, `read_items` (`evals/answer_sets.py`)
  - From Task 2: the `M5_STAGES` dict, `_data_m5()` and the `m5` subparser (Task 4 added `recall`)
  - `service/__init__.py` (Task 1)
  - From `pipeline/cli.py`: `_ladder`, `_deals_ladder`, `_deals_texts`, `_data_m4`, `HAIKU`, `_write_atomic`
- Produces:
  - `RunnerError(kind, message, usage=None)` with `.kind` and `.usage`; `str(e)` starts with `f"{kind}: "`. `KINDS`.
  - `make_api_runner(max_tokens, client=None, timeout=30.0)` → `runner(prompt, model) -> {"result", "usage", "stop_reason"}`
  - `Prices`, `load_prices(path)`, `cost_usd(p, usage)`, `worst_case_usd(p, prompt_chars, max_tokens)`
  - `anthropic_key(env_file=Path(".env")) -> str`
  - `calibration_sample(items, n)`, `ledger_path(root, model, max_tokens)`, `run_calibration(jobs, ledger, workers=3, max_new=None)`, `summarise(items, api, cli, prompt_chars, prices, max_tokens)`
  - `dtd m5 calibrate [--n 40] [--max-tokens 1024] [--workers 3] [--max-new N]`, which writes `data/m5/calibration.json`

SDK facts, verified on 2026-10-05 against `anthropic` 1.11.0, the version `uv add` picks:
- It is built on `httpx2`, not `httpx`.
- Status codes map to exceptions as follows:
  - 400 `BadRequestError`, 401 `AuthenticationError`, 403 `PermissionDeniedError`, 429 `RateLimitError`, 529 `OverloadedError`;
  - 500, 503 and 504 all raise `InternalServerError`;
  - 402 has no subclass and raises plain `APIStatusError`.
- `APITimeoutError` subclasses `APIConnectionError`, so check it first.
- Status errors are built as `cls(message, response=httpx2.Response(code, request=req), body=None)`, and connection errors as `cls(request=req)`.
- `Message.stop_reason` can be `"refusal"` and `"model_context_window_exceeded"`.
- `Usage.cache_creation_input_tokens` and `cache_read_input_tokens` may be `None`.
- `anthropic.Anthropic()` builds without a key and fails only at request time.

Design notes:
- **The runner makes one call:** no system prompt, no thinking, default temperature. Haiku 4.5 does not think unless asked, which is the M4 measurement M5 compares against.
- **Failure kinds:**
  - 500, 503 and 504 count as `overloaded` (transient, server side).
  - `billing` is a 400, 402 or 403 whose text mentions `credit`, `billing`, `spend` or `usage limit`. The bare word "limit" is too broad: "max_tokens exceeds the model's limit" is a `bad_request`, not a budget state.
- **Truncated and refused replies are permanent in the ledger.** Retrying one would pay for the same reply again.
- **The ledger's name carries the output cap.** A rerun at a new `--max-tokens` is new calls, not stale hits.
- **One ledger for both sets.** T-human ids (`contract_N|question`) and T-machine ids (`edgar_…|family`) never collide, so one file per (model, cap) is the whole record of calibration spend. The two sets need different ladders, so they are two `answer_all` calls into that one file.
- **Error-rate stop at 0.5.** Calibration exists to measure truncations and refusals, so only an outage should stop it. `answer_all` still stops after 20 failures in a row.

- [ ] **Step 1: Add the SDK**

Run: `uv add "anthropic>=1.11,<2"`
Then: `uv run python -c "import anthropic, httpx2; print(anthropic.__version__)"`
Expected: `1.11.x` (any 1.x ≥ 1.11). `pyproject.toml` `dependencies` now lists `"anthropic>=1.11,<2"` beside fastembed and sqlite-vec, and `uv.lock` is updated.

- [ ] **Step 2: Write the failing tests for the key and the runner** (append to `tests/test_env.py`; create `tests/test_api_runner.py`)

In `tests/test_env.py`, change the import to `from pipeline.env import anthropic_key, sec_contact`, then append:

```python
def test_api_key_comes_from_the_environment_first(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=file-key\n")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    assert anthropic_key(tmp_path / ".env") == "env-key"


def test_api_key_falls_back_to_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text('SEC_CONTACT=a@b.c\nANTHROPIC_API_KEY="file-key"\n')
    assert anthropic_key(tmp_path / ".env") == "file-key"


def test_missing_api_key_refuses_without_echoing_anything(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    (tmp_path / ".env").write_text("SEC_CONTACT=a@b.c\n")
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY") as e:
        anthropic_key(tmp_path / ".env")
    assert "a@b.c" not in str(e.value)
```

Create `tests/test_api_runner.py`:

```python
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from answer.api_runner import KINDS, RunnerError, make_api_runner

REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")
HAIKU = "claude-haiku-4-5-20251001"


def message(text='{"state": "not_stated", "claims": []}', stop="end_turn", **usage):
    u = {"input_tokens": 120, "output_tokens": 30, "cache_creation_input_tokens": None,
         "cache_read_input_tokens": None} | usage
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)], stop_reason=stop,
                           usage=SimpleNamespace(**u))


class FakeClient:
    """Stands in for anthropic.Anthropic: `client.messages.create(**kw)` records kw, then returns or raises."""
    def __init__(self, reply=None, error=None):
        self.reply, self.error, self.calls = reply, error, []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        if self.error is not None:
            raise self.error
        return self.reply


def status(cls, code, text):
    return cls(text, response=httpx2.Response(code, request=REQ), body=None)


def test_one_call_returns_text_usage_and_stop_reason():
    client = FakeClient(message())
    got = make_api_runner(1024, client=client)("PROMPT", HAIKU)
    assert got == {"result": '{"state": "not_stated", "claims": []}', "stop_reason": "end_turn",
                   "usage": {"input_tokens": 120, "output_tokens": 30, "cache_creation_input_tokens": 0,
                             "cache_read_input_tokens": 0}}
    # one plain call: no system prompt, no thinking, no temperature
    assert client.calls == [{"model": HAIKU, "max_tokens": 1024,
                             "messages": [{"role": "user", "content": "PROMPT"}]}]


def test_only_text_blocks_are_joined():
    msg = message()
    msg.content = [SimpleNamespace(type="thinking", thinking="hmm"), SimpleNamespace(type="text", text='{"a": '),
                   SimpleNamespace(type="text", text="1}")]
    assert make_api_runner(64, client=FakeClient(msg))("p", HAIKU)["result"] == '{"a": 1}'


@pytest.mark.parametrize("stop", ["max_tokens", "model_context_window_exceeded"])
def test_a_truncated_reply_is_an_error_that_carries_its_usage(stop):
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(message(stop=stop, output_tokens=64)))("p", HAIKU)
    assert e.value.kind == "truncated" and e.value.usage["output_tokens"] == 64
    assert str(e.value).startswith("truncated: ") and isinstance(e.value, RuntimeError)


def test_a_refusal_is_an_error_that_carries_its_usage():
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(message(stop="refusal", output_tokens=3)))("p", HAIKU)
    assert e.value.kind == "refusal" and e.value.usage["output_tokens"] == 3


@pytest.mark.parametrize("error, kind", [
    (status(anthropic.RateLimitError, 429, "rate limited"), "rate_limited"),
    (status(anthropic.OverloadedError, 529, "overloaded"), "overloaded"),
    (status(anthropic.InternalServerError, 500, "internal error"), "overloaded"),
    (anthropic.APITimeoutError(request=REQ), "timeout"),
    (anthropic.APIConnectionError(request=REQ), "connection"),
    (status(anthropic.BadRequestError, 400, "Your credit balance is too low to access the API"), "billing"),
    (status(anthropic.PermissionDeniedError, 403, "This workspace has reached its spend limit"), "billing"),
    (status(anthropic.APIStatusError, 402, "billing required"), "billing"),
    (status(anthropic.BadRequestError, 400, "max_tokens: exceeds the model's limit"), "bad_request"),
    (status(anthropic.AuthenticationError, 401, "invalid x-api-key"), "bad_request"),
])
def test_sdk_errors_map_to_kinds_with_no_usage(error, kind):
    with pytest.raises(RunnerError) as e:
        make_api_runner(64, client=FakeClient(error=error))("p", HAIKU)
    assert e.value.kind == kind and e.value.usage == {}


def test_unknown_kind_is_refused():
    with pytest.raises(ValueError):
        RunnerError("weird", "x")
    assert {"truncated", "refusal", "billing", "timeout"} <= set(KINDS)


def test_the_client_is_built_lazily_once_with_one_retry(monkeypatch):
    built = []

    class Recorder(FakeClient):
        def __init__(self, **kw):
            built.append(kw)
            super().__init__(message())
    monkeypatch.setattr("answer.api_runner.anthropic.Anthropic", Recorder)
    run = make_api_runner(64, timeout=12.5)
    assert built == []
    run("p", HAIKU)
    run("q", HAIKU)
    assert built == [{"max_retries": 1, "timeout": 12.5}]


@pytest.mark.model
def test_one_real_call_through_the_dev_key():
    from pipeline.env import anthropic_key
    try:
        key = anthropic_key()
    except RuntimeError:
        pytest.skip("ANTHROPIC_API_KEY (the dtd-dev key) is not set")
    run = make_api_runner(16, client=anthropic.Anthropic(api_key=key, max_retries=1, timeout=30.0))
    got = run("Reply with the single word: ok", HAIKU)
    assert got["result"].strip() and got["usage"]["input_tokens"] > 0 and got["stop_reason"] == "end_turn"
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_env.py tests/test_api_runner.py -q`
Expected: FAIL with `ImportError: cannot import name 'anthropic_key'` and `ModuleNotFoundError: No module named 'answer.api_runner'`.

- [ ] **Step 4: Implement the key lookup and the runner**

Replace `pipeline/env.py` with this. `sec_contact` behaves exactly as before: same lookup order and error message.

```python
import os
from pathlib import Path


def _value(name: str, env_file: Path) -> str:
    """The variable from the environment, else from the gitignored .env (KEY=value lines, quotes stripped)."""
    value = os.environ.get(name, "").strip()
    if not value and Path(env_file).exists():
        for line in Path(env_file).read_text(encoding="utf-8").splitlines():
            key, sep, val = line.partition("=")
            if sep and key.strip() == name:
                value = val.strip().strip('"').strip("'")
    return value


def sec_contact(env_file: Path = Path(".env")) -> str:
    value = _value("SEC_CONTACT", env_file)
    if "@" not in value:
        raise RuntimeError("SEC_CONTACT is not set: export it, or put SEC_CONTACT=<email> in the gitignored .env")
    return value


def anthropic_key(env_file: Path = Path(".env")) -> str:
    """The API key for offline calls (calibration, the real-call test): the dtd-dev workspace key, never the live one."""
    value = _value("ANTHROPIC_API_KEY", env_file)
    if not value:
        raise RuntimeError("ANTHROPIC_API_KEY is not set: export it, or put ANTHROPIC_API_KEY=<the dtd-dev key> in "
                           "the gitignored .env")
    return value
```

Create `answer/api_runner.py`:

```python
import threading

import anthropic

KINDS = ("rate_limited", "overloaded", "timeout", "connection", "bad_request", "billing", "refusal", "truncated")
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
# A 400/402/403 that says one of these is the account's money running out (a Console spend limit or no credit),
# which the service shows as the budget state. "limit" alone is not enough: "max_tokens exceeds the limit" is a bug.
BILLING_WORDS = ("credit", "billing", "spend", "usage limit")
TRUNCATED = ("max_tokens", "model_context_window_exceeded")


class RunnerError(RuntimeError):
    """A failed API call. `kind` is one of KINDS; `usage` is what the call was billed for ({} when nothing came
    back), so the spend ledger settles actual tokens. A RuntimeError, so evals.run_answers ledgers it as
    `runner: <kind>: …` like any runner failure."""

    def __init__(self, kind: str, message: str, usage: dict | None = None):
        if kind not in KINDS:
            raise ValueError(f"unknown runner error kind {kind!r}")
        super().__init__(f"{kind}: {message}")
        self.kind = kind
        self.usage = dict(usage or {})


def _usage(u) -> dict:
    return {k: int(getattr(u, k, None) or 0) for k in USAGE_KEYS}


def _kind(e: Exception) -> str:
    if isinstance(e, anthropic.APITimeoutError):  # a subclass of APIConnectionError: test it first
        return "timeout"
    if isinstance(e, anthropic.APIConnectionError):
        return "connection"
    if isinstance(e, anthropic.RateLimitError):
        return "rate_limited"
    if isinstance(e, (anthropic.OverloadedError, anthropic.InternalServerError)):
        return "overloaded"
    if (isinstance(e, anthropic.APIStatusError) and e.status_code in (400, 402, 403)
            and any(w in str(e).lower() for w in BILLING_WORDS)):
        return "billing"
    return "bad_request"


def make_api_runner(max_tokens: int, client=None, timeout: float = 30.0):
    """runner(prompt, model) -> {"result", "usage", "stop_reason"}: the `run_claude` contract over the Messages API.
    One user turn, no system prompt, no thinking, at most `max_tokens` out. The client is built on first use
    (one retry, `timeout` seconds) unless one is given. A truncated or refused reply raises RunnerError with its
    usage; it is never returned as an answer."""
    state, lock = {"client": client}, threading.Lock()

    def runner(prompt: str, model: str) -> dict:
        with lock:
            if state["client"] is None:
                state["client"] = anthropic.Anthropic(max_retries=1, timeout=timeout)
            c = state["client"]
        try:
            msg = c.messages.create(model=model, max_tokens=max_tokens,
                                    messages=[{"role": "user", "content": prompt}])
        except anthropic.AnthropicError as e:
            raise RunnerError(_kind(e), str(e)[:300]) from None
        usage = _usage(msg.usage)
        if msg.stop_reason in TRUNCATED:
            raise RunnerError("truncated", f"reply stopped at {msg.stop_reason} (max_tokens={max_tokens})", usage)
        if msg.stop_reason == "refusal":
            raise RunnerError("refusal", "the model declined to answer", usage)
        text = "".join(b.text for b in msg.content if getattr(b, "type", None) == "text")
        return {"result": text, "usage": usage, "stop_reason": msg.stop_reason}
    return runner
```

- [ ] **Step 5: Run them to see them pass**

Run: `uv run pytest tests/test_env.py tests/test_api_runner.py -q`
Expected: PASS. The `model`-marked test is deselected.

- [ ] **Step 6: Write the failing price tests** (`tests/test_prices.py`)

```python
import re

import pytest

from service.prices import Prices, cost_usd, load_prices, worst_case_usd

P = Prices("m", 1.0, 5.0, 1.25, 0.1, "https://example.test/pricing", "2026-10-05")


def test_committed_prices_are_for_the_live_model_with_a_source_and_date():
    p = load_prices("service/prices.json")
    assert p.model == "claude-haiku-4-5-20251001"
    assert p.source.startswith("https://") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.checked)
    assert 0 < p.cache_read < p.input < p.cache_write < p.output


def test_cost_counts_every_usage_field_and_treats_none_as_zero():
    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_creation_input_tokens": None,
             "cache_read_input_tokens": 200_000}
    assert cost_usd(P, usage) == pytest.approx(1.0 + 0.5 + 0.02)
    assert cost_usd(P, {}) == 0.0 and cost_usd(P, None) == 0.0


def test_worst_case_assumes_three_characters_a_token_and_the_full_output_cap():
    # 30,000 characters is at most 10,000 tokens in at $1, plus 4,000 tokens out at $5, per million
    assert worst_case_usd(P, 30_000, 4_000) == pytest.approx(0.03)
```

- [ ] **Step 7: Run them to see them fail**

Run: `uv run pytest tests/test_prices.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'service.prices'`.

- [ ] **Step 8: Confirm today's prices, then write the table and the arithmetic**

Fetch the pricing page (WebFetch `https://platform.claude.com/docs/en/about-claude/pricing.md`, prompt "Claude Haiku 4.5 base input, 5-minute cache write, cache hit and output price per million tokens").
- Expected on 2026-10-05: $1.00 in, $1.25 cache write, $0.10 cache read, $5.00 out.
- If any value differs, use the page's value. If `checked` is not today, set it to the date you fetched.

Create `service/prices.json`:

```json
{
  "model": "claude-haiku-4-5-20251001",
  "input_per_mtok": 1.00,
  "output_per_mtok": 5.00,
  "cache_write_per_mtok": 1.25,
  "cache_read_per_mtok": 0.10,
  "source": "https://platform.claude.com/docs/en/about-claude/pricing",
  "checked": "2026-10-05"
}
```

Create `service/prices.py`:

```python
import json
from dataclasses import dataclass
from pathlib import Path

PER = 1_000_000
CHARS_PER_TOKEN = 3  # deliberately low: contract English runs nearer four characters a token, so this over-reserves


@dataclass(frozen=True)
class Prices:
    """USD per million tokens for one model, with where and when the numbers were read."""
    model: str
    input: float
    output: float
    cache_write: float
    cache_read: float
    source: str
    checked: str


def load_prices(path) -> Prices:
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return Prices(d["model"], float(d["input_per_mtok"]), float(d["output_per_mtok"]),
                  float(d["cache_write_per_mtok"]), float(d["cache_read_per_mtok"]), d["source"], d["checked"])


def cost_usd(p: Prices, usage: dict | None) -> float:
    """What one call cost, from its usage (the four API counters; missing or None count as zero)."""
    u = usage or {}

    def n(k: str) -> int:
        return int(u.get(k) or 0)
    return (n("input_tokens") * p.input + n("output_tokens") * p.output
            + n("cache_creation_input_tokens") * p.cache_write + n("cache_read_input_tokens") * p.cache_read) / PER


def worst_case_usd(p: Prices, prompt_chars: int, max_tokens: int) -> float:
    """The most a call can cost before it is made: the prompt at three characters a token, plus the full output
    cap. The budget reserves this; calibration checks it is never below an actual cost."""
    return (prompt_chars / CHARS_PER_TOKEN * p.input + max_tokens * p.output) / PER
```

- [ ] **Step 9: Run them to see them pass**

Run: `uv run pytest tests/test_prices.py -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add pyproject.toml uv.lock pipeline/env.py answer/api_runner.py service/prices.json service/prices.py \
        tests/test_env.py tests/test_api_runner.py tests/test_prices.py
git commit -m "$(cat <<'EOF'
m5: Anthropic API runner with typed failures that carry their usage; price table for the live model

The runner keeps the run_claude contract (result, usage) plus stop_reason. A truncated or
refused reply, and every SDK error, raises RunnerError(kind, usage) so the spend ledger can
settle what was billed. ANTHROPIC_API_KEY comes from the environment or the gitignored .env.
Prices are Haiku 4.5's, with their source and the date they were read.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

- [ ] **Step 11: Write the failing test: truncated and refused replies are not retried** (append to `tests/test_run_answers.py`)

```python
def test_truncated_and_refused_api_replies_are_not_retried(tmp_path):
    from answer.api_runner import RunnerError

    def cut(prompt, model):
        raise RunnerError("truncated" if prompt.endswith("0") else "refusal", "x", {"input_tokens": 5})
    led = tmp_path / "l.jsonl"
    answer_all(items(2), FakeAnswerer(cut), led, max_error_rate=1.0)
    errors = sorted(r["error"].split(":")[1].strip() for r in load_answers(led, "m", items(2)).values())
    assert errors == ["refusal", "truncated"]
    runner.calls = []
    s = answer_all(items(2), FakeAnswerer(runner), led)
    assert s["new_calls"] == 0 and s["done"] == 2 and runner.calls == []
```

- [ ] **Step 12: Run it to see it fail**

Run: `uv run pytest tests/test_run_answers.py -q -k truncated`
Expected: FAIL. The second run makes 2 new calls, because every `runner:` error is treated as transient.

- [ ] **Step 13: Make those two kinds permanent** (`evals/run_answers.py`)

Replace `_is_done`:

```python
PERMANENT_RUNNER = ("runner: truncated", "runner: refusal")  # the model's own reply at this cap: a retry repeats it


def _is_done(rec: dict | None) -> bool:
    """A runner failure is transient, so a rerun retries it; a parse failure is permanent, and so is an API reply
    that was truncated at the output cap or refused (a retry would pay for the same reply)."""
    if rec is None:
        return False
    err = rec.get("error") or ""
    return not err.startswith("runner:") or err.startswith(PERMANENT_RUNNER)
```

Run: `uv run pytest tests/test_run_answers.py -q`
Expected: PASS. The older test `test_runner_errors_are_retried_on_rerun_and_parse_errors_are_not` still passes, because "runner: claude down" is still retried.

- [ ] **Step 14: Write the failing calibration tests** (`tests/test_calibrate.py`)

```python
import json
import os
import signal
import subprocess
import sys
import time

import pytest

from evals.answer_sets import AnswerItem, write_items
from evals.calibrate import calibration_sample, ledger_path, run_calibration, summarise
from evals.run_answers import load_answers
from pipeline import cli
from service.prices import Prices
from tests.test_run_answers import FakeAnswerer, runner

P = Prices("m", 1.0, 5.0, 1.25, 0.1, "s", "2026-10-05")


def item(iid, s="thuman", split="tune", expected="", choices=()):
    return AnswerItem(iid, s, "g", split, "c", f"q {iid}", choices, expected)


def ans(state="answered", choice=None, kept=1, dropped=0, tin=1000, tout=100):
    return {"state": state, "choice": choice, "claims": [{"quote": "q"}] * kept,
            "dropped": [{"reason": "quote_not_found"}] * dropped, "tokens_in": tin, "tokens_out": tout,
            "usage": {"input_tokens": tin, "output_tokens": tout}}


def rec(answer=None, error=None):
    return {"answer": answer, "error": error}


TH1 = item("th1", expected="Yes", choices=("No", "Yes"))
TH2 = item("th2", expected="No", choices=("No", "Yes"))
TH3 = item("th3", expected="No", choices=("No", "Yes"))
TM1, TM2 = item("tm1", "tmachine"), item("tm2", "tmachine")
ITEMS = [TH1, TH2, TH3, TM1, TM2]
CHARS = {"th1": 9000, "th2": 9000, "tm1": 12000, "tm2": 12000}


def test_sample_takes_tune_items_from_both_sets_stably():
    pool = ([item(f"h{k}") for k in range(10)] + [item(f"r{k}", split="report") for k in range(10)]
            + [item(f"m{k}", "tmachine") for k in range(10)])
    got = calibration_sample(pool, 6)
    assert [i.set for i in got] == ["thuman"] * 3 + ["tmachine"] * 3
    assert all(i.split == "tune" for i in got)
    assert [i.item_id for i in calibration_sample(list(reversed(pool)), 6)] == [i.item_id for i in got]
    assert len(calibration_sample(pool, 40)) == 20  # never more than the tune split holds


def test_ledger_name_carries_the_model_and_the_output_cap(tmp_path):
    a, b = ledger_path(tmp_path, "m", 1024), ledger_path(tmp_path, "m", 2048)
    assert a != b and a.name == "calibration_m_mt1024.jsonl" and a.parent == tmp_path


def test_summary_counts_tokens_cost_parity_and_stops_on_disagreement():
    api = {"th1": rec(ans(choice="Yes", kept=2, tin=1000, tout=100)),
           "th2": rec(ans("not_stated", choice="Yes", kept=0, dropped=1, tin=2000, tout=200)),
           "tm1": rec(ans(kept=1, dropped=1, tin=3000, tout=300)),
           "tm2": rec(error="runner: truncated: reply stopped at max_tokens (max_tokens=1024)")}
    cli_recs = {"th1": rec(ans(choice="Yes", kept=1, dropped=1)), "th2": rec(ans("not_stated", choice="No", kept=0)),
                "tm1": rec(ans("not_stated", kept=0)), "tm2": rec(ans())}
    s = summarise(ITEMS, api, cli_recs, CHARS, P, 1024)
    assert (s["n"], s["called"], s["errors"], s["missing"], s["truncated"], s["refused"]) == (5, 3, 1, 1, 1, 0)
    assert (s["api_tokens_in_mean"], s["api_tokens_in_p95"]) == (2000.0, 3000)
    assert (s["api_tokens_out_mean"], s["api_tokens_out_p95"], s["api_tokens_out_p99"]) == (200.0, 300, 300)
    # three answered calls at their actual cost, the truncated one at its worst case (12,000 chars, 1,024 out)
    assert s["cost_usd_total"] == pytest.approx(0.0015 + 0.003 + 0.0045 + 0.00912)
    assert s["cost_per_answer_mean"] == pytest.approx(0.003)
    assert s["cost_per_answer_p95"] == pytest.approx(0.0045)
    assert s["worst_case_ok"] is True and s["worst_case_min_margin_usd"] == pytest.approx(0.00462)
    assert s["paired"] == 3
    assert s["gate_pass_rate"] == {"api": 0.6, "cli": 0.5}
    assert s["state_agreement"] == 0.6667
    assert s["thuman_accuracy"] == {"api": 0.5, "cli": 1.0, "diff": -0.5, "n": 2}
    assert s["stop_rule"]["verdict"] == "stop" and len(s["stop_rule"]["reasons"]) == 2


def test_summary_goes_when_api_and_cli_agree():
    same = {"th1": rec(ans(choice="Yes")), "th2": rec(ans("not_stated", choice="No", kept=0)), "tm1": rec(ans())}
    s = summarise(ITEMS, same, same, CHARS, P, 1024)
    assert s["state_agreement"] == 1.0 and s["thuman_accuracy"]["diff"] == 0.0
    assert s["stop_rule"] == {"state_agreement_min": 0.8, "accuracy_diff_max": 0.15, "verdict": "go", "reasons": []}


def test_summary_stops_when_the_worst_case_estimate_is_below_an_actual_cost():
    a = {"th1": rec(ans(choice="Yes", tin=50_000, tout=100))}  # far more tokens than 9,000 characters / 3
    s = summarise([TH1], a, a, {"th1": 9000}, P, 1024)
    assert s["worst_case_ok"] is False and s["stop_rule"]["verdict"] == "stop"


def test_summary_stops_when_nothing_is_paired():
    s = summarise(ITEMS, {}, {}, CHARS, P, 1024)
    assert s["paired"] == 0 and s["state_agreement"] is None and s["cost_usd_total"] == 0.0
    assert s["stop_rule"]["verdict"] == "stop"


def test_a_few_failed_calls_do_not_stop_calibration(tmp_path):
    runner.calls = []

    def flaky(prompt, model):
        if prompt[-1] in "135":
            raise RuntimeError("overloaded: try later")
        return runner(prompt, model)
    its = [item(f"h{k}") for k in range(20)]  # h1 h3 h5 h11 h13 h15 fail: 30%, over answer_all's default 5%
    got = run_calibration([(its, FakeAnswerer(flaky))], tmp_path / "cal.jsonl", workers=2)
    assert got["errors"] == 6 and got["done"] == 14


SCRIPT = """
import sys, time
sys.path.insert(0, {root!r})
from evals.answer_sets import read_items
from evals.calibrate import run_calibration
from tests.test_run_answers import FakeAnswerer
def slow(prompt, model):
    time.sleep(0.05)
    return {{"result": "{{}}", "usage": {{}}}}
its = read_items({items!r})
jobs = [([i for i in its if i.set == s], FakeAnswerer(slow)) for s in ("thuman", "tmachine")]
run_calibration(jobs, {ledger!r}, workers=2)
"""


def test_sigkill_mid_calibration_then_resume(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    its = [item(f"h{k}") for k in range(30)] + [item(f"m{k}", "tmachine") for k in range(30)]
    write_items(tmp_path / "items.jsonl", its)
    ledger = tmp_path / "cal.jsonl"
    p = subprocess.Popen([sys.executable, "-c", SCRIPT.format(root=root, items=str(tmp_path / "items.jsonl"),
                                                             ledger=str(ledger))], cwd=root)
    deadline = time.time() + 30
    while time.time() < deadline and (not ledger.exists() or len(ledger.read_text().splitlines()) < 10):
        time.sleep(0.02)
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    before = len(load_answers(ledger, "m", its))
    assert 10 <= before < 60
    runner.calls = []
    jobs = [([i for i in its if i.set == s], FakeAnswerer(runner)) for s in ("thuman", "tmachine")]
    got = run_calibration(jobs, ledger, workers=2)
    assert got["new_calls"] == 60 - before and got["done"] == 60
    keys = [json.loads(l)["key"] for l in ledger.read_text().splitlines() if l.strip()]
    assert len(keys) == len(set(keys)) == 60


def test_calibrate_refuses_without_an_api_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")  # never the real .env, which may hold the dev key
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    monkeypatch.setattr(cli, "make_api_runner", lambda *a, **k: pytest.fail("no runner without a key"))
    assert cli.entry(["m5", "calibrate"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_the_cli_summarises_with_the_calibration_summary():
    import evals.calibrate
    import evals.disputes
    # cli.py also imports evals.disputes.summarise; the calibration one must not be shadowed by it, or vice versa
    assert cli.summarise_calibration is evals.calibrate.summarise and cli.summarise is evals.disputes.summarise


def test_calibrate_refuses_when_m4_inputs_are_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    monkeypatch.setattr(cli, "make_api_runner", lambda *a, **k: pytest.fail("no runner without inputs"))
    assert cli.entry(["m5", "calibrate"]) == 2
    assert "calibration inputs missing" in capsys.readouterr().err
```

- [ ] **Step 15: Run them to see them fail**

Run: `uv run pytest tests/test_calibrate.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'evals.calibrate'`.

- [ ] **Step 16: Implement calibration** (`evals/calibrate.py`)

```python
import hashlib
import math
from pathlib import Path

from answer.gate import normalise
from evals.answer_score import match_choice
from evals.run_answers import answer_all
from service.prices import cost_usd, worst_case_usd

STATE_AGREEMENT_MIN = 0.8  # spec §2: below this, API answers differ too much to inherit the M4 (CLI) numbers
ACCURACY_DIFF_MAX = 0.15  # spec §2: a larger T-human accuracy gap is a gross difference
MAX_ERROR_RATE = 0.5  # calibration measures truncations and refusals; only an outage (20 in a row) should stop it


def ledger_path(root: Path, model: str, max_tokens: int) -> Path:
    """One ledger per model and output cap: a rerun at a new cap is new calls, not stale hits."""
    return Path(root) / f"calibration_{model}_mt{max_tokens}.jsonl"


def calibration_sample(items, n: int) -> list:
    """n//2 tune-split T-human items, then n//2 tune-split T-machine items, the same ones on every run (ordered by
    sha1 of the item id), so a rerun resumes the same calls. The report split is never touched."""
    out = []
    for s in ("thuman", "tmachine"):
        pool = [i for i in items if i.set == s and i.split == "tune"]
        out += sorted(pool, key=lambda i: hashlib.sha1(i.item_id.encode()).hexdigest())[:n // 2]
    return out


def run_calibration(jobs, ledger: Path, workers: int = 3, max_new: int | None = None) -> dict:
    """answer_all once per (items, answerer) job into one ledger; the summaries summed. Kill and resume are
    answer_all's own: a rerun skips every ledgered key except transient runner failures."""
    total = dict.fromkeys(("items", "done", "new_calls", "errors"), 0)
    for items, answerer in jobs:
        got = answer_all(items, answerer, ledger, workers=workers, max_new=max_new, max_error_rate=MAX_ERROR_RATE)
        total = {k: total[k] + got[k] for k in total}
    return total


def _pct(values, p):
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)]


def _mean(values, digits):
    return round(sum(values) / len(values), digits) if values else None


def _rate(flags):
    return round(sum(flags) / len(flags), 4) if flags else None


def _gate(answers):
    kept = sum(len(a["claims"]) for a in answers)
    returned = kept + sum(len(a["dropped"]) for a in answers)
    return round(kept / returned, 4) if returned else None


def _right(answer: dict, item) -> bool:
    """evals.answer_score's T-human rule: the choice maps to exactly one option, equal to MAUD's answer."""
    picked = match_choice(answer.get("choice"), item.choices)
    return picked is not None and normalise(picked) == normalise(item.expected)


def summarise(items, api: dict, cli: dict, prompt_chars: dict, prices, max_tokens: int) -> dict:
    """API calibration against the M4 CLI answers for the same items. `api` and `cli` are load_answers records by
    item id; `prompt_chars` the length of each item's prompt. A call that failed after it was sent (truncated,
    refused, unparseable) is costed at its worst case, because its usage is not in the ledger."""
    ok = {i.item_id: api[i.item_id]["answer"] for i in items if (api.get(i.item_id) or {}).get("answer")}
    failed = {i.item_id: api[i.item_id] for i in items if i.item_id in api and not api[i.item_id].get("answer")}
    called = {iid: a for iid, a in ok.items() if a["tokens_in"]}  # which_deal and no-hit answers make no call
    tin = [a["tokens_in"] for a in called.values()]
    tout = [a["tokens_out"] for a in called.values()]
    cost = {iid: cost_usd(prices, a.get("usage") or {}) for iid, a in called.items()}
    worst = {iid: worst_case_usd(prices, prompt_chars[iid], max_tokens) for iid in called if iid in prompt_chars}
    failed_cost = sum(worst_case_usd(prices, prompt_chars[iid], max_tokens) for iid in failed if iid in prompt_chars)
    margins = [worst[iid] - cost[iid] for iid in worst]
    worst_ok = bool(margins) and min(margins) >= 0
    paired = [i for i in items if i.item_id in ok and (cli.get(i.item_id) or {}).get("answer")]
    a_side = [ok[i.item_id] for i in paired]
    c_side = [cli[i.item_id]["answer"] for i in paired]
    th = [i for i in paired if i.set == "thuman"]
    acc_api = _rate([_right(ok[i.item_id], i) for i in th])
    acc_cli = _rate([_right(cli[i.item_id]["answer"], i) for i in th])
    diff = round(acc_api - acc_cli, 4) if th else None
    agree = _rate([x["state"] == y["state"] for x, y in zip(a_side, c_side)])
    errors = [r.get("error") or "" for r in failed.values()]
    reasons = []
    if agree is None:
        reasons.append("no item has both an API and a CLI answer")
    elif agree < STATE_AGREEMENT_MIN:
        reasons.append(f"state agreement {agree} is below {STATE_AGREEMENT_MIN}")
    if diff is not None and abs(diff) > ACCURACY_DIFF_MAX:
        reasons.append(f"T-human accuracy differs by {diff}, more than {ACCURACY_DIFF_MAX}")
    if not worst_ok:
        reasons.append("the worst-case estimate is below an actual cost, so the budget would under-reserve")
    costs = list(cost.values())
    return {
        "n": len(items), "called": len(called), "errors": len(failed),
        "missing": sum(i.item_id not in api for i in items),
        "truncated": sum(e.startswith("runner: truncated") for e in errors),
        "refused": sum(e.startswith("runner: refusal") for e in errors),
        "api_tokens_in_mean": _mean(tin, 1), "api_tokens_in_p95": _pct(tin, 95),
        "api_tokens_out_mean": _mean(tout, 1), "api_tokens_out_p95": _pct(tout, 95),
        "api_tokens_out_p99": _pct(tout, 99),
        "cost_usd_total": round(sum(costs) + failed_cost, 6),
        "cost_per_answer_mean": _mean(costs, 6),
        "cost_per_answer_p95": round(_pct(costs, 95), 6) if costs else None,
        "worst_case_ok": worst_ok, "worst_case_min_margin_usd": round(min(margins), 6) if margins else None,
        "paired": len(paired), "gate_pass_rate": {"api": _gate(a_side), "cli": _gate(c_side)},
        "state_agreement": agree,
        "thuman_accuracy": {"api": acc_api, "cli": acc_cli, "diff": diff, "n": len(th)},
        "stop_rule": {"state_agreement_min": STATE_AGREEMENT_MIN, "accuracy_diff_max": ACCURACY_DIFF_MAX,
                      "verdict": "stop" if reasons else "go", "reasons": reasons},
    }
```

- [ ] **Step 17: Wire `dtd m5 calibrate`** (`pipeline/cli.py`)

Imports. Extend the existing `answer.answerer` and `pipeline.env` imports; the others are new. `summarise` is
imported under another name because `cli.py` already imports `evals.disputes.summarise`, and the later import would
silently replace the earlier one:

```python
from answer.answerer import Answerer, Prepared
from answer.api_runner import make_api_runner
from evals.calibrate import calibration_sample, ledger_path, run_calibration
from evals.calibrate import summarise as summarise_calibration
from pipeline.env import anthropic_key, sec_contact
from service.prices import load_prices
```

Constants, beside `FACTS`:

```python
ENV_FILE = Path(".env")
PRICES = Path("service/prices.json")
```

The client helper and the handler go right above `M5_STAGES` (below Task 4's `_m5_recall`), because the dict
literal refers to the handler:

```python
def _api_client(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=1, timeout=30.0)


def _m5_calibrate(args) -> int:
    """Tune-split items through the API (the dtd-dev key), compared with M4's CLI answers to the same items."""
    try:
        key = anthropic_key(ENV_FILE)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    sets = {s: _data_m4() / f"{s}_items.jsonl" for s in ("thuman", "tmachine")}
    cli_ledgers = {s: _data_m4() / f"answers_{s}_{HAIKU}.jsonl" for s in sets}
    needed = [*sets.values(), *cli_ledgers.values(), PRICES, INDEX, DEALS_INDEX]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        print("calibration inputs missing: " + ", ".join(missing) + "; run M4 (`dtd m4 sets`, `dtd m4 answer`) "
              "first", file=sys.stderr)
        return 2
    sample = calibration_sample(read_items(sets["thuman"]) + read_items(sets["tmachine"]), args.n)
    th = [i for i in sample if i.set == "thuman"]
    tm = [i for i in sample if i.set == "tmachine"]
    runner = make_api_runner(args.max_tokens, client=_api_client(key))
    th_ans = Answerer(_ladder(INDEX, {p.stem: load_contract(p) for p in sorted((RAW / "contracts").glob("*.txt"))}),
                      runner, HAIKU)  # the ladders `dtd m4 answer` used, so prompts match M4's
    tm_ans = Answerer(_deals_ladder(*_deals_texts()), runner, HAIKU)
    ledger = ledger_path(_data_m5(), HAIKU, args.max_tokens)
    try:
        run = run_calibration([(th, th_ans), (tm, tm_ans)], ledger, workers=args.workers, max_new=args.max_new)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    api = load_answers(ledger, HAIKU, sample)
    cli_recs = load_answers(cli_ledgers["thuman"], HAIKU, th) | load_answers(cli_ledgers["tmachine"], HAIKU, tm)
    chars = {}
    for items, ans in ((th, th_ans), (tm, tm_ans)):
        for i in items:
            p = ans.prepare(i.question, i.contract_id, i.choices)
            if isinstance(p, Prepared):
                chars[i.item_id] = len(p.prompt)
    summary = summarise_calibration(sample, api, cli_recs, chars, load_prices(PRICES), args.max_tokens)
    summary |= {"model": HAIKU, "max_tokens": args.max_tokens, "ledger": ledger.name, "run": run}
    _data_m5().mkdir(parents=True, exist_ok=True)
    _write_atomic(_data_m5() / "calibration.json", json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps({k: summary[k] for k in ("n", "paired", "errors", "truncated", "cost_usd_total", "stop_rule")}))
    return 0
```

Change the `M5_STAGES` literal to:

```python
M5_STAGES = {"parity": _m5_parity, "recall": _m5_recall, "calibrate": _m5_calibrate}  # Task 11 adds measure
```

In `entry`, right below `m5p.add_argument("stage", choices=tuple(M5_STAGES))`, add the four arguments
(`choices=tuple(M5_STAGES)` already picks up the new stage):

```python
    m5p.add_argument("--n", type=int, default=40)
    m5p.add_argument("--max-tokens", type=int, default=1024)
    m5p.add_argument("--workers", type=int, default=3)
    m5p.add_argument("--max-new", type=int, default=None)
```

- [ ] **Step 18: Run them to see them pass, then the whole suite**

Run: `uv run pytest tests/test_calibrate.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS. Nothing earlier changed behaviour except that truncated and refused API replies are now permanent.

- [ ] **Step 19: Commit**

```bash
git add evals/run_answers.py evals/calibrate.py pipeline/cli.py tests/test_run_answers.py tests/test_calibrate.py
git commit -m "$(cat <<'EOF'
m5: dtd m5 calibrate — tune-split items through the API, compared with M4's CLI answers

A stable sample of tune T-human and T-machine items runs through the API runner into one
ledger per (model, output cap); kill and resume are answer_all's. The summary gives API
tokens and cost, truncations, whether the worst-case estimate covers every actual cost,
gate pass rate, state agreement and T-human accuracy against the CLI, and the spec's stop
rule. A truncated or refused API reply is permanent in the ledger, so a rerun never pays
for the same reply twice. Refuses to run without ANTHROPIC_API_KEY.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Spend ledger and budget

**Files:**
- Create: `service/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Consumes: `Prices`, `cost_usd`, `worst_case_usd` (Task 5)
- Produces:
  - `Budget(db, month_cap, day_cap, prices, clock=time.time)`
  - `.reserve(prompt_chars, max_tokens) -> int | None`
  - `.settle(rid, usage: dict | None) -> float`. `usage=None` means unknown (a timeout): book the reservation's worst case.
  - `.release(rid) -> None`
  - `.spent() -> {"month", "day"}`, which counts open reservations at worst
  - `.state(min_call_usd) -> "ok" | "reached"`
  - `STALE_S`
- How Task 9's `Desk` must use it:
  - reserve before the call;
  - `settle(rid, reply["usage"])` on success, or on a parse error (the reply's usage);
  - `settle(rid, e.usage)` on a `RunnerError` whose `usage` is non-empty (truncated, refusal);
  - `settle(rid, None)` on `timeout` or `connection` with no usage, which may have been billed;
  - `release(rid)` on the other `RunnerError` kinds, which the API does not bill.

Design notes:
- **One `spend` table,** in SQLite (WAL, `busy_timeout` 5000), with every write in `BEGIN IMMEDIATE`. The service and `dtd warm` are two processes on the same file, so two `Budget` objects must never overshoot together. The per-object `threading.Lock` serialises threads that share one connection.
- **Caps** are UTC calendar month and UTC day, from the injected clock. A cap counts settled `usd`, plus `worst` for open rows.
- **Crash leftovers settle at worst only once stale** (older than `STALE_S` = 600 s, far beyond the 30 s timeout × 2 attempts).
  - Reconciling on every start would wrongly settle another live process's in-flight call. Example: `dtd warm` starting while the service is mid-call.
  - Until then an open row already counts at worst toward the caps, so the ledger never under-counts in the meantime.
  - Reconciliation runs on start and inside every `reserve`.

- [ ] **Step 1: Write the failing tests** (`tests/test_budget.py`)

```python
import sqlite3
import threading
from datetime import datetime, timezone

import pytest

from service.budget import STALE_S, Budget
from service.prices import Prices

P = Prices("m", 1.0, 5.0, 1.25, 0.1, "s", "2026-10-05")
CHARS, MAX_OUT = 30_000, 4_000  # worst case: 10,000 tokens in at $1 + 4,000 out at $5 per MTok = $0.03


class Clock:
    def __init__(self, *ymdhm):
        self.t = datetime(*ymdhm, tzinfo=timezone.utc).timestamp()

    def __call__(self):
        return self.t


def budget(tmp_path, month=1.0, day=1.0, clock=None):
    return Budget(tmp_path / "spend.db", month, day, P, clock or Clock(2026, 10, 5, 12, 0))


def statuses(tmp_path):
    return [r[0] for r in sqlite3.connect(tmp_path / "spend.db").execute("SELECT status FROM spend ORDER BY id")]


def test_a_reservation_counts_at_worst_until_settled_at_actual(tmp_path):
    b = budget(tmp_path)
    rid = b.reserve(CHARS, MAX_OUT)
    assert b.spent()["month"] == pytest.approx(0.03)
    assert b.settle(rid, {"input_tokens": 1000, "output_tokens": 100}) == pytest.approx(0.0015)
    assert b.spent() == {"month": pytest.approx(0.0015), "day": pytest.approx(0.0015)}
    assert statuses(tmp_path) == ["settled"]


def test_unknown_usage_settles_at_the_worst_case(tmp_path):
    b = budget(tmp_path)
    rid = b.reserve(CHARS, MAX_OUT)
    assert b.settle(rid, None) == pytest.approx(0.03)  # a timeout: the call may have been billed in full


def test_release_frees_the_headroom(tmp_path):
    b = budget(tmp_path, month=0.05)
    first = b.reserve(CHARS, MAX_OUT)
    assert first is not None and b.reserve(CHARS, MAX_OUT) is None
    b.release(first)
    assert b.reserve(CHARS, MAX_OUT) is not None
    assert statuses(tmp_path) == ["released", "open"]


def test_the_day_cap_resets_at_utc_midnight(tmp_path):
    clock = Clock(2026, 10, 5, 23, 59)
    b = budget(tmp_path, month=1.0, day=0.05, clock=clock)
    assert b.reserve(CHARS, MAX_OUT) is not None and b.reserve(CHARS, MAX_OUT) is None
    clock.t += 120  # 00:01 UTC the next day
    assert b.reserve(CHARS, MAX_OUT) is not None
    assert b.spent()["day"] == pytest.approx(0.03) and b.spent()["month"] == pytest.approx(0.06)


def test_the_month_cap_resets_on_the_first_in_utc(tmp_path):
    clock = Clock(2026, 10, 31, 23, 30)
    b = budget(tmp_path, month=0.05, day=1.0, clock=clock)
    b.settle(b.reserve(CHARS, MAX_OUT), {"input_tokens": 10_000, "output_tokens": 4_000})
    assert b.reserve(CHARS, MAX_OUT) is None
    clock.t += 3600  # 00:30 UTC on 1 November
    assert b.spent()["month"] == 0.0 and b.reserve(CHARS, MAX_OUT) is not None


def _race(budgets, n=50):
    got, start = [], threading.Barrier(n)

    def go(b):
        start.wait()
        got.append(b.reserve(CHARS, MAX_OUT))
    threads = [threading.Thread(target=go, args=(budgets[k % len(budgets)],)) for k in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return got


def test_fifty_threads_never_overshoot_the_cap(tmp_path):
    b = budget(tmp_path)
    got = _race([b])
    assert sum(r is not None for r in got) == 33  # 33 × $0.03 fits under $1; a 34th would not
    assert b.spent()["month"] <= 1.0


def test_two_processes_sharing_the_ledger_never_overshoot(tmp_path):
    a, b = budget(tmp_path), budget(tmp_path)  # two connections, as the service and `dtd warm` hold
    got = _race([a, b])
    assert sum(r is not None for r in got) == 33 and a.spent()["month"] <= 1.0


def test_spend_survives_a_restart(tmp_path):
    clock = Clock(2026, 10, 5, 12, 0)
    b = budget(tmp_path, clock=clock)
    b.settle(b.reserve(CHARS, MAX_OUT), {"input_tokens": 1000, "output_tokens": 100})
    assert budget(tmp_path, clock=clock).spent()["month"] == pytest.approx(0.0015)


def test_a_crashed_reservation_is_settled_at_worst_once_stale(tmp_path):
    clock = Clock(2026, 10, 5, 12, 0)
    budget(tmp_path, clock=clock).reserve(CHARS, MAX_OUT)  # the process dies before settle
    budget(tmp_path, clock=clock)  # a process starting now: that call may still be in flight elsewhere
    assert statuses(tmp_path) == ["open"]
    clock.t += STALE_S + 1
    b = budget(tmp_path, clock=clock)
    assert statuses(tmp_path) == ["settled"] and b.spent()["month"] == pytest.approx(0.03)


def test_state_is_reached_when_less_than_one_call_is_left(tmp_path):
    b = budget(tmp_path, month=0.05, day=1.0)
    assert b.state(min_call_usd=0.03) == "ok"
    b.reserve(CHARS, MAX_OUT)
    assert b.state(min_call_usd=0.03) == "reached"  # $0.02 left is less than one call
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_budget.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'service.budget'`.

- [ ] **Step 3: Implement the budget** (`service/budget.py`)

```python
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from service.prices import Prices, cost_usd, worst_case_usd

STALE_S = 600.0  # an open reservation this old belongs to a call that died: far beyond the timeout × attempts

SCHEMA = """
CREATE TABLE IF NOT EXISTS spend(
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, day TEXT NOT NULL, month TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('open', 'settled', 'released')), worst REAL NOT NULL,
    usd REAL NOT NULL DEFAULT 0, tokens_in INTEGER NOT NULL DEFAULT 0, tokens_out INTEGER NOT NULL DEFAULT 0,
    cache_write INTEGER NOT NULL DEFAULT 0, cache_read INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS spend_month ON spend(month);
CREATE INDEX IF NOT EXISTS spend_day ON spend(day);
"""
TOTAL = "SELECT COALESCE(SUM(CASE status WHEN 'open' THEN worst ELSE usd END), 0) FROM spend WHERE {col} = ?"


def _keys(t: float) -> tuple[str, str]:
    """(UTC day, UTC month) for a timestamp: the budget's calendar, whatever the server's timezone."""
    d = datetime.fromtimestamp(t, timezone.utc)
    return d.strftime("%Y-%m-%d"), d.strftime("%Y-%m")


class Budget:
    """The spend ledger and its month and day caps. A call reserves its worst case first and settles at actual
    cost after, so neither concurrent calls nor a crash between the two can take spend past a cap."""

    def __init__(self, db, month_cap: float, day_cap: float, prices: Prices, clock=time.time):
        db = Path(db)
        db.parent.mkdir(parents=True, exist_ok=True)
        self.month_cap, self.day_cap, self.prices, self.clock = float(month_cap), float(day_cap), prices, clock
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db, check_same_thread=False, isolation_level=None, timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.executescript(SCHEMA)
        with self._lock:
            self._tx(self._reconcile)

    def _tx(self, fn):
        c = self._conn
        c.execute("BEGIN IMMEDIATE")  # takes the write lock now, so another process cannot interleave
        try:
            out = fn(c)
            c.execute("COMMIT")
            return out
        except BaseException:
            c.execute("ROLLBACK")
            raise

    def _reconcile(self, c) -> None:
        c.execute("UPDATE spend SET status = 'settled', usd = worst WHERE status = 'open' AND ts < ?",
                  (self.clock() - STALE_S,))

    @staticmethod
    def _totals(c, now: float) -> tuple[float, float]:
        day, month = _keys(now)
        return (c.execute(TOTAL.format(col="month"), (month,)).fetchone()[0],
                c.execute(TOTAL.format(col="day"), (day,)).fetchone()[0])

    def reserve(self, prompt_chars: int, max_tokens: int) -> int | None:
        """A reservation id, or None when the worst case would take the month or the day past its cap."""
        worst = worst_case_usd(self.prices, prompt_chars, max_tokens)

        def fn(c):
            self._reconcile(c)
            now = self.clock()
            month, day = self._totals(c, now)
            if month + worst > self.month_cap or day + worst > self.day_cap:
                return None
            d, m = _keys(now)
            return c.execute("INSERT INTO spend(ts, day, month, status, worst) VALUES (?, ?, ?, 'open', ?)",
                             (now, d, m, worst)).lastrowid
        with self._lock:
            return self._tx(fn)

    def settle(self, rid: int, usage: dict | None) -> float:
        """Book a call at its actual cost; usage None (a timeout: billed or not is unknown) books its worst case."""
        u = usage or {}

        def fn(c):
            if usage is None:
                usd = c.execute("SELECT worst FROM spend WHERE id = ?", (rid,)).fetchone()[0]
            else:
                usd = cost_usd(self.prices, u)
            c.execute("UPDATE spend SET status = 'settled', usd = ?, tokens_in = ?, tokens_out = ?, cache_write = ?,"
                      " cache_read = ? WHERE id = ?",
                      (usd, int(u.get("input_tokens") or 0), int(u.get("output_tokens") or 0),
                       int(u.get("cache_creation_input_tokens") or 0), int(u.get("cache_read_input_tokens") or 0),
                       rid))
            return usd
        with self._lock:
            return self._tx(fn)

    def release(self, rid: int) -> None:
        """The call was never billed (refused before it ran): its reservation no longer counts."""
        with self._lock:
            self._tx(lambda c: c.execute("UPDATE spend SET status = 'released', usd = 0 WHERE id = ? AND"
                                         " status = 'open'", (rid,)))

    def spent(self) -> dict:
        """This UTC month's and day's spend in USD, open reservations at their worst case."""
        with self._lock:
            month, day = self._totals(self._conn, self.clock())
        return {"month": round(month, 6), "day": round(day, 6)}

    def state(self, min_call_usd: float) -> str:
        """'reached' when less than one typical call is left under either cap."""
        s = self.spent()
        if self.month_cap - s["month"] < min_call_usd or self.day_cap - s["day"] < min_call_usd:
            return "reached"
        return "ok"
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/test_budget.py -q`
Expected: PASS. Run it three times (`for i in 1 2 3; do uv run pytest tests/test_budget.py -q; done`) to shake out races; all three pass.

- [ ] **Step 5: Commit**

```bash
git add service/budget.py tests/test_budget.py
git commit -m "$(cat <<'EOF'
m5: spend ledger with month and day caps — reserve at worst, settle at actual

Reservations run in BEGIN IMMEDIATE under a lock, so concurrent threads or a second process
on the same file never overshoot a cap. Months and days are UTC. A timeout settles at the
worst case; an open reservation left by a crash counts at worst until it is stale, then is
settled at worst.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Answer cache

**Files:**
- Create: `service/cache.py`
- Test: `tests/test_cache.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `CACHEABLE`, `normalise_question(q) -> str`, `AnswerCache(db)` with `.get(model, prompt_sha) -> dict | None` and `.put(model, prompt_sha, payload) -> None`.

Design notes:
- **The key is (model, `Prepared.prompt_sha`).** A change to the bundle, lexicon, settings or template changes the prompt, so it misses on its own. There is no separate version key to forget.
- **The question is only whitespace-normalised before `prepare`.** Case reaches the prompt and can change retrieval, so it is kept.
- **Only model answers are stored:** `answered`, `not_stated`, `unfiled_schedule`. `which_deal` costs nothing to recompute, and the budget, `busy` and error states describe a moment, not the answer.
- **The payload is whatever dict `Desk` passes.** The cache neither adds to it nor strips it.

- [ ] **Step 1: Write the failing tests** (`tests/test_cache.py`)

```python
import pytest

from service.cache import CACHEABLE, AnswerCache, normalise_question

PAYLOAD = {"state": "answered", "amended": True, "candidates": [],
           "claims": [{"text": "The fee is $40m.", "quote": "The Termination Fee shall be $40,000,000",
                       "agreement": "Acme Software / Big Parent", "section_path": "Article VIII › 8.3",
                       "link": "https://www.sec.gov/Archives/x.htm", "amendment_no": 2,
                       "amendment_link": "https://www.sec.gov/Archives/y.htm"}]}


def test_a_hit_returns_the_payload_unchanged(tmp_path):
    c = AnswerCache(tmp_path / "cache.db")
    assert c.get("m", "abc") is None
    c.put("m", "abc", PAYLOAD)
    assert c.get("m", "abc") == PAYLOAD


def test_the_key_is_model_and_prompt_hash(tmp_path):
    c = AnswerCache(tmp_path / "cache.db")
    c.put("m", "abc", PAYLOAD)
    assert c.get("other-model", "abc") is None and c.get("m", "abd") is None


@pytest.mark.parametrize("state", ["which_deal", "budget_cached", "budget_reached", "busy", "error"])
def test_only_model_answers_are_cached(tmp_path, state):
    c = AnswerCache(tmp_path / "cache.db")
    c.put("m", "abc", PAYLOAD | {"state": state})
    assert c.get("m", "abc") is None
    assert set(CACHEABLE) == {"answered", "not_stated", "unfiled_schedule"}


def test_a_newer_answer_replaces_the_older(tmp_path):
    c = AnswerCache(tmp_path / "cache.db")
    c.put("m", "abc", PAYLOAD)
    c.put("m", "abc", {"state": "not_stated", "claims": []})
    assert c.get("m", "abc") == {"state": "not_stated", "claims": []}


def test_the_cache_survives_a_restart_and_a_second_writer(tmp_path):
    AnswerCache(tmp_path / "cache.db").put("m", "abc", PAYLOAD)
    AnswerCache(tmp_path / "cache.db").put("m", "def", {"state": "not_stated", "claims": []})
    fresh = AnswerCache(tmp_path / "cache.db")
    assert fresh.get("m", "abc") == PAYLOAD and fresh.get("m", "def")["state"] == "not_stated"


def test_questions_are_whitespace_normalised_only():
    assert normalise_question("  What is the\n termination   fee? ") == "What is the termination fee?"
    assert normalise_question("Fee?") != normalise_question("fee?")  # case reaches the prompt, so it is kept
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_cache.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'service.cache'`.

- [ ] **Step 3: Implement the cache** (`service/cache.py`)

```python
import json
import sqlite3
import threading
import time
from pathlib import Path

CACHEABLE = ("answered", "not_stated", "unfiled_schedule")  # what a model call produced; nothing momentary
SCHEMA = ("CREATE TABLE IF NOT EXISTS cache(model TEXT NOT NULL, prompt_sha TEXT NOT NULL, payload TEXT NOT NULL,"
          " created REAL NOT NULL, PRIMARY KEY(model, prompt_sha))")


def normalise_question(q: str) -> str:
    """Whitespace collapsed and trimmed. Nothing else: case and punctuation reach the prompt."""
    return " ".join(q.split())


class AnswerCache:
    """Answers by (model, prompt hash). The prompt carries the question, the retrieved passages and the template,
    so any change to the bundle, lexicon, settings or template misses on its own."""

    def __init__(self, db):
        db = Path(db)
        db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db, check_same_thread=False, isolation_level=None, timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(SCHEMA)

    def get(self, model: str, prompt_sha: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM cache WHERE model = ? AND prompt_sha = ?",
                                     (model, prompt_sha)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, model: str, prompt_sha: str, payload: dict) -> None:
        if payload.get("state") not in CACHEABLE:
            return
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                               (model, prompt_sha, json.dumps(payload, sort_keys=True), time.time()))
```

- [ ] **Step 4: Run them to see them pass**

Run: `uv run pytest tests/test_cache.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/cache.py tests/test_cache.py
git commit -m "$(cat <<'EOF'
m5: answer cache keyed by model and prompt hash

Only model answers (answered, not_stated, unfiled_schedule) are stored; any change to the
bundle, lexicon, settings or template changes the prompt and so misses. Questions are
whitespace-normalised only, since case reaches the prompt.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Request limits and service config

**Files:**
- Create: `service/limits.py`, `service/config.py`
- Test: `tests/test_limits.py`, `tests/test_config.py`

**Interfaces:**
- Consumes: `load_prices` (Task 5), for the check that the default model is the priced one.
- Produces:
  - `client_key(host) -> str`
  - `Buckets(per_window, window_s, clock=time.monotonic)` with `.allow(key) -> float`: `0.0` means go ahead; otherwise the seconds to wait, for `Retry-After`.
  - `Slots(n)` with `.try_acquire() -> bool` and `.release()`.
  - `Buckets(0, …)` never allows and `Slots(0)` never acquires: a closed limit. Task 9's tests use them to force `busy`.
  - `Config` (frozen, fields in the Interfaces block order) and `from_env(env=os.environ) -> Config`.
  - `git_sha` is `DTD_GIT_SHA`, else the contents of a `GIT_SHA` file in the working directory (Task 12's `push.sh`
    writes one into each release), else `"unknown"`.
- How Task 9 uses them:
  - `Buckets(cfg.ask_per_hour, 3600)` per client for `/ask`;
  - `Buckets(cfg.search_per_minute, 60)` per client for `/search`;
  - `Buckets(cfg.fresh_per_hour, 3600)` with the single key `"*"` as the global limit on fresh model calls;
  - `Slots(cfg.ask_slots)` for the fail-fast concurrency limit.

Design notes:
- **Client address.** IPv6 is keyed by its /64, because one host routinely holds a whole /64. An IPv4-mapped IPv6 address is keyed by its IPv4 address. Anything unparseable (Starlette's `TestClient` reports `"testclient"`) is used as is.
- **Rate limits use a sliding log per key.** Empty keys are pruned every 1,024 calls, so memory stays bounded.
- **The concurrency limit is a `BoundedSemaphore`,** so a double release fails loudly instead of growing the pool.
- **Zero is a closed limit:** `Buckets(0, …)` always answers with the full window, and `Slots(0)` never acquires.
  Config never produces a zero (every number must be positive); tests use it to reach `busy`.
- **Config:**
  - The month cap has no default: a service that doesn't know its budget must not start. The day cap defaults to a tenth of the month cap.
  - Every number must be positive. A tiny cap such as `0.0001` is allowed; the cap-trip test on the box needs it.
  - `max_tokens` defaults to 1024. Task 13 resets it in `/etc/dtd/env` from calibration's p99.

- [ ] **Step 1: Write the failing tests** (`tests/test_limits.py`, `tests/test_config.py`)

`tests/test_limits.py`:

```python
import threading

import pytest

from service.limits import Buckets, Slots, client_key


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_ipv4_is_its_own_key():
    assert client_key("203.0.113.7") == "203.0.113.7"


def test_ipv6_is_keyed_by_its_slash_64():
    a, b = client_key("2001:db8:1:2:3:4:5:6"), client_key("2001:db8:1:2:ffff::1")
    assert a == b == "2001:db8:1:2::/64"
    assert client_key("2001:db8:1:3::1") != a


def test_ipv4_mapped_ipv6_is_the_ipv4_address():
    assert client_key("::ffff:203.0.113.7") == "203.0.113.7"


@pytest.mark.parametrize("host", ["testclient", "", "not-an-ip"])
def test_anything_else_is_used_as_is(host):
    assert client_key(host) == host


def test_a_bucket_allows_n_per_window_then_says_how_long_to_wait():
    clock = Clock()
    b = Buckets(3, 60, clock)
    assert [b.allow("a") for _ in range(3)] == [0.0, 0.0, 0.0]
    assert b.allow("a") == pytest.approx(60.0)
    assert b.allow("b") == 0.0  # keys are independent
    clock.t = 30.0
    assert b.allow("a") == pytest.approx(30.0)
    clock.t = 60.0  # the three calls made at t=0 have all left the window
    assert [b.allow("a") for _ in range(3)] == [0.0, 0.0, 0.0] and b.allow("a") == pytest.approx(60.0)


def test_a_bucket_is_exact_under_threads():
    b, got, start = Buckets(10, 60, Clock()), [], threading.Barrier(20)

    def go():
        start.wait()
        got.append(b.allow("a"))
    threads = [threading.Thread(target=go) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(w == 0.0 for w in got) == 10


def test_idle_keys_are_pruned():
    clock = Clock()
    b = Buckets(1, 60, clock)
    for k in range(2000):
        b.allow(f"k{k}")
    clock.t = 61.0
    for _ in range(1024):
        b.allow("live")
    assert len(b._log) < 10


def test_slots_fail_fast_when_full():
    s = Slots(2)
    assert s.try_acquire() and s.try_acquire() and not s.try_acquire()
    s.release()
    assert s.try_acquire()


def test_releasing_more_than_was_taken_is_an_error():
    s = Slots(1)
    with pytest.raises(ValueError):
        s.release()


def test_zero_is_a_closed_limit():
    b = Buckets(0, 60, Clock())
    assert b.allow("a") == pytest.approx(60.0) and b.allow("b") == pytest.approx(60.0)
    assert Slots(0).try_acquire() is False
    with pytest.raises(ValueError):
        Buckets(-1, 60)
```

`tests/test_config.py`:

```python
from pathlib import Path

import pytest

from service.config import Config, from_env
from service.prices import load_prices


def test_defaults_need_only_the_month_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no GIT_SHA file here
    assert from_env({"DTD_MONTH_CAP_USD": "4.5"}) == Config(
        bundle=Path("data/live/live.db"), state_dir=Path("data/state"), prices_path=Path("service/prices.json"),
        facts_path=Path("facts.json"), model="claude-haiku-4-5-20251001", max_tokens=1024, month_cap_usd=4.5,
        day_cap_usd=0.45, question_max_chars=500, ask_per_hour=20, search_per_minute=60, fresh_per_hour=60,
        ask_slots=2, git_sha="unknown")


def test_the_month_cap_is_required():
    with pytest.raises(ValueError, match="DTD_MONTH_CAP_USD"):
        from_env({})
    with pytest.raises(ValueError, match="DTD_MONTH_CAP_USD"):
        from_env({"DTD_MONTH_CAP_USD": "  "})


@pytest.mark.parametrize("name, value", [("DTD_MONTH_CAP_USD", "lots"), ("DTD_MONTH_CAP_USD", "0"),
                                         ("DTD_DAY_CAP_USD", "-1"), ("DTD_MAX_TOKENS", "-5"),
                                         ("DTD_ASK_SLOTS", "1.5")])
def test_bad_numbers_are_refused_by_name(name, value):
    with pytest.raises(ValueError, match=name):
        from_env({"DTD_MONTH_CAP_USD": "4.5"} | {name: value})


def test_a_tiny_cap_is_allowed_for_the_cap_trip_test():
    assert from_env({"DTD_MONTH_CAP_USD": "0.0001"}).month_cap_usd == 0.0001


def test_every_setting_can_be_overridden():
    env = {"DTD_BUNDLE": "/srv/dtd/bundle/live.db", "DTD_STATE": "/var/lib/dtd", "DTD_PRICES": "/p.json",
           "DTD_FACTS": "/f.json", "DTD_MODEL": "m", "DTD_MAX_TOKENS": "900", "DTD_MONTH_CAP_USD": "4.8",
           "DTD_DAY_CAP_USD": "0.6", "DTD_QUESTION_MAX_CHARS": "400", "DTD_ASK_PER_HOUR": "10",
           "DTD_SEARCH_PER_MINUTE": "30", "DTD_FRESH_PER_HOUR": "40", "DTD_ASK_SLOTS": "3", "DTD_GIT_SHA": "abc1234"}
    assert from_env(env) == Config(Path("/srv/dtd/bundle/live.db"), Path("/var/lib/dtd"), Path("/p.json"),
                                   Path("/f.json"), "m", 900, 4.8, 0.6, 400, 10, 30, 40, 3, "abc1234")


def test_the_default_model_is_the_one_the_price_table_prices():
    assert from_env({"DTD_MONTH_CAP_USD": "1"}).model == load_prices("service/prices.json").model


def test_git_sha_comes_from_the_env_then_the_release_file_then_unknown(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert from_env({"DTD_MONTH_CAP_USD": "1"}).git_sha == "unknown"
    (tmp_path / "GIT_SHA").write_text("abc1234\n")  # push.sh writes this into each release
    assert from_env({"DTD_MONTH_CAP_USD": "1"}).git_sha == "abc1234"
    assert from_env({"DTD_MONTH_CAP_USD": "1", "DTD_GIT_SHA": "def5678"}).git_sha == "def5678"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_limits.py tests/test_config.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'service.limits'` (and `service.config`).

- [ ] **Step 3: Implement limits and config**

`service/limits.py`:

```python
import ipaddress
import threading
import time
from collections import deque

PRUNE_EVERY = 1024  # calls between sweeps of keys whose window has emptied


def client_key(host: str) -> str:
    """The address a rate limit counts: IPv4 as is; IPv6 by its /64 (one host routinely holds a whole /64);
    an IPv4-mapped IPv6 address as its IPv4; anything unparseable unchanged."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return host
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return str(ip.ipv4_mapped)
        return str(ipaddress.ip_network(f"{ip}/64", strict=False))
    return str(ip)


class Buckets:
    """At most `per_window` calls per key in any `window_s` seconds (a sliding log). allow() is 0.0 when the call
    may go ahead, else the seconds until the oldest call leaves the window (for Retry-After)."""

    def __init__(self, per_window: int, window_s: float, clock=time.monotonic):
        if per_window < 0 or window_s <= 0:
            raise ValueError("a bucket needs per_window >= 0 and window_s > 0")
        self.per_window, self.window_s, self.clock = per_window, float(window_s), clock
        self._log: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._calls = 0

    def allow(self, key: str) -> float:
        if self.per_window == 0:  # a closed limit: never allows
            return self.window_s
        with self._lock:
            now = self.clock()
            self._calls += 1
            if self._calls % PRUNE_EVERY == 0:
                self._prune(now)
            log = self._log.setdefault(key, deque())
            while log and log[0] <= now - self.window_s:
                log.popleft()
            if len(log) < self.per_window:
                log.append(now)
                return 0.0
            return max(log[0] + self.window_s - now, 0.001)

    def _prune(self, now: float) -> None:
        for k in [k for k, log in self._log.items() if not log or log[-1] <= now - self.window_s]:
            del self._log[k]


class Slots:
    """At most n calls at once; a full set refuses at once instead of queueing (the service answers `busy`).
    Slots(0) never acquires."""

    def __init__(self, n: int):
        self._sem = threading.BoundedSemaphore(n)

    def try_acquire(self) -> bool:
        return self._sem.acquire(blocking=False)

    def release(self) -> None:
        self._sem.release()  # BoundedSemaphore: releasing more than was taken raises ValueError
```

`service/config.py`:

```python
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Config:
    bundle: Path
    state_dir: Path
    prices_path: Path
    facts_path: Path
    model: str
    max_tokens: int
    month_cap_usd: float
    day_cap_usd: float
    question_max_chars: int
    ask_per_hour: int
    search_per_minute: int
    fresh_per_hour: int
    ask_slots: int
    git_sha: str


def _num(env, name: str, cast, default):
    raw = (env.get(name) or "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ValueError(f"{name} must be a {cast.__name__}, got {raw!r}") from None
    if value <= 0:
        raise ValueError(f"{name} must be positive, got {raw!r}")
    return value


def _git_sha(env) -> str:
    """The deployed commit: DTD_GIT_SHA, else the GIT_SHA file push.sh writes into each release, else unknown."""
    if (env.get("DTD_GIT_SHA") or "").strip():
        return env["DTD_GIT_SHA"].strip()
    f = Path("GIT_SHA")
    return (f.read_text(encoding="utf-8").strip() or "unknown") if f.exists() else "unknown"


def from_env(env=os.environ) -> Config:
    """The service's settings from DTD_* variables (on the box: /etc/dtd/env). The month cap has no default:
    a service that does not know its budget must not start."""
    if not (env.get("DTD_MONTH_CAP_USD") or "").strip():
        raise ValueError("DTD_MONTH_CAP_USD is not set: the month's model budget in USD (the $10 cap minus "
                         "hosting, from deploy/hosting.json)")
    month = _num(env, "DTD_MONTH_CAP_USD", float, None)
    return Config(
        bundle=Path(env.get("DTD_BUNDLE") or "data/live/live.db"),
        state_dir=Path(env.get("DTD_STATE") or "data/state"),
        prices_path=Path(env.get("DTD_PRICES") or "service/prices.json"),
        facts_path=Path(env.get("DTD_FACTS") or "facts.json"),
        model=env.get("DTD_MODEL") or "claude-haiku-4-5-20251001",
        max_tokens=_num(env, "DTD_MAX_TOKENS", int, 1024),
        month_cap_usd=month,
        day_cap_usd=_num(env, "DTD_DAY_CAP_USD", float, month / 10),
        question_max_chars=_num(env, "DTD_QUESTION_MAX_CHARS", int, 500),
        ask_per_hour=_num(env, "DTD_ASK_PER_HOUR", int, 20),
        search_per_minute=_num(env, "DTD_SEARCH_PER_MINUTE", int, 60),
        fresh_per_hour=_num(env, "DTD_FRESH_PER_HOUR", int, 60),
        ask_slots=_num(env, "DTD_ASK_SLOTS", int, 2),
        git_sha=_git_sha(env),
    )
```

- [ ] **Step 4: Run them to see them pass, then the whole suite**

Run: `uv run pytest tests/test_limits.py tests/test_config.py -q`
Expected: PASS.

Run: `uv run pytest -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add service/limits.py service/config.py tests/test_limits.py tests/test_config.py
git commit -m "$(cat <<'EOF'
m5: request limits and service config

Sliding-window buckets per client (IPv6 grouped by its /64), a fail-fast set of /ask slots,
and the service's settings from DTD_* variables. The month cap is required; the day cap
defaults to a tenth of it; every number must be positive. The deployed commit comes from
DTD_GIT_SHA or the release's GIT_SHA file.

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Desk, FastAPI app, warm

**Files:**
- Modify: `pyproject.toml`, `uv.lock` (fastapi, uvicorn; httpx2 as a dev dependency for `TestClient`)
- Create: `service/desk.py`, `service/app.py`, `service/warm.py`
- Modify: `pipeline/cli.py` (`dtd warm`)
- Test: `tests/test_desk.py`, `tests/test_app.py`

**Interfaces:**
- Consumes, from earlier tasks:
  - `Answerer(ladder, runner, model)` (its `answer_path` comes from settings), `Prepared`, `ParseError` (Task 2, M4);
  - `Retrieved.stages` (Task 3);
  - `build_bundle`, `build_live_ladder`, `bundle_meta`, `links_for` (Task 4);
  - `RunnerError`, `make_api_runner` (Task 5);
  - `Prices`, `load_prices`, `worst_case_usd`, `cost_usd` (Task 5), `Budget`, `STALE_S` (Task 6);
  - `AnswerCache`, `CACHEABLE`, `normalise_question` (Task 7);
  - `Buckets`, `Slots`, `client_key`, `Config`, `from_env` (Task 8).
- Uses `Budget.state(min_call_usd)`: `"reached"` once the month or the day has less than `min_call_usd` left, open
  reservations counted at worst case (Task 6).
- Uses `Buckets(0, …)` (never allows) and `Slots(0)` (never acquires) from Task 8 to reach `busy` in tests.
- Settles spend exactly as Task 6 prescribes:
  - success, or a parse error: `settle(rid, reply usage)`;
  - a `RunnerError` with usage (truncated, refusal): `settle(rid, e.usage)`;
  - `timeout` or `connection` with no usage: `settle(rid, None)`, the worst case, because it may have been billed;
  - any other `RunnerError`: `release(rid)`;
  - kind `billing` shows as `budget_reached`.
- Produces `STATES`, `Desk(ladder, runner, config, budget, cache, fresh, slots)`:
  - `.ask(question, deal=None) -> dict`
  - `.search(q, deal=None) -> dict`
  - `.deals() -> list[dict]`
  - `.health() -> dict`
  - and attributes `.answerer`, `.budget`, `.config`.
- `health()` returns the Interfaces keys plus three more:
  - `template_sha`, which `push.sh` uses to decide on re-warming;
  - `rss_mb`, peak resident memory, which Task 11 reads;
  - `bundle_meta`.
  It never exposes spend amounts. Task 15 reads the ledger over ssh.
- `ask()` payload keys: `state`, `question`, `deal`, `claims`, `amended`, `candidates`, `served_from`, `budget`, `tokens`, `ms`. A cache hit also carries `cached_state`.
- `search()` payload keys: `query`, `scope`, `hits`, `ms`.
- An unknown deal id raises `ValueError` (the app answers 422).
- Also produces `build_desk(config) -> Desk` and `create_app(config=None, desk=None) -> FastAPI` in `service/app.py`, `warm(desk, examples) -> dict`, and `dtd warm --examples PATH`.

- [ ] **Step 1: Add the web dependencies**

```bash
uv add "fastapi>=0.142.2,<0.143" "uvicorn>=0.54,<0.55"
uv add --dev "httpx2>=2.13,<3"
uv run python -c "import fastapi, uvicorn; from fastapi.testclient import TestClient; print(fastapi.__version__, uvicorn.__version__)"
```

Expected: two version strings (planning checked fastapi 0.142.2 and uvicorn 0.54.0).
- Starlette 1.x's `TestClient` needs `httpx2`. The anthropic SDK from Task 5 already pulls it in; the explicit dev pin keeps the tests working if that ever changes.
- With plain `httpx` instead, starlette warns `Using httpx with starlette.testclient is deprecated`.

- [ ] **Step 2: Write the failing Desk tests**

`tests/test_desk.py`:

```python
import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from answer.api_runner import RunnerError
from answer.prompt import TEMPLATE_SHA
from pipeline.bundle import build_bundle
from retrieval.deals import add_deals
from retrieval.index import build_index
from retrieval.ladder import Settings
from retrieval.live import build_live_ladder
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from service.budget import STALE_S, Budget
from service.cache import AnswerCache
from service.config import Config
from service.desk import STATES, Desk
from service.limits import Buckets, Slots
from service.prices import cost_usd, load_prices, worst_case_usd
from tests.fakes import FakeEmbedder, fake_claude
from tests.test_deals import deals_inputs

PRICES = Path("service/prices.json")
LEXICON = {"walk-away payment": ["Termination Fee"]}
SETTINGS = Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3)
AMEND_QUOTE = "The Termination Fee shall be $40,000,000"
OUTSIDE_QUOTE = "The Outside Date is June 30 of the year"
NOT_STATED = json.dumps({"state": "not_stated", "claims": []})


def make_bundle(tmp_path: Path) -> Path:
    """The deals fixture (one MAUD and one tech agreement, one amendment) as a live bundle with fake vectors."""
    db = tmp_path / "deals.db"
    deals, texts, amends = deals_inputs(tmp_path)
    build_index(db, texts)
    add_deals(db, deals, texts, amends)
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    conn.close()
    (tmp_path / "deals.jsonl").write_text("".join(json.dumps(d) + "\n" for d in deals), encoding="utf-8")
    (tmp_path / "settings.json").write_text(json.dumps({"settings": asdict(SETTINGS), "answer_path": "R7n"}),
                                            encoding="utf-8")
    (tmp_path / "lexicon.json").write_text(json.dumps({"entries": LEXICON}), encoding="utf-8")
    out = tmp_path / "live" / "live.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    build_bundle(db, out, texts=texts, amendment_texts=amends, deals_jsonl=tmp_path / "deals.jsonl",
                 settings_path=tmp_path / "settings.json", lexicon_path=tmp_path / "lexicon.json")
    return out


def make_config(tmp_path: Path, bundle: Path, **kw) -> Config:
    facts = tmp_path / "facts.json"
    facts.write_text('{"m4_answer_model": "claude-haiku-4-5-20251001"}\n', encoding="utf-8")
    base = dict(bundle=bundle, state_dir=tmp_path / "state", prices_path=PRICES, facts_path=facts,
                model="claude-haiku-4-5-20251001", max_tokens=1024, month_cap_usd=5.0, day_cap_usd=1.0,
                question_max_chars=300, ask_per_hour=60, search_per_minute=60, fresh_per_hour=60, ask_slots=2,
                git_sha="abc123")
    base.update(kw)
    return Config(**base)


def make_desk(tmp_path: Path, runner, **kw) -> Desk:
    config = make_config(tmp_path, make_bundle(tmp_path), **kw)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(config.state_dir / "budget.db", config.month_cap_usd, config.day_cap_usd,
                    load_prices(config.prices_path))
    ladder = build_live_ladder(config.bundle, FakeEmbedder(), LEXICON, SETTINGS)
    return Desk(ladder, runner, config, budget, AnswerCache(config.state_dir / "cache.db"),
                Buckets(config.fresh_per_hour, 3600.0), Slots(config.ask_slots))


class Scripted:
    """A runner that replays results (or raises exceptions) in order and records every call."""

    def __init__(self, *results, input_tokens=1000, output_tokens=200):
        self.results, self.calls = list(results), []
        self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return {"result": r, "usage": dict(self.usage), "stop_reason": "end_turn"}


def reply(**obj) -> str:
    return json.dumps(obj)


def ref_of(desk, question, deal, pred) -> str:
    """The label a block gets in this fixture (hit order decides it, not the test)."""
    p = desk.answerer.prepare(question, deal)
    return next(b.ref for b in p.blocks if pred(b))


def amended(b) -> bool:
    return any(p.kind == "amendment" for p in b.parts)


def test_states_are_the_spec_states():
    assert set(STATES) == {"answered", "not_stated", "unfiled_schedule", "which_deal", "budget_cached",
                           "budget_reached", "busy", "error"}


def test_answered_carries_quote_section_agreement_and_filing_link(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    q = "What is the Acme Software outside date?"
    ref = ref_of(desk, q, None, lambda b: OUTSIDE_QUOTE in b.parts[0].text)
    run.results.append(reply(state="answered", claims=[{"text": "June 30.", "quote": OUTSIDE_QUOTE, "ref": ref}]))
    got = desk.ask(q)
    assert got["state"] == "answered" and got["served_from"] == "live" and len(run.calls) == 1
    assert got["deal"]["id"] == "edgar_0001" and got["deal"]["link"] == "https://example.test/a"
    c = got["claims"][0]
    assert c["quote"] == OUTSIDE_QUOTE and c["section_path"] and c["link"] == "https://example.test/a"
    assert "Acme Software" in c["agreement"] and c["amendment_no"] is None
    assert got["tokens"] == {"in": 1000, "out": 200} and got["ms"] >= 0


def test_amended_claim_carries_its_number_and_the_amendment_link(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    ref = ref_of(desk, "termination fee", "edgar_0001", amended)
    run.results.append(reply(state="answered", claims=[{"text": "Fee is $40m.", "quote": AMEND_QUOTE, "ref": ref}]))
    got = desk.ask("termination fee", "edgar_0001")
    assert got["state"] == "answered" and got["amended"] is True
    c = got["claims"][0]
    assert c["amendment_no"] == 2 and c["amendment_link"] == "https://example.test/b"


def test_not_stated_by_the_model_and_by_retrieval(tmp_path):
    run = Scripted(NOT_STATED)
    desk = make_desk(tmp_path, run)
    assert desk.ask("termination fee", "edgar_0001")["state"] == "not_stated"
    nothing = desk.ask("???", "edgar_0001")  # no word to search for: no passage, no model call
    assert nothing["state"] == "not_stated" and nothing["served_from"] is None and len(run.calls) == 1


def test_unfiled_schedule(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    p = desk.answerer.prepare("termination fee schedule", "edgar_0001")
    tagged = next(b for b in p.blocks if b.schedule_ref)
    quote = tagged.parts[0].text.split(".")[0]
    run.results.append(reply(state="unfiled_schedule", claims=[{"text": "In a schedule.", "quote": quote,
                                                                "ref": tagged.ref}]))
    assert desk.ask("termination fee schedule", "edgar_0001")["state"] == "unfiled_schedule"


def test_which_deal_makes_no_call(tmp_path):
    run = Scripted()
    got = make_desk(tmp_path, run).ask("What is the outside date for Zeta Labs?")
    assert got["state"] == "which_deal" and run.calls == [] and got["candidates"] == [] and got["deal"] is None


def test_unknown_deal_is_refused(tmp_path):
    desk = make_desk(tmp_path, Scripted())
    with pytest.raises(ValueError):
        desk.ask("termination fee", "edgar_9999")
    with pytest.raises(ValueError):
        desk.search("termination fee", "edgar_9999")


def test_a_repeated_question_is_served_from_the_cache(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    ref = ref_of(desk, "termination fee", "edgar_0001", amended)
    run.results.append(reply(state="answered", claims=[{"text": "t", "quote": AMEND_QUOTE, "ref": ref}]))
    first = desk.ask("termination fee", "edgar_0001")
    again = desk.ask("  termination   fee ", "edgar_0001")
    assert again["served_from"] == "cache" and again["state"] == "answered" and len(run.calls) == 1
    assert again["claims"] == first["claims"] and again["tokens"] is None


def test_busy_when_no_slot_or_no_fresh_call_is_left(tmp_path):
    run = Scripted(NOT_STATED)
    assert make_desk(tmp_path / "a", run, ask_slots=0).ask("termination fee", "edgar_0001")["state"] == "busy"
    assert make_desk(tmp_path / "b", run, fresh_per_hour=0).ask("termination fee", "edgar_0001")["state"] == "busy"
    assert run.calls == []


def test_failures_are_errors_and_book_only_what_was_billed(tmp_path):
    prices = load_prices(PRICES)
    billed = {"input_tokens": 1000, "output_tokens": 0, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 0}
    run = Scripted(RunnerError("overloaded", "overloaded"), RunnerError("truncated", "max_tokens", billed),
                   "not json at all")
    desk = make_desk(tmp_path, run)
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"
    assert desk.budget.spent()["month"] == 0.0  # rejected before any work: released, not billed
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"
    after_truncated = desk.budget.spent()["month"]
    assert after_truncated == pytest.approx(cost_usd(prices, billed))
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"  # unparseable: its usage is booked
    assert desk.budget.spent()["month"] > after_truncated and len(run.calls) == 3  # errors are never cached


def test_a_billing_refusal_reads_as_budget_reached(tmp_path):
    run = Scripted(RunnerError("billing", "credit balance too low"))
    assert make_desk(tmp_path, run).ask("termination fee", "edgar_0001")["state"] == "budget_reached"


@pytest.mark.parametrize("kind", ["timeout", "connection"])
def test_a_timeout_or_lost_connection_is_booked_at_worst_case(tmp_path, kind):
    desk = make_desk(tmp_path, Scripted(RunnerError(kind, "no reply")))
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"
    p = desk.answerer.prepare("termination fee", "edgar_0001")
    worst = worst_case_usd(load_prices(PRICES), len(p.prompt), desk.config.max_tokens)
    assert desk.budget.spent()["month"] == pytest.approx(worst, abs=1e-6)  # spent() rounds to 6 places
    rows = sqlite3.connect(desk.config.state_dir / "budget.db").execute("SELECT status FROM spend").fetchall()
    assert rows == [("settled",)]


def test_the_cap_trips(tmp_path):
    """PRD M5 exit. Once spend reaches the cap, a new question gets budget_reached, a cached one is still served
    as budget_cached, and the model is never called again."""
    run = Scripted(input_tokens=200_000, output_tokens=20_000)  # one call costs far more than the cap
    desk = make_desk(tmp_path, run, month_cap_usd=0.05, day_cap_usd=0.05)
    ref = ref_of(desk, "termination fee", "edgar_0001", amended)
    run.results.append(reply(state="answered", claims=[{"text": "t", "quote": AMEND_QUOTE, "ref": ref}]))
    assert desk.ask("termination fee", "edgar_0001")["state"] == "answered"
    assert desk.health()["budget"] == "reached"
    fresh = desk.ask("What is the Acme Software outside date?")
    cached = desk.ask("termination fee", "edgar_0001")
    assert fresh["state"] == "budget_reached" and fresh["served_from"] is None
    assert cached["state"] == "budget_cached" and cached["cached_state"] == "answered"
    assert cached["served_from"] == "cache" and cached["claims"]
    assert len(run.calls) == 1


def test_search_never_calls_the_model_even_with_the_budget_spent(tmp_path):
    run = Scripted()
    got = make_desk(tmp_path, run, month_cap_usd=0.0, day_cap_usd=0.0).search("What is the Acme Software outside date?")
    assert run.calls == [] and got["hits"] and got["scope"]["deal"] == "edgar_0001"
    h = got["hits"][0]
    assert {"passage_id", "deal", "section_path", "text", "definitions", "link", "score", "stages"} <= set(h)
    assert set(h["stages"]) == {"bm25", "dense"} and h["text"]


def test_concurrent_asks_never_spend_past_the_cap(tmp_path):
    run = fake_claude(NOT_STATED, input_tokens=100, output_tokens=100)
    desk = make_desk(tmp_path, run, month_cap_usd=0.03, day_cap_usd=0.03, ask_slots=20)
    out: list[dict] = []
    threads = [threading.Thread(target=lambda i=i: out.append(desk.ask(f"termination fee clause {i}", "edgar_0001")))
               for i in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert desk.budget.spent()["month"] <= 0.03
    assert {o["state"] for o in out} <= {"not_stated", "budget_reached"} and len(out) == 20


def test_a_crash_between_reserve_and_settle_is_booked_at_worst_case_once(tmp_path):
    """A process killed during the model call leaves an open reservation. It counts at worst case at once; a
    restart after the stale window books it at worst case, and only once."""
    desk = make_desk(tmp_path, Scripted(SystemExit("killed")))
    with pytest.raises(SystemExit):
        desk.ask("termination fee", "edgar_0001")
    p = desk.answerer.prepare("termination fee", "edgar_0001")
    prices = load_prices(PRICES)
    worst = worst_case_usd(prices, len(p.prompt), desk.config.max_tokens)
    db = desk.config.state_dir / "budget.db"
    assert Budget(db, 5.0, 1.0, prices).spent()["month"] == pytest.approx(worst, abs=1e-6)  # open: at worst
    for _ in range(2):  # restarts after the stale window: settled at worst once, never twice
        Budget(db, 5.0, 1.0, prices, clock=lambda: time.time() + STALE_S + 1)
        rows = sqlite3.connect(db).execute("SELECT status, usd FROM spend").fetchall()
        assert len(rows) == 1 and rows[0][0] == "settled" and rows[0][1] == pytest.approx(worst)


def test_health_reports_the_running_code_bundle_and_facts(tmp_path):
    desk = make_desk(tmp_path, Scripted())
    h = desk.health()
    assert h["ok"] is True and h["git_sha"] == "abc123" and h["model"] == "claude-haiku-4-5-20251001"
    assert h["bundle_sha"] == hashlib.sha256(desk.config.bundle.read_bytes()).hexdigest()
    assert h["facts_sha"] == hashlib.sha256(desk.config.facts_path.read_bytes()).hexdigest()
    assert h["template_sha"] == TEMPLATE_SHA and h["budget"] == "ok" and h["rss_mb"] > 0
    assert isinstance(h["bundle_meta"], dict) and "spent" not in h  # spend amounts are never public


def test_deals_lists_every_agreement_for_the_picker(tmp_path):
    rows = make_desk(tmp_path, Scripted()).deals()
    assert {r["id"] for r in rows} == {"contract_1", "edgar_0001"}
    assert all({"id", "target", "parent", "signed", "source", "link"} <= set(r) for r in rows)
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/test_desk.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'service.desk'`.

- [ ] **Step 4: Write `service/desk.py`**

```python
import hashlib
import resource
import sys
import threading
import time

from answer.answerer import Answerer, ParseError, Prepared
from answer.api_runner import RunnerError
from answer.prompt import TEMPLATE_SHA
from retrieval.live import bundle_meta, links_for
from service.cache import normalise_question
from service.prices import load_prices, worst_case_usd

STATES = ("answered", "not_stated", "unfiled_schedule", "which_deal", "budget_cached", "budget_reached", "busy",
          "error")
# A typical prompt is about 15k characters: five passages with their definitions (measured on deals.db in M5
# planning). The budget reads "reached" once it cannot cover one such call at worst case.
TYPICAL_PROMPT_CHARS = 15_000
SEARCH_K = 10
# Failures with no usage after which the request may still have been billed: booked at worst case. Every other
# failure without usage was rejected unbilled and is released.
MAYBE_BILLED = ("timeout", "connection")
VOLATILE = ("served_from", "budget", "tokens", "ms")  # never stored in the cache


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rss_mb() -> float:
    """Peak resident memory of this process (ru_maxrss is KiB on Linux, bytes on macOS)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


class Desk:
    """The live service without HTTP: R7n retrieval, the M4 answerer, the spend ledger, the cache and the limits.
    One lock guards the bundle connection (retrieval); the model call runs outside it."""

    def __init__(self, ladder, runner, config, budget, cache, fresh, slots):
        self.ladder, self.runner, self.config = ladder, runner, config
        self.budget, self.cache, self.fresh, self.slots = budget, cache, fresh, slots
        self.answerer = Answerer(ladder, runner, config.model)
        self._lock = threading.Lock()
        self._min_call = worst_case_usd(load_prices(config.prices_path), TYPICAL_PROMPT_CHARS, config.max_tokens)
        rows = ladder.conn.execute("SELECT contract_id, source, target, parent, signed FROM deals").fetchall()
        self._deals = {cid: {"id": cid, "source": src, "target": t, "parent": p, "signed": s}
                       for cid, src, t, p, s in rows}
        self._links = {cid: links_for(ladder.conn, cid) for cid in self._deals}
        self._bundle_sha = _sha256(config.bundle)
        self._facts_sha = _sha256(config.facts_path)
        self._meta = bundle_meta(ladder.conn)

    def _check_deal(self, deal: str | None) -> None:
        if deal is not None and deal not in self._deals:
            raise ValueError(f"unknown deal {deal!r}")

    def _deal(self, cid: str | None) -> dict | None:
        d = self._deals.get(cid) if cid else None
        return None if d is None else dict(d, link=self._links[cid]["filing"])

    def _name(self, cid: str) -> str:
        d = self._deals.get(cid) or {}
        parts = [x for x in (d.get("target"), d.get("parent")) if x]
        return " – ".join(parts) if parts else cid

    def _claims(self, answer) -> list[dict]:
        out = []
        for c in answer.claims:
            links = self._links.get(c.contract_id, {"filing": None, "amendments": {}})
            amended = c.part == "amendment"
            out.append({"text": c.text, "quote": c.quote, "section_path": c.section_path,
                        "agreement": self._name(c.contract_id), "link": links["filing"],
                        "amendment_no": c.amendment_no if amended else None,
                        "amendment_link": links["amendments"].get(c.amendment_no) if amended else None})
        return out

    def _budget(self) -> str:
        return self.budget.state(self._min_call)

    def _payload(self, state: str, question: str, answer=None, served_from=None, tokens=None) -> dict:
        candidates = answer.candidates if answer is not None and state == "which_deal" else ()
        return {"state": state, "question": question,
                "deal": self._deal(answer.contract_id) if answer is not None else None,
                "claims": self._claims(answer) if answer is not None else [],
                "amended": bool(answer.amended) if answer is not None else False,
                "candidates": [{"id": c, "name": self._name(c)} for c in candidates],
                "served_from": served_from, "budget": self._budget(), "tokens": tokens}

    def ask(self, question: str, deal: str | None = None) -> dict:
        t0 = time.perf_counter()
        self._check_deal(deal)
        q = normalise_question(question)
        with self._lock:
            prep = self.answerer.prepare(q, deal)
        out = self._answer(q, prep)
        out["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return out

    def _answer(self, q: str, prep) -> dict:
        if not isinstance(prep, Prepared):  # which_deal, or nothing retrieved: never a model call
            return self._payload(prep.state, q, prep)
        hit = self.cache.get(self.config.model, prep.prompt_sha)
        if hit is not None:
            budget = self._budget()
            state = "budget_cached" if budget == "reached" else hit["state"]
            return dict(hit, state=state, cached_state=hit["state"], served_from="cache", budget=budget, tokens=None)
        if not self.slots.try_acquire():
            return self._payload("busy", q)
        try:
            if self.fresh.allow("*"):
                return self._payload("busy", q)
            rid = self.budget.reserve(len(prep.prompt), self.config.max_tokens)
            if rid is None:
                return self._payload("budget_reached", q)
            t1 = time.perf_counter()
            try:
                reply = self.runner(prep.prompt, self.config.model)
            except RunnerError as e:
                if e.usage:
                    self.budget.settle(rid, e.usage)
                elif e.kind in MAYBE_BILLED:
                    self.budget.settle(rid, None)
                else:
                    self.budget.release(rid)
                return self._payload("budget_reached" if e.kind == "billing" else "error", q)
            self.budget.settle(rid, reply.get("usage") or {})
            try:
                answer = self.answerer.finish(prep, reply, (time.perf_counter() - t1) * 1000.0 + prep.retrieval_ms)
            except ParseError:
                return self._payload("error", q)
            out = self._payload(answer.state, q, answer, "live", {"in": answer.tokens_in, "out": answer.tokens_out})
            self.cache.put(self.config.model, prep.prompt_sha, {k: v for k, v in out.items() if k not in VOLATILE})
            return out
        finally:
            self.slots.release()

    def search(self, q: str, deal: str | None = None) -> dict:
        self._check_deal(deal)
        q = normalise_question(q)
        with self._lock:
            got = self.ladder.run("R7n", q, deal, SEARCH_K)
            hits = []
            for h in got.hits:
                path = self.ladder.conn.execute("SELECT section_path FROM passages WHERE passage_id = ?",
                                                (h.passage_id,)).fetchone()[0]
                terms = [t for (t,) in self.ladder.conn.execute(
                    "SELECT term FROM passage_defs WHERE passage_id = ? ORDER BY rank", (h.passage_id,))]
                hits.append({"passage_id": h.passage_id, "deal": self._deal(h.contract_id), "section_path": path,
                             "text": self.ladder.texts[h.contract_id][h.start:h.end], "definitions": terms,
                             "link": self._links[h.contract_id]["filing"], "score": h.score,
                             "stages": got.stages.get(h.passage_id, {"bm25": None, "dense": None})})
        scope = got.scope
        cands = scope.candidates if scope is not None else ()
        return {"query": q, "scope": {"deal": scope.contract_id if scope is not None else deal,
                                      "candidates": [{"id": c, "name": self._name(c)} for c in cands]},
                "hits": hits, "ms": round(got.ms, 1)}

    def deals(self) -> list[dict]:
        return sorted((self._deal(cid) for cid in self._deals), key=lambda d: ((d["target"] or d["id"]).casefold(), d["id"]))

    def health(self) -> dict:
        return {"ok": True, "git_sha": self.config.git_sha, "bundle_sha": self._bundle_sha,
                "facts_sha": self._facts_sha, "template_sha": TEMPLATE_SHA, "model": self.config.model,
                "budget": self._budget(), "rss_mb": _rss_mb(), "bundle_meta": self._meta}
```

- [ ] **Step 5: Run the Desk tests**

Run: `uv run pytest tests/test_desk.py -q`
Expected: all pass.

If `test_concurrent_asks_never_spend_past_the_cap` fails, the reservation in `Budget` is not atomic. That is a Task 6 bug: go back to Task 6 rather than adding a lock here.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock service/desk.py tests/test_desk.py
git commit -m "m5: Desk — R7n retrieval, the M4 answerer, budget, cache and limits behind one object; the cap trips in a test

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Write the failing app, warm and CLI tests**

`tests/test_app.py`:

```python
import json

from fastapi.testclient import TestClient

from service.app import create_app
from service.warm import warm
from tests.fakes import fake_claude
from tests.test_desk import NOT_STATED, Scripted, make_desk


def client(tmp_path, runner=None, host="203.0.113.7", **kw):
    desk = make_desk(tmp_path, runner or Scripted(), **kw)
    return TestClient(create_app(desk.config, desk), client=(host, 50000)), desk


def test_round_trip(tmp_path):
    c, _ = client(tmp_path, Scripted(NOT_STATED))
    h = c.get("/api/health").json()
    assert h["ok"] is True and h["git_sha"] == "abc123"
    assert {d["id"] for d in c.get("/api/deals").json()} == {"contract_1", "edgar_0001"}
    s = c.get("/api/search", params={"q": "What is the Acme Software outside date?"}).json()
    assert s["hits"] and s["scope"]["deal"] == "edgar_0001"
    a = c.post("/api/ask", json={"question": "termination fee", "deal": "edgar_0001"}).json()
    assert a["state"] == "not_stated" and a["served_from"] == "live"
    assert c.get("/docs").status_code == 404 and c.get("/openapi.json").status_code == 404


def test_invalid_input_is_422_and_never_retrieves(tmp_path, monkeypatch):
    c, desk = client(tmp_path)

    def boom(*a, **k):
        raise AssertionError("retrieval ran for an invalid request")
    monkeypatch.setattr(desk.answerer, "prepare", boom)
    assert c.post("/api/ask", json={"question": "   "}).status_code == 422
    assert c.post("/api/ask", json={"question": "x" * 301}).status_code == 422
    assert c.post("/api/ask", json={"question": 7}).status_code == 422
    assert c.post("/api/ask", json={"question": "fee", "deal": 7}).status_code == 422
    assert c.post("/api/ask", json={"question": "fee", "deal": "edgar_9999"}).status_code == 422
    assert c.get("/api/search", params={"q": ""}).status_code == 422
    assert c.get("/api/search", params={"q": "fee", "deal": "edgar_9999"}).status_code == 422


def test_rate_limits_answer_429_with_retry_after(tmp_path):
    c, _ = client(tmp_path, Scripted(NOT_STATED), ask_per_hour=1, search_per_minute=1)
    assert c.post("/api/ask", json={"question": "termination fee", "deal": "edgar_0001"}).status_code == 200
    r = c.post("/api/ask", json={"question": "termination fee", "deal": "edgar_0001"})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    assert c.get("/api/search", params={"q": "outside date"}).status_code == 200
    assert c.get("/api/search", params={"q": "outside date"}).status_code == 429


def test_ipv6_neighbours_in_one_slash_64_share_a_bucket(tmp_path):
    c1, _ = client(tmp_path, host="2001:db8::1", search_per_minute=1)
    same = TestClient(c1.app, client=("2001:db8::2", 50000))
    other = TestClient(c1.app, client=("2001:db8:0:1::2", 50000))
    assert c1.get("/api/search", params={"q": "outside date"}).status_code == 200
    assert same.get("/api/search", params={"q": "outside date"}).status_code == 429
    assert other.get("/api/search", params={"q": "outside date"}).status_code == 200


def test_the_request_log_holds_no_address_and_no_question(tmp_path, capsys):
    c, _ = client(tmp_path, Scripted(NOT_STATED))
    c.post("/api/ask", json={"question": "termination fee secretword", "deal": "edgar_0001"})
    c.get("/api/search", params={"q": "outside date secretword"})
    err = capsys.readouterr().err
    assert '"route": "ask"' in err and '"route": "search"' in err
    assert "secretword" not in err and "203.0.113.7" not in err


def test_warm_answers_each_example_once(tmp_path):
    run = fake_claude(NOT_STATED)
    desk = make_desk(tmp_path, run)
    examples = [{"family": "termination_fee", "question": "What is the Acme Software termination fee?"},
                {"family": "equity_awards", "question": "What happens to options in the Gamma deal?"}]
    assert warm(desk, examples) == {"asked": 2, "cached": 0, "states": {"not_stated": 2}}
    assert warm(desk, examples)["cached"] == 2 and len(run.calls) == 2


def test_dtd_warm_builds_the_service_desk(tmp_path, monkeypatch, capsys):
    from pipeline import cli
    desk = make_desk(tmp_path, fake_claude(NOT_STATED))
    seen = {}

    def build(config):
        seen["config"] = config
        return desk
    monkeypatch.setattr(cli, "from_env", lambda: desk.config)
    monkeypatch.setattr(cli, "build_desk", build)
    path = tmp_path / "examples.json"
    path.write_text(json.dumps([{"family": "termination_fee", "question": "What is the Acme Software termination fee?"}]))
    assert cli.entry(["warm", "--examples", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["asked"] == 1
    assert seen["config"].fresh_per_hour >= 1
```

- [ ] **Step 8: Run them to see them fail**

Run: `uv run pytest tests/test_app.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'service.app'`.

- [ ] **Step 9: Write `service/app.py`, `service/warm.py` and `dtd warm`**

`service/app.py`:

```python
import json
import math
import sys
import time

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from answer.api_runner import make_api_runner
from retrieval.ladder import SETTINGS_PATH, load_settings
from retrieval.lexicon import LEXICON_PATH, load_lexicon
from retrieval.live import build_live_ladder
from retrieval.models import Embedder
from service.budget import Budget
from service.cache import AnswerCache
from service.config import Config, from_env
from service.desk import Desk
from service.limits import Buckets, Slots, client_key
from service.prices import load_prices


def build_desk(config: Config) -> Desk:
    """Everything the live service holds in memory, built once at startup."""
    embedder = Embedder(threads=2)
    embedder.embed_query("warm up")  # load the model now, not on the first visitor's question
    ladder = build_live_ladder(config.bundle, embedder, load_lexicon(LEXICON_PATH), load_settings(SETTINGS_PATH))
    config.state_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(config.state_dir / "budget.db", config.month_cap_usd, config.day_cap_usd,
                    load_prices(config.prices_path))
    return Desk(ladder, make_api_runner(config.max_tokens), config, budget, AnswerCache(config.state_dir / "cache.db"),
                Buckets(config.fresh_per_hour, 3600.0), Slots(config.ask_slots))


def _log(rec: dict) -> None:
    """One line per request, to stderr (journald on the box). Never the visitor's address or question."""
    print(json.dumps(rec, sort_keys=True), file=sys.stderr, flush=True)


def _invalid(detail: str) -> JSONResponse:
    return JSONResponse({"error": "invalid", "detail": detail}, status_code=422)


def _limited(wait: float) -> JSONResponse:
    return JSONResponse({"error": "rate_limited"}, status_code=429,
                        headers={"Retry-After": str(max(1, math.ceil(wait)))})


def create_app(config: Config | None = None, desk: Desk | None = None) -> FastAPI:
    """With no arguments (`uvicorn --factory service.app:create_app`), config comes from the environment and the desk
    is built here; tests pass both."""
    if desk is None:
        config = config or from_env()
        desk = build_desk(config)
    config = config or desk.config
    asks, searches = Buckets(config.ask_per_hour, 3600.0), Buckets(config.search_per_minute, 60.0)
    app = FastAPI(title="Deal Terms Desk", docs_url=None, redoc_url=None, openapi_url=None)

    def who(request: Request) -> str:
        return client_key(request.client.host if request.client else "unknown")

    def problem(question) -> str | None:
        if not isinstance(question, str) or not question.strip():
            return "the question is empty"
        if len(question) > config.question_max_chars:
            return "the question is too long"
        return None

    @app.get("/api/health")
    def health():
        return desk.health()

    @app.get("/api/deals")
    def deals():
        return desk.deals()

    @app.get("/api/search")
    def search(request: Request, q: str = "", deal: str | None = None):
        t0 = time.perf_counter()
        bad = problem(q)
        if bad:
            return _invalid(bad)
        wait = searches.allow(who(request))
        if wait:
            return _limited(wait)
        try:
            got = desk.search(q, deal or None)
        except ValueError as e:
            return _invalid(str(e))
        _log({"route": "search", "status": 200, "hits": len(got["hits"]),
              "ms": round((time.perf_counter() - t0) * 1000.0, 1)})
        return got

    @app.post("/api/ask")
    def ask(request: Request, body: dict = Body(...)):
        t0 = time.perf_counter()
        question, deal = body.get("question"), body.get("deal")
        bad = problem(question) or (None if deal is None or isinstance(deal, str) else "the deal must be an id")
        if bad:
            return _invalid(bad)
        wait = asks.allow(who(request))
        if wait:
            return _limited(wait)
        try:
            got = desk.ask(question, deal or None)
        except ValueError as e:
            return _invalid(str(e))
        _log({"route": "ask", "status": 200, "state": got["state"], "served_from": got["served_from"],
              "tokens": got["tokens"], "ms": round((time.perf_counter() - t0) * 1000.0, 1)})
        return got

    return app
```

`service/warm.py`:

```python
from collections import Counter


def warm(desk, examples: list[dict]) -> dict:
    """Ask every example through the live path, so the example chips never cost a visitor's call and the
    "budget reached" state still has answers to show. A rerun costs nothing: answered examples are cache hits."""
    states, cached = Counter(), 0
    for ex in examples:
        got = desk.ask(ex["question"], ex.get("deal"))
        states[got["state"]] += 1
        cached += got["served_from"] == "cache"
    return {"asked": len(examples), "cached": cached, "states": dict(sorted(states.items()))}
```

`pipeline/cli.py` changes:
- Imports at the top: `from service.app import build_desk`, `from service.config import from_env`, `from service.warm import warm`.
- Add the handler below `_cmd_report`:

```python
EXAMPLES = Path("site/examples.json")


def _cmd_warm(args) -> int:
    examples = json.loads(Path(args.examples).read_text(encoding="utf-8"))
    config = from_env()
    # warming is the operator's own call: it must not run out of the visitors' hourly fresh-call allowance
    desk = build_desk(replace(config, fresh_per_hour=max(config.fresh_per_hour, len(examples))))
    print(json.dumps(warm(desk, examples)))
    return 0
```

In `entry`, after the `report` parser:

```python
    warm_p = sub.add_parser("warm")
    warm_p.add_argument("--examples", default=str(EXAMPLES))
    warm_p.set_defaults(fn=_cmd_warm)
```

- [ ] **Step 10: Run the app tests and the whole suite**

Run: `uv run pytest tests/test_app.py tests/test_desk.py -q && uv run pytest -q`
Expected: all pass. The full suite now has one fewer model-free gap.

- [ ] **Step 11: Commit**

```bash
git add service/app.py service/warm.py pipeline/cli.py tests/test_app.py
git commit -m "m5: FastAPI app (health, deals, search, ask; 422, 429, no address or question in logs) and dtd warm

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: Site

**Files:**
- Create: `facts/labels.py`, `facts/site.py`, `site/templates/base.html`, `site/templates/index.html`,
  `site/templates/search.html`, `site/static/app.js`, `site/static/style.css`, `site/examples.json`
- Modify: `pipeline/cli.py` (`dtd site [--strict]`), `.gitignore` (`site/dist/`), `.github/workflows/ci.yml`
- Test: `tests/test_labels.py`, `tests/test_site.py`

**Interfaces:**
- Consumes:
  - `facts.json` keys, all verified present on 2026-10-05 except the `m5_*` ones, which come from Task 11;
  - `facts.report_m4.LABELS` and `GROUPS`, `evals.tmachine.FAMILIES`, `facts.m2.CHAR_KS`;
  - `retrieval.scope.Resolver`, for the examples test only.
- Produces:
  - `facts/labels.py`: `MACHINE_BUILT_PREFIXES`, `is_machine_built(key)`, `tier_label(key)`, plus the `MACHINE` and `HUMAN` constants;
  - `facts/site.py`: `render_site(facts, out, examples, strict=False) -> list[Path]`, plus `results_tables()`, `render_table`, `cell_keys`, `Facts`, `METHOD`;
  - `site/examples.json`: a list of `{"family", "question"}`, two per lead family.
- The pages fetch `/examples.json`, `/api/deals`, `/api/search` and `/api/ask`. They load `/static/style.css` and `/static/app.js`, with no inline script or style.

- [ ] **Step 1: Write the failing label tests**

`tests/test_labels.py`:

```python
import collections
import json
import re
from pathlib import Path

from facts.labels import HUMAN, MACHINE, is_machine_built, tier_label

NUM = re.compile(r"[-+]?\d+\.\d+")


def test_known_keys_are_classified():
    assert is_machine_built("m3_t_r6_report_recall_at_5") and is_machine_built("m3_tier_r1_machine_recall_at_5")
    assert is_machine_built("m2_r5_llm_report_recall_at_5") and is_machine_built("m4_cmp_model_haiku_tmachine_tune_agree")
    assert not is_machine_built("m3_tier_r1_human_recall_at_5") and not is_machine_built("m4_tokens_haiku_report_in_mean")
    assert tier_label("m2_r5_report_recall_at_5") == HUMAN and tier_label("m4_thuman_haiku_report_accuracy") == HUMAN
    assert tier_label("m4_refute_survival_rate") == MACHINE and tier_label("m4_gate_thuman_report_pass_rate") is None


def test_every_number_the_reports_print_as_machine_built_is_classified_so():
    """Cross-check against the committed M0-M4 reports. Take every number on a line that says machine-built, or
    under a heading ending "(machine-built)". When it is a float held by exactly one fact, that fact must be
    machine-built. "machine-built lexicon" describes R5's method, not the number beside it."""
    f = json.loads(Path("facts.json").read_text())
    by_value = collections.defaultdict(list)
    for k, v in f.items():
        if isinstance(v, float):
            by_value[v].append(k)
    unique = {v: ks[0] for v, ks in by_value.items() if len(ks) == 1}
    checked, wrong = 0, []
    for report in sorted(Path("docs").glob("m*/REPORT.md")):
        for section in re.split(r"\n(?=## )", report.read_text()):
            whole = "(machine-built)" in section.splitlines()[0]
            for line in section.splitlines():
                line = line.replace("machine-built lexicon", "")
                if not (whole or "machine-built" in line):
                    continue
                for n in NUM.findall(line):
                    key = unique.get(float(n))
                    if key is not None and n.lstrip("+") == str(f[key]):
                        checked += 1
                        if not is_machine_built(key):
                            wrong.append((report.parent.name, key))
    assert checked > 100 and wrong == []  # planning measured 159 checks, 0 wrong
```

- [ ] **Step 2: Run, see it fail, write `facts/labels.py`, run again**

Run: `uv run pytest tests/test_labels.py -q`. Expected: FAIL, `No module named 'facts.labels'`.

`facts/labels.py`:

```python
import re

MACHINE = "machine-built"
HUMAN = "human-labelled (MAUD)"

# Facts whose numbers come from model passes, not lawyers. Each carries "machine-built" wherever it is printed.
# Checked against the labels the committed M0-M4 reports already print (tests/test_labels.py).
MACHINE_BUILT_PREFIXES = (
    "m0_sample_", "m0_candidate_",
    "m2_lexicon_", "m2_llm_rewrite_", "m2_r5_llm_", "m2_cmp_r5_llm_", "m2_machine_disputed_",
    "m3_tm_", "m3_t_", "m3_cmp_t_", "m3_r5_llm_append_", "m3_cmp_r5_llm_append_", "m3_r7_",
    "m3_tier_kept", "m3_tier_match_", "m3_tier_tau", "m3_tier_machine_order",
    "m4_tmachine_", "m4_t_", "m4_cmp_t_", "m4_abstain_", "m4_refute_",
)
MACHINE_BUILT_PATTERNS = (re.compile(r"m3_tier_r\d_machine_"), re.compile(r"m4_cmp_model_[a-z]+_tmachine_"))
# Facts scored against MAUD's lawyers' labels.
HUMAN_PREFIXES = ("r1_", "m2_r1_", "m2_r2_", "m2_r3_", "m2_r4_", "m2_r5_", "m2_r6_", "m2_cmp_", "m2_cat_", "m2_fail_",
                  "m2_best_corpus", "m2_report_", "m3_tier_human_order", "m4_thuman_", "m4_r6n_", "m4_cmp_r6n_",
                  "m4_cmp_model_haiku_thuman_", "m4_cmp_model_sonnet_thuman_", "m5_bundle_r6n_")
HUMAN_PATTERNS = (re.compile(r"m3_tier_r\d_human_"),)


def is_machine_built(key: str) -> bool:
    return key.startswith(MACHINE_BUILT_PREFIXES) or any(p.match(key) for p in MACHINE_BUILT_PATTERNS)


def tier_label(key: str) -> str | None:
    """The label a fact must be shown under, or None when it depends on no answer key (sizes, timings, prices)."""
    if is_machine_built(key):
        return MACHINE
    if key.startswith(HUMAN_PREFIXES) or any(p.match(key) for p in HUMAN_PATTERNS):
        return HUMAN
    return None
```

Run: `uv run pytest tests/test_labels.py -q`. Expected: pass.

- [ ] **Step 3: Commit the labels**

```bash
git add facts/labels.py tests/test_labels.py
git commit -m "m5: machine-built / human-labelled classification of every fact, cross-checked against the reports

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 4: Write the failing site tests**

`tests/test_site.py`:

```python
import html
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from evals.tmachine import FAMILIES
from facts.labels import MACHINE, is_machine_built, tier_label
from facts.site import METHOD, Facts, cell_keys, render_cell, render_site, render_table, results_tables
from retrieval.scope import Resolver

EXAMPLES = json.loads(Path("site/examples.json").read_text())
# Names, not figures: rung names, the BM25 algorithm, metric cut-offs (recall@5) and percentile names.
ALLOWED = re.compile(r"0\.5|\bR[1-7]n?\b|BM25|@\d+|\bp(?:50|95)\b")
STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`')


class Every(dict):
    """Any fact renders as a placeholder number, so the page copy is checked, not the data."""
    def __missing__(self, key):
        return 0.5


def facts() -> dict:
    return json.loads(Path("facts.json").read_text())


def visible(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def stray_digits(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.search(r"\d", ALLOWED.sub("", line))]


def test_pages_render_from_the_committed_facts(tmp_path):
    written = render_site(facts(), tmp_path, EXAMPLES)
    assert {p.name for p in written} == {"index.html", "search.html", "results.html", "method.html", "examples.json"}
    assert (tmp_path / "static" / "app.js").exists() and (tmp_path / "static" / "style.css").exists()
    assert json.loads((tmp_path / "examples.json").read_text()) == EXAMPLES


def test_every_page_carries_the_disclaimer(tmp_path):
    for p in render_site(facts(), tmp_path, EXAMPLES)[:4]:
        assert "This is not legal advice." in p.read_text(), p.name


def test_page_copy_has_no_hard_coded_digits(tmp_path):
    for p in render_site(Every(), tmp_path, EXAMPLES)[:4]:
        assert stray_digits(visible(p.read_text())) == [], p.name


def test_templates_examples_and_app_strings_have_no_digits():
    for t in sorted(Path("site/templates").glob("*.html")):
        assert stray_digits(visible(re.sub(r"\{\{\w+\}\}", "", t.read_text()))) == [], t.name
    assert stray_digits("\n".join(e["question"] for e in EXAMPLES)) == []
    js = Path("site/static/app.js").read_text()
    assert stray_digits("\n".join(STRING.findall(js))) == []


def test_every_labelled_fact_sits_under_its_label():
    F = Facts(facts())
    for t in results_tables():
        rendered = render_table(F, t)
        cells = [(r, j, c) for r in t.rows for j, c in enumerate(r.cells)] + [(None, None, c) for c in t.note]
        for row, j, c in cells:
            col = t.head[j][1] if j is not None and j < len(t.head) else None
            effective = col or (row.tier if row is not None else None) or t.tier
            for key in cell_keys(c):
                want = tier_label(key)
                if want:
                    assert effective == want, (t.id, key, effective)
                    assert html.escape(want) in rendered, (t.id, want)


def test_method_paragraphs_with_machine_built_facts_say_so():
    F = Facts(facts())
    for _, paragraphs in METHOD:
        for para in paragraphs:
            if any(is_machine_built(k) for c in para for k in cell_keys(c)):
                assert MACHINE in "".join(render_cell(F, c) for c in para), para[0]


def test_missing_m5_facts_are_pending_unless_strict(tmp_path):
    f = {k: v for k, v in facts().items() if not k.startswith("m5_")}
    render_site(f, tmp_path / "loose", EXAMPLES)
    assert "pending" in (tmp_path / "loose" / "results.html").read_text()
    with pytest.raises(KeyError):
        render_site(f, tmp_path / "strict", EXAMPLES, strict=True)
    f.pop("m4_refute_claims")
    with pytest.raises(KeyError):  # any other missing fact is a bug, strict or not
        render_site(f, tmp_path / "broken", EXAMPLES)


def test_app_js_writes_text_never_markup():
    js = Path("site/static/app.js").read_text()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".style",
                   "javascript:"):
        assert banned not in js, banned


def test_pages_have_no_inline_script_style_or_handlers(tmp_path):
    for p in render_site(facts(), tmp_path, EXAMPLES)[:4]:
        page = p.read_text()
        assert not re.search(r"<script(?![^>]*\bsrc=)", page), p.name
        assert "style=" not in page and not re.search(r"\son[a-z]+=", page), p.name


def test_results_page_shows_every_table(tmp_path):
    render_site(facts(), tmp_path, EXAMPLES)
    page = (tmp_path / "results.html").read_text()
    for t in results_tables():
        assert f'id="{t.id}"' in page


def test_examples_cover_each_lead_family_twice_and_name_one_deal():
    assert Counter(e["family"] for e in EXAMPLES) == {fam: 2 for fam in FAMILIES}
    db = Path("data/index/deals.db")
    if not db.exists():
        pytest.skip("deals index not built in this checkout")
    resolver = Resolver(sqlite3.connect(f"file:{db}?mode=ro", uri=True))
    assert all(resolver.resolve(e["question"]).contract_id for e in EXAMPLES)


def test_dtd_site_writes_the_pages(tmp_path, monkeypatch):
    from pipeline import cli
    monkeypatch.setattr(cli, "SITE_DIST", tmp_path / "dist")
    assert cli.entry(["site"]) == 0
    assert (tmp_path / "dist" / "index.html").exists() and (tmp_path / "dist" / "static" / "app.js").exists()
```

- [ ] **Step 5: Run them to see them fail**

Run: `uv run pytest tests/test_site.py -q`
Expected: FAIL, `ModuleNotFoundError: No module named 'facts.site'`.

- [ ] **Step 6: Write the examples, templates and static files**

`site/examples.json`:
- Every question was checked on 2026-10-05 against `data/index/deals.db` and resolves to exactly one deal.
- The checks covered LinkedIn, Red Hat, Activision Blizzard, Mandiant, Cerner and HashiCorp.
- None of the questions contains a digit.

```json
[
  {"family": "equity_awards", "question": "What happens to employee stock options in the LinkedIn deal?"},
  {"family": "equity_awards", "question": "How are unvested restricted stock units treated when Red Hat is acquired?"},
  {"family": "termination_fee", "question": "How big is the break-up fee in the Activision Blizzard agreement, and when is it owed?"},
  {"family": "termination_fee", "question": "What termination fee does the Mandiant agreement set?"},
  {"family": "employee_benefits", "question": "Will Cerner employees keep their pay and benefits after the merger?"},
  {"family": "employee_benefits", "question": "What does the HashiCorp agreement promise employees about salaries and benefits?"}
]
```

`site/templates/base.html`:

```html
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{title}} · Deal Terms Desk</title>
<link rel="stylesheet" href="/static/style.css">
<script src="/static/app.js" defer></script>
</head>
<body data-page="{{page}}">
<header class="top">
<a class="brand" href="/">Deal Terms Desk</a>
<nav>{{nav}}</nav>
</header>
<main>
{{main}}
</main>
<footer>
<p class="disclaimer">This is not legal advice.</p>
<p>Every number on this site is generated from the project's measured facts. Numbers marked machine-built come from model passes, not lawyers.</p>
</footer>
</body>
</html>
```

`site/templates/index.html` (Ask):

```html
<h1>Ask an acquisition agreement</h1>
<p class="lede">Ask what a signed merger agreement says about employee stock, break-up fees, or employees' pay and benefits after the deal. Each claim in the answer quotes the agreement and links to the filing.</p>
<form id="ask-form" class="box">
<label for="question">Your question</label>
<textarea id="question" name="question" rows="3" required placeholder="What happens to employee stock options in the LinkedIn deal?"></textarea>
<label for="deal">Agreement (optional)</label>
<select id="deal" name="deal"><option value="">Any agreement: name the company in your question</option></select>
<button type="submit">Ask</button>
</form>
<section id="examples" class="examples" aria-label="Example questions"></section>
<section id="answer" class="answer" aria-live="polite"></section>
```

`site/templates/search.html`:

```html
<h1>Search the agreements</h1>
<p class="lede">The same retrieval as Ask, with no model call: ranked passages with each stage's rank and score. Search is never capped.</p>
<form id="search-form" class="box">
<label for="q">Search</label>
<input id="q" name="q" required placeholder="termination fee paid by the company">
<label for="deal">Agreement (optional)</label>
<select id="deal" name="deal"><option value="">All agreements, or the company named in the search</option></select>
<button type="submit">Search</button>
</form>
<section id="results" class="results" aria-live="polite"></section>
```

`site/static/app.js`:

```js
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
```

`site/static/style.css`:

```css
:root { --ink: #1d1d1f; --muted: #5f6368; --line: #d9d9de; --accent: #1f4e8c; --warn: #8a4b00; }
* { box-sizing: border-box; }
body { margin: 0; font: 17px/1.55 Georgia, "Times New Roman", serif; color: var(--ink); background: #fbfbf8; }
.top { display: flex; gap: 1.5rem; align-items: baseline; padding: 1rem 1.5rem; border-bottom: 1px solid var(--line); }
.brand { font-weight: bold; color: var(--ink); text-decoration: none; }
nav a { margin-right: 1rem; color: var(--accent); }
nav a[aria-current="page"] { font-weight: bold; text-decoration: none; color: var(--ink); }
main { max-width: 60rem; margin: 0 auto; padding: 1.5rem; }
footer { max-width: 60rem; margin: 2rem auto; padding: 0 1.5rem; color: var(--muted); font-size: 0.9rem; }
.disclaimer { font-weight: bold; color: var(--ink); }
.lede { color: var(--muted); }
.box { display: grid; gap: 0.5rem; margin: 1rem 0; }
textarea, input, select, button { font: inherit; padding: 0.5rem; }
button { cursor: pointer; background: var(--accent); color: #fff; border: 0; border-radius: 4px; }
.examples { display: flex; flex-wrap: wrap; gap: 0.5rem; margin: 1rem 0; }
.chip { background: #eef2f8; color: var(--accent); border: 1px solid var(--line); }
.state { font-weight: bold; }
.state-budget_cached, .state-budget_reached, .state-busy, .state-error { color: var(--warn); }
blockquote { margin: 0.5rem 0; padding-left: 1rem; border-left: 3px solid var(--accent); }
.source, .meta { color: var(--muted); font-size: 0.9rem; }
.passage { white-space: pre-wrap; font: 0.95rem/1.5 Georgia, serif; background: #fff; border: 1px solid var(--line); padding: 0.75rem; }
table { border-collapse: collapse; margin: 1rem 0 0.5rem; width: 100%; font-size: 0.92rem; }
caption { text-align: left; font-weight: bold; margin-bottom: 0.25rem; }
th, td { border-bottom: 1px solid var(--line); padding: 0.35rem 0.5rem; text-align: left; vertical-align: top; }
.tier { font-weight: normal; font-style: italic; color: var(--warn); }
.note { color: var(--muted); font-size: 0.9rem; }
```

- [ ] **Step 7: Write `facts/site.py`**

```python
import html
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from facts.labels import HUMAN, MACHINE
from facts.m2 import CHAR_KS
from facts.report_m4 import GROUPS, LABELS

SITE = Path(__file__).resolve().parent.parent / "site"
TEMPLATES, STATIC = SITE / "templates", SITE / "static"
DISCLAIMER = "This is not legal advice."
PENDING = "pending"
NAV = (("/", "ask", "Ask"), ("/search.html", "search", "Search"), ("/results.html", "results", "Results"),
       ("/method.html", "method", "Method"))


@dataclass(frozen=True)
class K:
    """A fact shown as it is."""
    key: str


@dataclass(frozen=True)
class CI:
    """A fact with its interval: key (key_lo to key_hi)."""
    key: str


@dataclass(frozen=True)
class D:
    """A paired difference: key_delta (key_lo to key_hi; helps / hurts / no measurable change)."""
    key: str


@dataclass(frozen=True)
class V:
    """A difference stored under its own name with _lo and _hi, read like D."""
    key: str


@dataclass(frozen=True)
class A:
    """A link in page copy."""
    text: str
    href: str


@dataclass(frozen=True)
class Row:
    cells: tuple
    tier: str | None = None  # the answer key behind this row's facts, when rows differ within a table


@dataclass(frozen=True)
class Table:
    id: str
    title: str
    tier: str | None  # the answer key behind every fact in the table, shown in the caption
    head: tuple  # (header text, tier or None) per column
    rows: tuple
    note: tuple = ()


class Facts:
    """Facts for the pages. A missing M5 fact (measured late in M5) renders as pending unless strict; any other
    missing fact is a bug and raises KeyError."""

    def __init__(self, facts, strict: bool = False):
        self.facts, self.strict = facts, strict

    def get(self, key: str):
        try:
            return self.facts[key]
        except KeyError:
            if key.startswith("m5_") and not self.strict:
                return None
            raise


def cell_keys(c) -> list[str]:
    if isinstance(c, K):
        return [c.key]
    if isinstance(c, (CI, V)):
        return [c.key, c.key + "_lo", c.key + "_hi"]
    if isinstance(c, D):
        return [c.key + "_delta", c.key + "_lo", c.key + "_hi"]
    return []


def _s(x) -> str:
    return PENDING if x is None else html.escape(str(x))


def _change(v, lo, hi) -> str:
    if v is None or lo is None or hi is None:
        return PENDING
    word = "helps" if lo > 0 else "hurts" if hi < 0 else "no measurable change"
    return f"{_s(v)} ({_s(lo)} to {_s(hi)}; {word})"


def render_cell(F: Facts, c) -> str:
    if isinstance(c, str):
        return html.escape(c)
    if isinstance(c, A):
        return f'<a href="{html.escape(c.href)}">{html.escape(c.text)}</a>'
    if isinstance(c, K):
        return _s(F.get(c.key))
    if isinstance(c, CI):
        v = F.get(c.key)
        return PENDING if v is None else f"{_s(v)} ({_s(F.get(c.key + '_lo'))} to {_s(F.get(c.key + '_hi'))})"
    if isinstance(c, D):
        return _change(F.get(c.key + "_delta"), F.get(c.key + "_lo"), F.get(c.key + "_hi"))
    if isinstance(c, V):
        return _change(F.get(c.key), F.get(c.key + "_lo"), F.get(c.key + "_hi"))
    raise TypeError(f"not a cell: {c!r}")


def _tag(tier) -> str:
    return f' <span class="tier">{html.escape(tier)}</span>' if tier else ""


def render_table(F: Facts, t: Table) -> str:
    by_row = any(r.tier for r in t.rows)
    head = [html.escape(h) + _tag(tier) for h, tier in t.head] + (["Answer key"] if by_row else [])
    out = [f'<table id="{t.id}">', f"<caption>{html.escape(t.title)}{_tag(t.tier)}</caption>",
           "<thead><tr>" + "".join(f'<th scope="col">{h}</th>' for h in head) + "</tr></thead>", "<tbody>"]
    for r in t.rows:
        cells = [render_cell(F, c) for c in r.cells] + ([html.escape(r.tier or "")] if by_row else [])
        out.append("<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    out.append("</tbody></table>")
    if t.note:
        out.append('<p class="note">' + "".join(render_cell(F, c) for c in t.note) + "</p>")
    return "\n".join(out)


RUNGS = ("r1", "r2", "r3", "r4", "r5", "r6")
ADDS = {"r1": "BM25 keyword search over section-aware passages",
        "r2": "Dense only: a local embedding model",
        "r3": "Hybrid: R1 and R2 fused by reciprocal rank",
        "r4": "R3 and a cross-encoder reranker",
        "r5": "R4 and a lexicon rewrite of lay words into contract words (the lexicon is machine-built)",
        "r6": "R5 and each passage's defined terms"}
# (label, slug in the M2 facts, slug in the M4 facts): the two milestones slugged MAUD's categories differently.
CATEGORIES = (("Conditions to closing", "conditions", "conditions_to_closing"),
              ("Deal protection", "deal_protection", "deal_protection_and_related_provisions"),
              ("General information", "general", "general_information"),
              ("Knowledge", "knowledge", "knowledge"),
              ("Material adverse effect", "mae", "material_adverse_effect"),
              ("Operating and efforts covenants", "covenants", "operating_and_efforts_covenant"),
              ("Remedies", "remedies", "remedies"))
FAMILY_ORDER = ("equity_awards", "termination_fee", "employee_benefits")
LBR = (("naive", "LegalBench-RAG: naive fixed-size chunks"),
       ("rcts", "LegalBench-RAG: recursive text splitter"),
       ("rcts_cohere", "LegalBench-RAG: recursive splitter and Cohere reranker"))
DASH = "—"


def _human_change(r):
    if r == "r1":
        return DASH
    return D("m2_cmp_r2_vs_r1_recall_at_5") if r == "r2" else D(f"m2_cmp_{r}_vs_prev_recall_at_5")


def _machine_change(r):
    if r == "r1":
        return DASH
    return D("m3_cmp_t_r2_vs_t_r1_recall_at_5") if r == "r2" else D(f"m3_cmp_t_{r}_vs_prev_recall_at_5")


def results_tables() -> tuple[Table, ...]:
    return (
        Table("ladder_human", "The retrieval ladder on MAUD's questions (report split)", HUMAN,
              (("Rung", None), ("What it adds", None), ("recall@5", None), ("recall@10", None), ("MRR@10", None),
               ("nDCG@10", None), ("recall@5 change from the rung above", None), ("ms p50", None),
               ("ms p95", None), ("Context tokens", None)),
              tuple(Row((r.upper(), ADDS[r], CI(f"m2_{r}_report_recall_at_5"), K(f"m2_{r}_report_recall_at_10"),
                         K(f"m2_{r}_report_mrr_at_10"), K(f"m2_{r}_report_ndcg_at_10"), _human_change(r),
                         K(f"m2_{r}_latency_ms_p50"), K(f"m2_{r}_latency_ms_p95"),
                         K(f"m2_{r}_context_tokens_mean"))) for r in RUNGS)
              + (Row(("R6n", "R6 without the reranker: the path the live desk answers from",
                      CI("m4_r6n_report_recall_at_5"), DASH, DASH, DASH, D("m4_cmp_r6n_vs_r6_recall_at_5"),
                      K("m5_live_r6n_latency_ms_p50"), K("m5_live_r6n_latency_ms_p95"), DASH)),
                 Row(("R6n, live index", "The same rung over the one index file the live desk reads",
                      CI("m5_bundle_r6n_report_recall_at_5"), DASH, DASH, DASH, DASH, DASH, DASH, DASH))),
              ("Report split: ", K("m2_report_items"), " questions from ", K("m2_report_contracts"),
               " agreements. Intervals are bootstrap intervals clustered by agreement; changes are paired. Timings "
               "were measured on the development machine; the live server's are in the last table.")),
        Table("ladder_machine", "The retrieval ladder on the tech deals (report split)", MACHINE,
              (("Rung", None), ("What it adds", None), ("recall@5", None), ("MRR@10", None),
               ("recall@5 change from the rung above", None), ("ms p95", None), ("Context tokens", None)),
              tuple(Row((r.upper(), ADDS[r], CI(f"m3_t_{r}_report_recall_at_5"), K(f"m3_t_{r}_report_mrr_at_10"),
                         _machine_change(r), K(f"m3_t_{r}_latency_ms_p95"), K(f"m3_t_{r}_context_tokens_mean")))
                    for r in RUNGS)
              + (Row(("R6, all agreements", "No deal scoping: every agreement searched at once",
                      CI("m3_t_r6_corpus_report_recall_at_5"), K("m3_t_r6_corpus_report_mrr_at_10"), DASH,
                      K("m3_t_r6_corpus_latency_ms_p95"), K("m3_t_r6_corpus_context_tokens_mean"))),
                 Row(("R7, all agreements", "R6 inside the deal the question names",
                      CI("m3_t_r7_corpus_report_recall_at_5"), K("m3_t_r7_corpus_report_mrr_at_10"),
                      D("m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5"), K("m3_t_r7_corpus_latency_ms_p95"),
                      K("m3_t_r7_corpus_context_tokens_mean"))),
                 Row(("R7n, all agreements", "R7 without the reranker: the live path",
                      CI("m4_t_r7n_corpus_report_recall_at_5"), DASH, D("m4_cmp_t_r7n_vs_t_r7_corpus_recall_at_5"),
                      K("m5_live_t_r7n_corpus_latency_ms_p95"), DASH))),
              ("Report split: ", K("m3_t_report_items"), " machine-built questions about ",
               K("m3_t_report_contracts"), " tech agreements, each a lay question naming the company. Across all "
               "agreements, a passage from the wrong agreement counts as a miss.")),
        Table("side", "Side comparisons, not rungs (MAUD's questions, report split)", None,
              (("Comparison", None), ("recall@5", None), ("Change", None)),
              (Row(("Fixed-size chunks instead of section-aware passages, on R3",
                    CI("m2_r3_fixed_report_recall_at_5"), D("m2_cmp_r3_fixed_vs_r3_recall_at_5")), HUMAN),
               Row(("A live model rewriting the question instead of the lexicon, on R5",
                    CI("m2_r5_llm_report_recall_at_5"), D("m2_cmp_r5_llm_vs_r5_recall_at_5")), MACHINE))),
        Table("families_human", "By MAUD deal-point category (report split)", HUMAN,
              (("Category", None), ("R6 recall@5", None), ("R6 change from R1", None), ("Answer accuracy", None),
               ("Most-common-answer baseline", None)),
              tuple(Row((label, K(f"m2_r6_cat_{a}_recall_at_5"), D(f"m2_cmp_r6_vs_r1_cat_{a}_recall_at_5"),
                         CI(f"m4_thuman_haiku_{b}_accuracy"), CI(f"m4_thuman_haiku_{b}_baseline")))
                    for label, a, b in CATEGORIES)),
        Table("families_machine", "By lead question family (tech deals, report split)", MACHINE,
              (("Family", None), ("Kept items", None), ("Two-pass agreement rate", None),
               ("R6 recall@5 inside the deal", None), ("R7 recall@5 across all agreements", None),
               ("Answer agrees", None), ("Agrees or partly", None)),
              tuple(Row((LABELS[fam], K(f"m3_tm_{fam}_kept"), K(f"m3_tm_{fam}_agreement_rate"),
                         K(f"m3_t_r6_{fam}_recall_at_5"), K(f"m3_t_r7_corpus_{fam}_recall_at_5"),
                         K(f"m4_tmachine_haiku_{fam}_agree"), K(f"m4_tmachine_haiku_{fam}_agree_or_partial")))
                    for fam in FAMILY_ORDER)),
        Table("tier_agreement", "The rung order under the lawyers' key and under the machine-built key", None,
              (("Rung", None), ("recall@5, lawyers' key", HUMAN), ("recall@5, machine-built key", MACHINE)),
              tuple(Row((r.upper(), K(f"m3_tier_{r}_human_recall_at_5"), K(f"m3_tier_{r}_machine_recall_at_5")))
                    for r in RUNGS),
              ("The same two-pass procedure that built the tech-deal key was run on MAUD's own questions, so those "
               "questions have two keys.",)),
        Table("tier_summary", "How far the machine-built key can be trusted", MACHINE,
              (("Measure", None), ("Value", None)),
              (Row(("The machine span overlaps the lawyers' span", CI("m3_tier_match_rate"))),
               Row(("Kendall's tau between the two rung orders", CI("m3_tier_tau"))),
               Row(("Items where both machine passes agreed", K("m3_tier_kept"))),
               Row(("Items asked", K("m3_tier_items"))),
               Row(("Agreements", K("m3_tier_contracts")))),
              ("This is evidence for or against trusting the machine-built key, not proof.",)),
        Table("answers_human", "Answers to MAUD's questions (report split)", HUMAN,
              (("Measure", None), ("Value", None)),
              (Row(("The answerer picks MAUD's answer", CI("m4_thuman_haiku_report_accuracy"))),
               Row(("The same, counting only picks whose citations survived the gate",
                    CI("m4_thuman_haiku_report_accuracy_cited"))),
               Row(("Always picking each question's most common answer (baseline)",
                    CI("m4_thuman_haiku_report_baseline"))),
               Row(("Answerer minus baseline", V("m4_thuman_haiku_report_vs_baseline"))),
               Row(("Questions scored", K("m4_thuman_haiku_report_n"))),
               Row(("Questions asked", K("m4_thuman_haiku_report_items")))),
              ("Answer model: ", K("m4_answer_model"), ".")),
        Table("answers_machine", "Answers to the tech-deal questions (report split)", MACHINE,
              (("Measure", None), ("Value", None)),
              (Row(("A judge model finds the answer agrees with the kept machine answers",
                    CI("m4_tmachine_haiku_report_agree"))),
               Row(("Agrees or partly agrees", CI("m4_tmachine_haiku_report_agree_or_partial"))),
               Row(("The judge declined to rate", K("m4_tmachine_haiku_report_declined"))),
               Row(("Questions", K("m4_tmachine_haiku_report_items")))),
              ("Judge model: ", K("m4_judge_model"), ". The judge compares each answer with the two kept machine "
               "answers.")),
        Table("abstention", "Declining when the answer is not there", MACHINE,
              (("Group", None), ("Questions", None), ("Correct decline", None), ("False answer", None)),
              tuple(Row((GROUPS[g], K(f"m4_abstain_{g}_items"), K(f"m4_abstain_{g}_correct_rate"),
                         K(f"m4_abstain_{g}_false_answer_rate")))
                    for g in ("absent", "earnout", "schedule", "unknown_deal", "ambiguous_deal")),
              ("The right answer to each of these is a decline: \"not stated in this agreement\", \"in a schedule "
               "that was not filed\" or \"which agreement?\". The two name groups hold by construction: they test "
               "the deal resolver, which makes no model call.",)),
        Table("gate", "The citation gate", None,
              (("Questions", None), ("Claims returned", None), ("Claims kept", None), ("Share kept", None)),
              (Row(("MAUD's questions", K("m4_gate_thuman_report_returned"), K("m4_gate_thuman_report_kept"),
                    K("m4_gate_thuman_report_pass_rate"))),
               Row(("Tech-deal questions", K("m4_gate_tmachine_report_returned"), K("m4_gate_tmachine_report_kept"),
                    K("m4_gate_tmachine_report_pass_rate")))),
              ("A claim is kept only if its quote occurs word for word in the passage it cites. This check needs "
               "no answer key.",)),
        Table("refute", "A second model tries to refute each kept claim", MACHINE,
              (("Measure", None), ("Value", None)),
              (Row(("Share of claims it failed to refute", K("m4_refute_survival_rate"))),
               Row(("Claims checked", K("m4_refute_claims"))),
               Row(("Unreadable replies", K("m4_refute_unparsed"))))),
        Table("misses", "Why retrieval misses or answers go wrong", None,
              (("Class", None), ("Value", None), ("What it counts", None)),
              (Row(("All misses (R6, MAUD)", K("m2_fail_r6_misses"),
                    "Report-split questions whose gold span is not in the top five passages"), HUMAN),
               Row(("Wrong section", K("m2_fail_r6_wrong_section"), "The gold span sits in another section"), HUMAN),
               Row(("Right section, definition missing", K("m2_fail_r6_definition_missing"),
                    "The section was found but the definition it depends on was not"), HUMAN),
               Row(("Right section, wrong passage", K("m2_fail_r6_right_section_wrong_passage"),
                    "Another passage of the right section was returned"), HUMAN),
               Row(("Wrong deal", K("m3_r7_wrong"),
                    "Tech-deal questions that R7 scoped to the wrong agreement"), MACHINE),
               Row(("Answer in an unfiled schedule", K("m4_abstain_schedule_false_answer_rate"),
                    "Share answered anyway when the answer sits in a schedule that was not filed (weakest key)"),
                   MACHINE),
               Row(("Label disputed", CI("m2_machine_disputed_share"),
                    "Share of sampled misses where a model judged the first result to answer the question"),
                   MACHINE),
               Row(("Superseded text", "not classified",
                    "Amended passages are shown with their amendment; misses on them were not counted apart"))),
              ),
        Table("lbr", "Against LegalBench-RAG's published MAUD baselines (all agreements, character recall, percent)",
              None, (("Method", None),) + tuple((f"recall@{k}", None) for k in CHAR_KS),
              tuple(Row((label,) + tuple(K(f"m2_lbr_{m}_recall_at_{k}_pct") for k in CHAR_KS), "published")
                    for m, label in LBR)
              + (Row(("This project, R1",) + tuple(K(f"m2_r1_corpus_char_recall_at_{k}_pct") for k in CHAR_KS),
                     HUMAN),
                 Row(("This project, its best rung",)
                     + tuple(K(f"m2_best_corpus_char_recall_at_{k}_pct") for k in CHAR_KS), HUMAN)),
              ("Published figures: ", K("m2_lbr_source"), ". The setups differ (chunking, query wording, and k "
               "counted in their chunks against our passages), so read this as indicative, not head to head.")),
        Table("live", "The live desk", None, (("Measure", None), ("Value", None)),
              (Row(("Answer model", K("m5_price_model"))),
               Row(("Price per million input tokens, US dollars", K("m5_price_input_per_mtok"))),
               Row(("Price per million output tokens, US dollars", K("m5_price_output_per_mtok"))),
               Row(("Prices checked on", K("m5_price_checked"))),
               Row(("Hosting per month, US dollars", K("m5_hosting_usd_month"))),
               Row(("Model budget per month, US dollars", K("m5_model_cap_usd"))),
               Row(("Model budget per day, US dollars", K("m5_day_cap_usd"))),
               Row(("Input tokens per answer, mean", K("m5_api_tokens_in_mean"))),
               Row(("Output tokens per answer, mean", K("m5_api_tokens_out_mean"))),
               Row(("Cost per new answer, mean, US dollars", K("m5_cost_per_answer_mean"))),
               Row(("New answers the monthly budget covers", K("m5_answers_per_month"))),
               Row(("Search on the server, ms p50", K("m5_server_search_latency_ms_p50"))),
               Row(("Search on the server, ms p95", K("m5_server_search_latency_ms_p95"))),
               Row(("A new answer on the server, ms p50", K("m5_server_ask_fresh_latency_ms_p50"))),
               Row(("A new answer on the server, ms p95", K("m5_server_ask_fresh_latency_ms_p95"))),
               Row(("A cached answer on the server, ms p50", K("m5_server_ask_cached_latency_ms_p50"))),
               Row(("Peak memory of the service, MB", K("m5_server_rss_mb"))),
               Row(("Index file, bytes", K("m5_bundle_bytes"))),
               Row(("The cap trips: a new question is refused", K("m5_cap_trip_budget_reached"))),
               Row(("The cap trips: a cached answer is still shown", K("m5_cap_trip_budget_cached")))),
              ("Token counts come from a calibration sample of ", K("m5_calibration_n"),
               " questions sent to the API. Server timings leave out the network.")),
    )


SECTIONS = (("Retrieval", ("ladder_human", "ladder_machine", "side")),
            ("By question family", ("families_human", "families_machine")),
            ("Do the two answer keys agree?", ("tier_agreement", "tier_summary")),
            ("Answers", ("answers_human", "answers_machine", "abstention")),
            ("Citations", ("gate", "refute")),
            ("Why things go wrong", ("misses",)),
            ("Against the published baselines", ("lbr",)),
            ("The live desk", ("live",)))
RESULTS_INTRO = ("Every number on this page is generated from the project's measured facts. Numbers marked "
                 "human-labelled (MAUD) are scored against lawyers' labels; numbers marked machine-built come from "
                 "model passes, not lawyers.")

METHOD = (
    ("What this is", (
        ("Ask what a signed acquisition agreement says about employee stock, break-up fees, or employees' pay and "
         "benefits after the deal, and get the clause quoted from the contract with a link to the filing. ",
         DISCLAIMER, " The system can be wrong; every claim shows its source so you can check it."),
    )),
    ("The agreements", (
        ("Two sources. The first is MAUD, a dataset in which lawyers labelled ", K("maud_label_contracts"),
         " merger agreements with ", K("maud_question_types"), " question types in ", K("maud_label_rows_all"),
         " label rows. ", K("maud_label_contracts_with_text"), " of those agreements have published text; ",
         K("m3_deals_maud_deals"), " of them are in the live index after ", K("m3_deals_maud_duplicates"),
         " copies of tech deals were dropped as duplicates."),
        ("The second is technology-company acquisitions filed on EDGAR: the merger agreement attached to a "
         "current report, signed on or after ", K("m0_start"), ", whose target's industry code is in ",
         K("m0_sic_ranges"), ". They are chosen by that rule, not by hand: ", K("m3_corpus_kept"),
         " agreements. The live index holds ", K("m3_deals_deals"), " agreements in ", K("m3_deals_passages"),
         " passages, cut on article and section boundaries."),
    )),
    ("Which numbers a person checked", (
        ("Numbers marked ", HUMAN, " are scored against the lawyers' labels in MAUD."),
        ("Numbers marked machine-built come from model passes, not lawyers. For the tech deals, two models (",
         K("m3_tm_model_a"), " and ", K("m3_tm_model_b"), ") each located the governing clause and stated the "
         "answer; only items where both agreed were kept. A third model (", K("m4_judge_model"), ") judged "
         "answers against that key. The lexicon that maps lay words to contract words was machine-built by ",
         K("m2_lexicon_model"), "."),
        ("To test whether the machine-built key can be trusted, the same two-pass procedure was run on MAUD's own "
         "questions, so those questions have two keys; the Results page shows how often they agree. That is "
         "evidence, not proof.",),
    )),
    ("What is not new", (
        ("Retrieval over MAUD is a published benchmark: ", K("m2_lbr_source"), ". This project does not claim the "
         "task. It claims a working, measured, deployed system on top of that benchmark, plus three question "
         "families its labels do not cover: employee equity awards, break-up fees, and employees' pay and "
         "benefits after the deal. The Results page compares against the published baselines."),
    )),
    ("How an answer is made", (
        ("The question is matched to one agreement by the company it names, or the one you pick. Inside that "
         "agreement, keyword search and a local embedding model (", K("m2_vec_model"), ") each rank passages and "
         "the two rankings are fused. Lay words are rewritten into the agreement's own vocabulary, and each "
         "passage is shown with the definitions it depends on."),
        ("The model (", K("m4_answer_model"), ") must return claims, each with a quote copied from a passage. A "
         "claim whose quote does not occur word for word in that passage is dropped; if none survives, the answer "
         "is \"not stated in this agreement\". A question that names no agreement, or several, gets \"which "
         "agreement?\" and no model call. Search shows the same ranked passages with no model call."),
    )),
    ("What it costs", (
        ("The desk runs under a hard monthly cap. Hosting costs ", K("m5_hosting_usd_month"), " US dollars a month; "
         "the model budget is the rest, ", K("m5_model_cap_usd"), ", with a daily ceiling of ",
         K("m5_day_cap_usd"), ". Prices were checked on ", K("m5_price_checked"), ": ",
         K("m5_price_input_per_mtok"), " US dollars per million input tokens and ", K("m5_price_output_per_mtok"),
         " per million output tokens. When the budget is spent, the desk shows cached answers only and says so. "
         "Search is never capped."),
    )),
    ("Stated limits", (
        ("The tech half is public-company acquisitions: small private exits rarely file their agreements.",),
        ("The tech-deal labels are machine-built. Two-pass agreement and the comparison with MAUD's lawyers are "
         "evidence, not proof.",),
        ("MAUD's agreements are older than many of the tech deals, follow one annotation scheme and are not "
         "tech-specific, so results on MAUD may not carry over to the tech deals; nothing here measures that "
         "directly.",),
        ("Lay questions are ambiguous. \"What happens to my options\" depends on vesting and on the agreement's own "
         "categories; the answer quotes the categories and does not pick one for you.",),
        ("The answer evaluations ran through the Claude command-line tool, not the API the live desk calls. A "
         "calibration sample of ", K("m5_calibration_n"), " questions run both ways agreed on the answer state in ",
         K("m5_calibration_state_agreement"), " of cases."),
        ("Answer accuracy on MAUD was measured on an index of MAUD agreements alone. On the live index, which also "
         "holds the tech deals, the live rung's recall@5 on MAUD's questions is ",
         CI("m5_bundle_r6n_report_recall_at_5"), " (", HUMAN, ")."),
        ("Ladder timings were measured on the development machine; the live server's own timings are on the "
         "Results page.",),
        (DISCLAIMER,),
    )),
    ("What is logged", (
        ("The service logs one line per request: the endpoint, the outcome, the time taken and the tokens used. It "
         "does not log your address or your question. Answers are kept in a cache with the question that produced "
         "them, so a repeated question costs nothing. Rate limits count requests per address in memory only.",),
    )),
    ("Data and licences", (
        ("MAUD (the Merger Agreement Understanding Dataset) is by The Atticus Project, under the ",
         A("Creative Commons Attribution licence", "https://creativecommons.org/licenses/by/4.0/"), "; ",
         A("the dataset", "https://huggingface.co/datasets/theatticusproject/maud"), "."),
        ("Agreements from EDGAR: the SEC states that its content \"is considered public information and may be "
         "copied or further distributed by users of the web site without the SEC's permission\". This site quotes "
         "clauses and links to each filing; the source repository ships the fetch script and filing identifiers, "
         "not the documents.",),
        ("Source code: ", A("github.com/MichaelFornal/deal-terms-desk",
                            "https://github.com/MichaelFornal/deal-terms-desk"), "."),
    )),
)


def results_main(F: Facts) -> str:
    tables = {t.id: t for t in results_tables()}
    parts = ["<h1>Results</h1>", f'<p class="lede">{html.escape(RESULTS_INTRO)}</p>']
    for title, ids in SECTIONS:
        parts.append(f"<h2>{html.escape(title)}</h2>")
        parts += [render_table(F, tables[i]) for i in ids]
    return "\n".join(parts)


def method_main(F: Facts) -> str:
    out = ["<h1>Method</h1>"]
    for title, paragraphs in METHOD:
        out.append(f"<h2>{html.escape(title)}</h2>")
        out += ["<p>" + "".join(render_cell(F, c) for c in p) + "</p>" for p in paragraphs]
    return "\n".join(out)


def _read(name: str) -> str:
    return (TEMPLATES / name).read_text(encoding="utf-8")


def _nav(current: str) -> str:
    return "".join(f'<a href="{href}"' + (' aria-current="page"' if page == current else "") + f">{text}</a>"
                   for href, page, text in NAV)


def _page(page: str, title: str, main: str) -> str:
    return (_read("base.html").replace("{{title}}", html.escape(title)).replace("{{page}}", page)
            .replace("{{nav}}", _nav(page)).replace("{{main}}", main))


def render_site(facts: dict, out: Path, examples: list[dict], strict: bool = False) -> list[Path]:
    """The four pages, the static files and the example questions. Every page is built before anything is written,
    so a missing fact leaves the previous site in place."""
    F, out = Facts(facts, strict), Path(out)
    pages = {"index.html": ("ask", "Ask", _read("index.html")), "search.html": ("search", "Search", _read("search.html")),
             "results.html": ("results", "Results", results_main(F)), "method.html": ("method", "Method", method_main(F))}
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, (page, title, main) in pages.items():
        (out / name).write_text(_page(page, title, main), encoding="utf-8")
        written.append(out / name)
    shutil.copytree(STATIC, out / "static", dirs_exist_ok=True)
    (out / "examples.json").write_text(json.dumps(examples, indent=2) + "\n", encoding="utf-8")
    return written + [out / "examples.json"]
```

- [ ] **Step 8: Add `dtd site`, ignore `site/dist`, add the CI step**

`pipeline/cli.py`:
- Import `from facts.site import render_site`.
- Add `SITE_DIST = Path("site/dist")` beside `EXAMPLES`.
- Add the handler below `_cmd_warm`:

```python
def _cmd_site(args) -> int:
    if not FACTS.exists():
        print("facts.json missing; run `dtd facts` first", file=sys.stderr)
        return 2
    try:
        written = render_site(json.loads(FACTS.read_text(encoding="utf-8")), SITE_DIST,
                              json.loads(EXAMPLES.read_text(encoding="utf-8")), strict=args.strict)
    except KeyError as e:
        print(f"a fact the site prints is missing: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"written": [str(p) for p in written]}))
    return 0
```

In `entry`:

```python
    site_p = sub.add_parser("site")
    site_p.add_argument("--strict", action="store_true", help="fail on any missing fact, M5 ones included (M6)")
    site_p.set_defaults(fn=_cmd_site)
```

`.gitignore`: add the line `site/dist/`.

`.github/workflows/ci.yml`: add after the `Tests` step:

```yaml
      - name: Facts check
        run: |
          uv run pytest -q tests/test_report_m0.py tests/test_report_m2.py tests/test_report_m3.py tests/test_report_m4.py tests/test_facts.py tests/test_labels.py tests/test_site.py
          uv run dtd site
```

- [ ] **Step 9: Run the site tests and the whole suite**

Run: `uv run pytest tests/test_site.py tests/test_labels.py -q && uv run dtd site && uv run pytest -q`
Expected:
- all tests pass;
- `dtd site` prints the five written paths;
- `site/dist/results.html` shows "pending" in the M5 rows only.

Open `site/dist/index.html` over `python -m http.server -d site/dist`. With no API it renders and the deal picker stays empty. Check the layout by eye.

- [ ] **Step 10: Commit**

```bash
git add facts/site.py site/templates site/static site/examples.json pipeline/cli.py .gitignore .github/workflows/ci.yml tests/test_site.py
git commit -m "m5: the four pages rendered from facts.json, labels checked per fact, text-only JS; dtd site; CI facts check

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: M5 facts, report, server measurement

**Files:**
- Create: `facts/m5.py`, `facts/report_m5.py`, `evals/measure.py`
- Modify: `facts/m2.py` (`is_unstable` also covers `rss_mb`), `pipeline/cli.py` (`_all_facts`, `_cmd_report`, `REPORT_M5`, `HOSTING`, `dtd m5 measure`), `tests/test_facts.py` (the committed-keys test allows `m5_`)
- Test: `tests/test_facts_m5.py`, `tests/test_report_m5.py`, `tests/test_measure.py`

**Interfaces:**
- Consumes these files. The names and shapes below are what this task reads; Tasks 2, 4 and 5 must write exactly them:
  - `data/live/bundle.json`: `{"sha256", "bytes", "contracts", "passages", "rebuilt"}` (Task 4).
  - `data/out/m5/parity.json`: one `prompt_parity()` result `{"checked", "same", "differ"}` per M4 answer set
    (`thuman`, `tmachine`, `abstain`), summed here (Task 2's `dtd m5 parity`).
  - `data/out/m5/bundle_parity.json`: `r7n_parity()`'s `{"checked", "same", "differ"}` plus `bundle_sha256` (Task 4).
  - `data/out/m5/bundle_r6n.json`: `evaluate()` output, read at `["by_split"]["report"]["recall@5"]` as `{mean, lo, hi}` (Task 4's `dtd m5 recall`).
  - `data/m5/calibration.json`: Task 5's `summarise()` output. This task reads:
    - `n`, `called`, `truncated`;
    - `api_tokens_in_mean`, `api_tokens_in_p95`, `api_tokens_out_mean`, `api_tokens_out_p95`, `api_tokens_out_p99`;
    - `cost_usd_total`, `cost_per_answer_mean`, `cost_per_answer_p95`;
    - `worst_case_ok`, `state_agreement`;
    - `gate_pass_rate` `{api, cli}` and `thuman_accuracy` `{api, cli, diff, n}`;
    - `stop_rule["verdict"]` (`"go"` or `"stop"`).
  - `data/out/m4/r6n.json` and `t_r7n_corpus.json`, read at `["latency_ms"]["p50"/"p95"]`, rounded to two places like
    M2's latency facts.
  - `service/prices.json` via `load_prices`.
  - `deploy/hosting.json` (Task 12).
  - `data/m5/server.json` (this task's `measure`).
  - `data/m5/cap_trip.json`: `{"budget_reached", "budget_cached", "ledger_unchanged", "health_budget"}`, written
    by Task 12's `smoke.py --cap-trip` in Task 15.
  - `GET /api/search` and `/api/ask` payloads carry `ms`, and `/api/health` carries `rss_mb`, `git_sha` and `bundle_sha` (Task 9).
- Produces:
  - `present_m5(data_m5)` (true when `data_m5.parent / "live" / "bundle.json"` exists);
  - `build_m5(data_m5, live_dir, out_m4, out_m5, prices_path, hosting_path) -> dict`;
  - `render_m5(f) -> str`;
  - `measure(base_url, questions, fresh, reference=None, cached=()) -> dict`, where `cached` is an addition to the header's signature: the example questions, answered from the cache;
  - `reference_hits(ladder, questions) -> dict[str, list[int]]`;
  - `dtd m5 measure --base URL [--search-n N] [--fresh N]`: the `measure` entry in `M5_STAGES`. It runs from the
    development machine; server-side times come from each payload's `ms`, so they exclude the network.
- Every `m5_*` key the site's `live` table and Method page read is produced here.

- [ ] **Step 1: Write the failing facts tests**

`tests/test_facts_m5.py`:

```python
import json
import math
from pathlib import Path

from facts.m2 import is_unstable
from facts.m5 import build_m5, present_m5
from service.prices import load_prices

PRICES = Path("service/prices.json")
HOSTING_EMPTY = {"provider": "Hetzner Cloud", "plan": "CAX11", "eur_month": 4.49, "extras_eur_month": None,
                 "eur_usd": None, "eur_usd_date": None, "eur_usd_source": None, "budget_usd_month": 10.0,
                 "day_cap_usd": None, "checked": None}


def _write(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def dirs(tmp_path):
    data_m5, live, out_m4, out_m5 = (tmp_path / "data" / "m5", tmp_path / "data" / "live", tmp_path / "out" / "m4",
                                     tmp_path / "out" / "m5")
    _write(live / "bundle.json", {"sha256": "ab" * 32, "bytes": 1000, "contracts": 3, "passages": 40,
                                  "rebuilt": True})
    return data_m5, live, out_m4, out_m5


def test_present_needs_the_bundle(tmp_path):
    assert not present_m5(tmp_path / "data" / "m5")
    data_m5, *_ = dirs(tmp_path)
    assert present_m5(data_m5)


def test_with_only_the_bundle_the_later_sections_are_absent(tmp_path):
    data_m5, live, out_m4, out_m5 = dirs(tmp_path)
    hosting = _write(tmp_path / "hosting.json", HOSTING_EMPTY)
    f = build_m5(data_m5, live, out_m4, out_m5, PRICES, hosting)
    assert f["m5_bundle_bytes"] == 1000 and f["m5_bundle_sha"] == "ab" * 32
    assert f["m5_price_model"] == load_prices(PRICES).model
    later = ("m5_hosting", "m5_model_cap", "m5_calibration", "m5_server", "m5_cap_trip", "m5_answers_per_month",
             "m5_prompt_parity", "m5_bundle_parity", "m5_bundle_r6n")
    assert not [k for k in f if k.startswith(later)]


def test_every_section_once_its_input_exists(tmp_path):
    data_m5, live, out_m4, out_m5 = dirs(tmp_path)
    for name in ("r6n", "t_r7n_corpus"):
        _write(out_m4 / f"{name}.json", {"latency_ms": {"p50": 46.39566600235412, "p95": 300.0}})
    _write(out_m5 / "parity.json", {"thuman": {"checked": 6, "same": 6, "differ": []},
                                    "tmachine": {"checked": 3, "same": 3, "differ": []},
                                    "abstain": {"checked": 1, "same": 1, "differ": []}})
    _write(out_m5 / "bundle_parity.json", {"checked": 5, "same": 5, "differ": [], "bundle_sha256": "ab" * 32})
    _write(out_m5 / "bundle_r6n.json", {"by_split": {"report": {"recall@5": {"mean": 0.6, "lo": 0.5, "hi": 0.7}}}})
    _write(data_m5 / "calibration.json", {  # the shape of Task 5's summarise(), plus what dtd m5 calibrate adds
        "n": 40, "called": 38, "errors": 2, "missing": 0, "truncated": 1, "refused": 0,
        "api_tokens_in_mean": 4000.0, "api_tokens_in_p95": 6000, "api_tokens_out_mean": 300.0,
        "api_tokens_out_p95": 500, "api_tokens_out_p99": 600, "cost_usd_total": 0.8, "cost_per_answer_mean": 0.02,
        "cost_per_answer_p95": 0.03, "worst_case_ok": True, "worst_case_min_margin_usd": 0.001, "paired": 38,
        "gate_pass_rate": {"api": 0.88, "cli": 0.86}, "state_agreement": 0.9,
        "thuman_accuracy": {"api": 0.6, "cli": 0.62, "diff": -0.02, "n": 19},
        "stop_rule": {"state_agreement_min": 0.8, "accuracy_diff_max": 0.15, "verdict": "go", "reasons": []},
        "model": "claude-haiku-4-5-20251001", "max_tokens": 1024})
    span = {"n": 50, "p50": 20.0, "p95": 40.0}
    _write(data_m5 / "server.json", {
        "search": {"e2e": {"n": 50, "p50": 120.0, "p95": 200.0}, "server": span},
        "ask_cached": {"e2e": span, "server": span, "states": {}}, "ask_fresh": {"e2e": span, "server": span, "states": {}},
        "rss_mb": 900.0, "embed_parity": {"n": 50, "same": 49, "rate": 0.98}})
    _write(data_m5 / "cap_trip.json", {"budget_reached": True, "budget_cached": True, "ledger_unchanged": True,
                                       "health_budget": "reached"})
    hosting = _write(tmp_path / "hosting.json", dict(HOSTING_EMPTY, eur_usd=1.1, eur_usd_date="2026-10-10",
                                                     eur_usd_source="ECB reference rate", day_cap_usd=0.5,
                                                     checked="2026-10-10"))
    f = build_m5(data_m5, live, out_m4, out_m5, PRICES, hosting)
    usd = round(4.49 * 1.1, 2)
    assert f["m5_hosting_usd_month"] == usd and f["m5_model_cap_usd"] == round(10.0 - usd, 2)
    assert f["m5_day_cap_usd"] == 0.5 and f["m5_answers_per_month"] == math.floor(round(10.0 - usd, 2) / 0.02)
    assert f["m5_bundle_r6n_report_recall_at_5"] == 0.6 and f["m5_bundle_r6n_report_recall_at_5_lo"] == 0.5
    assert f["m5_prompt_parity_same"] == 10 and f["m5_prompt_parity_checked"] == 10 and f["m5_bundle_parity_checked"] == 5
    assert f["m5_live_r6n_latency_ms_p95"] == 300.0 and f["m5_live_t_r7n_corpus_latency_ms_p50"] == 46.4
    assert f["m5_api_tokens_in_mean"] == 4000.0 and f["m5_api_tokens_out_p99"] == 600
    assert f["m5_calibration_stop_rule"] == "go" and f["m5_calibration_accuracy_cli"] == 0.62
    assert f["m5_calibration_gate_pass_api"] == 0.88 and f["m5_calibration_estimator_ok"] is True
    assert f["m5_server_search_latency_ms_p95"] == 40.0 and f["m5_e2e_search_latency_ms_p95"] == 200.0
    assert f["m5_server_rss_mb"] == 900.0 and f["m5_server_embed_parity"] == 0.98
    assert f["m5_cap_trip_budget_reached"] is True and f["m5_cap_trip_ledger_unchanged"] is True


def test_wall_clock_facts_are_unstable_for_the_check():
    assert is_unstable("m5_server_rss_mb") and is_unstable("m5_server_search_latency_ms_p95")
    assert is_unstable("m5_live_r6n_latency_ms_p50") and not is_unstable("m5_bundle_bytes")
```

`tests/test_report_m5.py`:

```python
import json
import re
from pathlib import Path

import pytest

from facts.report_m5 import render_m5


class Every(dict):
    """Any fact renders as a placeholder number unless overridden, so the template is checked, not the data."""
    def __missing__(self, key):
        return 0.5

    def get(self, key, default=None):
        return self[key]


def test_report_has_every_section_and_its_labels():
    text = render_m5(Every())
    for heading in ("## Live index", "## The same path the evals measured", "## API calibration",
                    "## Cost and budget", "## Server", "## The cap trips"):
        assert heading in text
    assert "human-labelled (MAUD)" in text and "This is not legal advice." in text


def test_missing_facts_render_pending():
    text = render_m5({})
    assert "pending" in text and "None" not in text


def test_report_copy_has_no_hard_coded_digits():
    text = render_m5(Every())
    stripped = re.sub(r"0\.5|R6n|R7n|M[0-9]|@5|\bp(?:50|95)\b|sha256", "", text)
    assert not re.search(r"\d", stripped), re.findall(r".{20}\d.{20}", stripped)[:3]


def test_committed_m5_report_is_rendered_from_committed_facts():
    f = json.loads(Path("facts.json").read_text())
    if "m5_bundle_sha" not in f:
        pytest.skip("M5 facts not yet committed")
    assert Path("docs/m5/REPORT.md").read_text() == render_m5(f)


def test_dtd_report_writes_the_m5_report_when_its_facts_exist(tmp_path, monkeypatch):
    from pipeline import cli
    f = json.loads(Path("facts.json").read_text()) | {"m5_bundle_sha": "ab", "m5_bundle_bytes": 1}
    (tmp_path / "facts.json").write_text(json.dumps(f))
    monkeypatch.setattr(cli, "FACTS", tmp_path / "facts.json")
    for name in ("REPORT", "REPORT_M0", "REPORT_M2", "REPORT_M3", "REPORT_M4", "REPORT_M5"):
        monkeypatch.setattr(cli, name, tmp_path / name / "REPORT.md")
    assert cli.entry(["report"]) == 0
    assert (tmp_path / "REPORT_M5" / "REPORT.md").read_text() == render_m5(f)
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_facts_m5.py tests/test_report_m5.py -q`
Expected: FAIL, `No module named 'facts.m5'` and `No module named 'facts.report_m5'`.

- [ ] **Step 3: Write `facts/m5.py`, `facts/report_m5.py`, extend `is_unstable`, wire the CLI**

`facts/m2.py`: `is_unstable` also covers peak memory, a wall-clock measurement like latency:

```python
def is_unstable(name: str) -> bool:
    return ("latency_ms" in name or "load_avg" in name or name.endswith("index_bytes")
            or name.endswith("rss_mb"))
```

`facts/m5.py`:

```python
import math
from pathlib import Path

from facts.m2 import _ci, _json
from service.prices import load_prices

BUDGET_USD_MONTH = 10.0  # PRD §1: the hard cap, hosting plus model calls
HOSTING_NEEDS = ("eur_month", "eur_usd", "day_cap_usd", "checked")


def present_m5(data_m5: Path) -> bool:
    """M5 facts exist once the live bundle has been built (data/live sits beside data/m5)."""
    return (Path(data_m5).parent / "live" / "bundle.json").exists()


def build_m5(data_m5, live_dir, out_m4, out_m5, prices_path, hosting_path) -> dict:
    """Each section appears once its input exists, so the facts grow as M5's measurements land. The site shows
    a missing M5 fact as pending until M6, where `dtd site --strict` requires them all."""
    data_m5, live_dir, out_m4, out_m5 = map(Path, (data_m5, live_dir, out_m4, out_m5))
    b = _json(live_dir / "bundle.json")
    f: dict = {"m5_bundle_sha": b["sha256"], "m5_bundle_bytes": b["bytes"], "m5_bundle_contracts": b["contracts"],
               "m5_bundle_passages": b["passages"]}
    for r, name in (("r6n", "m5_live_r6n"), ("t_r7n_corpus", "m5_live_t_r7n_corpus")):
        if (out_m4 / f"{r}.json").exists():
            lat = _json(out_m4 / f"{r}.json")["latency_ms"]
            f[f"{name}_latency_ms_p50"], f[f"{name}_latency_ms_p95"] = round(lat["p50"], 2), round(lat["p95"], 2)
    if (out_m5 / "parity.json").exists():  # dtd m5 parity: one block per M4 answer set
        sets = _json(out_m5 / "parity.json").values()
        f["m5_prompt_parity_checked"] = sum(v["checked"] for v in sets)
        f["m5_prompt_parity_same"] = sum(v["same"] for v in sets)
    if (out_m5 / "bundle_parity.json").exists():
        p = _json(out_m5 / "bundle_parity.json")
        f["m5_bundle_parity_checked"], f["m5_bundle_parity_same"] = p["checked"], p["same"]
    if (out_m5 / "bundle_r6n.json").exists():
        _ci(f, "m5_bundle_r6n_report_recall_at_5", _json(out_m5 / "bundle_r6n.json")["by_split"]["report"]["recall@5"])

    p = load_prices(prices_path)
    f |= {"m5_price_model": p.model, "m5_price_input_per_mtok": p.input, "m5_price_output_per_mtok": p.output,
          "m5_price_cache_write_per_mtok": p.cache_write, "m5_price_cache_read_per_mtok": p.cache_read,
          "m5_price_checked": p.checked, "m5_price_source": p.source}

    h = _json(hosting_path)
    if all(h.get(k) is not None for k in HOSTING_NEEDS):
        usd = round((h["eur_month"] + (h.get("extras_eur_month") or 0.0)) * h["eur_usd"], 2)
        f |= {"m5_hosting_usd_month": usd,
              "m5_model_cap_usd": round(h.get("budget_usd_month", BUDGET_USD_MONTH) - usd, 2),
              "m5_day_cap_usd": h["day_cap_usd"], "m5_hosting_checked": h["checked"]}

    if (data_m5 / "calibration.json").exists():
        c = _json(data_m5 / "calibration.json")  # Task 5's summarise()
        f |= {"m5_calibration_n": c["n"], "m5_calibration_called": c["called"],
              "m5_api_tokens_in_mean": c["api_tokens_in_mean"], "m5_api_tokens_in_p95": c["api_tokens_in_p95"],
              "m5_api_tokens_out_mean": c["api_tokens_out_mean"], "m5_api_tokens_out_p95": c["api_tokens_out_p95"],
              "m5_api_tokens_out_p99": c["api_tokens_out_p99"],
              "m5_cost_per_answer_mean": c["cost_per_answer_mean"], "m5_cost_per_answer_p95": c["cost_per_answer_p95"],
              "m5_calibration_cost_usd_total": c["cost_usd_total"],
              "m5_calibration_state_agreement": c["state_agreement"],
              "m5_calibration_accuracy_api": c["thuman_accuracy"]["api"],
              "m5_calibration_accuracy_cli": c["thuman_accuracy"]["cli"],
              "m5_calibration_gate_pass_api": c["gate_pass_rate"]["api"],
              "m5_calibration_gate_pass_cli": c["gate_pass_rate"]["cli"],
              "m5_calibration_truncated": c["truncated"], "m5_calibration_estimator_ok": c["worst_case_ok"],
              "m5_calibration_stop_rule": c["stop_rule"]["verdict"]}
        if "m5_model_cap_usd" in f and c["cost_per_answer_mean"]:
            f["m5_answers_per_month"] = math.floor(f["m5_model_cap_usd"] / c["cost_per_answer_mean"])

    if (data_m5 / "server.json").exists():
        s = _json(data_m5 / "server.json")
        for part in ("search", "ask_cached", "ask_fresh"):
            for q in ("p50", "p95"):
                f[f"m5_server_{part}_latency_ms_{q}"] = s[part]["server"][q]
                f[f"m5_e2e_{part}_latency_ms_{q}"] = s[part]["e2e"][q]
        f["m5_server_rss_mb"] = s["rss_mb"]
        if "embed_parity" in s:
            f["m5_server_embed_parity"], f["m5_server_embed_parity_n"] = s["embed_parity"]["rate"], s["embed_parity"]["n"]

    if (data_m5 / "cap_trip.json").exists():
        t = _json(data_m5 / "cap_trip.json")
        f |= {"m5_cap_trip_budget_reached": t["budget_reached"], "m5_cap_trip_budget_cached": t["budget_cached"],
              "m5_cap_trip_ledger_unchanged": t["ledger_unchanged"]}
    return f
```

`facts/report_m5.py`:

```python
PENDING = "pending"


def _v(f, k) -> str:
    x = f.get(k)
    return PENDING if x is None else str(x)


def _ci(f, k) -> str:
    x = f.get(k)
    return PENDING if x is None else f"{x} ({_v(f, k + '_lo')} to {_v(f, k + '_hi')})"


def _pair(f, a, b) -> str:
    return f"{_v(f, a)} / {_v(f, b)}"


def render_m5(f) -> str:
    return f"""# M5: the live desk

Generated from `facts.json` by `dtd report`; do not edit by hand. Numbers marked machine-built come from model passes, not lawyers. This is not legal advice.

## Live index

The service reads one file holding the index, the agreement texts and the links: {_v(f, 'm5_bundle_bytes')} bytes, {_v(f, 'm5_bundle_contracts')} agreements, {_v(f, 'm5_bundle_passages')} passages; sha256 `{_v(f, 'm5_bundle_sha')}`.

## The same path the evals measured

Re-preparing M4's answer items through the live code produced the same prompt for {_v(f, 'm5_prompt_parity_same')} of {_v(f, 'm5_prompt_parity_checked')} items. R7n over the live file returned the same passages, in the same order, as over the evaluation index for {_v(f, 'm5_bundle_parity_same')} of {_v(f, 'm5_bundle_parity_checked')} questions.

| Index | R6n recall@5 on MAUD's questions (human-labelled (MAUD), report split) |
|---|---|
| MAUD agreements alone (the M4 measurement) | {_ci(f, 'm4_r6n_report_recall_at_5')} |
| The live index | {_ci(f, 'm5_bundle_r6n_report_recall_at_5')} |

Live-path retrieval on the development machine, p50 / p95 ms: R6n {_pair(f, 'm5_live_r6n_latency_ms_p50', 'm5_live_r6n_latency_ms_p95')}; R7n across all agreements {_pair(f, 'm5_live_t_r7n_corpus_latency_ms_p50', 'm5_live_t_r7n_corpus_latency_ms_p95')}.

## API calibration

{_v(f, 'm5_calibration_n')} tune-split questions were answered through the API with the live settings and compared with M4's command-line answers to the same questions. Stop rule: {_v(f, 'm5_calibration_stop_rule')}.

| Measure | API | Command-line tool |
|---|---|---|
| Answer state matches the other run | {_v(f, 'm5_calibration_state_agreement')} | — |
| MAUD answer accuracy on the sample (human-labelled (MAUD)) | {_v(f, 'm5_calibration_accuracy_api')} | {_v(f, 'm5_calibration_accuracy_cli')} |
| Claims kept by the citation gate | {_v(f, 'm5_calibration_gate_pass_api')} | {_v(f, 'm5_calibration_gate_pass_cli')} |
| Replies cut off at the output cap | {_v(f, 'm5_calibration_truncated')} | — |
| Input tokens per answer, mean / p95 | {_pair(f, 'm5_api_tokens_in_mean', 'm5_api_tokens_in_p95')} | — |
| Output tokens per answer, mean / p95 | {_pair(f, 'm5_api_tokens_out_mean', 'm5_api_tokens_out_p95')} | — |

The budget's worst-case estimate covered every calibrated call: {_v(f, 'm5_calibration_estimator_ok')}.

## Cost and budget

Model {_v(f, 'm5_price_model')} at {_v(f, 'm5_price_input_per_mtok')} US dollars per million input tokens and {_v(f, 'm5_price_output_per_mtok')} per million output tokens (checked {_v(f, 'm5_price_checked')}; {_v(f, 'm5_price_source')}). Hosting costs {_v(f, 'm5_hosting_usd_month')} US dollars a month (checked {_v(f, 'm5_hosting_checked')}); the model budget is the rest of the monthly cap, {_v(f, 'm5_model_cap_usd')}, with a daily ceiling of {_v(f, 'm5_day_cap_usd')}. A new answer costs {_v(f, 'm5_cost_per_answer_mean')} on average (p95 {_v(f, 'm5_cost_per_answer_p95')}), so a month covers {_v(f, 'm5_answers_per_month')} new answers. Cached answers and Search cost nothing.

## Server

Measured against the live service from the development machine. Server times are the service's own, without the network; end-to-end times include it.

| Request | Server p50 / p95 ms | End-to-end p50 / p95 ms |
|---|---|---|
| Search | {_pair(f, 'm5_server_search_latency_ms_p50', 'm5_server_search_latency_ms_p95')} | {_pair(f, 'm5_e2e_search_latency_ms_p50', 'm5_e2e_search_latency_ms_p95')} |
| Cached answer | {_pair(f, 'm5_server_ask_cached_latency_ms_p50', 'm5_server_ask_cached_latency_ms_p95')} | {_pair(f, 'm5_e2e_ask_cached_latency_ms_p50', 'm5_e2e_ask_cached_latency_ms_p95')} |
| New answer | {_pair(f, 'm5_server_ask_fresh_latency_ms_p50', 'm5_server_ask_fresh_latency_ms_p95')} | {_pair(f, 'm5_e2e_ask_fresh_latency_ms_p50', 'm5_e2e_ask_fresh_latency_ms_p95')} |

Peak memory of the service: {_v(f, 'm5_server_rss_mb')} MB. The server's searches returned the same top passages as the development machine's for a share of {_v(f, 'm5_server_embed_parity')} of {_v(f, 'm5_server_embed_parity_n')} questions (query embeddings are computed on each machine).

## The cap trips

With the service restarted under a tiny cap: a new question got "budget reached": {_v(f, 'm5_cap_trip_budget_reached')}; a cached question was still answered as "budget reached, showing a cached answer": {_v(f, 'm5_cap_trip_budget_cached')}; the month's spend did not move: {_v(f, 'm5_cap_trip_ledger_unchanged')}. The same check runs in the test suite (`tests/test_desk.py`, `test_the_cap_trips`).
"""
```

`pipeline/cli.py`:
- Import `from facts.m5 import build_m5, present_m5` and `from facts.report_m5 import render_m5`.
- Add constants `REPORT_M5 = Path("docs/m5/REPORT.md")` (beside `REPORT_M4`) and `HOSTING = Path("deploy/hosting.json")`
  (beside Task 5's `PRICES`).
- In `_all_facts`, before the `m0` block:

```python
    if present_m5(DATA / "m5"):
        facts |= build_m5(DATA / "m5", DATA / "live", _out_m4(), OUT / "m5", PRICES, HOSTING)
```

In `_cmd_report`, after the M4 block:

```python
    if "m5_bundle_sha" in facts:
        REPORT_M5.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M5.write_text(render_m5(facts), encoding="utf-8")
```

`tests/test_cli.py` needs nothing: Task 1's `data` fixture already redirects every `REPORT*` path, `REPORT_M5`
included.

`tests/test_facts.py`: in `test_committed_facts_file_has_exactly_the_named_queries`, change the prefix tuple to
`("m2_", "m0_", "m3_", "m4_", "m5_")`, so committed M5 facts are not mistaken for M1 queries.

- [ ] **Step 4: Run them**

Run: `uv run pytest tests/test_facts_m5.py tests/test_report_m5.py tests/test_cli.py tests/test_facts.py -q`
Expected: pass. The committed-render test skips until real M5 facts exist.

- [ ] **Step 5: Commit**

```bash
git add facts/m5.py facts/report_m5.py facts/m2.py pipeline/cli.py tests/test_facts_m5.py tests/test_report_m5.py tests/test_facts.py
git commit -m "m5: M5 facts (bundle, parity, prices, hosting, calibration, server, cap trip) and docs/m5/REPORT.md

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: Write the failing measurement tests**

`tests/test_measure.py`:

```python
import json
import threading
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from evals.answer_sets import AnswerItem, write_items
from evals.measure import measure, reference_hits


class Handler(BaseHTTPRequestHandler):
    hits = {"q one": [1, 2], "q two": [3]}
    limited = [True]  # the first search is rate-limited once, with Retry-After: 0

    def _send(self, code, obj, headers=()):
        body = json.dumps(obj).encode()
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/search":
            if Handler.limited[0]:
                Handler.limited[0] = False
                return self._send(429, {"error": "rate_limited"}, [("Retry-After", "0")])
            q = parse_qs(u.query)["q"][0]
            return self._send(200, {"hits": [{"passage_id": p} for p in Handler.hits[q]], "ms": 5.0})
        if u.path == "/api/health":
            return self._send(200, {"rss_mb": 512.0, "git_sha": "g", "bundle_sha": "b"})
        self._send(404, {})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self._send(200, {"state": "answered" if "fresh" in body["question"] else "budget_cached", "ms": 9.0})

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_measure_times_requests_waits_out_a_429_and_scores_parity(server):
    got = measure(server, ["q one", "q two"], ["a fresh question"], {"q one": [1, 2], "q two": [9]},
                  cached=["an example"])
    assert got["search"]["server"] == {"n": 2, "p50": 5.0, "p95": 5.0} and got["search"]["e2e"]["n"] == 2
    assert got["embed_parity"] == {"n": 2, "same": 1, "rate": 0.5}
    assert got["ask_fresh"]["states"] == {"answered": 1} and got["ask_cached"]["states"] == {"budget_cached": 1}
    assert got["ask_cached"]["server"]["p50"] == 9.0 and got["rss_mb"] == 512.0 and got["bundle_sha"] == "b"


def test_reference_hits_runs_the_service_search_on_this_machine():
    seen = []

    class Ladder:
        def run(self, rung, q, deal, k):
            seen.append((rung, q, deal, k))
            return types.SimpleNamespace(hits=[types.SimpleNamespace(passage_id=7)])
    assert reference_hits(Ladder(), ["  outside   date "]) == {"  outside   date ": [7]}
    assert seen == [("R7n", "outside date", None, 10)]


def test_dtd_m5_measure_writes_server_json(tmp_path, monkeypatch):
    from pipeline import cli
    items = [AnswerItem(f"edgar_{i}|termination_fee", "tmachine", "termination_fee", "tune", None, f"Question {i}?")
             for i in range(6)]
    write_items(tmp_path / "m4" / "tmachine_items.jsonl", items)
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(cli, "Embedder", lambda *a, **k: None)
    monkeypatch.setattr(cli, "build_live_ladder", lambda *a, **k: "ladder")
    monkeypatch.setattr(cli, "reference_hits", lambda ladder, qs: {q: [1] for q in qs})
    seen = {}

    def fake_measure(base, questions, fresh, reference=None, cached=()):
        seen.update(base=base, questions=questions, fresh=fresh, cached=cached)
        return {"search": {}, "rss_mb": 1.0}
    monkeypatch.setattr(cli, "measure", fake_measure)
    assert cli.entry(["m5", "measure", "--base", "http://x", "--search-n", "4", "--fresh", "2"]) == 0
    assert len(seen["questions"]) == 4 and len(seen["fresh"]) == 2 and seen["cached"]
    assert not set(seen["questions"]) & set(seen["fresh"])
    assert json.loads((tmp_path / "m5" / "server.json").read_text())["rss_mb"] == 1.0
```

- [ ] **Step 7: Run them to see them fail**

Run: `uv run pytest tests/test_measure.py -q`
Expected: FAIL, `No module named 'evals.measure'`.

- [ ] **Step 8: Write `evals/measure.py` and `dtd m5 measure`**

`evals/measure.py`:

```python
import json
import time
import urllib.error
import urllib.parse
import urllib.request

from evals.run_rung import _percentile
from service.cache import normalise_question

SEARCH_K = 10
MAX_WAITS = 5


def _call(url: str, body: dict | None = None, timeout: float = 120.0) -> tuple[dict, float]:
    """One request timed end to end. A 429 is waited out (Retry-After) and retried, up to MAX_WAITS times: the
    measurement runs under the same per-address limits as any visitor."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    headers = {} if body is None else {"Content-Type": "application/json"}
    for _ in range(MAX_WAITS + 1):
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=headers), timeout=timeout) as r:
                payload = json.loads(r.read().decode("utf-8"))
            return payload, (time.perf_counter() - t0) * 1000.0
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(float(e.headers.get("Retry-After") or 1))
    raise RuntimeError(f"still rate-limited after {MAX_WAITS} waits: {url}")


def _dist(xs: list[float]) -> dict:
    s = sorted(xs)
    if not s:
        return {"n": 0, "p50": None, "p95": None}
    return {"n": len(s), "p50": round(_percentile(s, 0.5), 1), "p95": round(_percentile(s, 0.95), 1)}


def reference_hits(ladder, questions: list[str]) -> dict[str, list[int]]:
    """The top passages each question gets on this machine, through the same R7n search the service runs."""
    return {q: [h.passage_id for h in ladder.run("R7n", normalise_question(q), None, SEARCH_K).hits]
            for q in questions}


def measure(base_url: str, questions: list[str], fresh: list[str], reference: dict | None = None,
            cached=()) -> dict:
    """Search latency over `questions`, answer latency for `cached` (example questions, served from the cache) and
    `fresh` (new, billed questions), peak memory, and, given `reference`, how often the server's top passages
    match this machine's. Server-side ms come from each payload; end-to-end ms include the network."""
    base = base_url.rstrip("/")
    e2e, server, same = [], [], 0
    for q in questions:
        got, ms = _call(f"{base}/api/search?" + urllib.parse.urlencode({"q": q}))
        e2e.append(ms)
        server.append(got["ms"])
        if reference is not None and [h["passage_id"] for h in got["hits"]] == reference.get(q):
            same += 1

    def asks(qs) -> dict:
        a_e2e, a_server, states = [], [], {}
        for q in qs:
            got, ms = _call(f"{base}/api/ask", {"question": q, "deal": None})
            a_e2e.append(ms)
            a_server.append(got["ms"])
            states[got["state"]] = states.get(got["state"], 0) + 1
        return {"e2e": _dist(a_e2e), "server": _dist(a_server), "states": dict(sorted(states.items()))}

    out = {"base": base, "search": {"e2e": _dist(e2e), "server": _dist(server)}, "ask_cached": asks(cached),
           "ask_fresh": asks(fresh)}
    health, _ = _call(f"{base}/api/health")
    out |= {"rss_mb": health["rss_mb"], "git_sha": health["git_sha"], "bundle_sha": health["bundle_sha"]}
    if reference is not None:
        out["embed_parity"] = {"n": len(questions), "same": same,
                               "rate": round(same / len(questions), 4) if questions else None}
    return out
```

`pipeline/cli.py`:
- Import `from evals.measure import measure, reference_hits`. `hashlib`, `Embedder`, `load_lexicon`,
  `load_settings`, `read_items` and `build_live_ladder` are already imported by earlier tasks.
- Add the handler right above `M5_STAGES` (below Task 5's `_m5_calibrate`):

```python
def _m5_measure(args) -> int:
    """Run from the development machine against the live URL: the reference searches run here, over the same
    bundle the box serves, so the parity compares the two machines' query embeddings."""
    if not args.base:
        print("--base is required, e.g. https://deals.forn.al", file=sys.stderr)
        return 2
    items = [i for i in read_items(_data_m4() / "tmachine_items.jsonl") if i.split == "tune"]
    picked = sorted(items, key=lambda i: hashlib.sha1(i.item_id.encode()).hexdigest())
    questions = [i.question for i in picked[:args.search_n]]
    fresh = [i.question for i in picked[args.search_n:args.search_n + args.fresh]]
    cached = [e["question"] for e in json.loads(EXAMPLES.read_text(encoding="utf-8"))]
    ladder = build_live_ladder(_live_db(), Embedder(), load_lexicon(LEXICON_PATH), load_settings(SETTINGS_PATH))
    got = measure(args.base, questions, fresh, reference_hits(ladder, questions), cached=cached)
    out = _data_m5() / "server.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(out, json.dumps(got, indent=2, sort_keys=True))
    print(json.dumps({"search": got.get("search"), "rss_mb": got.get("rss_mb")}))
    return 0
```

Change the `M5_STAGES` literal to:

```python
M5_STAGES = {"parity": _m5_parity, "recall": _m5_recall, "calibrate": _m5_calibrate, "measure": _m5_measure}
```

In `entry`, below Task 5's four `m5p` arguments, add:

```python
    m5p.add_argument("--base", default=None)
    m5p.add_argument("--search-n", type=int, default=50)
    m5p.add_argument("--fresh", type=int, default=3)
```

- [ ] **Step 9: Run them and the whole suite**

Run: `uv run pytest tests/test_measure.py -q && uv run pytest -q`
Expected: all pass.

- [ ] **Step 10: Commit**

```bash
git add evals/measure.py pipeline/cli.py tests/test_measure.py
git commit -m "m5: dtd m5 measure — server and end-to-end latency, peak memory, cross-machine embedding parity

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Deploy files

**Files:**
- Create: `deploy/Caddyfile`, `deploy/dtd.service`, `deploy/provision.sh`, `deploy/push.sh`, `deploy/smoke.py`,
  `deploy/hosting.json`, `deploy/env.example`
- Test: `tests/test_deploy.py`

**Interfaces:**
- Consumes:
  - `service.app:create_app` as a zero-argument factory (Task 9);
  - `/api/health` keys `git_sha`, `bundle_sha`, `facts_sha`, `template_sha` and `budget` (Task 9). Health shows no
    spend amounts, so the cap-trip check reads the box's ledger over ssh;
  - `dtd bundle` writing `data/live/live.db` and `bundle.json` (Task 4);
  - `dtd site`, `dtd warm` and `dtd facts --check`.
- Uses Task 8's `from_env`, which reads the variables named in `deploy/env.example`:
  - `ANTHROPIC_API_KEY` is read by the SDK;
  - `DTD_BUNDLE`, `DTD_STATE`, `DTD_MONTH_CAP_USD` and `DTD_DAY_CAP_USD`;
  - every other `Config` field has a default;
  - `git_sha` is read from a `GIT_SHA` file in the working directory when `DTD_GIT_SHA` is unset, because `push.sh` writes that file into each release.
- Produces:
  - the box layout:
    - `/srv/dtd/releases/<git sha>/`, each holding the code, `.venv`, `site/dist`, a `live.db` symlink and `GIT_SHA`;
    - `/srv/dtd/bundles/<bundle sha>/`;
    - the `/srv/dtd/current` symlink;
    - `/var/lib/dtd` for the ledger, cache and model files;
  - `smoke.py`'s check functions, and `--cap-trip OUT --fresh Q --ssh TARGET`, which writes `data/m5/cap_trip.json`
    (`{"budget_reached", "budget_cached", "ledger_unchanged", "health_budget"}`) for Task 11.
- `hosting.json` ships with `null` for the exchange rate, the day cap and the checked date. Those are data, filled from dated sources in Task 14 when the server exists. `build_m5` leaves the hosting facts pending until they are filled.

- [ ] **Step 1: Write the failing deploy tests**

`tests/test_deploy.py`:

```python
import importlib.util
import json
import re
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pytest

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
spec = importlib.util.spec_from_file_location("smoke", Path("deploy/smoke.py"))
smoke = importlib.util.module_from_spec(spec)
spec.loader.exec_module(smoke)


def test_caddy_sets_the_exact_csp_and_proxies_only_the_api():
    text = Path("deploy/Caddyfile").read_text()
    assert f'Content-Security-Policy "{CSP}"' in text and smoke.CSP == CSP
    assert "unsafe-inline" not in text and "unsafe-eval" not in text
    assert "handle /api/*" in text and "reverse_proxy 127.0.0.1:8000" in text
    assert "root * /srv/dtd/current/site/dist" in text and not re.search(r"^\s*log\b", text, re.M)


def test_service_unit_runs_one_worker_without_access_logs():
    text = Path("deploy/dtd.service").read_text()
    for flag in ("--factory service.app:create_app", "--host 127.0.0.1", "--port 8000", "--workers 1",
                 "--no-access-log", "--forwarded-allow-ips 127.0.0.1"):
        assert flag in text
    for line in ("User=dtd", "WorkingDirectory=/srv/dtd/current", "EnvironmentFile=/etc/dtd/env",
                 "ProtectSystem=strict", "ReadWritePaths=/var/lib/dtd", "MemoryMax=2G", "Restart=always",
                 "WantedBy=multi-user.target"):
        assert line in text


def test_push_refuses_a_dirty_tree_and_ships_only_committed_code():
    text = Path("deploy/push.sh").read_text()
    for s in ("set -euo pipefail", "git status --porcelain", "git archive", "dtd facts --check", "dtd bundle",
              "dtd site", "uv sync --frozen --no-dev", "UV_PYTHON_PREFERENCE=only-system", "/api/health",
              "sha256sum -c", "dtd warm"):
        assert s in text, s
    assert not re.search(r"rsync[^\n]*\s\.\s", text)  # the code never leaves as the working tree
    subprocess.run(["bash", "-n", "deploy/push.sh"], check=True)


def test_provision_locks_the_box_down():
    text = Path("deploy/provision.sh").read_text()
    for s in ("set -euo pipefail", "ufw allow 22/tcp", "ufw allow 80/tcp", "ufw allow 443/tcp",
              "PasswordAuthentication no", "unattended-upgrades", "useradd --system", "SystemMaxUse=",
              "UV_INSTALL_DIR=/usr/local/bin"):
        assert s in text, s
    subprocess.run(["bash", "-n", "deploy/provision.sh"], check=True)


def test_hosting_record_has_every_field_the_facts_read():
    h = json.loads(Path("deploy/hosting.json").read_text())
    assert set(h) == {"provider", "plan", "eur_month", "extras_eur_month", "eur_usd", "eur_usd_date",
                      "eur_usd_source", "budget_usd_month", "day_cap_usd", "checked"}
    assert h["budget_usd_month"] == 10.0 and h["eur_month"] > 0


def test_env_example_names_the_variables_and_holds_no_secret():
    text = Path("deploy/env.example").read_text()
    for name in ("ANTHROPIC_API_KEY=", "DTD_BUNDLE=", "DTD_STATE=", "DTD_MONTH_CAP_USD=", "DTD_DAY_CAP_USD=",
                 "FASTEMBED_CACHE_PATH="):
        assert name in text
    assert "sk-ant-" not in text and "@" not in text


class Box(BaseHTTPRequestHandler):
    """A fake live desk: healthy unless a test flips a class attribute."""
    csp, disclaimer, searches, limit_after = CSP, True, [0], 3

    def _send(self, code, body: bytes, ctype="application/json", headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code=200, headers=()):
        self._send(code, json.dumps(obj).encode(), headers=headers)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/health":
            return self._json({"git_sha": "g", "bundle_sha": "b", "facts_sha": "f", "budget": "ok"})
        if path == "/api/deals":
            return self._json([{"id": "x"}])
        if path == "/api/search":
            Box.searches[0] += 1
            if Box.searches[0] > Box.limit_after:  # keyed on the socket address, whatever the header says
                return self._json({"error": "rate_limited"}, 429, [("Retry-After", "30")])
            return self._json({"hits": [{"stages": {"bm25": None, "dense": {"rank": 1, "score": 0.9}}}], "ms": 3.0})
        if path in smoke.PAGES:
            page = f"<p>{smoke.DISCLAIMER if Box.disclaimer else ''}</p>".encode()
            return self._send(200, page, "text/html", [("Content-Security-Policy", Box.csp)] if Box.csp else [])
        self._json({}, 404)

    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["question"]
        if len(q) > 300:
            return self._json({"error": "invalid"}, 422)
        if "Nonexistent" in q:
            return self._json({"state": "which_deal", "served_from": None, "claims": []})
        return self._json({"state": "answered", "served_from": "cache",
                           "claims": [{"link": "https://www.sec.gov/Archives/x.htm"}]})

    def log_message(self, *args):
        pass


@pytest.fixture
def box():
    Box.csp, Box.disclaimer, Box.searches = CSP, True, [0]
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Box)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_smoke_passes_against_a_healthy_box(box):
    problems = (smoke.check_health(box, {"git_sha": "g", "bundle_sha": "b", "facts_sha": "f"})
                + smoke.check_pages(box) + smoke.check_deals(box) + smoke.check_search(box, "fee")
                + smoke.check_ask(box, "fee", smoke.ANSWERED, served_from="cache", sec_link=True)
                + smoke.check_ask(box, smoke.NO_DEAL, {"which_deal"}) + smoke.check_invalid(box)
                + smoke.check_burst(box, "fee"))
    assert problems == []


def test_smoke_reports_a_stale_release_and_bare_pages(box):
    Box.csp, Box.disclaimer = None, False
    assert smoke.check_health(box, {"git_sha": "other"}) == ["health: git_sha is 'g', want 'other'"]
    problems = smoke.check_pages(box)
    assert any("no disclaimer" in p for p in problems) and any("CSP" in p for p in problems)


def test_cap_trip_reads_states_and_the_ledger(box):
    still = iter(["3|0.01", "3|0.01"])  # the ledger snapshot before and after, as `ledger_over_ssh` reads it
    got = smoke.cap_trip(box, "fresh question", "cached question", lambda: next(still))
    assert got["ledger_unchanged"] is True and got["budget_reached"] is False  # this fake box is not capped
    assert got["health_budget"] == "ok"
    moved = iter(["3|0.01", "4|0.02"])
    assert smoke.cap_trip(box, "fresh question", "cached question", lambda: next(moved))["ledger_unchanged"] is False


def test_the_ledger_is_read_over_ssh_as_the_service_user(monkeypatch):
    seen = []
    monkeypatch.setattr(smoke.subprocess, "check_output", lambda cmd, text: seen.append(cmd) or "3|0.01\n")
    assert smoke.ledger_over_ssh("root@box")() == "3|0.01"
    assert seen[0][:2] == ["ssh", "root@box"] and "sudo -u dtd sqlite3 /var/lib/dtd/budget.db" in seen[0][2]
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/test_deploy.py -q`
Expected: FAIL at collection, because `deploy/smoke.py` does not exist (`FileNotFoundError`).

- [ ] **Step 3: Write the deploy files**

`deploy/Caddyfile`:

```
# deals.forn.al: static pages from the current release, /api/* to the one uvicorn worker on localhost.
# Caddy keeps no access log unless a `log` directive asks for one; there is none on purpose.
deals.forn.al {
	encode zstd gzip
	header {
		Content-Security-Policy "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
		Strict-Transport-Security "max-age=31536000"
		X-Content-Type-Options "nosniff"
		Referrer-Policy "no-referrer"
		-Server
	}
	handle /api/* {
		reverse_proxy 127.0.0.1:8000
	}
	handle {
		root * /srv/dtd/current/site/dist
		file_server
	}
}
```

`deploy/dtd.service`:

```ini
[Unit]
Description=Deal Terms Desk API
After=network-online.target
Wants=network-online.target

[Service]
User=dtd
Group=dtd
WorkingDirectory=/srv/dtd/current
EnvironmentFile=/etc/dtd/env
ExecStart=/srv/dtd/current/.venv/bin/uvicorn --factory service.app:create_app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --forwarded-allow-ips 127.0.0.1
Restart=always
RestartSec=2
MemoryMax=2G
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
ReadWritePaths=/var/lib/dtd

[Install]
WantedBy=multi-user.target
```

`deploy/env.example`. It holds names only. The real file is `/etc/dtd/env` on the box, root-owned with mode 0600, written by hand and never committed.

```
# /etc/dtd/env on the box (root-owned, mode 0600). Values are set on the box, never in the repo.
ANTHROPIC_API_KEY=
DTD_BUNDLE=/srv/dtd/current/live.db
DTD_STATE=/var/lib/dtd
DTD_MONTH_CAP_USD=
DTD_DAY_CAP_USD=
FASTEMBED_CACHE_PATH=/var/lib/dtd/fastembed
HF_HOME=/var/lib/dtd/huggingface
```

`deploy/hosting.json`:

```json
{
  "provider": "Hetzner Cloud",
  "plan": "CAX11",
  "eur_month": 4.49,
  "extras_eur_month": null,
  "eur_usd": null,
  "eur_usd_date": null,
  "eur_usd_source": null,
  "budget_usd_month": 10.0,
  "day_cap_usd": null,
  "checked": null
}
```

`deploy/provision.sh`:

```bash
#!/usr/bin/env bash
# One-time, idempotent setup of the Deal Terms Desk box (Ubuntu 24.04 LTS). Run as root from the repo root:
#   ssh root@$HOST 'bash -s' < deploy/provision.sh
# Then write /etc/dtd/env (see deploy/env.example; root-owned, mode 0600) and run deploy/push.sh.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

apt-get update -q
apt-get upgrade -yq
apt-get install -yq unattended-upgrades ufw curl ca-certificates gnupg debian-keyring debian-archive-keyring \
  apt-transport-https sqlite3 rsync
dpkg-reconfigure -f noninteractive unattended-upgrades

# Firewall: ssh and the web only.
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# Keys only.
install -d /etc/ssh/sshd_config.d
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin prohibit-password\n' \
  > /etc/ssh/sshd_config.d/10-dtd.conf
systemctl reload ssh

# Caddy from its official apt repository.
if ! command -v caddy >/dev/null; then
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' > /etc/apt/sources.list.d/caddy-stable.list
  apt-get update -q
  apt-get install -yq caddy
fi

# uv, using the system Python (Ubuntu 24.04 ships 3.12, which the project requires).
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh
fi

# The service user and its directories.
id dtd >/dev/null 2>&1 || useradd --system --home-dir /var/lib/dtd --shell /usr/sbin/nologin dtd
install -d -o root -g root -m 755 /srv/dtd /srv/dtd/releases /srv/dtd/bundles
install -d -o dtd -g dtd -m 750 /var/lib/dtd /var/lib/dtd/fastembed /var/lib/dtd/huggingface
install -d -o root -g root -m 700 /etc/dtd

# Keep the journal small.
install -d /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=200M\n' > /etc/systemd/journald.conf.d/10-dtd.conf
systemctl restart systemd-journald

echo "provisioned; next: write /etc/dtd/env (mode 0600), then run deploy/push.sh"
```

`deploy/push.sh`:

```bash
#!/usr/bin/env bash
# Ship HEAD to the Deal Terms Desk box. Safe to rerun: a release, bundle or site already on the box is kept, and an
# interrupted run resumes. Needs DTD_HOST, the ssh target (for example root@deals.forn.al).
set -euo pipefail
: "${DTD_HOST:?set DTD_HOST to the ssh target, for example root@deals.forn.al}"
BASE="${DTD_BASE:-https://deals.forn.al}"
cd "$(git rev-parse --show-toplevel)"

dirty() { [ -n "$(git status --porcelain)" ]; }
if dirty; then
  echo "refusing to deploy: the working tree is dirty; commit or stash first" >&2
  exit 1
fi

# Release gates: CI's checks plus the ones that need data/.
uv run pytest -q
uv run dtd facts --check
uv run dtd bundle
uv run dtd site
if dirty; then
  echo "refusing to deploy: the release gates changed tracked files; review and commit them first" >&2
  exit 1
fi

SHA="$(git rev-parse HEAD)"
BUNDLE_SHA="$(uv run python -c 'import json; print(json.load(open("data/live/bundle.json"))["sha256"])')"
FACTS_SHA="$(uv run python -c 'import hashlib; print(hashlib.sha256(open("facts.json", "rb").read()).hexdigest())')"
TEMPLATE_SHA="$(uv run python -c 'from answer.prompt import TEMPLATE_SHA; print(TEMPLATE_SHA)')"
REL="/srv/dtd/releases/$SHA"
BUN="/srv/dtd/bundles/$BUNDLE_SHA"
BEFORE="$(curl -fsS "$BASE/api/health" || echo '{}')"
AS_DTD="set -a; . /etc/dtd/env; set +a; sudo -E -u dtd env HOME=/var/lib/dtd"

# Code: the committed tree only, never the working tree. .complete marks a finished release.
if ! ssh "$DTD_HOST" test -f "$REL/.complete"; then
  ssh "$DTD_HOST" "rm -rf $REL && mkdir -p $REL"
  git archive --format=tar HEAD | ssh "$DTD_HOST" "tar -x -C $REL"
  ssh "$DTD_HOST" "cd $REL && echo $SHA > GIT_SHA && UV_PYTHON_PREFERENCE=only-system uv sync --frozen --no-dev && touch .complete"
fi

# Bundle: only when the box lacks this exact file. Resumable, then checked against its sha256.
if ! ssh "$DTD_HOST" test -f "$BUN/live.db"; then
  ssh "$DTD_HOST" "mkdir -p $BUN"
  rsync -a --partial data/live/live.db "$DTD_HOST:$BUN/live.db.part"
  ssh "$DTD_HOST" "cd $BUN && echo '$BUNDLE_SHA  live.db.part' | sha256sum -c --quiet - && mv live.db.part live.db"
fi
rsync -a data/live/bundle.json "$DTD_HOST:$BUN/bundle.json"
ssh "$DTD_HOST" "ln -sfn $BUN/live.db $REL/live.db"

# Site: rendered from this commit's facts.json.
rsync -a --delete site/dist/ "$DTD_HOST:$REL/site/dist/"

# The embedding model, downloaded once into the service's cache, as the service user.
ssh "$DTD_HOST" "cd $REL && $AS_DTD .venv/bin/python -c 'from retrieval.models import Embedder; Embedder().embed_query(\"warm up\")'"

# Switch: atomic symlink swap, config from the release, restart.
ssh "$DTD_HOST" "ln -sfn $REL /srv/dtd/current.next && mv -T /srv/dtd/current.next /srv/dtd/current \
  && install -m 644 $REL/deploy/Caddyfile /etc/caddy/Caddyfile \
  && install -m 644 $REL/deploy/dtd.service /etc/systemd/system/dtd.service \
  && systemctl daemon-reload && systemctl enable --now caddy dtd && systemctl reload caddy && systemctl restart dtd"

# The box must now serve exactly this code, bundle and facts.
matches() {
  uv run python - "$1" "$SHA" "$BUNDLE_SHA" "$FACTS_SHA" <<'PY'
import json, sys
try:
    h = json.loads(sys.argv[1])
except ValueError:
    sys.exit(1)
sys.exit(0 if [h.get("git_sha"), h.get("bundle_sha"), h.get("facts_sha")] == sys.argv[2:] else 1)
PY
}
live=""
for _ in $(seq 60); do
  if matches "$(curl -fsS "$BASE/api/health" || echo '{}')"; then live=1; break; fi
  sleep 2
done
if [ -z "$live" ]; then
  echo "the box never reported this release. Earlier releases are in /srv/dtd/releases: roll back with" >&2
  echo "  ssh $DTD_HOST 'ln -sfn /srv/dtd/releases/<sha> /srv/dtd/current && systemctl restart dtd'" >&2
  exit 1
fi

# Re-warm the example answers whenever the prompt could have changed (new bundle or new template).
OLD="$(uv run python -c 'import json, sys; h = json.loads(sys.argv[1]); print(h.get("bundle_sha", ""), h.get("template_sha", ""))' "$BEFORE")"
if [ "$OLD" != "$BUNDLE_SHA $TEMPLATE_SHA" ]; then
  ssh "$DTD_HOST" "cd /srv/dtd/current && $AS_DTD .venv/bin/dtd warm --examples site/examples.json"
fi
echo "deployed $SHA"
```

`deploy/smoke.py`:

```python
"""Smoke test of the live Deal Terms Desk, run from the repo root on the development machine:

    uv run python deploy/smoke.py https://deals.forn.al [--fresh "a question not asked before"]
    uv run python deploy/smoke.py https://deals.forn.al --cap-trip data/m5/cap_trip.json --fresh "..." --ssh root@HOST

Without --fresh it makes no model call. Exits 1 on any problem."""
import argparse
import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
DISCLAIMER = "This is not legal advice."
PAGES = ("/", "/search.html", "/results.html", "/method.html")
NO_DEAL = "What is the outside date for Nonexistent Widgets Company?"
ANSWERED = {"answered", "not_stated", "unfiled_schedule"}


def fetch(url, body=None, headers=None, timeout=120.0):
    """(status, headers, raw body); an HTTP error status is returned, not raised."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    h = dict(headers or {})
    if body is not None:
        h["Content-Type"] = "application/json"
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=timeout) as r:
            return r.status, r.headers, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers, e.read()


def _json(raw: bytes):
    try:
        return json.loads(raw.decode("utf-8"))
    except ValueError:
        return None


def _search(base, q, headers=None):
    return fetch(f"{base}/api/search?" + urllib.parse.urlencode({"q": q}), headers=headers)


def check_health(base, want: dict) -> list[str]:
    status, _, raw = fetch(f"{base}/api/health")
    h = _json(raw) if status == 200 else None
    if not isinstance(h, dict):
        return [f"health: status {status}"]
    return [f"health: {k} is {h.get(k)!r}, want {v!r}" for k, v in want.items() if h.get(k) != v]


def check_pages(base) -> list[str]:
    out = []
    for path in PAGES:
        status, headers, raw = fetch(base + path)
        if status != 200:
            out.append(f"{path}: status {status}")
            continue
        if DISCLAIMER not in raw.decode("utf-8", "replace"):
            out.append(f"{path}: no disclaimer")
        if headers.get("Content-Security-Policy") != CSP:
            out.append(f"{path}: CSP is {headers.get('Content-Security-Policy')!r}")
    return out


def check_deals(base) -> list[str]:
    status, _, raw = fetch(f"{base}/api/deals")
    rows = _json(raw) if status == 200 else None
    return [] if isinstance(rows, list) and rows else [f"deals: status {status}, no rows"]


def check_search(base, q) -> list[str]:
    status, _, raw = _search(base, q)
    got = _json(raw) if status == 200 else None
    if not isinstance(got, dict) or not got.get("hits"):
        return [f"search: status {status}, no hits"]
    return [] if set(got["hits"][0].get("stages") or {}) == {"bm25", "dense"} else ["search: no per-stage scores"]


def check_ask(base, q, states, served_from=None, sec_link=False) -> list[str]:
    status, _, raw = fetch(f"{base}/api/ask", {"question": q, "deal": None})
    got = _json(raw) if status == 200 else None
    if not isinstance(got, dict):
        return [f"ask {q!r}: status {status}"]
    out = []
    if got.get("state") not in states:
        out.append(f"ask {q!r}: state {got.get('state')!r}, want one of {sorted(states)}")
    if served_from is not None and got.get("served_from") != served_from:
        out.append(f"ask {q!r}: served from {got.get('served_from')!r}, want {served_from!r}")
    if sec_link and not any(str(c.get("link") or "").startswith("https://www.sec.gov/") for c in got.get("claims", [])):
        out.append(f"ask {q!r}: no claim links to sec.gov")
    return out


def check_invalid(base) -> list[str]:
    status, _, _ = fetch(f"{base}/api/ask", {"question": "x" * 5000, "deal": None})
    return [] if status == 422 else [f"over-long question: status {status}, want 422"]


def check_burst(base, q, tries=500) -> list[str]:
    """Search until rate-limited (Search makes no model call). The same search with a forged X-Forwarded-For must
    still be limited: Caddy replaces the header, so a visitor cannot choose their own address."""
    for _ in range(tries):
        status, headers, _ = _search(base, q)
        if status == 429:
            if not headers.get("Retry-After"):
                return ["burst: 429 without Retry-After"]
            forged, _, _ = _search(base, q, {"X-Forwarded-For": "203.0.113.9"})
            return [] if forged == 429 else [f"forged X-Forwarded-For: status {forged}, want 429"]
    return [f"burst: no 429 after {tries} searches"]


def ledger_over_ssh(target: str):
    """A function returning the box's spend ledger as "rows|usd", read as the service user. Spend is never served
    over HTTP, so this is the only way to see it."""
    def snapshot() -> str:
        sql = "SELECT COUNT(*), ROUND(COALESCE(SUM(usd), 0), 6) FROM spend"
        return subprocess.check_output(["ssh", target, f"sudo -u dtd sqlite3 /var/lib/dtd/budget.db '{sql}'"],
                                       text=True).strip()
    return snapshot


def cap_trip(base, fresh_q, cached_q, ledger) -> dict:
    """Run with the service restarted under a tiny cap: a new question must get budget_reached, a cached one
    budget_cached, and the spend ledger (`ledger()`, a snapshot) must not move."""
    before = ledger()
    fresh = _json(fetch(f"{base}/api/ask", {"question": fresh_q, "deal": None})[2]) or {}
    cached = _json(fetch(f"{base}/api/ask", {"question": cached_q, "deal": None})[2]) or {}
    after = ledger()
    health = _json(fetch(f"{base}/api/health")[2]) or {}
    return {"budget_reached": fresh.get("state") == "budget_reached",
            "budget_cached": cached.get("state") == "budget_cached",
            "ledger_unchanged": before == after, "health_budget": health.get("budget")}


def local_shas(root: Path = Path(".")) -> dict:
    return {"git_sha": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip(),
            "bundle_sha": json.loads((root / "data" / "live" / "bundle.json").read_text(encoding="utf-8"))["sha256"],
            "facts_sha": hashlib.sha256((root / "facts.json").read_bytes()).hexdigest()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="smoke")
    ap.add_argument("base")
    ap.add_argument("--fresh", help="an uncached question: one real, billed answer that must link to sec.gov")
    ap.add_argument("--cap-trip", metavar="OUT", help="only the cap-trip check (service under a tiny cap); result to OUT")
    ap.add_argument("--ssh", metavar="TARGET", help="with --cap-trip: the ssh target whose spend ledger is read")
    args = ap.parse_args(argv)
    base = args.base.rstrip("/")
    cached_q = json.loads(Path("site/examples.json").read_text(encoding="utf-8"))[0]["question"]
    if args.cap_trip:
        if not (args.fresh and args.ssh):
            ap.error("--cap-trip needs --fresh and --ssh")
        got = cap_trip(base, args.fresh, cached_q, ledger_over_ssh(args.ssh))
        Path(args.cap_trip).parent.mkdir(parents=True, exist_ok=True)
        Path(args.cap_trip).write_text(json.dumps(got, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(got))
        return 0 if got["budget_reached"] and got["budget_cached"] and got["ledger_unchanged"] else 1
    problems = (check_health(base, local_shas()) + check_pages(base) + check_deals(base) + check_search(base, cached_q)
                + check_ask(base, cached_q, ANSWERED, served_from="cache") + check_ask(base, NO_DEAL, {"which_deal"})
                + check_invalid(base))
    if args.fresh:
        problems += check_ask(base, args.fresh, {"answered"}, served_from="live", sec_link=True)
    problems += check_burst(base, cached_q)  # last: it leaves this machine rate-limited for a minute
    for p in problems:
        print("FAIL", p)
    print("smoke: ok" if not problems else f"smoke: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
```

Make the scripts executable: `chmod +x deploy/push.sh deploy/provision.sh deploy/smoke.py`.

- [ ] **Step 4: Run them**

Run: `uv run pytest tests/test_deploy.py -q && (command -v shellcheck >/dev/null && shellcheck deploy/push.sh deploy/provision.sh || true) && uv run pytest -q`
Expected: all pass.

`shellcheck` runs only where it is installed. Any warning it prints is fixed in the script, not silenced.

- [ ] **Step 5: Commit**

```bash
git add deploy tests/test_deploy.py
git commit -m "m5: deploy files — Caddy (exact CSP, no access log), systemd unit, idempotent provision and push, smoke and cap trip

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Real offline runs and the API calibration

This task is operational: no new code unless a run exposes a bug. A bug goes back through TDD in the owning task's
files. Log every command's output under `data/m5/` (`mkdir -p data/m5` first).

**Needs:** Tasks 1–12 committed on `m5`. The `dtd-dev` key is in local `.env` as `ANTHROPIC_API_KEY` (roadmap 0.5).
Michael approves the calibration estimate before Step 3.

- [ ] **Step 1: The real-data checks from Tasks 2 and 4.** Re-run them if any retrieval, answer or bundle code changed
  since they ran.

```bash
uv run dtd m5 parity 2>&1 | tee data/m5/parity.log; echo "exit=$?"
uv run dtd bundle 2>&1 | tee data/m5/bundle.log
uv run dtd m5 recall 2>&1 | tee data/m5/recall.log; echo "exit=$?"
```

Expected:
- **Parity:** `exit=0`, and `data/out/m5/parity.json` has `"differ": []` for `thuman`, `tmachine` and `abstain`.
  - If anything differs, read three of the differing items and compare the prompts.
  - Dense ties between byte-identical passages are a known source (M3 carry-over). The fix is a deterministic
    tie-break in `retrieval/dense.py`, and M4's recall is then re-run.
  - Never continue with a non-empty `differ` that is unexplained.
- **Bundle:** `"rebuilt": false` if Task 4 Step 9 already built it from the same inputs. The bundle's kill test was
  Task 4 Step 9.
- **Recall:** `exit=0` and `"parity": {"checked": 200, "same": 200}`.
  - `data/out/m5/bundle_r6n.json` `by_split.report["recall@5"]` sits near `m4_r6n_report_recall_at_5`.
  - A difference is expected and gets published: BM25 statistics differ, and the bundle holds 88 of the 100 MAUD
    agreements.

- [ ] **Step 2: One real API call (model test)**

Run: `uv run pytest -m model tests/test_api_runner.py -v`

Expected: `test_one_real_call_through_the_dev_key` passes, at a cost under a cent on `dtd-dev`.

- [ ] **Step 3: [Michael approves] Calibration smoke, kill, full run**

The estimate to show Michael first: 40 items × (about 14k tokens in × $1/MTok + at most 1,024 out × $5/MTok) ≈ $0.80
worst case, at the price Task 5 Step 8 confirmed.

```bash
LEDGER=data/m5/calibration_claude-haiku-4-5-20251001_mt1024.jsonl
uv run dtd m5 calibrate --n 40 --max-new 4 2>&1 | tee data/m5/calibrate_smoke.log
tail -n 4 "$LEDGER" | python3 -m json.tool --json-lines | head -80
(uv run dtd m5 calibrate --n 40 > data/m5/calibrate_kill.log 2>&1 &) ; sleep 25 ; pkill -9 -f "dtd m5 calibrate"
uv run dtd m5 calibrate --n 40 2>&1 | tee -a data/m5/calibrate_kill.log
python3 -c "
import json
ks = [json.loads(l)['key'] for l in open('$LEDGER') if l.strip()]
print(len(ks), len(set(ks)))" | tee -a data/m5/calibrate_kill.log
```

Expected:
- the smoke records show `answer.usage` with real token counts;
- after the kill and rerun, the two printed counts are equal and at most 40;
- `data/m5/calibration.json` exists, and its `run` block shows `done` equal to the sample size.

- [ ] **Step 4: Read the calibration and apply the stop rule.** Open `data/m5/calibration.json`.
- **`stop_rule.verdict == "stop"`: stop.** Read `stop_rule.reasons`, then bring Michael the two options from spec §2:
  - a priced API rerun of the report split; or
  - accept and label the difference on the Method page.

  Do not deploy until he picks.
- **`worst_case_ok` must be `true`.** If it is not, the characters-per-token estimate is too high: lower
  `CHARS_PER_TOKEN` in `service/prices.py` through TDD, then re-run `uv run dtd m5 calibrate --n 40`. The ledger
  is reused, so this makes no new calls.
- **Set the output cap from `api_tokens_out_p99`:** round it up to the next multiple of 256, plus 256.
  - If that is above 1,024, re-run calibration at the new cap: `uv run dtd m5 calibrate --n 40 --max-tokens <cap>`
    writes a new `_mt<cap>` ledger, and its calls are new.
  - Then change the `DTD_MAX_TOKENS` default in `service/config.py` (`_num(env, "DTD_MAX_TOKENS", int, 1024)`) and
    the `max_tokens=1024` in `tests/test_config.py::test_defaults_need_only_the_month_cap` to the chosen cap.
- **Answers per month** = model cap ÷ `cost_per_answer_mean`. If that is lower than Michael considers enough, raise
  it with him before any definitions cap. Spec §2: capping definitions changes the prompt, so the M4 report-split
  answers would be re-run through `claude -p`.

- [ ] **Step 5: Commit the config change**

```bash
uv run pytest -q tests/test_config.py
git add service/config.py tests/test_config.py
git commit -m "m5: output cap from calibration p99

<paste: parity counts per set, bundle sha256 and bytes, bundle recall@5 vs m4, calibration n, tokens in/out mean
and p99, cost per answer mean, stop-rule verdict>

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Provision the box and deploy

> **Superseded in part (2026-10-06):** the server is a Hetzner CX23 (x86, 4 GB, Falkenstein), billed in USD and created through the Hetzner API. `deploy/hosting.json` holds the USD record (Task 13c), and the caps come from `facts/m5.py`, not the Step 1 script. Step 3's provisioning reload fix is `systemctl try-reload-or-restart ssh`.

**Needs:**
- Task 13 passed its stop rule.
- Michael has done roadmap 0.3–0.5:
  - the private GitHub repo is created and pushed;
  - the `dtd-live` workspace exists, with its key, a spend limit just above the model cap, and spend alerts;
  - the Hetzner project has his SSH key.

Below, `$IP` is the server's IPv4 address and `DTD_HOST=root@$IP`.

- [ ] **Step 1: [Michael] Create the server.** Hetzner Cloud, type CAX11 (arm64, 4 GB), Ubuntu 24.04 LTS, an EU
  location, his SSH key, IPv4 and IPv6.

  Then fill the `null` fields of `deploy/hosting.json`:
  - `extras_eur_month`: primary IPv4 and any VAT;
  - `eur_usd`, `eur_usd_date` and `eur_usd_source`: a dated reference rate, such as the ECB's;
  - `day_cap_usd`: a tenth of the model cap, rounded down to the cent;
  - `checked`: today.

  Print the two caps the env file needs, exactly as `facts/m5.py` computes them:

```bash
uv run python -c "
import json; h = json.load(open('deploy/hosting.json'))
usd = round((h['eur_month'] + (h['extras_eur_month'] or 0)) * h['eur_usd'], 2)
print(f'DTD_MONTH_CAP_USD={h[\"budget_usd_month\"] - usd:.2f}', f'DTD_DAY_CAP_USD={h[\"day_cap_usd\"]}')"
uv run pytest -q tests/test_deploy.py
git add deploy/hosting.json
git commit -m "m5: hosting cost of record (published price, dated exchange rate) and the day cap

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 2: [Michael] DNS.** At the DNS host for `forn.al`, add `A deals → <IPv4>` and `AAAA deals → <IPv6>`.
  Then check:

```bash
dig +short deals.forn.al A ; dig +short deals.forn.al AAAA ; dig +short forn.al CAA
```

Expected: both addresses are the server's, and CAA is empty or allows `letsencrypt.org`. Do not deploy before this
passes: Caddy's certificate requests are rate-limited when they fail.

- [ ] **Step 3: Provision, twice**

```bash
ssh "$DTD_HOST" 'bash -s' < deploy/provision.sh 2>&1 | tee data/m5/provision.log
ssh "$DTD_HOST" 'bash -s' < deploy/provision.sh 2>&1 | tee -a data/m5/provision.log
ssh "$DTD_HOST" 'python3 --version; ufw status; id dtd'
```

Expected:
- the second run finishes the same way, because it is idempotent;
- Python 3.12.x;
- ufw allows only 22, 80 and 443;
- the `dtd` user exists.

- [ ] **Step 4: [Michael] The env file.** Michael runs this in his own terminal, not through Claude, so the live key
  never passes through the session:

```bash
ssh root@<IPv4> 'install -m 600 /dev/null /etc/dtd/env && cat > /etc/dtd/env'
```

He types these lines (names from `deploy/env.example`), then Ctrl-D:

```
ANTHROPIC_API_KEY=<the dtd-live key>
DTD_BUNDLE=/srv/dtd/current/live.db
DTD_STATE=/var/lib/dtd
DTD_MONTH_CAP_USD=<from Step 1>
DTD_DAY_CAP_USD=<from Step 1>
FASTEMBED_CACHE_PATH=/var/lib/dtd/fastembed
HF_HOME=/var/lib/dtd/huggingface
```

Check the names without printing the values: `ssh "$DTD_HOST" "cut -d= -f1 /etc/dtd/env; stat -c '%a %U' /etc/dtd/env"`.
Expected: the seven names, then `600 root`.

- [ ] **Step 5: Interim M5 facts of record.** Once `data/live/bundle.json` exists, `dtd facts` builds `m5_*` keys,
  so `dtd facts --check` (a `push.sh` gate) fails until they are committed. Commit what is measured so far: bundle,
  parity, recall, calibration, prices and hosting. The server, measure and cap-trip facts follow in Task 16; until
  then the site shows them as "pending".

```bash
uv run dtd facts && uv run dtd report && uv run dtd site
uv run dtd facts --check; echo "facts --check exit $?"
uv run pytest -q
git add facts.json docs/m5/REPORT.md
git commit -m "m5: interim M5 facts (bundle, parity, recall, calibration, prices, hosting) before the first deploy

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 6: First deploy**

Run: `DTD_HOST="$DTD_HOST" deploy/push.sh 2>&1 | tee data/m5/push1.log`

Expected, in order:
- the local gates pass (`pytest`, `dtd facts --check`, `dtd bundle`, `dtd site`);
- `/srv/dtd/releases/<sha>` is built with `uv sync --frozen --no-dev`;
- the bundle uploads and passes its `sha256sum -c`;
- the embedder downloads once into `/var/lib/dtd/fastembed`;
- the `current` symlink swaps and Caddy obtains the certificate;
- `/api/health` reports the local `git_sha`, `bundle_sha` and `facts_sha`;
- `dtd warm` runs on the box and prints `"asked": 6`;
- the last line is `deployed <sha>`.

- [ ] **Step 7: TLS and headers**

```bash
curl -sI https://deals.forn.al/ | tee data/m5/headers.log
curl -s https://deals.forn.al/api/health | python3 -m json.tool
```

Expected:
- HTTP/2 200, with the exact CSP from Task 12, HSTS, `x-content-type-options: nosniff` and `referrer-policy: no-referrer`;
- health shows `ok: true`, `budget: "ok"` and the `rss_mb`, `template_sha` and `bundle_meta` keys, with no spend amounts.

- [ ] **Step 8: Measure.** Run it from the development machine. Server-side times come from each payload's `ms`, so
  they exclude the network; end-to-end times include it.

Run: `uv run dtd m5 measure --base https://deals.forn.al 2>&1 | tee data/m5/measure.log`

This makes 50 searches (free), 6 example asks (cached) and 3 fresh asks (billed on `dtd-live`). It writes
`data/m5/server.json`.

Expected:
- **Embedding parity:** `embed_parity.rate` is 1.0 or near it. The reference searches ran here over the same
  bundle. A drop means arm64 ONNX numerics differ enough to change rankings: it is published in facts and named on the
  Method page, not hidden.
- **Memory:** `rss_mb` is well under the unit's `MemoryMax` of 2,048.
- **States:** `ask_cached.states` is all cached states, and `ask_fresh.states` has no `error`.

---

### Task 15: M5 exit on the real box

- [ ] **Step 1: Smoke**

Run:

```bash
uv run python deploy/smoke.py https://deals.forn.al --fresh "What does the Mandiant agreement say about employee benefits after closing?" 2>&1 | tee data/m5/smoke.log
```

Pick a `--fresh` question that names a deal but is not one of the examples.

Expected: `smoke: ok`. It runs the burst check last, which leaves this machine rate-limited for a minute.

- [ ] **Step 2: In the browser.** Use the claude-in-chrome tools and record a GIF named `deals_ask_states.gif`. On
  `https://deals.forn.al`:
  - ask one example per lead family (cached);
  - ask one fresh question that names a deal;
  - ask an ambiguous-deal question (a parent company with several deals);
  - ask an earn-out question about a tech deal (absent: expect "not stated");
  - use Search with a deal picked.

  Check that:
  - each state shows its own copy, with quotes and links to sec.gov;
  - an amended claim, if one comes up, says "uses amended text (Amendment No. N)";
  - the console shows no errors;
  - Results and Method show "pending" only for M5 facts not yet built.

- [ ] **Step 3: The cap trips on the real box**

```bash
ssh "$DTD_HOST" "cp /etc/dtd/env /etc/dtd/env.bak && sed -i 's/^DTD_MONTH_CAP_USD=.*/DTD_MONTH_CAP_USD=0.0001/' /etc/dtd/env && systemctl restart dtd"
until curl -fsS https://deals.forn.al/api/health | grep -q '"budget":"reached"'; do sleep 2; done
uv run python deploy/smoke.py https://deals.forn.al --cap-trip data/m5/cap_trip.json --ssh "$DTD_HOST" \
  --fresh "What does the Red Hat agreement say about the termination fee?" ; echo "exit=$?"
ssh "$DTD_HOST" "mv /etc/dtd/env.bak /etc/dtd/env && systemctl restart dtd"
until curl -fsS https://deals.forn.al/api/health | grep -q '"budget":"ok"'; do sleep 2; done
```

Expected:
- `exit=0`;
- `data/m5/cap_trip.json` has `budget_reached`, `budget_cached` and `ledger_unchanged` all `true`, and
  `health_budget` `"reached"`;
- after the restore, health shows `"budget":"ok"` again.

- [ ] **Step 4: Kill test on the box.** It follows Task 6's rules:
  - a reservation left open by a crash counts at its worst case at once;
  - it is settled at worst case once it is older than `STALE_S` (600 s), on the next start or reservation;
  - spend never goes down.

```bash
LEDGER="sudo -u dtd sqlite3 /var/lib/dtd/budget.db"
SUM="SELECT ROUND(SUM(CASE status WHEN 'open' THEN worst ELSE usd END), 6), COUNT(*) FROM spend"
ssh "$DTD_HOST" "$LEDGER \"$SUM\"" | tee data/m5/kill.log
for q in "Cerner stock options" "HashiCorp severance" "LinkedIn termination fee trigger"; do
  curl -s -X POST https://deals.forn.al/api/ask -H 'Content-Type: application/json' \
    -d "{\"question\": \"What does the agreement say about $q?\"}" > /dev/null &
done
sleep 2; ssh "$DTD_HOST" systemctl kill -s KILL dtd; wait
until curl -fsS https://deals.forn.al/api/health > /dev/null; do sleep 2; done
ssh "$DTD_HOST" "$LEDGER \"$SUM\"; $LEDGER \"SELECT status, COUNT(*) FROM spend GROUP BY status\"" | tee -a data/m5/kill.log
sleep 620; ssh "$DTD_HOST" "systemctl restart dtd"
until curl -fsS https://deals.forn.al/api/health > /dev/null; do sleep 2; done
ssh "$DTD_HOST" "$LEDGER \"$SUM\"; $LEDGER \"SELECT status, COUNT(*) FROM spend GROUP BY status\"" | tee -a data/m5/kill.log
ssh "$DTD_HOST" "sudo -u dtd sqlite3 /var/lib/dtd/cache.db 'SELECT COUNT(*) FROM cache'" | tee -a data/m5/kill.log
```

Expected:
- systemd restarted the service, and health answers;
- the spend sum never decreases from one snapshot to the next;
- right after the kill, any killed call's row may be `open`; after the stale window and a restart, no row is `open`;
- the cache count is at least the number of example questions.

---

### Task 16: Numbers of record, PRD note, review, merge

- [ ] **Step 1: Facts, report, site**

```bash
uv run dtd facts && uv run dtd report && uv run dtd site
uv run dtd facts --check; echo "facts --check exit $?"
uv run pytest; echo "pytest exit $?"
git diff --stat facts.json docs/
```

Expected:
- `facts --check` exits 0, and pytest passes, including `test_committed_m5_report_is_rendered_from_committed_facts`;
- `git diff facts.json` adds only `m5_*` keys. If an older key changed, find out why before committing.

- [ ] **Step 2: Read `docs/m5/REPORT.md` and `site/dist/results.html` and `method.html` as a reader would.**
  - Every M5 row has a value; nothing says "pending".
  - Machine-built and human-labelled labels are present.
  - Cost per answer, the caps and answers per month agree with each other.
  - The Method page's stated limits include `claude -p` vs the API, `maud.db` vs the live index, and
    development-machine latency.

- [ ] **Step 3: PRD outcome note.** Under §9, after the M5 decisions note, add a dated "M5 outcome" paragraph:
  - what shipped;
  - the cap-trip result;
  - any calibration or parity finding a reader of the PRD needs.

  Name facts by key; don't copy digits from them.

- [ ] **Step 4: Commit the numbers of record.** `data/` is gitignored, so the logs and measurement files stay local;
  the facts carry their numbers.

```bash
git add facts.json docs/m5/REPORT.md docs/PRD.md
git commit -m "m5: real run — bundle, calibration, deploy, smoke, cap trip and kill test; facts and report

<paste: parity, bundle sha256 and bytes, calibration summary, server p50/p95, smoke ok, cap-trip result, kill-test
snapshots, facts --check 0, pytest N passed>

Assisted-by: Claude
Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 5: Push again so the live site carries the final facts**

```bash
DTD_HOST="$DTD_HOST" deploy/push.sh 2>&1 | tee data/m5/push_final.log
curl -s https://deals.forn.al/api/health | python3 -c "import sys, json, hashlib; h = json.load(sys.stdin); print(h['facts_sha'] == hashlib.sha256(open('facts.json', 'rb').read()).hexdigest())"
```

Expected: `deployed <sha>`, then `True`.

- [ ] **Step 6: Whole-branch review.** Run superpowers:requesting-code-review over `main..m5`, with this plan and the
  spec as the brief.
  - Fix findings through TDD in the owning task's files.
  - Re-run Step 1, and push again (Step 5) if served code changed.
  - Commit the fixes as `m5: fixes from the final review`.

- [ ] **Step 7: Carry-overs and merge.**
  1. Save memory `m5-carryovers-for-m6.md`:
     - measured cost per answer and answers per month;
     - server RSS and p95;
     - calibration findings;
     - anything left open for M6 (licence choice, the copy checker, `dtd site --strict`, the uptime monitor);
     - updating `deploy/hosting.json` from the first Hetzner invoice (spec: the hosting cost of record), then
       `dtd facts`.
  2. Hand the branch to superpowers:finishing-a-development-branch:
     - merge `--no-ff` into `main` as `Merge m5: live service, cost cap, site, deploy; M5 report final`;
     - push `main` to the private remote;
     - confirm CI is green, including the "Facts check" step.

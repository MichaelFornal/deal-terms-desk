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
    except (urllib.error.URLError, OSError) as e:  # refused, DNS, timeout, reset: a failed check, not a traceback
        return 0, {}, json.dumps({"fetch_error": str(e)}).encode("utf-8")


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

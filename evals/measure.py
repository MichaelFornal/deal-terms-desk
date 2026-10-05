import json
import time
import urllib.error
import urllib.parse
import urllib.request

from evals.run_rung import _percentile
from service.cache import normalise_question

SEARCH_K = 10
MAX_WAITS = 5
MAX_SLEEP_S = 30.0  # one wait never exceeds this, whatever Retry-After asks for
DEFAULT_SLEEP_S = 1.0  # Retry-After missing or not a number


def _retry_after(value) -> float:
    """Seconds to wait: the header if it is a number, capped; a small default otherwise."""
    try:
        secs = float(value)
    except (TypeError, ValueError):
        return DEFAULT_SLEEP_S
    if secs != secs or secs < 0:  # NaN or negative
        return DEFAULT_SLEEP_S
    return min(secs, MAX_SLEEP_S)


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
            time.sleep(_retry_after(e.headers.get("Retry-After")))
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


def _reason(e: Exception) -> str:
    return f"{type(e).__name__}: {e}"[:120]


def measure(base_url: str, questions: list[str], fresh: list[str], reference: dict | None = None,
            cached=()) -> dict:
    """Search latency over `questions`, answer latency for `cached` (example questions, served from the cache) and
    `fresh` (new, billed questions), peak memory, and, given `reference`, how often the server's top passages
    match this machine's. Server-side ms come from each payload; end-to-end ms include the network.
    An answer is timed under what served it (`served_from`: live -> ask_fresh, cache -> ask_cached). One served
    other than meant is counted in `errors` with its reason and in `misrouted`; one with no answer (busy, …) is
    counted in `errors` and timed nowhere.
    A request that fails (HTTP error, timeout, bad body, missing field) is counted in `errors` with its route and
    reason, its sample is skipped and the run goes on, so one bad request never loses the others."""
    base = base_url.rstrip("/")
    errors: list[dict] = []
    e2e, server, same = [], [], 0
    for q in questions:
        try:
            got, ms = _call(f"{base}/api/search?" + urllib.parse.urlencode({"q": q}))
            server_ms, ids = float(got["ms"]), [h["passage_id"] for h in got["hits"]]
        except Exception as e:  # noqa: BLE001 - every failure is a counted sample, not a crash
            errors.append({"route": "search", "reason": _reason(e)})
            continue
        e2e.append(ms)
        server.append(server_ms)
        if reference is not None and ids == reference.get(q):
            same += 1

    # Answer samples are timed by what served them, not by what was meant: a rerun finds the "fresh" questions in
    # the cache, and an example missing from the cache is answered live (and billed).
    timed = {"live": ([], []), "cache": ([], [])}  # served_from -> (e2e ms, server ms)
    states = {"ask_fresh": {}, "ask_cached": {}}  # every reply a route's questions got, whatever served it
    misrouted = {"fresh_served_from_cache": 0, "cached_answered_live": 0}
    for route, qs, meant, what in (("ask_cached", cached, "cache", "cached example"),
                                   ("ask_fresh", fresh, "live", "fresh question")):
        for q in qs:
            try:
                got, ms = _call(f"{base}/api/ask", {"question": q, "deal": None})
                server_ms, state, served = float(got["ms"]), got["state"], got["served_from"]
            except Exception as e:  # noqa: BLE001
                errors.append({"route": route, "reason": _reason(e)})
                continue
            states[route][state] = states[route].get(state, 0) + 1
            if not isinstance(served, str) or served not in timed:  # which_deal, busy, …: no answer to time
                errors.append({"route": route, "reason": f"{what} got no answer (state {state})"})
                continue
            timed[served][0].append(ms)
            timed[served][1].append(server_ms)
            if served != meant:
                if served == "cache":
                    misrouted["fresh_served_from_cache"] += 1
                    errors.append({"route": route, "reason": "fresh question was served from cache"})
                else:
                    misrouted["cached_answered_live"] += 1
                    errors.append({"route": route, "reason": "cached example was answered live (billed)"})

    def asks(route, served) -> dict:
        a_e2e, a_server = timed[served]
        return {"e2e": _dist(a_e2e), "server": _dist(a_server), "states": dict(sorted(states[route].items()))}

    out = {"base": base, "search": {"e2e": _dist(e2e), "server": _dist(server)},
           "ask_cached": asks("ask_cached", "cache"), "ask_fresh": asks("ask_fresh", "live"), "misrouted": misrouted}
    try:
        health, _ = _call(f"{base}/api/health")
        if not isinstance(health, dict):
            raise ValueError("health is not an object")
    except Exception as e:  # noqa: BLE001
        errors.append({"route": "health", "reason": _reason(e)})
        health = {}
    out |= {"rss_mb": health.get("rss_mb"), "git_sha": health.get("git_sha"), "bundle_sha": health.get("bundle_sha")}
    out["errors"], out["error_log"] = len(errors), errors[:20]
    if reference is not None:
        n = len(server)
        out["embed_parity"] = {"n": n, "same": same, "rate": round(same / n, 4) if n else None}
    return out

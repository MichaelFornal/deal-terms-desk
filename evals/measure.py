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

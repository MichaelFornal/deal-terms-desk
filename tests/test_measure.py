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
        fresh = "fresh" in body["question"]
        self._send(200, {"state": "answered" if fresh else "budget_cached", "served_from": "live" if fresh else "cache",
                         "ms": 9.0})

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


class Flaky(BaseHTTPRequestHandler):
    """Search: 'boom' -> 500, 'junk' -> not JSON, 'nomsp' -> no ms. Ask: 'boom' -> 500. Health lacks rss_mb."""
    retry = "abc"

    def _raw(self, code, body: bytes, headers=()):
        self.send_response(code)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/health":
            return self._raw(200, b'{"git_sha": "g", "bundle_sha": "b"}')
        q = parse_qs(u.query)["q"][0]
        if q == "limited":
            return self._raw(429, b"{}", [("Retry-After", Flaky.retry)])
        if q == "boom":
            return self._raw(500, b"{}")
        if q == "junk":
            return self._raw(200, b"<html>")
        if q == "nomsp":
            return self._raw(200, b'{"hits": []}')
        self._raw(200, b'{"hits": [{"passage_id": 1}], "ms": 4.0}')

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if body["question"] == "boom":
            return self._raw(500, b"{}")
        served = "cache" if body["question"] == "c" else "live"
        self._raw(200, json.dumps({"state": "answered", "served_from": served, "ms": 8.0}).encode())

    def log_message(self, *args):
        pass


@pytest.fixture
def flaky():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Flaky)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_failed_requests_are_counted_and_the_other_samples_survive(flaky):
    got = measure(flaky, ["ok", "boom", "junk", "nomsp", "ok2"], ["boom", "fresh"], {}, cached=["c"])
    assert got["search"]["server"]["n"] == 2 and got["search"]["e2e"]["n"] == 2
    assert got["ask_fresh"]["server"]["n"] == 1 and got["ask_cached"]["server"]["n"] == 1
    assert got["rss_mb"] is None and got["bundle_sha"] == "b"
    assert got["errors"] == 4 and {e["route"] for e in got["error_log"]} == {"search", "ask_fresh"}


def test_nothing_succeeding_gives_none_percentiles(flaky):
    got = measure(flaky, ["boom"], [], None)
    assert got["search"]["server"] == {"n": 0, "p50": None, "p95": None} and got["errors"] == 1


def test_retry_after_is_capped_parsed_defensively_and_given_up_on(flaky, monkeypatch):
    from evals import measure as m
    slept = []
    monkeypatch.setattr(m.time, "sleep", slept.append)
    Flaky.retry = "3600"
    got = measure(flaky, ["limited"], [], None)
    assert slept == [m.MAX_SLEEP_S] * (m.MAX_WAITS + 1) and got["errors"] == 1
    assert "still rate-limited" in got["error_log"][0]["reason"]
    slept.clear()
    Flaky.retry = "soon"
    measure(flaky, ["limited"], [], None)
    assert slept == [m.DEFAULT_SLEEP_S] * (m.MAX_WAITS + 1)
    Flaky.retry = "abc"


class Routed(BaseHTTPRequestHandler):
    """Ask only. What serves each question is the server's business, whatever the caller meant to measure."""
    replies = {"new question": ("answered", "live", 900.0), "already cached": ("answered", "cache", 9.0),
               "an example": ("answered", "cache", 8.0), "example missing from the cache": ("not_stated", "live", 950.0),
               "too busy": ("busy", None, 1.0), "no served_from": ("answered", "absent", 5.0)}

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"rss_mb": 1.0})

    def do_POST(self):
        q = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["question"]
        state, served, ms = Routed.replies[q]
        self._send({"state": state, "ms": ms} | ({} if served == "absent" else {"served_from": served}))

    def log_message(self, *args):
        pass


@pytest.fixture
def routed():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Routed)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_ask_samples_are_timed_by_what_served_them(routed):
    """A rerun finds the "fresh" questions cached, and an example missing from the cache is billed: neither may be
    reported as the other. Each such sample is counted with its reason."""
    got = measure(routed, [], ["new question", "already cached", "too busy", "no served_from"], None,
                  cached=["an example", "example missing from the cache"])
    fresh, cached = got["ask_fresh"]["server"], got["ask_cached"]["server"]
    assert fresh["n"] == 2 and fresh["p50"] >= 900.0  # the new question and the example answered live
    assert cached["n"] == 2 and cached["p95"] <= 9.0  # the example and the fresh question the cache served
    assert got["ask_fresh"]["e2e"]["n"] == 2 and got["ask_cached"]["e2e"]["n"] == 2
    log = got["error_log"]
    assert {"route": "ask_fresh", "reason": "fresh question was served from cache"} in log
    assert {"route": "ask_cached", "reason": "cached example was answered live (billed)"} in log
    assert {"route": "ask_fresh", "reason": "fresh question got no answer (state busy)"} in log
    assert any(e["route"] == "ask_fresh" and "served_from" in e["reason"] for e in log)  # a missing field
    assert got["errors"] == 4 and got["misrouted"] == {"fresh_served_from_cache": 1, "cached_answered_live": 1}
    # every reply a route's questions got, whatever served it
    assert got["ask_fresh"]["states"] == {"answered": 2, "busy": 1}
    assert got["ask_cached"]["states"] == {"answered": 1, "not_stated": 1}

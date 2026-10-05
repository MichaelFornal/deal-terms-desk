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

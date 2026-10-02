import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from pipeline.sec_client import COOLDOWN_S, MIN_INTERVAL, Blocked, SecClient, _NoRedirect

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
        if isinstance(out, Exception):
            raise out
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
    assert clock.slept == [MIN_INTERVAL, MIN_INTERVAL]
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


def test_a_redirect_is_not_followed_and_is_an_error(tmp_path):
    net = Net({A: 301})
    c, _ = client(tmp_path, net)
    with pytest.raises(RuntimeError, match="301"):
        c.get(A)
    assert len(net.seen) == 1 and c.ledger.get(A) is None
    req = urllib.request.Request(A)
    assert _NoRedirect().redirect_request(req, None, 301, "x", {}, "https://evil.example/") is None


def test_plain_http_is_refused(tmp_path):
    c, _ = client(tmp_path, Net({}))
    with pytest.raises(ValueError):
        c.get("http://www.sec.gov/x")


def test_a_second_client_waits_for_the_previous_request(tmp_path):
    clock = Clock()
    c, _ = client(tmp_path, Net({A: b"a", B: b"b"}), clock)
    c.get(A)
    c.close()
    clock.slept.clear()
    c2, _ = client(tmp_path, Net({B: b"b"}), clock)
    c2.get(B)
    assert clock.slept == [MIN_INTERVAL]


def test_a_forked_process_is_refused(tmp_path, monkeypatch):
    c, _ = client(tmp_path, Net({A: b"a"}))
    monkeypatch.setattr(os, "getpid", lambda: -1)
    with pytest.raises(RuntimeError, match="fork"):
        c.get(A)


def test_threads_never_overlap_on_the_network(tmp_path):
    state = {"now": 0, "max": 0}

    def opener(req, timeout=None):
        state["now"] += 1
        state["max"] = max(state["max"], state["now"])
        time.sleep(0.05)
        state["now"] -= 1
        return Resp(b"x")

    clock = Clock()
    c = SecClient(tmp_path / "sec", CONTACT, opener=opener, clock=clock.now, wall=clock.now, sleep=clock.sleep)
    urls = [f"https://www.sec.gov/{i}" for i in range(4)]
    threads = [threading.Thread(target=c.get, args=(u,)) for u in urls]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert state["max"] == 1 and c.requests == 4


def test_the_guard_blocks_name_resolution_and_other_openers():
    with pytest.raises(AssertionError, match="sec.gov"):
        socket.getaddrinfo("www.sec.gov.", 443)
    with pytest.raises(AssertionError, match="sec.gov"):
        urllib.request.build_opener().open("https://efts.sec.gov/x")


def test_spacing_holds_after_a_404_and_after_an_error(tmp_path):
    net = Net({A: 404, B: urllib.error.URLError("boom"), "https://www.sec.gov/c": b"c"})
    c, clock = client(tmp_path, net)
    assert c.get(A) is None
    clock.slept.clear()
    with pytest.raises(urllib.error.URLError):
        c.get(B)
    assert clock.slept == [MIN_INTERVAL]
    clock.slept.clear()
    assert c.get("https://www.sec.gov/c") == b"c"
    assert clock.slept == [MIN_INTERVAL]


def test_a_malformed_block_marker_fails_closed(tmp_path):
    net = Net({A: b"a"})
    (tmp_path / "sec").mkdir()
    (tmp_path / "sec" / "blocked.json").write_text("{not json")
    c, _ = client(tmp_path, net)
    with pytest.raises(Blocked):
        c.get(A)
    assert net.seen == []


def test_close_is_idempotent_and_a_context_manager(tmp_path):
    with client(tmp_path, Net({}))[0] as c:
        pass
    c.close()
    client(tmp_path, Net({}))[0].close()

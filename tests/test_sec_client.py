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

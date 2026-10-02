import fcntl
import gzip
import hashlib
import json
import os
import threading
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect would be an extra, unspaced request and could leave the allowed hosts: surface it instead."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _atomic_write(path: Path, text: str) -> None:
    part = path.with_name(path.name + ".part")
    part.write_text(text, encoding="utf-8")
    os.replace(part, path)


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
        self._opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open
        self._clock, self._wall, self._sleep = clock, wall, sleep
        self._last: float | None = None
        self._last_file = self.root / "last_request"
        try:
            self._last_wall = float(self._last_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self._last_wall = self._wall()
        self._mutex = threading.Lock()
        self._pid = os.getpid()
        self._closed = False
        self.requests = 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if os.getpid() == self._pid:
            fcntl.flock(self._lock, fcntl.LOCK_UN)
        self._lock.close()  # in a forked child: only this copy of the fd; the parent keeps its lock

    def __enter__(self) -> "SecClient":
        return self

    def __exit__(self, *exc) -> bool:
        self.close()
        return False

    def _cached(self, url: str) -> Path:
        return self.root / "cache" / hashlib.sha1(url.encode("utf-8")).hexdigest()

    def _refuse_if_blocked(self) -> None:
        marker = self.root / "blocked.json"
        if marker.exists():
            try:
                at = float(json.loads(marker.read_text(encoding="utf-8"))["at"])
            except (OSError, ValueError, KeyError, TypeError) as e:
                raise Blocked("blocked.json is unreadable; failing closed until it is fixed or removed") from e
            age = self._wall() - at
            if age < COOLDOWN_S:
                raise Blocked(f"sec.gov refused a request {int(age)} s ago; waiting out the {COOLDOWN_S} s cooldown")

    def get(self, url: str) -> bytes | None:
        parts = urlparse(url)
        if parts.scheme != "https" or parts.hostname not in HOSTS:
            raise ValueError(f"host not allowed (https on sec.gov hosts only): {url}")
        if os.getpid() != self._pid:
            raise RuntimeError("SecClient used from a forked process; M0 runs as one process")
        with self._mutex:
            if self._closed:
                raise RuntimeError("SecClient is closed")
            rec = self.ledger.get(url)
            if rec and rec["status"] == "missing":
                return None
            path = self._cached(url)
            if rec and path.exists():
                return path.read_bytes()
            self._refuse_if_blocked()
            wait = self._last_wall + MIN_INTERVAL - self._wall()
            wait = min(wait, MIN_INTERVAL)
            if self._last is not None:
                wait = max(wait, self._last + MIN_INTERVAL - self._clock())
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            self._last_wall = self._wall()
            _atomic_write(self._last_file, repr(self._last_wall))
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": self._ua, "Accept-Encoding": "gzip"})
            try:
                with self._opener(req, timeout=60) as resp:
                    body = resp.read()
                    if resp.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
            except urllib.error.HTTPError as e:
                if e.code in STOP_CODES:
                    _atomic_write(self.root / "blocked.json",
                                  json.dumps({"at": self._wall(), "status": e.code, "url": url}))
                    raise Blocked(f"sec.gov answered {e.code} for {url}; stopped, no retry") from e
                if e.code == 404:
                    self.ledger.put({"url": url, "status": "missing"})
                    return None
                if 300 <= e.code < 400:
                    raise RuntimeError(f"sec.gov answered a redirect ({e.code}) for {url}; not followed") from e
                raise
            part = path.with_name(path.name + ".part")
            part.write_bytes(body)
            os.replace(part, path)
            self.ledger.put({"url": url, "status": "ok", "bytes": len(body),
                             "sha256": hashlib.sha256(body).hexdigest()})
            return body

    def get_json(self, url: str) -> dict | None:
        body = self.get(url)
        return None if body is None else json.loads(body)

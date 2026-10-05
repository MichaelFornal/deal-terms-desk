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

import re
import sqlite3
from collections import defaultdict
from dataclasses import dataclass

WORD = re.compile(r"[a-z0-9]+")


def tokens(s: str) -> tuple[str, ...]:
    return tuple(WORD.findall(s.lower().replace("&", " and ")))


@dataclass(frozen=True)
class Scope:
    contract_id: str | None
    alias: str | None
    candidates: tuple[str, ...]


class Resolver:
    def __init__(self, conn: sqlite3.Connection):
        self.by_kind: dict[str, dict[tuple[str, ...], set[str]]] = {"target": defaultdict(set),
                                                                     "parent": defaultdict(set)}
        for alias, cid, kind in conn.execute("SELECT alias, contract_id, kind FROM aliases"):
            t = tokens(alias)
            if t:
                self.by_kind[kind][t].add(cid)

    @staticmethod
    def _occurs(alias: tuple[str, ...], q: tuple[str, ...]) -> bool:
        n = len(alias)
        return any(q[i:i + n] == alias for i in range(len(q) - n + 1))

    def resolve(self, query: str) -> Scope:
        q = tokens(query)
        for kind in ("target", "parent"):
            hits = [a for a in self.by_kind[kind] if self._occurs(a, q)]
            if not hits:
                continue
            longest = max(len(a) for a in hits)
            top = [a for a in hits if len(a) == longest]
            cids = sorted(set().union(*(self.by_kind[kind][a] for a in top)))
            alias = " ".join(sorted(top)[0])
            return Scope(cids[0], alias, tuple(cids)) if len(cids) == 1 else Scope(None, alias, tuple(cids))
        return Scope(None, None, ())

import json
import time
from dataclasses import dataclass, replace
from pathlib import Path

from retrieval import bm25
from retrieval.dense import search_dense
from retrieval.hybrid import rrf
from retrieval.lexicon import rewrite
from retrieval.result import CONTEXT_K, Retrieved

RUNGS = ("R1", "R2", "R3", "R4", "R5", "R6")
SETTINGS_PATH = Path(__file__).with_name("settings.json")


@dataclass(frozen=True)
class Settings:
    depth: int = 50
    rrf_k0: int = 60
    reranker: str = "BAAI/bge-reranker-base"
    rerank_depth: int = 20


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    path = Path(path)
    if not path.exists():
        return Settings()
    return Settings(**json.loads(path.read_text(encoding="utf-8"))["settings"])


class Ladder:
    def __init__(self, conn, texts: dict[str, str], embedder=None, reranker=None, lexicon: dict | None = None,
                 settings: Settings = Settings(), amendment_texts: dict[str, str] | None = None):
        self.conn = conn
        self.texts = texts
        self.embedder = embedder
        self.reranker = reranker
        self.lexicon = lexicon
        self.settings = settings
        self.amendment_texts = amendment_texts or {}
        self.has_amendments = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'superseded'").fetchone() is not None

    def _passage(self, h) -> str:
        return self.texts[h.contract_id][h.start:h.end]

    def _amendments(self, h) -> list[tuple]:
        if not self.has_amendments:
            return []
        return self.conn.execute(
            "SELECT amendment_id, amendment_no, file_date, amend_start, amend_end FROM superseded"
            " WHERE passage_id = ? ORDER BY file_date, amendment_id", (h.passage_id,)).fetchall()

    def _shown(self, h, with_defs: bool) -> str:
        text = self._passage(h)
        if with_defs:
            defs = [self.texts[h.contract_id][s:e] for s, e in self.conn.execute(
                "SELECT def_start, def_end FROM passage_defs WHERE passage_id = ? ORDER BY rank", (h.passage_id,))]
            text = "\n\n".join([text] + defs)
        for aid, no, filed, a0, a1 in self._amendments(h):
            text += f"\n\n[Amended by Amendment No. {no}, filed {filed}]\n" + self.amendment_texts[aid][a0:a1]
        return text

    def _dense(self, q: str, contract_id: str | None, k: int):
        if not bm25.TOKEN.search(q):
            return []
        return search_dense(self.conn, self.embedder.embed_query(q), contract_id, k)

    def run(self, rung: str, query: str, contract_id: str | None = None, k: int = 10,
            rewritten: str | None = None) -> Retrieved:
        if rung not in RUNGS:
            raise ValueError(f"unknown rung {rung!r}; expected one of {RUNGS}")
        n = RUNGS.index(rung) + 1
        if n >= 5 and rewritten is None and self.lexicon is None:
            raise ValueError("R5 and R6 need the lexicon; run `dtd lexicon` first")
        t0 = time.perf_counter()
        adjust = 0.0
        q = query if n < 5 else (rewritten if rewritten is not None else rewrite(query, self.lexicon))
        table = "passages_x_fts" if n == 6 else "passages_fts"
        if n == 1:
            hits = bm25.search(self.conn, q, contract_id, k)
        elif n == 2:
            hits = self._dense(q, contract_id, k)
        else:
            depth = max(k, self.settings.depth)
            legs = [bm25.search(self.conn, q, contract_id, depth, table=table), self._dense(q, contract_id, depth)]
            fused = rrf(legs, self.settings.rrf_k0, 2 * depth)
            if n == 3:
                hits = fused[:k]
            else:
                head = fused[:self.settings.rerank_depth]
                t1 = time.perf_counter()
                scores, compute_ms = self.reranker.score(query, [self._passage(h) for h in head])
                adjust += compute_ms - (time.perf_counter() - t1) * 1000.0
                order = sorted(range(len(head)), key=lambda i: (-scores[i], head[i].passage_id))
                hits = ([replace(head[i], score=scores[i]) for i in order] + fused[len(head):])[:k]
        ms = (time.perf_counter() - t0) * 1000.0 + adjust
        amended = tuple(dict.fromkeys(a[0] for h in hits[:CONTEXT_K] for a in self._amendments(h)))
        return Retrieved(hits, ms, [self._shown(h, n == 6) for h in hits[:CONTEXT_K]], amended)

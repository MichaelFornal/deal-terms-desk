import hashlib
import resource
import sqlite3
import sys
import threading
import time

from answer.answerer import Answerer, ParseError, Prepared
from answer.api_runner import RunnerError
from answer.prompt import TEMPLATE_SHA
from retrieval.live import bundle_meta, links_for
from service.cache import normalise_question
from service.prices import load_prices, worst_case_usd

STATES = ("answered", "not_stated", "unfiled_schedule", "which_deal", "budget_cached", "budget_reached", "busy",
          "error")
# A typical prompt is about 15k characters: five passages with their definitions (measured on deals.db in M5
# planning). The budget reads "reached" once it cannot cover one such call at worst case.
TYPICAL_PROMPT_CHARS = 15_000
SEARCH_K = 10
# Failures with no usage after which the request may still have been billed: booked at worst case. Every other
# failure without usage was rejected unbilled and is released.
MAYBE_BILLED = ("timeout", "connection")
VOLATILE = ("served_from", "budget", "tokens", "ms")  # never stored in the cache


def _sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _rss_mb() -> float:
    """Peak resident memory of this process (ru_maxrss is KiB on Linux, bytes on macOS)."""
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(peak / (1024 * 1024 if sys.platform == "darwin" else 1024), 1)


class Desk:
    """The live service without HTTP: R7n retrieval, the M4 answerer, the spend ledger, the cache and the limits.
    One lock guards the bundle connection (retrieval); the model call runs outside it."""

    def __init__(self, ladder, runner, config, budget, cache, fresh, slots):
        self.ladder, self.runner, self.config = ladder, runner, config
        self.budget, self.cache, self.fresh, self.slots = budget, cache, fresh, slots
        self.answerer = Answerer(ladder, runner, config.model)
        # The cache's model part carries the answer settings too: an answer made with another thinking budget or
        # output cap is never served. The prompt hash already covers the question, passages and template.
        self._cache_model = f"{config.model}|tb{config.thinking_budget}|mt{config.max_tokens}"
        self._lock = threading.Lock()
        self._min_call = worst_case_usd(load_prices(config.prices_path), TYPICAL_PROMPT_CHARS, config.max_tokens)
        rows = ladder.conn.execute("SELECT contract_id, source, target, parent, signed FROM deals").fetchall()
        self._deals = {cid: {"id": cid, "source": src, "target": t, "parent": p, "signed": s}
                       for cid, src, t, p, s in rows}
        self._links = {cid: links_for(ladder.conn, cid) for cid in self._deals}
        self._bundle_sha = _sha256(config.bundle)
        self._facts_sha = _sha256(config.facts_path)
        self._meta = bundle_meta(ladder.conn)

    def _check_deal(self, deal: str | None) -> None:
        if deal is not None and deal not in self._deals:
            raise ValueError(f"unknown deal {deal!r}")

    def _deal(self, cid: str | None) -> dict | None:
        d = self._deals.get(cid) if cid else None
        return None if d is None else dict(d, link=self._links[cid]["filing"])

    def _name(self, cid: str) -> str:
        d = self._deals.get(cid) or {}
        parts = [x for x in (d.get("target"), d.get("parent")) if x]
        return " – ".join(parts) if parts else cid

    def _claims(self, answer) -> list[dict]:
        out = []
        for c in answer.claims:
            links = self._links.get(c.contract_id, {"filing": None, "amendments": {}})
            amended = c.part == "amendment"
            out.append({"text": c.text, "quote": c.quote, "section_path": c.section_path,
                        "agreement": self._name(c.contract_id), "link": links["filing"],
                        "amendment_no": c.amendment_no if amended else None,
                        "amendment_link": links["amendments"].get(c.amendment_no) if amended else None})
        return out

    def _budget(self) -> str:
        return self.budget.state(self._min_call)

    def _payload(self, state: str, question: str, answer=None, served_from=None, tokens=None) -> dict:
        candidates = answer.candidates if answer is not None and state == "which_deal" else ()
        return {"state": state, "question": question,
                "deal": self._deal(answer.contract_id) if answer is not None else None,
                "claims": self._claims(answer) if answer is not None else [],
                "amended": bool(answer.amended) if answer is not None else False,
                "candidates": [{"id": c, "name": self._name(c)} for c in candidates],
                "served_from": served_from, "budget": self._budget(), "tokens": tokens}

    def ask(self, question: str, deal: str | None = None) -> dict:
        t0 = time.perf_counter()
        self._check_deal(deal)
        q = normalise_question(question)
        with self._lock:
            prep = self.answerer.prepare(q, deal)
        out = self._answer(q, prep)
        out["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
        return out

    def _answer(self, q: str, prep) -> dict:
        if not isinstance(prep, Prepared):  # which_deal, or nothing retrieved: never a model call
            return self._payload(prep.state, q, prep)
        hit = self.cache.get(self._cache_model, prep.prompt_sha)
        if hit is not None:
            budget = self._budget()
            state = "budget_cached" if budget == "reached" else hit["state"]
            return dict(hit, state=state, cached_state=hit["state"], served_from="cache", budget=budget, tokens=None)
        if not self.slots.try_acquire():
            return self._payload("busy", q)
        try:
            if self.fresh.allow("*"):
                return self._payload("busy", q)
            try:
                rid = self.budget.reserve(len(prep.prompt), self.config.max_tokens)
            except sqlite3.OperationalError:  # the ledger is locked: nothing was reserved, so nothing to settle
                return self._payload("busy", q)
            if rid is None:
                return self._payload("budget_reached", q)
            t1 = time.perf_counter()
            try:
                reply = self.runner(prep.prompt, self.config.model)
            except RunnerError as e:
                try:
                    if e.usage:
                        self.budget.settle(rid, e.usage)
                    elif e.kind in MAYBE_BILLED:
                        self.budget.settle(rid, None)
                    else:
                        self.budget.release(rid)
                except sqlite3.OperationalError:  # ledger locked: the reservation stays open, counted at worst case
                    pass
                return self._payload("budget_reached" if e.kind == "billing" else "error", q)
            try:  # missing or empty usage settles at worst case (fail closed)
                self.budget.settle(rid, reply.get("usage") or None)
            except sqlite3.OperationalError:  # ledger locked: the reservation stays open, counted at worst case
                pass
            try:
                answer = self.answerer.finish(prep, reply, (time.perf_counter() - t1) * 1000.0 + prep.retrieval_ms)
            except ParseError:
                return self._payload("error", q)
            out = self._payload(answer.state, q, answer, "live", {"in": answer.tokens_in, "out": answer.tokens_out})
            self.cache.put(self._cache_model, prep.prompt_sha, {k: v for k, v in out.items() if k not in VOLATILE})
            return out
        finally:
            self.slots.release()

    def search(self, q: str, deal: str | None = None) -> dict:
        self._check_deal(deal)
        q = normalise_question(q)
        with self._lock:
            got = self.ladder.run("R7n", q, deal, SEARCH_K)
            hits = []
            for h in got.hits:
                path = self.ladder.conn.execute("SELECT section_path FROM passages WHERE passage_id = ?",
                                                (h.passage_id,)).fetchone()[0]
                terms = [t for (t,) in self.ladder.conn.execute(
                    "SELECT term FROM passage_defs WHERE passage_id = ? ORDER BY rank", (h.passage_id,))]
                hits.append({"passage_id": h.passage_id, "deal": self._deal(h.contract_id), "section_path": path,
                             "text": self.ladder.texts[h.contract_id][h.start:h.end], "definitions": terms,
                             "link": self._links[h.contract_id]["filing"], "score": h.score,
                             "stages": got.stages.get(h.passage_id, {"bm25": None, "dense": None})})
        scope = got.scope
        cands = scope.candidates if scope is not None else ()
        return {"query": q, "scope": {"deal": scope.contract_id if scope is not None else deal,
                                      "candidates": [{"id": c, "name": self._name(c)} for c in cands]},
                "hits": hits, "ms": round(got.ms, 1)}

    def deals(self) -> list[dict]:
        return sorted((self._deal(cid) for cid in self._deals), key=lambda d: ((d["target"] or d["id"]).casefold(), d["id"]))

    def health(self) -> dict:
        return {"ok": True, "git_sha": self.config.git_sha, "bundle_sha": self._bundle_sha,
                "facts_sha": self._facts_sha, "template_sha": TEMPLATE_SHA, "model": self.config.model,
                "thinking_budget": self.config.thinking_budget, "max_tokens": self.config.max_tokens,
                "budget": self._budget(), "rss_mb": _rss_mb(), "bundle_meta": self._meta}

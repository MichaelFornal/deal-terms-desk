import hashlib
import json
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path

from answer.answerer import Answer, ParseError
from answer.prompt import TEMPLATE_SHA
from pipeline.ledger import Ledger

MAX_CONSECUTIVE = 20  # this many failures in a row stop the run at once (a late outage)
MIN_FOR_RATE = 20  # the error-rate stop needs this many finished calls before it can fire


def _item_sha(item) -> str:
    return hashlib.sha1(json.dumps([item.question, item.contract_id, list(item.choices)]).encode()).hexdigest()[:8]


def _key(item, model: str) -> str:
    """Item id, model, template and the item's content, so a changed question is a new call, not a stale hit."""
    return f"{item.item_id}|{model}|{TEMPLATE_SHA}|{_item_sha(item)}"


def load_answers(ledger_path: Path, model: str, items) -> dict[str, dict]:
    """The record for each current item, by item id: exactly the ledger key `_key(item, model)`. A record made for a
    different question, choices or template (or a legacy record without the item hash) is absent, so a stale answer
    is never read; an item with no match is simply missing."""
    if not Path(ledger_path).exists():
        return {}
    led = Ledger(ledger_path, key="key")
    out = {}
    for item in items:
        rec = led.get(_key(item, model))
        if rec is not None:
            out[item.item_id] = rec
    return out


def _is_done(rec: dict | None) -> bool:
    """A runner failure is transient, so a rerun retries it; a parse failure is permanent."""
    return rec is not None and not (rec.get("error") or "").startswith("runner:")


def answer_all(items, answerer, ledger_path: Path, workers: int = 4, max_new: int | None = None,
               max_error_rate: float = 0.05) -> dict:
    """Answer every item once per (model, template). Retrieval runs here; only the model call runs in the pool.
    A rerun skips ledgered keys (except runner failures); a kill loses at most the calls in flight."""
    led, lock, model = Ledger(ledger_path, key="key"), threading.Lock(), answerer.model
    new_calls = 0
    st = {"errors": 0, "finished": 0, "consecutive": 0}

    def put(item, answer: Answer | None, error: str | None, result: str | None = None):
        with lock:
            led.put({"key": _key(item, model), "item_id": item.item_id, "item_sha": _item_sha(item), "model": model,
                     "template_sha": TEMPLATE_SHA, "answer": asdict(answer) if answer else None, "error": error,
                     "result": result})

    def call(prep):
        t0 = time.perf_counter()
        reply = answerer.runner(prep.prompt, model)
        return reply, (time.perf_counter() - t0) * 1000.0

    def drain(pending):
        ready, _ = wait(list(pending), return_when=FIRST_COMPLETED)
        for fut in ready:
            _record(pending.pop(fut), fut, answerer, put, st)

    def stop_if_bad():
        if _bad(st, max_error_rate):
            raise RuntimeError(f"error rate {st['errors']}/{st['finished']} (or {st['consecutive']} in a row) is "
                               f"over the limit; stopping. Records so far are ledgered; fix the cause and rerun")

    todo = [i for i in items if not _is_done(led.get(_key(i, model)))]
    pending: dict = {}
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        for item in todo:
            if max_new is not None and new_calls >= max_new:
                break
            prep = answerer.prepare(item.question, item.contract_id, item.choices)
            if isinstance(prep, Answer):
                put(item, prep, None)
                continue
            new_calls += 1
            pending[pool.submit(call, prep)] = (item, prep)
            while len(pending) >= workers * 2:
                drain(pending)
                stop_if_bad()
        while pending:
            drain(pending)
            stop_if_bad()
    except BaseException:
        # Cancel calls that have not started, let the running ones finish, and ledger what they return.
        for fut in list(pending):
            if fut.cancel():
                del pending[fut]
        pool.shutdown(wait=True)
        for fut in list(pending):
            _record(pending.pop(fut), fut, answerer, put, st)
        raise
    finally:
        pool.shutdown(wait=True)
    done = sum(1 for i in items if _is_done(led.get(_key(i, model))))
    return {"items": len(items), "done": done, "new_calls": new_calls, "errors": st["errors"]}


def _record(entry, fut, answerer, put, st):
    item, prep = entry
    st["finished"] += 1
    try:
        reply, ms = fut.result()
    except BaseException as e:
        if not isinstance(e, RuntimeError):
            raise
        st["errors"] += 1
        st["consecutive"] += 1
        put(item, None, f"runner: {str(e)[:300]}")
        return
    text = reply.get("result") if isinstance(reply, dict) else None
    try:
        put(item, answerer.finish(prep, reply, ms + prep.retrieval_ms), None, text)
        st["consecutive"] = 0
    except ParseError as e:
        st["errors"] += 1
        st["consecutive"] += 1
        put(item, None, str(e)[:300], text)


def _bad(st, max_error_rate) -> bool:
    if st["consecutive"] >= MAX_CONSECUTIVE:
        return True
    return st["finished"] >= MIN_FOR_RATE and st["errors"] / st["finished"] > max_error_rate

import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from pathlib import Path

from answer.answerer import Answer, ParseError
from answer.prompt import TEMPLATE_SHA
from pipeline.ledger import Ledger

MIN_FOR_RATE = 20  # the error-rate stop needs this many finished calls before it can fire


def _key(item_id: str, model: str) -> str:
    return f"{item_id}|{model}|{TEMPLATE_SHA}"


def load_answers(ledger_path: Path, model: str) -> dict[str, dict]:
    """Current-template records for one model, by item id."""
    if not Path(ledger_path).exists():
        return {}
    led = Ledger(ledger_path, key="key")
    return {r["item_id"]: r for r in led._recs.values() if r["model"] == model and r["template_sha"] == TEMPLATE_SHA}


def answer_all(items, answerer, ledger_path: Path, workers: int = 4, max_new: int | None = None,
               max_error_rate: float = 0.05) -> dict:
    """Answer every item once per (model, template). Retrieval runs here; only the model call runs in the pool.
    A rerun skips ledgered keys; a kill loses at most the calls in flight."""
    led, lock, model = Ledger(ledger_path, key="key"), threading.Lock(), answerer.model
    new_calls = errors = finished = 0

    def put(item, answer: Answer | None, error: str | None):
        with lock:
            led.put({"key": _key(item.item_id, model), "item_id": item.item_id, "model": model,
                     "template_sha": TEMPLATE_SHA, "answer": asdict(answer) if answer else None, "error": error})

    def call(prep):
        t0 = time.perf_counter()
        reply = answerer.runner(prep.prompt, model)
        return reply, (time.perf_counter() - t0) * 1000.0

    todo = [i for i in items if led.get(_key(i.item_id, model)) is None]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = {}
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
                errors, finished = _drain(pending, answerer, put, errors, finished)
                _check_rate(errors, finished, max_error_rate)
        while pending:
            errors, finished = _drain(pending, answerer, put, errors, finished)
            _check_rate(errors, finished, max_error_rate)
    done = sum(1 for i in items if led.get(_key(i.item_id, model)) is not None)
    return {"items": len(items), "done": done, "new_calls": new_calls, "errors": errors}


def _drain(pending, answerer, put, errors, finished):
    ready, _ = wait(list(pending), return_when=FIRST_COMPLETED)
    for fut in ready:
        item, prep = pending.pop(fut)
        finished += 1
        try:
            reply, ms = fut.result()
            put(item, answerer.finish(prep, reply, ms + prep.retrieval_ms), None)
        except ParseError as e:
            errors += 1
            put(item, None, str(e)[:300])
        except RuntimeError as e:
            errors += 1
            put(item, None, f"runner: {str(e)[:300]}")
    return errors, finished


def _check_rate(errors, finished, max_error_rate):
    if finished >= MIN_FOR_RATE and errors / finished > max_error_rate:
        raise RuntimeError(f"error rate {errors}/{finished} is over {max_error_rate:.0%}; stopping. Records so far "
                           "are ledgered; fix the cause and rerun")

import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor

from evals.tmachine import _ask
from pipeline.ledger import Ledger
from pipeline.m0 import _json_object

JUDGE_MODEL = REFUTE_MODEL = "claude-sonnet-5-5"
VERDICTS = ("agree", "partial", "disagree", "declined")

JUDGE = """Two careful readers each answered a question about one merger agreement. A system then answered the same question. Compare the system's answer with the readers' answers.

Question: {question}

Reader A: {a}
Reader B: {b}

System's answer:
{answer}

Verdict "agree" if the system states the same terms as the readers (amounts, triggers, who pays, which awards and how); "partial" if it is right but leaves out or blurs a term the readers state; "disagree" if it states a term that contradicts them.
Reply with one JSON object and nothing else: {{"verdict": "agree" | "partial" | "disagree", "reason": "one sentence"}}
"""

REFUTE = """Below is a claim and the quote offered as its source. Try to refute the claim using only the quote: does the quote fail to support it, or say something different?

Claim: {claim}
Quote: "{quote}"

Reply with one JSON object and nothing else: {{"refuted": true | false, "reason": "one sentence"}}
"""


def _sha(s: str) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:12]


def _parse(reply: str, key: str):
    try:
        return _json_object(reply, (key,))
    except RuntimeError:
        return {}


def _pool(jobs, workers):
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return dict(zip([k for k, _ in jobs], pool.map(lambda j: j[1](), jobs)))


def judge_all(items, answers: dict, runner, ledger_path, workers: int = 4) -> dict:
    led, lock, out, jobs = Ledger(ledger_path, key="key"), threading.Lock(), {}, []
    for it in items:
        rec = answers.get(it.item_id)
        if rec is None or rec["answer"] is None:
            continue
        ans = rec["answer"]
        if ans["state"] != "answered":
            out[it.item_id] = {"verdict": "declined", "reason": f"system state {ans['state']}"}
            continue
        text = "\n".join(f"- {c['text']}" for c in ans["claims"])
        prompt = JUDGE.format(question=it.question, a=it.meta["a"], b=it.meta["b"], answer=text)
        key = f"judge|{JUDGE_MODEL}|{it.item_id}|{_sha(text)}"
        jobs.append((it.item_id, lambda p=prompt, k=key: _ask(led, lock, k, p, JUDGE_MODEL, runner)))
    for item_id, reply in _pool(jobs, workers).items():
        obj = _parse(reply, "verdict")
        v = obj.get("verdict")
        out[item_id] = {"verdict": v if v in VERDICTS[:3] else None, "reason": str(obj.get("reason", ""))}
    return out


def refute_all(answers: dict, runner, ledger_path, workers: int = 4) -> dict:
    led, lock, jobs = Ledger(ledger_path, key="key"), threading.Lock(), []
    for item_id, rec in sorted(answers.items()):
        if rec["answer"] is None or rec["answer"]["state"] != "answered":
            continue
        for i, c in enumerate(rec["answer"]["claims"]):
            prompt = REFUTE.format(claim=c["text"], quote=c["quote"])
            key = f"refute|{REFUTE_MODEL}|{_sha(c['text'] + chr(0) + c['quote'])}"
            jobs.append((f"{item_id}#{i}", lambda p=prompt, k=key: _ask(led, lock, k, p, REFUTE_MODEL, runner)))
    out = {}
    for ck, reply in _pool(jobs, workers).items():
        obj = _parse(reply, "refuted")
        r = obj.get("refuted")
        out[ck] = {"refuted": r if isinstance(r, bool) else None, "reason": str(obj.get("reason", ""))}
    return out

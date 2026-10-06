import hashlib
import math
from pathlib import Path

from answer.gate import normalise
from evals.answer_score import match_choice
from evals.run_answers import answer_all
from service.prices import cost_usd, worst_case_usd

STATE_AGREEMENT_MIN = 0.8  # spec §2: below this, API answers differ too much to inherit the M4 (CLI) numbers
ACCURACY_DIFF_MAX = 0.15  # spec §2: a larger T-human accuracy gap is a gross difference
MAX_ERROR_RATE = 0.5  # calibration measures truncations and refusals; only an outage (20 in a row) should stop it


def ledger_path(root: Path, model: str, max_tokens: int, thinking_budget: int = 0) -> Path:
    """One ledger per model, output cap and thinking budget: a rerun at a new setting is new calls, not stale hits.
    No budget keeps the name the no-thinking run already has on disk."""
    tb = f"_tb{thinking_budget}" if thinking_budget else ""
    return Path(root) / f"calibration_{model}_mt{max_tokens}{tb}.jsonl"


def calibration_sample(items, n: int) -> list:
    """n//2 tune-split T-human items, then n//2 tune-split T-machine items, the same ones on every run (ordered by
    sha1 of the item id), so a rerun resumes the same calls. The report split is never touched."""
    out = []
    for s in ("thuman", "tmachine"):
        pool = [i for i in items if i.set == s and i.split == "tune"]
        out += sorted(pool, key=lambda i: hashlib.sha1(i.item_id.encode()).hexdigest())[:n // 2]
    return out


def run_calibration(jobs, ledger: Path, workers: int = 3, max_new: int | None = None) -> dict:
    """answer_all once per (items, answerer) job into one ledger; the summaries summed. Kill and resume are
    answer_all's own: a rerun skips every ledgered key except transient runner failures."""
    total = dict.fromkeys(("items", "done", "new_calls", "errors"), 0)
    for items, answerer in jobs:
        got = answer_all(items, answerer, ledger, workers=workers, max_new=max_new, max_error_rate=MAX_ERROR_RATE)
        total = {k: total[k] + got[k] for k in total}
    return total


def _pct(values, p):
    """Nearest-rank percentile; None for no values."""
    if not values:
        return None
    v = sorted(values)
    return v[max(0, math.ceil(p / 100 * len(v)) - 1)]


def _mean(values, digits):
    return round(sum(values) / len(values), digits) if values else None


def _rate(flags):
    return round(sum(flags) / len(flags), 4) if flags else None


def _gate(answers):
    kept = sum(len(a["claims"]) for a in answers)
    returned = kept + sum(len(a["dropped"]) for a in answers)
    return round(kept / returned, 4) if returned else None


def _right(answer: dict, item) -> bool:
    """evals.answer_score's T-human rule: the choice maps to exactly one option, equal to MAUD's answer."""
    picked = match_choice(answer.get("choice"), item.choices)
    return picked is not None and normalise(picked) == normalise(item.expected)


def summarise(items, api: dict, cli: dict, prompt_chars: dict, prices, max_tokens: int,
              thinking_budget: int = 0) -> dict:
    """API calibration against the M4 CLI answers for the same items. `api` and `cli` are load_answers records by
    item id; `prompt_chars` the length of each item's prompt. A call that failed after it was sent (truncated,
    refused, unparseable) is costed at its worst case, because its usage is not in the ledger."""
    ok = {i.item_id: api[i.item_id]["answer"] for i in items if (api.get(i.item_id) or {}).get("answer")}
    failed = {i.item_id: api[i.item_id] for i in items if i.item_id in api and not api[i.item_id].get("answer")}
    called = {iid: a for iid, a in ok.items() if a["tokens_in"]}  # which_deal and no-hit answers make no call
    tin = [a["tokens_in"] for a in called.values()]
    tout = [a["tokens_out"] for a in called.values()]
    cost = {iid: cost_usd(prices, a.get("usage") or {}) for iid, a in called.items()}
    worst = {iid: worst_case_usd(prices, prompt_chars[iid], max_tokens) for iid in called if iid in prompt_chars}
    failed_cost = sum(worst_case_usd(prices, prompt_chars[iid], max_tokens) for iid in failed if iid in prompt_chars)
    margins = [worst[iid] - cost[iid] for iid in worst]
    worst_ok = bool(margins) and min(margins) >= 0
    paired = [i for i in items if i.item_id in ok and (cli.get(i.item_id) or {}).get("answer")]
    a_side = [ok[i.item_id] for i in paired]
    c_side = [cli[i.item_id]["answer"] for i in paired]
    th = [i for i in paired if i.set == "thuman"]
    acc_api = _rate([_right(ok[i.item_id], i) for i in th])
    acc_cli = _rate([_right(cli[i.item_id]["answer"], i) for i in th])
    diff = round(acc_api - acc_cli, 4) if th else None
    agree = _rate([x["state"] == y["state"] for x, y in zip(a_side, c_side)])
    errors = [r.get("error") or "" for r in failed.values()]
    reasons = []
    if agree is None:
        reasons.append("no item has both an API and a CLI answer")
    elif agree < STATE_AGREEMENT_MIN:
        reasons.append(f"state agreement {agree} is below {STATE_AGREEMENT_MIN}")
    if diff is not None and abs(diff) > ACCURACY_DIFF_MAX:
        reasons.append(f"T-human accuracy differs by {diff}, more than {ACCURACY_DIFF_MAX}")
    if not worst_ok:
        reasons.append("the worst-case estimate is below an actual cost, so the budget would under-reserve")
    costs = list(cost.values())
    return {
        "thinking_budget": thinking_budget, "n": len(items), "called": len(called), "errors": len(failed),
        "missing": sum(i.item_id not in api for i in items),
        "truncated": sum(e.startswith("runner: truncated") for e in errors),
        "refused": sum(e.startswith("runner: refusal") for e in errors),
        "api_tokens_in_mean": _mean(tin, 1), "api_tokens_in_p95": _pct(tin, 95),
        "api_tokens_out_mean": _mean(tout, 1), "api_tokens_out_p95": _pct(tout, 95),
        "api_tokens_out_p99": _pct(tout, 99),
        "cost_usd_total": round(sum(costs) + failed_cost, 6),
        "cost_per_answer_mean": _mean(costs, 6),
        "cost_per_answer_p95": round(_pct(costs, 95), 6) if costs else None,
        "worst_case_ok": worst_ok, "worst_case_min_margin_usd": round(min(margins), 6) if margins else None,
        "paired": len(paired), "gate_pass_rate": {"api": _gate(a_side), "cli": _gate(c_side)},
        "state_agreement": agree,
        "thuman_accuracy": {"api": acc_api, "cli": acc_cli, "diff": diff, "n": len(th)},
        "stop_rule": {"state_agreement_min": STATE_AGREEMENT_MIN, "accuracy_diff_max": ACCURACY_DIFF_MAX,
                      "verdict": "stop" if reasons else "go", "reasons": reasons},
    }

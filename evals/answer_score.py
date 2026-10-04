from collections import Counter, defaultdict

from evals.answer_sets import ABSTAIN_GROUPS
from evals.bootstrap import cluster_bootstrap


def _ci(values: list[tuple[str, float]], n_boot: int):
    by = defaultdict(list)
    for cluster, v in values:
        by[cluster].append(v)
    return cluster_bootstrap(by, n_boot=n_boot) if by else None


def _baseline(tune_items) -> dict[str, str]:
    votes = defaultdict(Counter)
    for i in tune_items:
        votes[i.item_id.split("|", 1)[1]][i.expected] += 1
    return {q: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for q, c in votes.items()}


def _thuman(items, recs, n_boot):
    base = _baseline([i for i in items if i.split == "tune"])
    out = {}
    for split in ("tune", "report"):
        acc, bl, cats, ool, err = [], [], defaultdict(lambda: ([], [])), 0, 0
        for i in (x for x in items if x.split == split):
            r = recs.get(i.item_id)
            if r is None:
                continue
            if r["answer"] is None:
                err += 1
                continue
            choice = r["answer"]["choice"]
            ool += choice not in i.choices
            a = (i.contract_id, float(choice == i.expected))
            b = (i.contract_id, float(base.get(i.item_id.split("|", 1)[1]) == i.expected))
            acc.append(a)
            bl.append(b)
            cats[i.group][0].append(a)
            cats[i.group][1].append(b)
        if acc:
            out[split] = {"accuracy": _ci(acc, n_boot), "baseline": _ci(bl, n_boot), "out_of_list": ool,
                          "errors": err, "n": len(acc),
                          "by_category": {c: {"accuracy": _ci(a, n_boot), "baseline": _ci(b, n_boot)}
                                          for c, (a, b) in sorted(cats.items())}}
    return out


def _tmachine(items, recs, verdicts, n_boot):
    out = {}
    for split in ("tune", "report"):
        ag, ap, fams, declined, unparsed, wrong, err = [], [], defaultdict(lambda: ([], [])), 0, 0, 0, 0
        for i in (x for x in items if x.split == split):
            r = recs.get(i.item_id)
            if r is None:
                continue
            if r["answer"] is None:
                err += 1
                continue
            wrong += r["answer"]["contract_id"] not in (None, i.expected)
            v = verdicts.get(i.item_id, {}).get("verdict")
            if v is None:
                unparsed += 1
                continue
            declined += v == "declined"
            a, p = (i.expected, float(v == "agree")), (i.expected, float(v in ("agree", "partial")))
            ag.append(a)
            ap.append(p)
            fams[i.group][0].append(a)
            fams[i.group][1].append(p)
        if ag:
            out[split] = {"agree": _ci(ag, n_boot), "agree_or_partial": _ci(ap, n_boot), "declined": declined,
                          "judge_unparsed": unparsed, "wrong_deal": wrong, "errors": err, "n": len(ag),
                          "by_family": {f: {"agree": _ci(a, n_boot), "agree_or_partial": _ci(p, n_boot)}
                                        for f, (a, p) in sorted(fams.items())}}
    return out


def _abstain(items, recs):
    out = {}
    for g in ABSTAIN_GROUPS:
        c = Counter()
        for i in (x for x in items if x.group == g):
            r = recs.get(i.item_id)
            if r is None:
                continue
            if r["answer"] is None:
                c["errors"] += 1
                continue
            st = r["answer"]["state"]
            c["n"] += 1
            c["correct" if st == i.expected else "false_answer" if st == "answered" else "other"] += 1
        if c["n"]:
            out[g] = {k: c[k] for k in ("n", "correct", "false_answer", "other", "errors")} | {
                "correct_rate": round(c["correct"] / c["n"], 4), "false_answer_rate": round(c["false_answer"] / c["n"], 4)}
    return out


def score(sets, answers, judge, refute, models, n_boot: int = 2000) -> dict:
    s = {"thuman": {}, "tmachine": {}, "abstain": {}, "gate": {}, "tokens": defaultdict(dict)}
    for m in models:
        if "thuman" in sets and answers.get(("thuman", m)):
            s["thuman"][m] = _thuman(sets["thuman"], answers[("thuman", m)], n_boot)
        if "tmachine" in sets and answers.get(("tmachine", m)):
            s["tmachine"][m] = _tmachine(sets["tmachine"], answers[("tmachine", m)], judge.get(m, {}), n_boot)
    if "abstain" in sets and answers.get(("abstain", models[0])):
        s["abstain"] = _abstain(sets["abstain"], answers[("abstain", models[0])])
    for (set_name, m), recs in answers.items():
        done = [r["answer"] for r in recs.values() if r["answer"] is not None]
        if m == models[0]:
            kept = sum(len(a["claims"]) for a in done)
            reasons = Counter(d["reason"] for a in done for d in a["dropped"])
            returned = kept + sum(reasons.values())
            s["gate"][set_name] = {"returned": returned, "kept": kept, "by_reason": dict(reasons),
                                   "pass_rate": round(kept / returned, 4) if returned else None}
        called = [a for a in done if a["tokens_in"]]
        if called:
            s["tokens"][m][set_name] = {"in_mean": round(sum(a["tokens_in"] for a in called) / len(called), 1),
                                        "out_mean": round(sum(a["tokens_out"] for a in called) / len(called), 1),
                                        "n": len(called)}
    vals = [v["refuted"] for v in refute.values()]
    decided = [v for v in vals if v is not None]
    s["refute"] = {"claims": len(vals), "not_refuted": sum(1 for v in decided if v is False),
                   "unparsed": len(vals) - len(decided),
                   "survival_rate": round(sum(1 for v in decided if v is False) / len(decided), 4) if decided else None}
    s["tokens"] = dict(s["tokens"])
    return s

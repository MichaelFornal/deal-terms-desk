from collections import Counter, defaultdict

from answer.gate import normalise
from evals.answer_sets import ABSTAIN_GROUPS
from evals.bootstrap import cluster_bootstrap


def _ci(values: list[tuple[str, float]], n_boot: int):
    by = defaultdict(list)
    for cluster, v in values:
        by[cluster].append(v)
    return cluster_bootstrap(by, n_boot=n_boot) if by else None


def _norm(s) -> str | None:
    return None if s is None else normalise(str(s))


def _key(s: str) -> str:
    return " ".join(normalise(s).replace('"', "").split()).casefold()


def _segment(option: str) -> str | None:
    parts = normalise(option).split('"')
    return parts[1] if len(parts) >= 3 else None


def match_choice(choice, options) -> str | None:
    """The one option a model's choice means, or None. Tolerates dropped quote marks, case, and a bare quoted segment."""
    if choice is None or not _key(str(choice)):
        return None
    k = _key(str(choice))
    hit = [o for o in options if _key(o) == k]
    if len(hit) == 1:
        return hit[0]
    hit = [o for o in options if (seg := _segment(o)) is not None and _key(seg) == k]
    return hit[0] if len(hit) == 1 else None


def _baseline(tune_items) -> dict[str, str]:
    votes = defaultdict(Counter)
    for i in tune_items:
        votes[i.item_id.split("|", 1)[1]][i.expected] += 1
    return {q: sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[0][0] for q, c in votes.items()}


def _thuman(items, recs, n_boot):
    base = _baseline([i for i in items if i.split == "tune"])
    out = {}
    for split in ("tune", "report"):
        acc, bl, cit, diff = [], [], [], []
        cats, ool, err, total, missing = defaultdict(lambda: ([], [], [])), 0, 0, 0, 0
        for i in (x for x in items if x.split == split):
            total += 1
            r = recs.get(i.item_id)
            if r is None:
                missing += 1
                continue
            if r["answer"] is None:
                err += 1
                continue
            matched = match_choice(r["answer"]["choice"], i.choices)
            ool += matched is None
            right = matched is not None and _norm(matched) == _norm(i.expected)
            a = (i.contract_id, float(right))
            b = (i.contract_id, float(base.get(i.item_id.split("|", 1)[1]) == i.expected))
            c = (i.contract_id, float(right and r["answer"]["state"] == "answered"))
            acc.append(a)
            bl.append(b)
            cit.append(c)
            diff.append((i.contract_id, a[1] - b[1]))
            cats[i.group][0].append(a)
            cats[i.group][1].append(b)
            cats[i.group][2].append(c)
        if acc:
            out[split] = {"accuracy": _ci(acc, n_boot), "accuracy_cited": _ci(cit, n_boot),
                          "baseline": _ci(bl, n_boot), "vs_baseline": _ci(diff, n_boot), "out_of_list": ool,
                          "errors": err, "n": len(acc), "items": total, "missing": missing,
                          "by_category": {k: {"accuracy": _ci(a, n_boot), "accuracy_cited": _ci(c, n_boot),
                                              "baseline": _ci(b, n_boot)}
                                          for k, (a, b, c) in sorted(cats.items())}}
    return out


def _tmachine(items, recs, verdicts, n_boot):
    out = {}
    for split in ("tune", "report"):
        ag, ap, fams, declined, unparsed, wrong, err = [], [], defaultdict(lambda: ([], [])), 0, 0, 0, 0
        total = missing = not_judged = 0
        for i in (x for x in items if x.split == split):
            total += 1
            r = recs.get(i.item_id)
            if r is None:
                missing += 1
                continue
            if r["answer"] is None:
                err += 1
                continue
            wrong += r["answer"]["contract_id"] not in (None, i.expected)
            if i.item_id not in verdicts:
                not_judged += 1
                continue
            v = verdicts[i.item_id].get("verdict")
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
                          "judge_unparsed": unparsed, "not_judged": not_judged, "wrong_deal": wrong, "errors": err,
                          "n": len(ag), "items": total, "missing": missing,
                          "by_family": {f: {"agree": _ci(a, n_boot), "agree_or_partial": _ci(p, n_boot)}
                                        for f, (a, p) in sorted(fams.items())}}
    return out


def _abstain_judged(st, v) -> str:
    """Group `absent`: a decline is correct; an answer is correct when the judge finds it matches the two passes."""
    if st == "not_stated":
        return "correct"
    if st != "answered":
        return "other"
    if v is ...:
        return "not_judged"
    if v is None:
        return "judge_unparsed"
    return "correct" if v in ("agree", "partial") else "false_answer" if v == "disagree" else "other"


def _abstain(items, recs, verdicts=None):
    verdicts = verdicts or {}
    out = {}
    for g in ABSTAIN_GROUPS:
        c = Counter()
        for i in (x for x in items if x.group == g):
            c["items"] += 1
            r = recs.get(i.item_id)
            if r is None:
                c["missing"] += 1
                continue
            if r["answer"] is None:
                c["errors"] += 1
                continue
            st = r["answer"]["state"]
            if g == "absent":
                v = verdicts[i.item_id].get("verdict") if i.item_id in verdicts else ...
                k = _abstain_judged(st, v)
            else:
                k = "correct" if st == i.expected else "false_answer" if st == "answered" else "other"
            c[k] += 1
            c["n"] += k not in ("not_judged", "judge_unparsed")
        if c["items"] and c["items"] > c["missing"]:
            n = c["n"]
            out[g] = {k: c[k] for k in ("n", "correct", "false_answer", "other", "errors", "items", "missing",
                                        "not_judged", "judge_unparsed")} | {
                "correct_rate": round(c["correct"] / n, 4) if n else None,
                "false_answer_rate": round(c["false_answer"] / n, 4) if n else None}
    return out


def _gate(done) -> dict:
    kept = sum(len(a["claims"]) for a in done)
    reasons = Counter(d["reason"] for a in done for d in a["dropped"])
    returned = kept + sum(reasons.values())
    return {"returned": returned, "kept": kept, "by_reason": dict(reasons),
            "pass_rate": round(kept / returned, 4) if returned else None}


def score(sets, answers, judge, refute, models, n_boot: int = 2000) -> dict:
    s = {"thuman": {}, "tmachine": {}, "abstain": {}, "gate": {}, "tokens": defaultdict(dict)}
    for m in models:
        if "thuman" in sets and answers.get(("thuman", m)):
            s["thuman"][m] = _thuman(sets["thuman"], answers[("thuman", m)], n_boot)
        if "tmachine" in sets and answers.get(("tmachine", m)):
            s["tmachine"][m] = _tmachine(sets["tmachine"], answers[("tmachine", m)], judge.get(m, {}), n_boot)
    if "abstain" in sets and answers.get(("abstain", models[0])):
        s["abstain"] = _abstain(sets["abstain"], answers[("abstain", models[0])], judge.get("abstain:" + models[0], {}))
    for (set_name, m), recs in answers.items():
        split = {i.item_id: i.split for i in sets.get(set_name, ())}
        if m == models[0]:  # per split, so the report split lines up with the refute pass, which covers it alone
            done = defaultdict(list)
            for iid, r in recs.items():
                if r["answer"] is not None and iid in split:
                    done[split[iid]].append(r["answer"])
            s["gate"][set_name] = {sp: _gate(c) for sp, c in sorted(done.items())}
        by_split = defaultdict(list)
        for iid, r in recs.items():
            if r["answer"] is not None and r["answer"]["tokens_in"] and iid in split:
                by_split[split[iid]].append(r["answer"])
        if by_split:
            s["tokens"][m][set_name] = {
                sp: {"in_mean": round(sum(a["tokens_in"] for a in c) / len(c), 1),
                     "out_mean": round(sum(a["tokens_out"] for a in c) / len(c), 1), "n": len(c)}
                for sp, c in sorted(by_split.items())}
    vals = [v["refuted"] for v in refute.values()]
    decided = [v for v in vals if v is not None]
    s["refute"] = {"claims": len(vals), "not_refuted": sum(1 for v in decided if v is False),
                   "unparsed": len(vals) - len(decided),
                   "survival_rate": round(sum(1 for v in decided if v is False) / len(decided), 4) if decided else None}
    s["tokens"] = dict(s["tokens"])
    return s

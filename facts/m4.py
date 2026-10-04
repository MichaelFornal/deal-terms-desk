from pathlib import Path

from evals.compare import load_items, paired_bootstrap
from evals.tmachine import FAMILIES
from facts.m2 import _ci, _delta, _json, slug

MODELS = (("haiku", "claude-haiku-4-5-20251001"), ("sonnet", "claude-sonnet-5-5"))
ABSTAIN_KEYS = ("correct_rate", "false_answer_rate", "correct", "false_answer", "other", "errors", "items", "missing",
                "not_judged", "judge_unparsed")


def present_m4(out_m4: Path) -> bool:
    return (Path(out_m4) / "scores.json").exists()


def _ci_or_none(f, name, block):
    if block is None:
        for s in ("", "_lo", "_hi"):
            f[name + s] = None
    else:
        _ci(f, name, block)


def _mean(block):
    return round(block["mean"], 4) if block else None


def _tokens_mean(tok, split, k):
    """n-weighted mean tokens per called answer over the T-human and T-machine sets on one split."""
    blocks = [tok[st][split] for st in ("thuman", "tmachine") if split in tok.get(st, {})]
    n = sum(b["n"] for b in blocks)
    return round(sum(b[f"{k}_mean"] * b["n"] for b in blocks) / n, 1) if n else None


def build_m4(out_m4, out_dir, data_m4, n_boot: int = 2000) -> dict:
    out_m4, out_dir, data_m4 = map(Path, (out_m4, out_dir, data_m4))
    needed = [out_m4 / "scores.json", data_m4 / "sets_summary.json", out_dir / "r6_items.jsonl",
              out_dir / "m3" / "t_r6_items.jsonl"] + [out_m4 / f"{r}{x}" for r in ("r6n", "t_r6n", "t_r7_corpus",
                                                                                 "t_r7n_corpus")
                                                      for x in (".json", "_items.jsonl")]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        raise FileNotFoundError("M4 inputs missing: " + ", ".join(missing))
    f: dict = {"m4_answer_model": MODELS[0][1], "m4_judge_model": MODELS[1][1]}

    for r in ("r6n", "t_r6n", "t_r7_corpus", "t_r7n_corpus"):
        _ci(f, f"m4_{r}_report_recall_at_5", _json(out_m4 / f"{r}.json")["by_split"]["report"]["recall@5"])
    _delta(f, "m4_cmp_r6n_vs_r6_recall_at_5",
           paired_bootstrap(load_items(out_dir / "r6_items.jsonl"), load_items(out_m4 / "r6n_items.jsonl"),
                            "recall@5", n_boot=n_boot))
    _delta(f, "m4_cmp_t_r6n_vs_t_r6_recall_at_5",
           paired_bootstrap(load_items(out_dir / "m3" / "t_r6_items.jsonl"),
                            load_items(out_m4 / "t_r6n_items.jsonl"), "recall@5", n_boot=n_boot))
    _delta(f, "m4_cmp_t_r7n_vs_t_r7_corpus_recall_at_5",
           paired_bootstrap(load_items(out_m4 / "t_r7_corpus_items.jsonl"),
                            load_items(out_m4 / "t_r7n_corpus_items.jsonl"), "recall@5", n_boot=n_boot))

    sets = _json(data_m4 / "sets_summary.json")
    f["m4_thuman_items"], f["m4_tmachine_items"] = sets["thuman"], sets["tmachine"]
    for k in ("disputed", "too_many_options"):
        f[f"m4_thuman_excluded_{k}"] = sets["thuman_excluded"][k]
    f["m4_thuman_questions_too_many_options"] = sets["thuman_excluded"]["questions_too_many_options"]
    for g, n in sets["abstain"].items():
        f[f"m4_abstain_{g}_n"] = n

    s = _json(out_m4 / "scores.json")
    for short, mid in MODELS:
        th = s["thuman"].get(mid, {})
        tm = s["tmachine"].get(mid, {})
        if short == "haiku":
            r = th.get("report", {})
            for k in ("accuracy", "accuracy_cited", "baseline", "vs_baseline"):
                _ci_or_none(f, f"m4_thuman_haiku_report_{k}", r.get(k))
            for k in ("n", "errors", "out_of_list", "items", "missing"):
                f[f"m4_thuman_haiku_report_{k}"] = r.get(k)
            for cat, v in r.get("by_category", {}).items():
                for k in ("accuracy", "accuracy_cited", "baseline"):
                    f[f"m4_thuman_haiku_{slug(cat)}_{k}"] = _mean(v.get(k))
            t = tm.get("report", {})
            _ci_or_none(f, "m4_tmachine_haiku_report_agree", t.get("agree"))
            _ci_or_none(f, "m4_tmachine_haiku_report_agree_or_partial", t.get("agree_or_partial"))
            for k in ("declined", "wrong_deal", "judge_unparsed", "errors", "n", "items", "missing", "not_judged"):
                f[f"m4_tmachine_haiku_report_{k}"] = t.get(k)
            for fam in FAMILIES:
                v = t.get("by_family", {}).get(fam)
                f[f"m4_tmachine_haiku_{fam}_agree"] = _mean(v["agree"]) if v else None
                f[f"m4_tmachine_haiku_{fam}_agree_or_partial"] = _mean(v["agree_or_partial"]) if v else None
        f[f"m4_cmp_model_{short}_thuman_tune_accuracy"] = _mean(th.get("tune", {}).get("accuracy"))
        f[f"m4_cmp_model_{short}_tmachine_tune_agree"] = _mean(tm.get("tune", {}).get("agree"))
        tok = s["tokens"].get(mid, {})
        for k in ("in", "out"):  # tune split only, so both models are compared on the same items
            f[f"m4_cmp_model_{short}_tokens_{k}_mean"] = _tokens_mean(tok, "tune", k)
            if short == "haiku":  # the answer model on the report split prices the live demo (M5)
                f[f"m4_tokens_haiku_report_{k}_mean"] = _tokens_mean(tok, "report", k)
    for g, v in s["abstain"].items():
        for k in ABSTAIN_KEYS:
            f[f"m4_abstain_{g}_{k}"] = v.get(k)
    nf = s["abstain"].get("absent_not_filed")  # answered share: the machine key here is contradicted by retrieval
    f["m4_abstain_absent_not_filed_answered_rate"] = (round(nf["false_answer"] / nf["n"], 4)
                                                      if nf and nf.get("n") else None)
    for set_name, v in s["gate"].items():
        for k in ("pass_rate", "returned", "kept"):
            f[f"m4_gate_{set_name}_{k}"] = v[k]
    for k in ("survival_rate", "claims", "unparsed"):
        f[f"m4_refute_{k}"] = s["refute"][k]
    return f

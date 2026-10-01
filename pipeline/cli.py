import argparse
import json
import sqlite3
import sys
from dataclasses import asdict
from pathlib import Path

from evals.bootstrap import split_of
from evals.llm_rewrite import REWRITE_MODEL, rewrite_all
from evals.run_rung import evaluate, load_context
from evals.tune import tune
from facts.build import build as build_facts
from facts.build import check as check_facts
from facts.report import render
from pipeline.build_lexicon import build as build_lexicon
from pipeline.claude import run_claude
from pipeline.fetch_maud import fetch_all
from pipeline.normalise import load_contract
from pipeline.paths import CACHE, CSV_NAMES, INDEX, INDEX_FIXED, OUT, RAW
from retrieval import vectors
from retrieval.index import build_index
from retrieval.ladder import RUNGS, SETTINGS_PATH, Ladder, load_settings
from retrieval.lexicon import LEXICON_PATH, load_lexicon
from retrieval.models import Embedder, Reranker
from retrieval.rerank_cache import CachedReranker
from retrieval.result import Retrieved

FACTS = Path("facts.json")
REPORT = Path("docs/m1/REPORT.md")
REWRITES = "llm_rewrites.jsonl"


def _csv_paths() -> list[Path]:
    return [RAW / n for n in CSV_NAMES if (RAW / n).exists()]


def _cmd_fetch(args) -> int:
    print(json.dumps(fetch_all(RAW)))
    return 0


def _cmd_build(args) -> int:
    files = sorted((RAW / "contracts").glob("*.txt")) if (RAW / "contracts").exists() else []
    if not files:
        print(f"no contracts under {RAW / 'contracts'}; run `dtd fetch` first", file=sys.stderr)
        return 2
    print(json.dumps(build_index(INDEX, {p.stem: load_contract(p) for p in files})))
    return 0


def _models():
    return Embedder(), Reranker


def _has_vectors(db: Path) -> bool:
    conn = vectors.connect(db)
    row = conn.execute("SELECT name FROM sqlite_master WHERE name = 'vec_meta'").fetchone()
    return bool(row) and conn.execute("SELECT vectors FROM vec_meta").fetchone()[0] > 0


def _cmd_embed(args) -> int:
    db = INDEX_FIXED if args.fixed else INDEX
    if not db.exists():
        print(f"{db} missing; run `dtd build{' --fixed' if args.fixed else ''}` first", file=sys.stderr)
        return 2
    embedder, _ = _models()
    conn = vectors.connect(db)
    cache = vectors.open_cache(CACHE / "embeddings.db")
    texts = [t for _, _, t in vectors.indexed_passages(conn)]
    summary = vectors.fill_cache(cache, embedder, texts,
                                 on_batch=lambda done, n: print(f"embedded {done}/{n}", file=sys.stderr, flush=True))
    summary |= vectors.build_vectors(conn, cache, embedder.name)
    print(json.dumps(summary))
    return 0


def _ladder(db: Path, texts: dict[str, str]) -> Ladder:
    embedder, make_reranker = _models()
    settings = load_settings(SETTINGS_PATH)
    reranker = CachedReranker(make_reranker(settings.reranker), CACHE / "rerank.db")
    lexicon = load_lexicon(LEXICON_PATH) if LEXICON_PATH.exists() else None
    return Ladder(vectors.connect(db), texts, embedder, reranker, lexicon, settings)


def _eval_rung(rung: str, db: Path, name: str, ctx, **kw) -> dict:
    ladder = _ladder(db, ctx.texts)
    return evaluate(ctx, name, lambda q, c, k: ladder.run(rung, q, c, k), OUT,
                    count_tokens=ladder.embedder.count_tokens,
                    extra={"settings": asdict(ladder.settings)}, **kw)


def _cmd_eval(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    rung = args.rung
    if rung not in RUNGS + ("R5-llm",):
        print(f"unknown rung {rung}", file=sys.stderr)
        return 2
    if rung != "R1" and not _has_vectors(INDEX):
        print("no vectors in the index; run `dtd embed` first", file=sys.stderr)
        return 2
    if rung in ("R5", "R6") and not LEXICON_PATH.exists():
        print("no lexicon; run `dtd lexicon` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    if rung == "R5-llm":
        path = CACHE / REWRITES
        if not path.exists():
            print("no LLM rewrites; run `dtd rewrite` first", file=sys.stderr)
            return 2
        rewrites = rewrite_all([i.query for i in ctx.items], path, runner=_refuse_new_calls)
        ladder = _ladder(INDEX, ctx.texts)

        def retrieve(q, c, k):
            r = rewrites[q]
            got = ladder.run("R5", q, c, k, rewritten=r["rewrite"])
            return Retrieved(got.hits, got.ms + r["api_ms"], got.context)
        n = len(rewrites)
        result = evaluate(ctx, "R5-llm", retrieve, OUT, count_tokens=ladder.embedder.count_tokens, extra={
            "settings": asdict(ladder.settings), "model": REWRITE_MODEL, "queries": n,
            "input_tokens_mean": sum(r["input_tokens"] for r in rewrites.values()) / n,
            "output_tokens_mean": sum(r["output_tokens"] for r in rewrites.values()) / n})
    else:
        result = _eval_rung(rung, INDEX, rung, ctx)
    print(json.dumps(result["overall"], indent=2))
    return 0


def _refuse_new_calls(prompt, model):
    raise SystemExit("a query has no cached LLM rewrite; run `dtd rewrite` first")


def _cmd_rewrite(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    try:
        out = rewrite_all([i.query for i in ctx.items], CACHE / REWRITES, runner=run_claude)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps({"queries": len(out)}))
    return 0


def _cmd_lexicon(args) -> int:
    if not INDEX.exists():
        print("index missing; run `dtd build` first", file=sys.stderr)
        return 2
    files = sorted((RAW / "contracts").glob("*.txt"))
    tune_texts = [load_contract(p) for p in files if split_of(p.stem) == "tune"]
    try:
        doc = build_lexicon(sqlite3.connect(INDEX), tune_texts, LEXICON_PATH, runner=run_claude)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps({"entries": len(doc["entries"])}))
    return 0


def _cmd_tune(args) -> int:
    if not INDEX.exists() or not _csv_paths() or not _has_vectors(INDEX):
        print("index, vectors or label CSVs missing; run `dtd build` then `dtd embed` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    embedder, make_reranker = _models()
    doc = tune(ctx, vectors.connect(INDEX), embedder, make_reranker, CACHE / "rerank.db", SETTINGS_PATH)
    print(json.dumps({"settings": doc["settings"], "live_path_ok": doc["live_path_ok"]}))
    return 0


def _cmd_facts(args) -> int:
    r1 = OUT / "r1.json"
    if not INDEX.exists() or not r1.exists() or not _csv_paths():
        print("index, r1.json or label CSVs missing; run `dtd fetch`, `dtd build` then `dtd eval` first",
              file=sys.stderr)
        return 2
    if args.check:
        stale = check_facts(INDEX, r1, FACTS, _csv_paths())
        if stale:
            print("stale facts: " + ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    facts = build_facts(INDEX, r1, _csv_paths())
    FACTS.write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def _cmd_report(args) -> int:
    if not FACTS.exists():
        print("facts.json missing; run `dtd facts` first", file=sys.stderr)
        return 2
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(json.loads(FACTS.read_text(encoding="utf-8"))), encoding="utf-8")
    return 0


def entry(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dtd")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(fn=_cmd_fetch)
    sub.add_parser("build").set_defaults(fn=_cmd_build)
    embed = sub.add_parser("embed")
    embed.add_argument("--fixed", action="store_true")
    embed.set_defaults(fn=_cmd_embed)
    ev = sub.add_parser("eval")
    ev.add_argument("--rung", default="R1")
    ev.set_defaults(fn=_cmd_eval)
    sub.add_parser("rewrite").set_defaults(fn=_cmd_rewrite)
    sub.add_parser("tune").set_defaults(fn=_cmd_tune)
    sub.add_parser("lexicon").set_defaults(fn=_cmd_lexicon)
    facts = sub.add_parser("facts")
    facts.add_argument("--check", action="store_true")
    facts.set_defaults(fn=_cmd_facts)
    sub.add_parser("report").set_defaults(fn=_cmd_report)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(entry())

import argparse
import hashlib
import json
import sqlite3
import sys
from dataclasses import asdict, replace
from pathlib import Path

from answer.answerer import Answerer, Prepared
from answer.api_runner import make_api_runner
from evals.answer_score import score as score_answers
from evals.answer_judge import judge_all, refute_all
from evals.answer_sets import abstain_items, read_items, thuman_items, tmachine_items, write_items
from evals.bootstrap import split_of
from evals.calibrate import calibration_sample, ledger_path, run_calibration
from evals.calibrate import summarise as summarise_calibration
from evals.compare import load_items
from evals.disputes import DISPUTE_MODEL, PROMPT as DISPUTE_PROMPT, judge, sample_misses, summarise
from evals.failures import classify
from evals.live_parity import prompt_parity, r7n_parity
from evals.measure import measure, reference_hits
from evals.llm_rewrite import rewrite_all
from evals.maud_labels import load_rows
from evals.run_answers import answer_all, load_answers
from evals.run_rung import Context, evaluate, load_context, with_passages
from evals.tier import RUNG_NAMES, tier_report, tier_sample, tier_topics
from evals.tmachine import PASSES, TOPICS, items_from_rows, label_all, scope_report
from evals.tune import tune
from facts.build import build as build_facts
from facts.build import UNSTABLE
from facts.m0 import build_m0
from facts.m2 import build_m2, is_unstable
from facts.m3 import build_m3, present_m3
from facts.m4 import build_m4, present_m4
from facts.m5 import build_m5, present_m5
from facts.m2 import present as m2_present
from facts.report import render
from facts.report_m0 import render_m0
from facts.report_m2 import render_m2
from facts.report_m3 import render_m3
from facts.report_m4 import render_m4
from facts.report_m5 import render_m5
from facts.site import render_site
from pipeline import m0
from service.app import build_desk
from service.config import from_env
from service.warm import warm
from pipeline.bundle import MANIFEST, build_bundle, bundle_is_current
from pipeline.build_lexicon import build as build_lexicon
from pipeline.chunk_fixed import fixed_chunker, fixed_size
from pipeline.claude import run_claude
from pipeline.env import anthropic_key, sec_contact
from pipeline.fetch_maud import fetch_all
from pipeline.normalise import load_contract
from pipeline.paths import CACHE, DATA, CSV_NAMES, DEALS_INDEX, EDGAR, INDEX, INDEX_FIXED, OUT, RAW
from pipeline.sec_client import Blocked, SecClient
from pipeline.tech_corpus import assemble
from retrieval import vectors
from retrieval.deals import add_deals, maud_duplicates
from retrieval.index import build_index
from retrieval.ladder import ANSWER_RUNGS, RUNGS, SETTINGS_PATH, Ladder, load_settings
from retrieval.lexicon import LEXICON_PATH, load_lexicon
from retrieval.live import build_live_ladder
from retrieval.models import Embedder, Reranker
from retrieval.rerank_cache import CachedReranker
from retrieval.scope import Resolver
from service.prices import load_prices

FACTS = Path("facts.json")
ENV_FILE = Path(".env")
PRICES = Path("service/prices.json")
HOSTING = Path("deploy/hosting.json")
REPORT = Path("docs/m1/REPORT.md")
EXTERNAL = Path("facts/external.json")
EXAMPLES = Path("site/examples.json")
SITE_DIST = Path("site/dist")
REPORT_M2 = Path("docs/m2/REPORT.md")
REPORT_M0 = Path("docs/m0/REPORT.md")
REPORT_M3 = Path("docs/m3/REPORT.md")
REPORT_M4 = Path("docs/m4/REPORT.md")
REPORT_M5 = Path("docs/m5/REPORT.md")
M0_STAGES = ("search", "candidates", "fetch", "deals", "sample", "press", "measure")
NEEDS_SEC = {"search", "candidates", "fetch", "deals", "press"}
REWRITES = "llm_rewrites.jsonl"
CHAR_KS = (1, 2, 4, 8, 16, 32, 64)


def _write_atomic(path: Path, text: str) -> None:
    """Write beside the target, then rename over it, so a kill never leaves a torn file."""
    tmp = path.with_name(path.name + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def _rewrite_model(rewrites: dict[str, dict]) -> str:
    models = {r["model"] for r in rewrites.values()}
    if len(models) != 1:
        raise ValueError(f"LLM rewrites come from more than one model: {sorted(models)}")
    return models.pop()


def _csv_paths() -> list[Path]:
    return [RAW / n for n in CSV_NAMES if (RAW / n).exists()]


def _cmd_fetch(args) -> int:
    print(json.dumps(fetch_all(RAW)))
    return 0


def _deals_texts() -> tuple[dict[str, str], dict[str, str]]:
    """(MAUD + tech contract texts, amendment texts) for the combined deals index."""
    def read(d: Path) -> dict[str, str]:
        return {p.stem: load_contract(p) for p in sorted(d.glob("*.txt"))} if d.exists() else {}
    return read(RAW / "contracts") | read(EDGAR / "contracts"), read(EDGAR / "amendments")


def _build_deals() -> int:
    if not (EDGAR / "deals.jsonl").exists():
        print(f"{EDGAR / 'deals.jsonl'} missing; run `dtd m3 corpus` first", file=sys.stderr)
        return 2
    deals = [json.loads(line) for line in (EDGAR / "deals.jsonl").read_text(encoding="utf-8").splitlines() if line]
    contracts, amendment_texts = _deals_texts()
    tech = {d["contract_id"] for d in deals}
    pairs = maud_duplicates(deals, {cid: t for cid, t in contracts.items() if cid not in tech})
    dropped = {m for m, _ in pairs}  # one canonical copy per agreement: the tech copy stays, maud.db is untouched
    contracts = {cid: t for cid, t in contracts.items() if cid not in dropped}
    summary = build_index(DEALS_INDEX, contracts)
    summary |= add_deals(DEALS_INDEX, deals, contracts, amendment_texts)
    summary |= {"maud_duplicates": len(pairs), "maud_duplicate_pairs": pairs}
    (DATA / "m3").mkdir(parents=True, exist_ok=True)
    _write_atomic(DATA / "m3" / "deals_summary.json", json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary))
    return 0


def _live_db() -> Path:
    return DATA / "live" / "live.db"


def _cmd_bundle(args) -> int:
    if not DEALS_INDEX.exists() or not _has_vectors(DEALS_INDEX):
        print("deals index missing or has no vectors; run `dtd build --deals` then `dtd embed --deals` first",
              file=sys.stderr)
        return 2
    if not (EDGAR / "deals.jsonl").exists():
        print(f"{EDGAR / 'deals.jsonl'} missing; run `dtd m3 corpus` first", file=sys.stderr)
        return 2
    if not (SETTINGS_PATH.exists() and LEXICON_PATH.exists()):
        print("retrieval settings or lexicon missing; run `dtd tune` and `dtd lexicon` first", file=sys.stderr)
        return 2
    contracts, amendment_texts = _deals_texts()
    try:
        summary = build_bundle(DEALS_INDEX, _live_db(), texts=contracts, amendment_texts=amendment_texts,
                               deals_jsonl=EDGAR / "deals.jsonl", settings_path=SETTINGS_PATH,
                               lexicon_path=LEXICON_PATH)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(json.dumps(summary))
    return 0


def _cmd_build(args) -> int:
    if args.deals:
        return _build_deals()
    files = sorted((RAW / "contracts").glob("*.txt")) if (RAW / "contracts").exists() else []
    if not files:
        print(f"no contracts under {RAW / 'contracts'}; run `dtd fetch` first", file=sys.stderr)
        return 2
    contracts = {p.stem: load_contract(p) for p in files}
    if not args.fixed:
        print(json.dumps(build_index(INDEX, contracts)))
        return 0
    if not INDEX.exists():
        print("the section-aware index sets the chunk size; run `dtd build` first", file=sys.stderr)
        return 2
    size = fixed_size(sqlite3.connect(INDEX))
    summary = build_index(INDEX_FIXED, contracts, chunker=fixed_chunker(size))
    conn = sqlite3.connect(INDEX_FIXED)
    conn.execute("CREATE TABLE chunking(size INTEGER NOT NULL)")
    conn.execute("INSERT INTO chunking VALUES (?)", (size,))
    conn.commit()
    conn.close()
    print(json.dumps(summary | {"size": size}))
    return 0


def _models():
    return Embedder(), Reranker


def _has_vectors(db: Path) -> bool:
    conn = vectors.connect(db)
    row = conn.execute("SELECT name FROM sqlite_master WHERE name = 'vec_meta'").fetchone()
    return bool(row) and conn.execute("SELECT vectors FROM vec_meta").fetchone()[0] > 0


def _cmd_embed(args) -> int:
    db = DEALS_INDEX if args.deals else INDEX_FIXED if args.fixed else INDEX
    if not db.exists():
        flag = " --deals" if args.deals else " --fixed" if args.fixed else ""
        print(f"{db} missing; run `dtd build{flag}` first", file=sys.stderr)
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


def _deals_ladder(contracts: dict[str, str], amendment_texts: dict[str, str]) -> Ladder:
    embedder, make_reranker = _models()
    settings = load_settings(SETTINGS_PATH)
    reranker = CachedReranker(make_reranker(settings.reranker), CACHE / "rerank.db")
    lexicon = load_lexicon(LEXICON_PATH) if LEXICON_PATH.exists() else None
    conn = vectors.connect(DEALS_INDEX)
    return Ladder(conn, contracts, embedder, reranker, lexicon, settings, amendment_texts=amendment_texts,
                  resolver=Resolver(conn))


def _eval_rung(rung: str, db: Path, name: str, ctx, out: Path = OUT, **kw) -> dict:
    ladder = _ladder(db, ctx.texts)
    return evaluate(ctx, name, lambda q, c, k: ladder.run(rung, q, c, k), out,
                    count_tokens=ladder.embedder.count_tokens,
                    extra={"settings": asdict(ladder.settings)}, **kw)


def _cmd_eval(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    rung = args.rung
    out = Path(args.out) if args.out else OUT
    if rung not in RUNGS + ("R5-llm", "R5-llm-append", "R3-fixed", "corpus"):
        print(f"unknown rung {rung}", file=sys.stderr)
        return 2
    if rung != "R1" and not _has_vectors(INDEX):
        print("no vectors in the index; run `dtd embed` first", file=sys.stderr)
        return 2
    if rung in ("R5", "R6") and not LEXICON_PATH.exists():
        print("no lexicon; run `dtd lexicon` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    if rung in ("R5-llm", "R5-llm-append"):
        path = CACHE / REWRITES
        if not path.exists():
            print("no LLM rewrites; run `dtd rewrite` first", file=sys.stderr)
            return 2
        rewrites = rewrite_all([i.query for i in ctx.items], path, runner=_refuse_new_calls)
        ladder = _ladder(INDEX, ctx.texts)

        def retrieve(q, c, k):
            r = rewrites[q]
            text = r["rewrite"] if rung == "R5-llm" else f"{q} {r['rewrite']}"
            got = ladder.run("R5", q, c, k, rewritten=text)
            return replace(got, ms=got.ms + r["api_ms"])
        n = len(rewrites)
        try:
            model = _rewrite_model(rewrites)
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        result = evaluate(ctx, rung, retrieve, out, count_tokens=ladder.embedder.count_tokens, extra={
            "settings": asdict(ladder.settings), "model": model, "queries": n,
            "input_tokens_mean": sum(r["input_tokens"] for r in rewrites.values()) / n,
            "output_tokens_mean": sum(r["output_tokens"] for r in rewrites.values()) / n})
    elif rung == "R3-fixed":
        if not INDEX_FIXED.exists() or not _has_vectors(INDEX_FIXED):
            print("fixed-size index or its vectors missing; run `dtd build --fixed` then `dtd embed --fixed`",
                  file=sys.stderr)
            return 2
        result = _eval_rung("R3", INDEX_FIXED, "R3-fixed", with_passages(ctx, INDEX_FIXED), out)
    elif rung == "corpus":
        best = _best_rung() or "R1"
        if best in ("R5", "R6") and not LEXICON_PATH.exists():
            print("no lexicon; run `dtd lexicon` first", file=sys.stderr)
            return 2
        _eval_rung("R1", INDEX, "R1-corpus", ctx, out, scope="corpus-wide", k=max(CHAR_KS), char_ks=CHAR_KS)
        ladder = _ladder(INDEX, ctx.texts)
        result = evaluate(ctx, "best-corpus", lambda q, c, k: ladder.run(best, q, c, k), out,
                          count_tokens=ladder.embedder.count_tokens, scope="corpus-wide", k=max(CHAR_KS),
                          char_ks=CHAR_KS, extra={"rung": best, "settings": asdict(ladder.settings)})
    else:
        result = _eval_rung(rung, INDEX, rung, ctx, out)
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


def _best_rung() -> str | None:
    scored = {r: json.loads((OUT / f"{r.lower()}.json").read_text())["by_split"]["report"]["recall@5"]["mean"]
              for r in RUNGS if (OUT / f"{r.lower()}.json").exists()}
    return max(scored, key=lambda r: (scored[r], -RUNGS.index(r))) if scored else None


def _cmd_disputes(args) -> int:
    rung = _best_rung()
    if rung is None:
        print("no rung results; run `dtd eval --rung ...` first", file=sys.stderr)
        return 2
    items_path = OUT / f"{rung.lower()}_items.jsonl"
    if not items_path.exists():
        print(f"{items_path.name} missing; re-run `dtd eval --rung {rung}`", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    sample = sample_misses(load_items(items_path))
    try:
        judged = judge(sample, ctx.texts, sqlite3.connect(INDEX), CACHE / "disputes.jsonl", runner=run_claude)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    # No misses to judge (only on toy data): record an empty sample instead of bootstrapping nothing.
    share = summarise(judged) if judged else {"mean": 0.0, "lo": 0.0, "hi": 0.0, "n_items": 0, "n_clusters": 0}
    doc = {"rung": rung, "model": DISPUTE_MODEL, "sample": len(judged), "share": share,
           "machine_built": True, "prompt": DISPUTE_PROMPT}
    _write_atomic(OUT / "disputes.json", json.dumps(doc, indent=2, sort_keys=True))
    print(json.dumps({"rung": rung, "share": doc["share"]["mean"]}))
    return 0


def _cmd_tune(args) -> int:
    if not INDEX.exists() or not _csv_paths() or not _has_vectors(INDEX):
        print("index, vectors or label CSVs missing; run `dtd build` then `dtd embed` first", file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    embedder, make_reranker = _models()
    doc = tune(ctx, vectors.connect(INDEX), embedder, make_reranker, CACHE / "rerank.db", SETTINGS_PATH,
                progress=lambda s: print(s, file=sys.stderr, flush=True))
    print(json.dumps({"settings": doc["settings"], "live_path_ok": doc["live_path_ok"]}))
    return 0


def _all_facts() -> dict:
    facts = build_facts(INDEX, OUT / "r1.json", _csv_paths())
    if m2_present(OUT):
        facts |= build_m2(OUT, INDEX, INDEX_FIXED, SETTINGS_PATH, LEXICON_PATH, EXTERNAL)
    if present_m5(DATA / "m5"):
        facts |= build_m5(DATA / "m5", DATA / "live", _out_m4(), OUT / "m5", PRICES, HOSTING)
    if present_m3(OUT / "m3"):
        facts |= build_m3(OUT / "m3", OUT, DATA / "m3", EDGAR, DEALS_INDEX)
    if present_m4(_out_m4()):
        facts |= build_m4(_out_m4(), OUT, DATA / "m4")
    if (DATA / "m0" / "measure.json").exists():
        facts |= build_m0(DATA / "m0", facts, DATA / "sec")
    return facts


def _cmd_facts(args) -> int:
    r1 = OUT / "r1.json"
    if not INDEX.exists() or not r1.exists() or not _csv_paths():
        print("index, r1.json or label CSVs missing; run `dtd fetch`, `dtd build` then `dtd eval` first",
              file=sys.stderr)
        return 2
    try:
        fresh = _all_facts()
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    except sqlite3.OperationalError as e:
        print(f"an index lacks a table the facts read ({e}); rerun `dtd build --fixed` and `dtd embed --fixed` "
              "(and `dtd build` then `dtd embed` for the section-aware index) before `dtd facts`", file=sys.stderr)
        return 2
    if args.check:
        stored = json.loads(FACTS.read_text(encoding="utf-8")) if FACTS.exists() else {}

        def stable(n: str) -> bool:
            return n not in UNSTABLE and not is_unstable(n)
        stale = sorted(n for n in fresh if stable(n) and stored.get(n) != fresh[n])
        gone = sorted(n for n in stored if n not in fresh and stable(n))
        if stale:
            print("stale facts: " + ", ".join(stale), file=sys.stderr)
        if gone:
            print("facts no longer built: " + ", ".join(gone), file=sys.stderr)
        return 1 if stale or gone else 0
    _write_atomic(FACTS, json.dumps(fresh, indent=2, sort_keys=True) + "\n")
    return 0


def _cmd_failures(args) -> int:
    done = []
    for rung in RUNGS:
        items = OUT / f"{rung.lower()}_items.jsonl"
        if items.exists():
            try:
                out = classify(sqlite3.connect(INDEX), items)
            except ValueError as err:
                print(f"{rung}: {err}", file=sys.stderr)
                return 2
            _write_atomic(OUT / f"failures_{rung.lower()}.json", json.dumps(out, indent=2, sort_keys=True))
            done.append(rung)
    if not done:
        print("no rung results; run `dtd eval --rung ...` first", file=sys.stderr)
        return 2
    print(json.dumps({"classified": done}))
    return 0


def _out_m4() -> Path:
    return OUT / "m4"


def _data_m4() -> Path:
    return DATA / "m4"


def _m4_recall() -> int:
    tm = DATA / "m3" / "tmachine.jsonl"
    if not (INDEX.exists() and DEALS_INDEX.exists() and _has_vectors(DEALS_INDEX) and tm.exists()
            and LEXICON_PATH.exists() and _csv_paths()):
        print("need maud.db, deals.db with vectors, data/m3/tmachine.jsonl and the lexicon; run M2 and M3 first",
              file=sys.stderr)
        return 2
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    _eval_rung("R6n", INDEX, "R6n", ctx, _out_m4())  # T-human, within agreement, next to M2's r6.json
    contracts, amendment_texts = _deals_texts()
    rows = [json.loads(line) for line in tm.read_text(encoding="utf-8").splitlines() if line]
    items = items_from_rows(rows)
    tctx = with_passages(Context(items, {"source": "T-machine (machine-built)", "items": len(items)}, contracts, {}),
                         DEALS_INDEX)
    ladder = _deals_ladder(contracts, amendment_texts)
    kw = {"count_tokens": ladder.embedder.count_tokens, "extra": {"settings": asdict(ladder.settings)}}
    evaluate(tctx, "T-R6n", lambda q, c, k: ladder.run("R6n", q, c, k), _out_m4(), **kw)
    # R7 is rerun after Task 1's resolver fixes so R7n is compared with the same resolver
    evaluate(tctx, "T-R7-corpus", lambda q, c, k: ladder.run("R7", q, None, k), _out_m4(), scope="corpus-wide", **kw)
    evaluate(tctx, "T-R7n-corpus", lambda q, c, k: ladder.run("R7n", q, None, k), _out_m4(), scope="corpus-wide", **kw)
    _write_atomic(_out_m4() / "r7_scope.json", json.dumps(scope_report(items, ladder.resolver), indent=2, sort_keys=True))
    print(json.dumps({"written": sorted(p.name for p in _out_m4().iterdir())}))
    return 0


def _m4_sets() -> int:
    tm = DATA / "m3" / "tmachine.jsonl"
    if not (INDEX.exists() and DEALS_INDEX.exists() and tm.exists() and _csv_paths()):
        print("need maud.db, deals.db, data/m3/tmachine.jsonl and the label CSVs", file=sys.stderr)
        return 2
    maud_ids = {r[0] for r in sqlite3.connect(INDEX).execute("SELECT contract_id FROM contracts")}
    th, ex = thuman_items(load_rows(_csv_paths()), maud_ids)
    rows = [json.loads(line) for line in tm.read_text(encoding="utf-8").splitlines() if line]
    deals = {d["contract_id"]: d for d in map(json.loads, (EDGAR / "deals.jsonl").read_text().splitlines()) if d}
    sample = [json.loads(line) for line in (DATA / "m0" / "sample.jsonl").read_text().splitlines() if line]
    names = [n for c in map(json.loads, (DATA / "m0" / "candidates.jsonl").read_text().splitlines()) for n in c["names"]]
    conn = sqlite3.connect(DEALS_INDEX)
    ab = abstain_items(rows, sample, deals, names, Resolver(conn), conn)
    tmi = tmachine_items(rows)
    write_items(_data_m4() / "thuman_items.jsonl", th)
    write_items(_data_m4() / "tmachine_items.jsonl", tmi)
    write_items(_data_m4() / "abstain_items.jsonl", ab)
    summary = {"thuman": len(th), "thuman_excluded": ex, "tmachine": len(tmi),
               "abstain": {g: sum(1 for i in ab if i.group == g) for g in sorted({i.group for i in ab})}}
    _write_atomic(_data_m4() / "sets_summary.json", json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary))
    return 0


def _m4_answer(args) -> int:
    if not args.set_name:
        print("--set is required: thuman, tmachine or abstain", file=sys.stderr)
        return 2
    path = _data_m4() / f"{args.set_name}_items.jsonl"
    if not path.exists():
        print(f"{path} missing; run `dtd m4 sets` first", file=sys.stderr)
        return 2
    items = [i for i in read_items(path) if args.split is None or i.split == args.split]
    if args.set_name == "thuman":
        ladder = _ladder(INDEX, {p.stem: load_contract(p) for p in sorted((RAW / "contracts").glob("*.txt"))})
    else:
        ladder = _deals_ladder(*_deals_texts())
    ledger = _data_m4() / f"answers_{args.set_name}_{args.model}.jsonl"
    try:
        summary = answer_all(items, Answerer(ladder, run_claude, args.model), ledger, workers=args.workers,
                             max_new=args.max_new)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps(summary))
    return 0


HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5-5"


def _m4_judge(args) -> int:
    items = read_items(_data_m4() / "tmachine_items.jsonl")
    jobs = [(model, items, _data_m4() / f"answers_tmachine_{model}.jsonl") for model in (HAIKU, SONNET)]
    if (_data_m4() / "abstain_items.jsonl").exists():  # the absent group: an answer is judged against the two passes
        absent = [i for i in read_items(_data_m4() / "abstain_items.jsonl") if i.group == "absent"]
        jobs.append(("abstain:" + HAIKU, absent, _data_m4() / f"answers_abstain_{HAIKU}.jsonl"))
    out = {}
    for key, its, path in jobs:
        answers = load_answers(path, key.removeprefix("abstain:"), its)
        if answers:
            try:
                out[key] = judge_all(its, answers, run_claude, _data_m4() / "judge_ledger.jsonl", workers=args.workers)
            except RuntimeError as e:
                print(str(e), file=sys.stderr)
                return 2
    _write_atomic(_data_m4() / "judge.json", json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({m: len(v) for m, v in out.items()}))
    return 0


def _m4_refute(args) -> int:
    answers = {}
    for s in ("thuman", "tmachine"):
        items = {i.item_id: i for i in read_items(_data_m4() / f"{s}_items.jsonl")}
        for iid, rec in load_answers(_data_m4() / f"answers_{s}_{HAIKU}.jsonl", HAIKU, items.values()).items():
            if items[iid].split == "report":
                answers[f"{s}:{iid}"] = rec
    try:
        out = refute_all(answers, run_claude, _data_m4() / "refute_ledger.jsonl", workers=args.workers)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    _write_atomic(_data_m4() / "refute.json", json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({"claims": len(out)}))
    return 0


def _m4_score(args) -> int:
    sets = {s: read_items(_data_m4() / f"{s}_items.jsonl") for s in ("thuman", "tmachine", "abstain")
            if (_data_m4() / f"{s}_items.jsonl").exists()}
    answers = {(s, m): load_answers(_data_m4() / f"answers_{s}_{m}.jsonl", m, sets[s]) for s in sets for m in (HAIKU, SONNET)}
    answers = {k: v for k, v in answers.items() if v}
    judge = json.loads((_data_m4() / "judge.json").read_text()) if (_data_m4() / "judge.json").exists() else {}
    refute = json.loads((_data_m4() / "refute.json").read_text()) if (_data_m4() / "refute.json").exists() else {}
    s = score_answers(sets, answers, judge, refute, (HAIKU, SONNET))
    _out_m4().mkdir(parents=True, exist_ok=True)
    _write_atomic(_out_m4() / "scores.json", json.dumps(s, indent=2, sort_keys=True))
    print(json.dumps({"written": str(_out_m4() / "scores.json")}))
    return 0


def _cmd_m4(args) -> int:
    stages = {"recall": lambda: _m4_recall(), "sets": lambda: _m4_sets(), "answer": lambda: _m4_answer(args),
              "judge": lambda: _m4_judge(args), "refute": lambda: _m4_refute(args), "score": lambda: _m4_score(args)}
    return stages[args.stage]()


def _cmd_m3(args) -> int:
    if args.stage == "corpus":
        summary = assemble(DATA / "m0", EDGAR)
        _write_atomic(EDGAR / "summary.json", json.dumps(summary, indent=2, sort_keys=True))
        print(json.dumps(summary))
    elif args.stage == "label":
        return _m3_label(args)
    elif args.stage == "eval":
        return _m3_eval()
    elif args.stage == "tier":
        return _m3_tier(args)
    return 0


def _m3_label(args) -> int:
    if not DEALS_INDEX.exists():
        print(f"{DEALS_INDEX} missing; run `dtd build --deals` first", file=sys.stderr)
        return 2
    if not (EDGAR / "deals.jsonl").exists():
        print(f"{EDGAR / 'deals.jsonl'} missing; run `dtd m3 corpus` first", file=sys.stderr)
        return 2
    deals = [json.loads(line) for line in (EDGAR / "deals.jsonl").read_text(encoding="utf-8").splitlines() if line]
    texts = {p.stem: load_contract(p) for p in sorted((EDGAR / "contracts").glob("*.txt"))}
    contracts = sorted((d["contract_id"], d["target"] or d["aliases"][0]) for d in deals)
    out = DATA / "m3"
    out.mkdir(parents=True, exist_ok=True)
    try:
        rows, summary = label_all(sqlite3.connect(DEALS_INDEX, check_same_thread=False), texts, contracts, TOPICS,
                                  PASSES, run_claude, out / "tmachine_ledger.jsonl", workers=args.workers,
                                  max_new=args.max_new)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    _write_atomic(out / "tmachine.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    _write_atomic(out / "tmachine_summary.json", json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps(summary))
    return 0


def _m3_eval() -> int:
    tm = DATA / "m3" / "tmachine.jsonl"
    if not DEALS_INDEX.exists() or not _has_vectors(DEALS_INDEX):
        print("deals index missing or has no vectors; run `dtd build --deals` then `dtd embed --deals` first",
              file=sys.stderr)
        return 2
    if not tm.exists():
        print(f"{tm} missing; run `dtd m3 label` first", file=sys.stderr)
        return 2
    if not LEXICON_PATH.exists():
        print("lexicon missing; run `dtd lexicon` first", file=sys.stderr)
        return 2
    contracts, amendment_texts = _deals_texts()
    rows = [json.loads(line) for line in tm.read_text(encoding="utf-8").splitlines() if line]
    items = items_from_rows(rows)
    if not items:
        print("no kept T-machine items to evaluate", file=sys.stderr)
        return 2
    ctx = with_passages(Context(items, {"source": "T-machine (machine-built)", "items": len(items)}, contracts, {}),
                        DEALS_INDEX)
    ladder = _deals_ladder(contracts, amendment_texts)
    out, kw = OUT / "m3", {"count_tokens": ladder.embedder.count_tokens,
                           "extra": {"settings": asdict(ladder.settings)}}
    for rung in RUNGS:
        evaluate(ctx, f"T-{rung}", lambda q, c, k, r=rung: ladder.run(r, q, c, k), out, **kw)
    bare = replace(ctx, items=items_from_rows(rows, bare=True))  # the same items, the company's name left out
    for rung in RUNGS:
        evaluate(bare, f"T-bare-{rung}", lambda q, c, k, r=rung: ladder.run(r, q, c, k), out, **kw)
    evaluate(ctx, "T-R6-corpus", lambda q, c, k: ladder.run("R6", q, None, k), out, scope="corpus-wide", **kw)
    evaluate(ctx, "T-R7-corpus", lambda q, c, k: ladder.run("R7", q, None, k), out, scope="corpus-wide", **kw)
    _write_atomic(out / "r7_scope.json", json.dumps(scope_report(items, ladder.resolver), indent=2, sort_keys=True))
    print(json.dumps({"items": len(items), "written": sorted(p.name for p in out.iterdir())}))
    return 0


def _m3_tier(args) -> int:
    missing = [r for r in RUNG_NAMES if not (OUT / f"{r.lower()}_items.jsonl").exists()]
    if not INDEX.exists():
        print(f"{INDEX} missing; run `dtd build` first", file=sys.stderr)
        return 2
    if missing:
        print(f"missing M2 items for {', '.join(missing)}; run " + ", ".join(f"`dtd eval --rung {r}`" for r in missing),
              file=sys.stderr)
        return 2
    rung_rows = {r: load_items(OUT / f"{r.lower()}_items.jsonl") for r in RUNG_NAMES}
    cids = tier_sample(rung_rows["R1"])
    topics_by_contract, keymap = {}, {}
    for cid in cids:
        topics, ids = tier_topics(rung_rows["R1"], cid)
        topics_by_contract[cid] = topics
        keymap |= {(cid, key): item_id for key, item_id in ids.items()}
    texts = {cid: load_contract(RAW / "contracts" / f"{cid}.txt") for cid in cids}
    conn = sqlite3.connect(INDEX, check_same_thread=False)
    out = DATA / "m3"
    out.mkdir(parents=True, exist_ok=True)
    try:
        rows, _ = label_all(conn, texts, [(cid, cid) for cid in cids], {}, PASSES, run_claude,
                            out / "tier_ledger.jsonl", workers=args.workers, topics_by_contract=topics_by_contract)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    spans = {pid: (s, e) for pid, s, e in conn.execute("SELECT passage_id, start_char, end_char FROM passages")}
    rows = [r for r in rows if (r["contract_id"], r["family"]) in keymap]
    if not rows:
        print("no tier items were labelled", file=sys.stderr)
        return 2
    need = {keymap[(r["contract_id"], r["family"])] for r in rows if r["status"] == "kept"}
    short = [r for r in RUNG_NAMES if need - rung_rows[r].keys()]
    if short:
        print(f"kept items missing from M2 results for {', '.join(short)}; re-run "
              + ", ".join(f"`dtd eval --rung {r}`" for r in short), file=sys.stderr)
        return 2
    report = tier_report(rows, keymap, rung_rows, spans)
    _write_atomic(out / "tier_rows.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    (OUT / "m3").mkdir(parents=True, exist_ok=True)
    _write_atomic(OUT / "m3" / "tier.json", json.dumps(report, indent=2, sort_keys=True))
    print(json.dumps({k: report[k] for k in ("match", "tau", "tau_lo", "tau_hi")}))
    return 0


def _cmd_m0(args) -> int:
    stages = M0_STAGES if args.stage == "all" else (args.stage,)
    client = None
    try:
        if NEEDS_SEC & set(stages):
            client = SecClient(DATA / "sec", sec_contact())
        out = DATA / "m0"
        for stage in stages:
            fn = getattr(m0, "stage_candidates_sample" if stage == "candidate-sample" else f"stage_{stage}")
            if stage in ("sample", "measure", "candidate-sample"):
                summary = fn(out)
            elif stage == "search":
                summary = fn(client, out, today=m0.search_end(out))  # a rerun asks the same windows
            else:
                summary = fn(client, out)
            print(json.dumps({stage: summary}), flush=True)
        return 0
    except Blocked as e:
        print(str(e), file=sys.stderr)
        return 3
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 2
    finally:
        if client is not None:
            client.close()


def _cmd_report(args) -> int:
    if not FACTS.exists():
        print("facts.json missing; run `dtd facts` first", file=sys.stderr)
        return 2
    facts = json.loads(FACTS.read_text(encoding="utf-8"))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render(facts), encoding="utf-8")
    if "m2_r1_report_recall_at_5" in facts:
        REPORT_M2.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M2.write_text(render_m2(facts), encoding="utf-8")
    if "m3_t_r1_report_recall_at_5" in facts:
        REPORT_M3.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M3.write_text(render_m3(facts), encoding="utf-8")
    if "m4_thuman_haiku_report_accuracy" in facts:
        REPORT_M4.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M4.write_text(render_m4(facts), encoding="utf-8")
    if "m5_bundle_sha" in facts:
        REPORT_M5.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M5.write_text(render_m5(facts), encoding="utf-8")
    if "m0_gate_pass" in facts:
        REPORT_M0.parent.mkdir(parents=True, exist_ok=True)
        REPORT_M0.write_text(render_m0(facts), encoding="utf-8")
    return 0


def _out_m5() -> Path:
    return OUT / "m5"


def _data_m5() -> Path:
    return DATA / "m5"


def _no_model_call(prompt, model):
    raise RuntimeError("this stage only prepares prompts; it never calls a model")


def _m5_parity(args) -> int:
    """Re-prepare every M4 answer item with the ladder M4 used and compare each prompt's hash with the ledgered
    one, so the live answer path is provably the measured one. Exit 1 if any differ."""
    sets = ("thuman", "tmachine", "abstain")
    needed = ([INDEX, DEALS_INDEX] + [_data_m4() / f"{s}_items.jsonl" for s in sets]
              + [_data_m4() / f"answers_{s}_{HAIKU}.jsonl" for s in sets])
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        print("missing: " + ", ".join(missing) + "; run M3, `dtd m4 sets` and `dtd m4 answer` first",
              file=sys.stderr)
        return 2
    out, deals = {}, None
    for s in sets:
        items = read_items(_data_m4() / f"{s}_items.jsonl")
        records = load_answers(_data_m4() / f"answers_{s}_{HAIKU}.jsonl", HAIKU, items)
        if s == "thuman":  # as `dtd m4 answer`: T-human on maud.db, the other sets on deals.db
            ladder = _ladder(INDEX, {p.stem: load_contract(p) for p in sorted((RAW / "contracts").glob("*.txt"))})
        else:
            deals = deals or _deals_ladder(*_deals_texts())
            ladder = deals
        out[s] = prompt_parity(items, Answerer(ladder, _no_model_call, HAIKU), records)
        print(json.dumps({s: {"checked": out[s]["checked"], "same": out[s]["same"]}}), file=sys.stderr, flush=True)
    _out_m5().mkdir(parents=True, exist_ok=True)
    _write_atomic(_out_m5() / "parity.json", json.dumps(out, indent=2, sort_keys=True))
    print(json.dumps({s: {"checked": v["checked"], "same": v["same"]} for s, v in out.items()}))
    return 1 if any(v["differ"] for v in out.values()) else 0


PARITY_N = 200  # questions sampled for R7n bundle-vs-deals.db parity


def _m5_recall(args) -> int:
    """T-human R6n recall over the live bundle's MAUD agreements (the evals ran on maud.db; this measures the index
    visitors get), and R7n parity between the bundle and deals.db on a stable sample of M4's questions."""
    live = _live_db()
    if not bundle_is_current(live):
        print(f"{live} missing or not matching its manifest; run `dtd bundle` first", file=sys.stderr)
        return 2
    sets = [_data_m4() / f"{s}_items.jsonl" for s in ("tmachine", "abstain")]
    if not (INDEX.exists() and _csv_paths() and LEXICON_PATH.exists() and all(p.exists() for p in sets)):
        print("need maud.db, the label CSVs, the lexicon and M4's item sets; run M2 and `dtd m4 sets` first",
              file=sys.stderr)
        return 2
    embedder, _ = _models()
    settings = load_settings(SETTINGS_PATH)
    ladder = build_live_ladder(live, embedder, load_lexicon(LEXICON_PATH), settings)
    sha = json.loads(live.with_name(MANIFEST).read_text(encoding="utf-8"))["sha256"]
    maud_ids = {r[0] for r in ladder.conn.execute("SELECT contract_id FROM deals WHERE source = 'maud'")}
    ctx = load_context(INDEX, _csv_paths(), RAW / "contracts")
    ctx = with_passages(replace(ctx, items=[i for i in ctx.items if i.contract_id in maud_ids]), live)
    evaluate(ctx, "bundle-R6n", lambda q, c, k: ladder.run("R6n", q, c, k), _out_m5(),
             count_tokens=embedder.count_tokens, extra={"settings": asdict(settings), "bundle_sha256": sha})
    items = [i for p in sets for i in read_items(p)]
    sample = sorted(items, key=lambda i: hashlib.sha1(i.item_id.encode()).hexdigest())[:PARITY_N]
    par = r7n_parity([(i.question, i.contract_id) for i in sample], ladder, _deals_ladder(*_deals_texts()))
    _write_atomic(_out_m5() / "bundle_parity.json",
                  json.dumps(par | {"bundle_sha256": sha}, indent=2, sort_keys=True))
    print(json.dumps({"bundle_r6n": str(_out_m5() / "bundle_r6n.json"),
                      "parity": {"checked": par["checked"], "same": par["same"]}}))
    return 1 if par["differ"] else 0


def _api_client(key: str):
    import anthropic
    return anthropic.Anthropic(api_key=key, max_retries=0, timeout=90.0)


def _calibration_runner(args, key: str):
    """The calibration runner: the live settings, so the sample measures what visitors get."""
    return make_api_runner(args.max_tokens, client=_api_client(key), thinking_budget=args.thinking_budget or None)


def _m5_calibrate(args) -> int:
    """Tune-split items through the API (the dtd-dev key), compared with M4's CLI answers to the same items."""
    try:
        key = anthropic_key(ENV_FILE)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    sets = {s: _data_m4() / f"{s}_items.jsonl" for s in ("thuman", "tmachine")}
    cli_ledgers = {s: _data_m4() / f"answers_{s}_{HAIKU}.jsonl" for s in sets}
    needed = [*sets.values(), *cli_ledgers.values(), PRICES, INDEX, DEALS_INDEX]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        print("calibration inputs missing: " + ", ".join(missing) + "; run M4 (`dtd m4 sets`, `dtd m4 answer`) "
              "first", file=sys.stderr)
        return 2
    sample = calibration_sample(read_items(sets["thuman"]) + read_items(sets["tmachine"]), args.n)
    th = [i for i in sample if i.set == "thuman"]
    tm = [i for i in sample if i.set == "tmachine"]
    try:
        runner = _calibration_runner(args, key)
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    th_ans = Answerer(_ladder(INDEX, {p.stem: load_contract(p) for p in sorted((RAW / "contracts").glob("*.txt"))}),
                      runner, HAIKU)  # the ladders `dtd m4 answer` used, so prompts match M4's
    tm_ans = Answerer(_deals_ladder(*_deals_texts()), runner, HAIKU)
    ledger = ledger_path(_data_m5(), HAIKU, args.max_tokens, args.thinking_budget)
    try:
        run = run_calibration([(th, th_ans), (tm, tm_ans)], ledger, workers=args.workers, max_new=args.max_new)
    except RuntimeError as e:
        print(e, file=sys.stderr)
        return 2
    api = load_answers(ledger, HAIKU, sample)
    cli_recs = load_answers(cli_ledgers["thuman"], HAIKU, th) | load_answers(cli_ledgers["tmachine"], HAIKU, tm)
    chars = {}
    for items, ans in ((th, th_ans), (tm, tm_ans)):
        for i in items:
            p = ans.prepare(i.question, i.contract_id, i.choices)
            if isinstance(p, Prepared):
                chars[i.item_id] = len(p.prompt)
    summary = summarise_calibration(sample, api, cli_recs, chars, load_prices(PRICES), args.max_tokens,
                                   args.thinking_budget)
    summary |= {"model": HAIKU, "max_tokens": args.max_tokens, "ledger": ledger.name, "run": run}
    _data_m5().mkdir(parents=True, exist_ok=True)
    _write_atomic(_data_m5() / "calibration.json", json.dumps(summary, indent=2, sort_keys=True))
    print(json.dumps({k: summary[k] for k in ("n", "paired", "errors", "truncated", "cost_usd_total", "stop_rule")}))
    return 0


def _m5_measure(args) -> int:
    """Run from the development machine against the live URL: the reference searches run here, over the same
    bundle the box serves, so the parity compares the two machines' query embeddings."""
    if not args.base:
        print("--base is required, e.g. https://deals.forn.al", file=sys.stderr)
        return 2
    items = [i for i in read_items(_data_m4() / "tmachine_items.jsonl") if i.split == "tune"]
    picked = sorted(items, key=lambda i: hashlib.sha1(i.item_id.encode()).hexdigest())
    questions = [i.question for i in picked[:args.search_n]]
    fresh = [i.question for i in picked[args.search_n:args.search_n + args.fresh]]
    cached = [e["question"] for e in json.loads(EXAMPLES.read_text(encoding="utf-8"))]
    ladder = build_live_ladder(_live_db(), Embedder(), load_lexicon(LEXICON_PATH), load_settings(SETTINGS_PATH))
    got = measure(args.base, questions, fresh, reference_hits(ladder, questions), cached=cached)
    out = _data_m5() / "server.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(out, json.dumps(got, indent=2, sort_keys=True))
    print(json.dumps({"search": got.get("search"), "rss_mb": got.get("rss_mb")}))
    return 0


M5_STAGES = {"parity": _m5_parity, "recall": _m5_recall, "calibrate": _m5_calibrate, "measure": _m5_measure}


def _cmd_m5(args) -> int:
    return M5_STAGES[args.stage](args)


def _cmd_warm(args) -> int:
    examples = json.loads(Path(args.examples).read_text(encoding="utf-8"))
    config = from_env()
    # warming is the operator's own call: it must not run out of the visitors' hourly fresh-call allowance
    desk = build_desk(replace(config, fresh_per_hour=max(config.fresh_per_hour, len(examples))))
    print(json.dumps(warm(desk, examples)))
    return 0


def _cmd_site(args) -> int:
    if not FACTS.exists():
        print("facts.json missing; run `dtd facts` first", file=sys.stderr)
        return 2
    try:
        written = render_site(json.loads(FACTS.read_text(encoding="utf-8")), SITE_DIST,
                              json.loads(EXAMPLES.read_text(encoding="utf-8")), strict=args.strict)
    except KeyError as e:
        print(f"a fact the site prints is missing: {e}", file=sys.stderr)
        return 1
    print(json.dumps({"written": [str(p) for p in written]}))
    return 0


def entry(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="dtd")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch").set_defaults(fn=_cmd_fetch)
    build = sub.add_parser("build")
    build.add_argument("--fixed", action="store_true")
    build.add_argument("--deals", action="store_true")
    build.set_defaults(fn=_cmd_build)
    embed = sub.add_parser("embed")
    embed.add_argument("--fixed", action="store_true")
    embed.add_argument("--deals", action="store_true")
    embed.set_defaults(fn=_cmd_embed)
    ev = sub.add_parser("eval")
    ev.add_argument("--rung", default="R1")
    ev.add_argument("--out", default=None, help="write results here instead of data/out")
    ev.set_defaults(fn=_cmd_eval)
    sub.add_parser("rewrite").set_defaults(fn=_cmd_rewrite)
    sub.add_parser("tune").set_defaults(fn=_cmd_tune)
    sub.add_parser("lexicon").set_defaults(fn=_cmd_lexicon)
    sub.add_parser("disputes").set_defaults(fn=_cmd_disputes)
    facts = sub.add_parser("facts")
    facts.add_argument("--check", action="store_true")
    facts.set_defaults(fn=_cmd_facts)
    sub.add_parser("failures").set_defaults(fn=_cmd_failures)
    sub.add_parser("report").set_defaults(fn=_cmd_report)
    warm_p = sub.add_parser("warm")
    warm_p.add_argument("--examples", default=str(EXAMPLES))
    warm_p.set_defaults(fn=_cmd_warm)
    site_p = sub.add_parser("site")
    site_p.add_argument("--strict", action="store_true", help="fail on any missing fact, M5 ones included (M6)")
    site_p.set_defaults(fn=_cmd_site)
    sub.add_parser("bundle").set_defaults(fn=_cmd_bundle)
    m0p = sub.add_parser("m0")
    m0p.add_argument("stage", choices=M0_STAGES + ("all", "candidate-sample"))
    m0p.set_defaults(fn=_cmd_m0)
    m3p = sub.add_parser("m3")
    m3p.add_argument("stage", choices=("corpus", "label", "eval", "tier"))
    m3p.add_argument("--workers", type=int, default=4)
    m3p.add_argument("--max-new", type=int, default=None)
    m3p.set_defaults(fn=_cmd_m3)
    m4p = sub.add_parser("m4")
    m4p.add_argument("stage", choices=("recall", "sets", "answer", "judge", "refute", "score"))
    m4p.add_argument("--set", dest="set_name", choices=("thuman", "tmachine", "abstain"), default=None)
    m4p.add_argument("--model", default="claude-haiku-4-5-20251001")
    m4p.add_argument("--split", choices=("tune", "report"), default=None)
    m4p.add_argument("--workers", type=int, default=4)
    m4p.add_argument("--max-new", type=int, default=None)
    m4p.set_defaults(fn=_cmd_m4)
    m5p = sub.add_parser("m5")
    m5p.add_argument("stage", choices=tuple(M5_STAGES))
    m5p.add_argument("--n", type=int, default=40)
    m5p.add_argument("--max-tokens", type=int, default=6144)
    m5p.add_argument("--thinking-budget", type=int, default=4096, help="extended-thinking tokens; 0 is off")
    m5p.add_argument("--workers", type=int, default=3)
    m5p.add_argument("--max-new", type=int, default=None)
    m5p.add_argument("--base", default=None)
    m5p.add_argument("--search-n", type=int, default=50)
    m5p.add_argument("--fresh", type=int, default=3)
    m5p.set_defaults(fn=_cmd_m5)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(entry())

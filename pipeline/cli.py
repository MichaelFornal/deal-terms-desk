import argparse
import json
import sys
from pathlib import Path

from evals.run_r1 import run as run_r1
from facts.build import build as build_facts
from facts.build import check as check_facts
from facts.report import render
from pipeline.fetch_maud import fetch_all
from pipeline.normalise import load_contract
from pipeline.paths import CSV_NAMES, INDEX, OUT, RAW
from retrieval.index import build_index

FACTS = Path("facts.json")
REPORT = Path("docs/m1/REPORT.md")


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


def _cmd_eval(args) -> int:
    if not INDEX.exists() or not _csv_paths():
        print("index or label CSVs missing; run `dtd fetch` then `dtd build` first", file=sys.stderr)
        return 2
    result = run_r1(INDEX, _csv_paths(), RAW / "contracts", OUT)
    print(json.dumps(result["overall"], indent=2))
    return 0


def _cmd_facts(args) -> int:
    r1 = OUT / "r1.json"
    if not INDEX.exists() or not r1.exists():
        print("index or r1.json missing; run `dtd build` then `dtd eval` first", file=sys.stderr)
        return 2
    if args.check:
        stale = check_facts(INDEX, r1, FACTS)
        if stale:
            print("stale facts: " + ", ".join(stale), file=sys.stderr)
            return 1
        return 0
    FACTS.write_text(json.dumps(build_facts(INDEX, r1), indent=2, sort_keys=True) + "\n", encoding="utf-8")
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
    sub.add_parser("eval").set_defaults(fn=_cmd_eval)
    facts = sub.add_parser("facts")
    facts.add_argument("--check", action="store_true")
    facts.set_defaults(fn=_cmd_facts)
    sub.add_parser("report").set_defaults(fn=_cmd_report)
    args = parser.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(entry())

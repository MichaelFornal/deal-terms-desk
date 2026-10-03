import json
import re
from pathlib import Path

from evals.bootstrap import split_of
from pipeline.edgar_search import START, doc_url
from pipeline.edgar_text import is_merger_agreement, normalise_edgar
from pipeline.target import norm

STOP = {"the", "and", "inc", "corp", "group", "holdings", "company", "parent", "merger"}
TICKER = re.compile(r"\(([A-Z][A-Z0-9.\-]{0,9})\)")


def contract_id_for(adsh: str) -> str:
    return "edgar_" + adsh.replace("-", "")


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(l) for l in Path(path).read_text(encoding="utf-8").splitlines() if l.strip()]


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _aliases(target: str, display_names: list[str]) -> list[str]:
    out = [norm(target)] if target else []
    for d in display_names:
        out.append(norm(re.sub(r"\(.*?\)|/[A-Z]{2,3}/?", " ", d)))  # "ARI NETWORK SERVICES INC /WI"
        out += [m.group(1).lower() for m in TICKER.finditer(d) if not m.group(1).startswith("CIK")]
    keep = []
    for a in out:
        if len(a) >= 4 and a not in STOP and a not in keep:
            keep.append(a)
    return keep


def assemble(m0_dir: Path, out_dir: Path) -> dict:
    m0_dir, out_dir = Path(m0_dir), Path(out_dir)
    deals = [d for d in _read_jsonl(m0_dir / "deals.jsonl") if d["tech"] and d["signed"] >= START.isoformat()]
    docs = [d for d in _read_jsonl(m0_dir / "docs.jsonl") if not d.get("missing")]
    by_adsh = {d["adsh"]: d for d in docs}
    rows, excluded, n_amend, n_alias = [], 0, 0, 0
    for d in sorted(deals, key=lambda d: d["canonical"]["adsh"]):
        c = d["canonical"]
        text = normalise_edgar(Path(c["text"]).read_text(encoding="utf-8"))
        if not is_merger_agreement(text):
            excluded += 1
            continue
        cid = contract_id_for(c["adsh"])
        _write(out_dir / "contracts" / f"{cid}.txt", text)
        doc = by_adsh.get(c["adsh"], {})
        names = [n for cik, n in zip(doc.get("ciks", []), doc.get("names", [])) if cik == d["target_cik"]]
        amends = []
        for a in docs:
            if a.get("amendment") and a.get("company") and a.get("parent") and \
                    [norm(a["company"]), norm(a["parent"])] == d["key"][:2]:
                acid = contract_id_for(a["adsh"])
                _write(out_dir / "amendments" / f"{acid}.txt", normalise_edgar(Path(a["text"]).read_text(encoding="utf-8")))
                amends.append({"contract_id": acid, "file_date": a["file_date"], "url": doc_url(a)})
        aliases = _aliases(doc.get("company") or "", names)
        n_amend += len(amends)
        n_alias += len(aliases)
        rows.append({"contract_id": cid, "target": doc.get("company"), "parent": doc.get("parent"),
                     "target_cik": d["target_cik"], "signed": d["signed"], "url": doc_url(c), "aliases": aliases,
                     "amendments": sorted(amends, key=lambda a: a["file_date"]), "split": split_of(cid)})
    _write(out_dir / "deals.jsonl", "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows))
    return {"deals": len(deals), "kept": len(rows), "excluded_not_merger": excluded, "amendments": n_amend,
            "aliases": n_alias}

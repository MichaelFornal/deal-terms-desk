import csv
import hashlib
import os
import urllib.error
import urllib.request
from pathlib import Path

from pipeline.ledger import Ledger
from pipeline.paths import CSV_NAMES, MAUD_BASE

USER_AGENT = "deal-terms-desk/0.1 (+https://github.com/MichaelFornal)"
PSEUDO_CONTRACT = "<RARE_ANSWERS>"


def fetch(url: str, dest: Path, ledger: Ledger, opener=urllib.request.urlopen) -> dict:
    """Download url to dest atomically. Skips work already recorded in the ledger."""
    done = ledger.get(url)
    if done and done["status"] == "missing":
        return done
    if done and dest.exists() and dest.stat().st_size == done["bytes"]:
        return done
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    size = 0
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener(req) as resp, open(part, "wb") as f:
            while chunk := resp.read(1 << 16):
                f.write(chunk)
                digest.update(chunk)
                size += len(chunk)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            rec = {"url": url, "status": "missing"}
            ledger.put(rec)
            return rec
        raise
    except Exception:
        # Clean up .part file on any error (including ConnectionError)
        part.unlink(missing_ok=True)
        raise
    os.replace(part, dest)
    rec = {"url": url, "status": "ok", "bytes": size, "sha256": digest.hexdigest()}
    ledger.put(rec)
    return rec


def contract_names(csv_paths: list[Path]) -> list[str]:
    csv.field_size_limit(10**9)
    names: set[str] = set()
    for p in csv_paths:
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if row["contract_name"] != PSEUDO_CONTRACT:
                    names.add(row["contract_name"])
    return sorted(names)


def fetch_all(raw_dir: Path, opener=urllib.request.urlopen) -> dict:
    raw_dir = Path(raw_dir)
    ledger = Ledger(raw_dir / "ledger.jsonl")
    summary = {"ok": 0, "missing": 0}
    csv_paths = []
    for name in CSV_NAMES:
        dest = raw_dir / name
        rec = fetch(f"{MAUD_BASE}/{name}", dest, ledger, opener)
        summary[rec["status"]] += 1
        if rec["status"] == "ok":
            csv_paths.append(dest)
    for name in contract_names(csv_paths):
        rec = fetch(f"{MAUD_BASE}/contracts/{name}.txt", raw_dir / "contracts" / f"{name}.txt", ledger, opener)
        summary[rec["status"]] += 1
    return summary

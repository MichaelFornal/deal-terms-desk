import json
from pathlib import Path

from pipeline.edgar_search import START
from pipeline.m0 import CANDIDATE_SPECS, FAMILIES, SAMPLE
from pipeline.target import TECH_SIC

GATE_AGREEMENTS = 100
GATE_FAMILY_SHARE = 0.5
ADOPTED_FAMILY = "employee_benefits"  # replaces earn-outs as the third lead family; see the PRD note before §10
COPIED = ("search_docs", "ex21_docs", "ex2_bare_docs", "candidates", "fetched", "missing", "fetch_errors", "not_merger", "keyed",
          "company_parsed", "amendment_docs", "deals", "orphan_restated", "deals_resolved", "tech_deals", "tech_targets",
          "tech_multi_copy", "tech_amended", "sample", "press_fee", "press_release", "press_both",
          "press_restated", "press_unusable", "passages_total", "passages_mean", "passages_median", "lead_model")


def _rate(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def _rows(path: Path) -> list[dict]:
    """Complete JSONL rows; a torn last line (a kill mid-append) is ignored, as the Ledger does."""
    if not path.exists():
        return []
    data = path.read_text(encoding="utf-8")
    lines = data.split("\n")[:-1]  # the last piece is "" after a final newline, or a torn line
    return [json.loads(line) for line in lines if line.strip()]


def access(sec_dir: Path) -> dict:
    """What the sec.gov client's own logs show: requests answered, the smallest spacing, refusals and
    server errors met."""
    sec_dir = Path(sec_dir)
    if not (sec_dir / "ledger.jsonl").exists():
        return {}
    rows = [r for r in _rows(sec_dir / "ledger.jsonl") if r.get("status") in ("ok", "missing")]
    errors = _rows(sec_dir / "server_errors.jsonl")
    # Every request start counts, answered or not. Hand-appended rows carry approximate times: left out of the gaps.
    starts = sorted([r["at"] for r in rows if "at" in r]
                    + [r["at"] for r in errors if "at" in r and not r.get("recorded_later")])
    gaps = [b - a for a, b in zip(starts, starts[1:])]
    return {"m0_sec_requests": len(rows),
            "m0_min_request_gap_s": round(min(gaps), 3) if gaps else None,
            "m0_blocked_events": len(_rows(sec_dir / "blocked_events.jsonl")),
            "m0_server_errors": len(errors),
            "m0_server_errors_recorded_later": sum(1 for r in errors if r.get("recorded_later"))}


def build_m0(m0_dir: Path, facts: dict | None = None, sec_dir: Path | None = None) -> dict:
    m = json.loads((Path(m0_dir) / "measure.json").read_text(encoding="utf-8"))
    f = {f"m0_{k}": m[k] for k in COPIED}
    f["m0_company_parsed_rate"] = _rate(m["company_parsed"], m["fetched"])
    f["m0_target_resolved_rate"] = _rate(m["deals_resolved"], m["deals"])
    f["m0_duplicate_rate"] = _rate(m["tech_multi_copy"], m["tech_deals"])
    f["m0_amendment_rate"] = _rate(m["tech_amended"], m["tech_deals"])
    f["m0_press_restated_share"] = _rate(m["press_restated"], m["press_both"])
    for fam in FAMILIES:
        f[f"m0_sample_{fam}_present"] = m["family_present"][fam]
        f[f"m0_sample_{fam}_share"] = _rate(m["family_present"][fam], m["sample"])
        f[f"m0_sample_{fam}_regex"] = m["family_regex"][fam]
        f[f"m0_sample_{fam}_truncated"] = m["family_truncated"][fam]
    f["m0_sample_target"] = SAMPLE
    f["m0_start"] = START.isoformat()
    f["m0_sic_ranges"] = ", ".join(f"{lo}–{hi}" for lo, hi in TECH_SIC)
    f["m0_gate_agreements_min"] = GATE_AGREEMENTS
    f["m0_gate_family_share_min"] = GATE_FAMILY_SHARE
    f["m0_gate_count_ok"] = m["tech_deals"] >= GATE_AGREEMENTS
    f["m0_gate_families_ok"] = m["sample"] > 0 and all(
        m["family_present"][fam] / m["sample"] >= GATE_FAMILY_SHARE for fam in FAMILIES)
    f["m0_gate_pass"] = f["m0_gate_count_ok"] and f["m0_gate_families_ok"]
    cpath = Path(m0_dir) / "candidate_measure.json"
    if cpath.exists():
        c = json.loads(cpath.read_text(encoding="utf-8"))
        for sp in CANDIDATE_SPECS:
            n = sp.name
            f[f"m0_candidate_{n}_present"] = c["family_present"][n]
            f[f"m0_candidate_{n}_share"] = _rate(c["family_present"][n], c["sample"])
            f[f"m0_candidate_{n}_regex"] = c["family_regex"][n]
            f[f"m0_candidate_{n}_truncated"] = c["family_truncated"][n]
        f["m0_candidate_sample"] = c["sample"]
        f["m0_adopted_family"] = ADOPTED_FAMILY
        kept = [(m["family_present"][fam], m["sample"]) for fam in FAMILIES if fam != "contingent_consideration"]
        kept.append((c["family_present"][ADOPTED_FAMILY], c["sample"]))
        f["m0_gate_families_ok_adopted"] = all(s > 0 and p / s >= GATE_FAMILY_SHARE for p, s in kept)
        f["m0_gate_pass_adopted"] = f["m0_gate_count_ok"] and f["m0_gate_families_ok_adopted"]
    if facts and facts.get("m2_index_bytes") and facts.get("m2_vec_passages"):
        f["m0_estimate_index_bytes"] = round(m["passages_total"] * facts["m2_index_bytes"] / facts["m2_vec_passages"])
    if sec_dir is not None:
        f |= access(sec_dir)
    return dict(sorted(f.items()))

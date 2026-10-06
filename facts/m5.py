import math
from pathlib import Path

from facts.m2 import _ci, _json
from service.prices import load_prices

BUDGET_USD_MONTH = 10.0  # PRD §1: the hard cap, hosting plus model calls
HOSTING_NEEDS = ("currency", "price_month", "extras_month", "day_cap_usd", "checked")


def present_m5(data_m5: Path) -> bool:
    """M5 facts exist once the live bundle has been built (data/live sits beside data/m5)."""
    return (Path(data_m5).parent / "live" / "bundle.json").exists()


def build_m5(data_m5, live_dir, out_m4, out_m5, prices_path, hosting_path) -> dict:
    """Each section appears once its input exists, so the facts grow as M5's measurements land. The site shows
    a missing M5 fact as pending until M6, where `dtd site --strict` requires them all."""
    data_m5, live_dir, out_m4, out_m5 = map(Path, (data_m5, live_dir, out_m4, out_m5))
    b = _json(live_dir / "bundle.json")
    f: dict = {"m5_bundle_sha": b["sha256"], "m5_bundle_bytes": b["bytes"], "m5_bundle_contracts": b["contracts"],
               "m5_bundle_passages": b["passages"]}
    for r, name in (("r6n", "m5_live_r6n"), ("t_r7n_corpus", "m5_live_t_r7n_corpus")):
        if (out_m4 / f"{r}.json").exists():
            lat = _json(out_m4 / f"{r}.json")["latency_ms"]
            f[f"{name}_latency_ms_p50"], f[f"{name}_latency_ms_p95"] = round(lat["p50"], 2), round(lat["p95"], 2)
    if (out_m5 / "parity.json").exists():  # dtd m5 parity: one block per M4 answer set
        sets = _json(out_m5 / "parity.json").values()
        f["m5_prompt_parity_checked"] = sum(v["checked"] for v in sets)
        f["m5_prompt_parity_same"] = sum(v["same"] for v in sets)
    if (out_m5 / "bundle_parity.json").exists():
        p = _json(out_m5 / "bundle_parity.json")
        f["m5_bundle_parity_checked"], f["m5_bundle_parity_same"] = p["checked"], p["same"]
    if (out_m5 / "bundle_r6n.json").exists():
        _ci(f, "m5_bundle_r6n_report_recall_at_5", _json(out_m5 / "bundle_r6n.json")["by_split"]["report"]["recall@5"])

    p = load_prices(prices_path)
    f |= {"m5_price_model": p.model, "m5_price_input_per_mtok": p.input, "m5_price_output_per_mtok": p.output,
          "m5_price_cache_write_per_mtok": p.cache_write, "m5_price_cache_read_per_mtok": p.cache_read,
          "m5_price_checked": p.checked, "m5_price_source": p.source}

    if Path(hosting_path).exists():  # deploy/hosting.json arrives with the deploy task
        h = _json(hosting_path)
        if all(h.get(k) is not None for k in HOSTING_NEEDS):
            if h["currency"] != "USD":
                raise ValueError(f"deploy/hosting.json is priced in {h['currency']}; the cost of record is USD")
            usd = round(h["price_month"] + h["extras_month"], 2)
            f |= {"m5_hosting_usd_month": usd,
                  "m5_model_cap_usd": round(h.get("budget_usd_month", BUDGET_USD_MONTH) - usd, 2),
                  "m5_day_cap_usd": h["day_cap_usd"], "m5_hosting_checked": h["checked"]}

    if (data_m5 / "calibration.json").exists():
        c = _json(data_m5 / "calibration.json")  # Task 5's summarise()
        f |= {"m5_calibration_n": c["n"], "m5_calibration_called": c["called"],
              "m5_api_tokens_in_mean": c["api_tokens_in_mean"], "m5_api_tokens_in_p95": c["api_tokens_in_p95"],
              "m5_api_tokens_out_mean": c["api_tokens_out_mean"], "m5_api_tokens_out_p95": c["api_tokens_out_p95"],
              "m5_api_tokens_out_p99": c["api_tokens_out_p99"],
              "m5_cost_per_answer_mean": c["cost_per_answer_mean"], "m5_cost_per_answer_p95": c["cost_per_answer_p95"],
              "m5_calibration_cost_usd_total": c["cost_usd_total"],
              "m5_calibration_state_agreement": c["state_agreement"],
              "m5_calibration_accuracy_api": c["thuman_accuracy"]["api"],
              "m5_calibration_accuracy_cli": c["thuman_accuracy"]["cli"],
              "m5_calibration_thuman_n": c["thuman_accuracy"]["n"],  # the accuracy's n: a count, so no tier label
              "m5_calibration_gate_pass_api": c["gate_pass_rate"]["api"],
              "m5_calibration_gate_pass_cli": c["gate_pass_rate"]["cli"],
              "m5_calibration_truncated": c["truncated"], "m5_calibration_estimator_ok": c["worst_case_ok"],
              "m5_calibration_stop_rule": c["stop_rule"]["verdict"]}
        if c.get("thinking_budget", 0) > 0:  # a plain measurement of the run's setting; none for a no-thinking or older run
            f["m5_thinking_budget_tokens"] = c["thinking_budget"]
        if "m5_model_cap_usd" in f and c["cost_per_answer_mean"]:
            f["m5_answers_per_month"] = math.floor(f["m5_model_cap_usd"] / c["cost_per_answer_mean"])

    if (data_m5 / "server.json").exists():
        s = _json(data_m5 / "server.json")
        for part in ("search", "ask_cached", "ask_fresh"):
            for q in ("p50", "p95"):
                f[f"m5_server_{part}_latency_ms_{q}"] = s[part]["server"][q]
                f[f"m5_e2e_{part}_latency_ms_{q}"] = s[part]["e2e"][q]
            f[f"m5_server_{part}_n"], f[f"m5_e2e_{part}_n"] = s[part]["server"]["n"], s[part]["e2e"]["n"]
        if "errors" in s:
            f["m5_server_errors"] = s["errors"]
        if "misrouted" in s:  # answers served other than meant: counted in errors, timed under what served them
            f["m5_server_fresh_served_from_cache"] = s["misrouted"]["fresh_served_from_cache"]
            f["m5_server_cached_answered_live"] = s["misrouted"]["cached_answered_live"]
        f["m5_server_rss_mb"] = s["rss_mb"]
        if "embed_parity" in s:
            e = s["embed_parity"]
            f["m5_server_embed_parity"], f["m5_server_embed_parity_n"] = e["rate"], e["n"]
            f["m5_server_embed_parity_same"] = e["same"]

    if (data_m5 / "cap_trip.json").exists():
        t = _json(data_m5 / "cap_trip.json")
        f |= {"m5_cap_trip_budget_reached": t["budget_reached"], "m5_cap_trip_budget_cached": t["budget_cached"],
              "m5_cap_trip_ledger_unchanged": t["ledger_unchanged"]}
    return f

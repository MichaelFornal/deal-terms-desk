import json
import math
from pathlib import Path

from facts.m2 import is_unstable
from facts.m5 import build_m5, present_m5
from service.prices import load_prices

PRICES = Path("service/prices.json")
HOSTING_EMPTY = {"provider": "Hetzner Cloud", "plan": "CAX11", "eur_month": 4.49, "extras_eur_month": None,
                 "eur_usd": None, "eur_usd_date": None, "eur_usd_source": None, "budget_usd_month": 10.0,
                 "day_cap_usd": None, "checked": None}


def _write(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")
    return p


def dirs(tmp_path):
    data_m5, live, out_m4, out_m5 = (tmp_path / "data" / "m5", tmp_path / "data" / "live", tmp_path / "out" / "m4",
                                     tmp_path / "out" / "m5")
    _write(live / "bundle.json", {"sha256": "ab" * 32, "bytes": 1000, "contracts": 3, "passages": 40,
                                  "rebuilt": True})
    return data_m5, live, out_m4, out_m5


def test_present_needs_the_bundle(tmp_path):
    assert not present_m5(tmp_path / "data" / "m5")
    data_m5, *_ = dirs(tmp_path)
    assert present_m5(data_m5)


def test_with_only_the_bundle_the_later_sections_are_absent(tmp_path):
    data_m5, live, out_m4, out_m5 = dirs(tmp_path)
    hosting = _write(tmp_path / "hosting.json", HOSTING_EMPTY)
    f = build_m5(data_m5, live, out_m4, out_m5, PRICES, hosting)
    assert f["m5_bundle_bytes"] == 1000 and f["m5_bundle_sha"] == "ab" * 32
    assert f["m5_price_model"] == load_prices(PRICES).model
    later = ("m5_hosting", "m5_model_cap", "m5_calibration", "m5_server", "m5_cap_trip", "m5_answers_per_month",
             "m5_prompt_parity", "m5_bundle_parity", "m5_bundle_r6n")
    assert not [k for k in f if k.startswith(later)]


def test_every_section_once_its_input_exists(tmp_path):
    data_m5, live, out_m4, out_m5 = dirs(tmp_path)
    for name in ("r6n", "t_r7n_corpus"):
        _write(out_m4 / f"{name}.json", {"latency_ms": {"p50": 46.39566600235412, "p95": 300.0}})
    _write(out_m5 / "parity.json", {"thuman": {"checked": 6, "same": 6, "differ": []},
                                    "tmachine": {"checked": 3, "same": 3, "differ": []},
                                    "abstain": {"checked": 1, "same": 1, "differ": []}})
    _write(out_m5 / "bundle_parity.json", {"checked": 5, "same": 5, "differ": [], "bundle_sha256": "ab" * 32})
    _write(out_m5 / "bundle_r6n.json", {"by_split": {"report": {"recall@5": {"mean": 0.6, "lo": 0.5, "hi": 0.7}}}})
    _write(data_m5 / "calibration.json", {  # the shape of Task 5's summarise(), plus what dtd m5 calibrate adds
        "n": 40, "called": 38, "errors": 2, "missing": 0, "truncated": 1, "refused": 0,
        "api_tokens_in_mean": 4000.0, "api_tokens_in_p95": 6000, "api_tokens_out_mean": 300.0,
        "api_tokens_out_p95": 500, "api_tokens_out_p99": 600, "cost_usd_total": 0.8, "cost_per_answer_mean": 0.02,
        "cost_per_answer_p95": 0.03, "worst_case_ok": True, "worst_case_min_margin_usd": 0.001, "paired": 38,
        "gate_pass_rate": {"api": 0.88, "cli": 0.86}, "state_agreement": 0.9,
        "thuman_accuracy": {"api": 0.6, "cli": 0.62, "diff": -0.02, "n": 19},
        "stop_rule": {"state_agreement_min": 0.8, "accuracy_diff_max": 0.15, "verdict": "go", "reasons": []},
        "model": "claude-haiku-4-5-20251001", "max_tokens": 1024})
    span = {"n": 50, "p50": 20.0, "p95": 40.0}
    _write(data_m5 / "server.json", {
        "search": {"e2e": {"n": 50, "p50": 120.0, "p95": 200.0}, "server": span},
        "ask_cached": {"e2e": span, "server": span, "states": {}}, "ask_fresh": {"e2e": span, "server": span, "states": {}},
        "rss_mb": 900.0, "embed_parity": {"n": 50, "same": 49, "rate": 0.98}})
    _write(data_m5 / "cap_trip.json", {"budget_reached": True, "budget_cached": True, "ledger_unchanged": True,
                                       "health_budget": "reached"})
    hosting = _write(tmp_path / "hosting.json", dict(HOSTING_EMPTY, eur_usd=1.1, eur_usd_date="2026-10-10",
                                                     eur_usd_source="ECB reference rate", day_cap_usd=0.5,
                                                     checked="2026-10-10"))
    f = build_m5(data_m5, live, out_m4, out_m5, PRICES, hosting)
    usd = round(4.49 * 1.1, 2)
    assert f["m5_hosting_usd_month"] == usd and f["m5_model_cap_usd"] == round(10.0 - usd, 2)
    assert f["m5_day_cap_usd"] == 0.5 and f["m5_answers_per_month"] == math.floor(round(10.0 - usd, 2) / 0.02)
    assert f["m5_bundle_r6n_report_recall_at_5"] == 0.6 and f["m5_bundle_r6n_report_recall_at_5_lo"] == 0.5
    assert f["m5_prompt_parity_same"] == 10 and f["m5_prompt_parity_checked"] == 10 and f["m5_bundle_parity_checked"] == 5
    assert f["m5_live_r6n_latency_ms_p95"] == 300.0 and f["m5_live_t_r7n_corpus_latency_ms_p50"] == 46.4
    assert f["m5_api_tokens_in_mean"] == 4000.0 and f["m5_api_tokens_out_p99"] == 600
    assert f["m5_calibration_stop_rule"] == "go" and f["m5_calibration_accuracy_cli"] == 0.62
    assert f["m5_calibration_gate_pass_api"] == 0.88 and f["m5_calibration_estimator_ok"] is True
    assert f["m5_server_search_latency_ms_p95"] == 40.0 and f["m5_e2e_search_latency_ms_p95"] == 200.0
    assert f["m5_server_rss_mb"] == 900.0 and f["m5_server_embed_parity"] == 0.98
    assert f["m5_cap_trip_budget_reached"] is True and f["m5_cap_trip_ledger_unchanged"] is True


def test_wall_clock_facts_are_unstable_for_the_check():
    assert is_unstable("m5_server_rss_mb") and is_unstable("m5_server_search_latency_ms_p95")
    assert is_unstable("m5_live_r6n_latency_ms_p50") and not is_unstable("m5_bundle_bytes")

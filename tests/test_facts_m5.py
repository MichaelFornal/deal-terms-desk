import json
import math
from pathlib import Path

from facts.labels import tier_label
from facts.m2 import is_unstable
from facts.m5 import build_m5, present_m5
from service.prices import load_prices

PRICES = Path("service/prices.json")
HOSTING_FULL = {"provider": "Hetzner Cloud", "plan": "CX23", "location": "fsn1", "currency": "USD",
                "price_month": 6.49, "extras_month": 0.60, "extras_note": "primary IPv4 address", "vat_rate": 0.0,
                "budget_usd_month": 10.0, "day_cap_usd": 0.29, "source": "Hetzner Cloud API", "checked": "2026-10-06"}
HOSTING_EMPTY = dict(HOSTING_FULL, day_cap_usd=None, checked=None)


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


def every_input(tmp_path, calibration: dict | None = None, server: dict | None = None) -> tuple:
    """Every input build_m5 reads, so it emits every M5 fact. `calibration` and `server` replace top-level fields
    of calibration.json and server.json. -> the build_m5 arguments."""
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
        "model": "claude-haiku-4-5-20251001", "max_tokens": 6144, "thinking_budget": 4096} | (calibration or {}))
    span = {"n": 50, "p50": 20.0, "p95": 40.0}
    _write(data_m5 / "server.json", {
        "search": {"e2e": {"n": 50, "p50": 120.0, "p95": 200.0}, "server": span},
        "ask_cached": {"e2e": span, "server": span, "states": {}}, "ask_fresh": {"e2e": span, "server": span, "states": {}},
        "rss_mb": 900.0, "embed_parity": {"n": 50, "same": 49, "rate": 0.98}, "errors": 3,
        "misrouted": {"fresh_served_from_cache": 1, "cached_answered_live": 2}} | (server or {}))
    _write(data_m5 / "cap_trip.json", {"budget_reached": True, "budget_cached": True, "ledger_unchanged": True,
                                       "health_budget": "reached"})
    hosting = _write(tmp_path / "hosting.json", HOSTING_FULL)
    return data_m5, live, out_m4, out_m5, PRICES, hosting


def test_every_section_once_its_input_exists(tmp_path):
    f = build_m5(*every_input(tmp_path))
    usd = 7.09
    assert f["m5_hosting_usd_month"] == usd and f["m5_model_cap_usd"] == round(10.0 - usd, 2)
    assert f["m5_model_cap_usd"] == 2.91 and f["m5_day_cap_usd"] == 0.29 and f["m5_answers_per_month"] == math.floor(round(10.0 - usd, 2) / 0.02)
    assert f["m5_bundle_r6n_report_recall_at_5"] == 0.6 and f["m5_bundle_r6n_report_recall_at_5_lo"] == 0.5
    assert f["m5_prompt_parity_same"] == 10 and f["m5_prompt_parity_checked"] == 10 and f["m5_bundle_parity_checked"] == 5
    assert f["m5_live_r6n_latency_ms_p95"] == 300.0 and f["m5_live_t_r7n_corpus_latency_ms_p50"] == 46.4
    assert f["m5_api_tokens_in_mean"] == 4000.0 and f["m5_api_tokens_out_p99"] == 600
    assert f["m5_calibration_stop_rule"] == "go" and f["m5_calibration_accuracy_cli"] == 0.62
    assert f["m5_thinking_budget_tokens"] == 4096 and tier_label("m5_thinking_budget_tokens") is None
    assert not is_unstable("m5_thinking_budget_tokens")
    assert f["m5_calibration_gate_pass_api"] == 0.88 and f["m5_calibration_estimator_ok"] is True
    assert f["m5_server_search_latency_ms_p95"] == 40.0 and f["m5_e2e_search_latency_ms_p95"] == 200.0
    assert f["m5_server_search_n"] == 50 and f["m5_e2e_search_n"] == 50 and f["m5_server_ask_fresh_n"] == 50
    assert f["m5_e2e_ask_cached_n"] == 50
    assert f["m5_server_rss_mb"] == 900.0 and f["m5_server_embed_parity"] == 0.98 and f["m5_server_errors"] == 3
    assert f["m5_server_fresh_served_from_cache"] == 1 and f["m5_server_cached_answered_live"] == 2
    assert f["m5_cap_trip_budget_reached"] is True and f["m5_cap_trip_ledger_unchanged"] is True


def test_wall_clock_facts_are_unstable_for_the_check():
    assert is_unstable("m5_server_rss_mb") and is_unstable("m5_server_search_latency_ms_p95")
    assert is_unstable("m5_live_r6n_latency_ms_p50") and not is_unstable("m5_bundle_bytes")


def test_every_measurement_run_key_is_unstable_and_the_rest_is_stable():
    for k in ("m5_server_search_n", "m5_server_errors", "m5_server_embed_parity", "m5_server_embed_parity_n",
              "m5_server_fresh_served_from_cache", "m5_server_cached_answered_live",
              "m5_e2e_search_latency_ms_p95", "m5_e2e_ask_fresh_n"):
        assert is_unstable(k), k
    for k in ("m5_bundle_sha", "m5_prompt_parity_same", "m5_calibration_n"):
        assert not is_unstable(k), k


def test_a_calibration_without_thinking_emits_no_budget(tmp_path):
    args = every_input(tmp_path)
    path = args[0] / "calibration.json"
    old = json.loads(path.read_text())
    for budget in (0, None):  # a no-thinking run (0), and an older file with no field
        path.write_text(json.dumps(old | {"thinking_budget": 0} if budget == 0 else
                                   {k: v for k, v in old.items() if k != "thinking_budget"}))
        assert "m5_thinking_budget_tokens" not in build_m5(*args)


def test_hosting_in_another_currency_raises(tmp_path):
    import pytest
    ins = list(every_input(tmp_path))
    _write(ins[5], dict(HOSTING_FULL, currency="EUR"))
    with pytest.raises(ValueError, match="EUR"):
        build_m5(*ins)


def test_hosting_with_a_null_field_is_skipped(tmp_path):
    ins = list(every_input(tmp_path))
    _write(ins[5], dict(HOSTING_FULL, price_month=None))
    f = build_m5(*ins)
    assert not any(k.startswith("m5_hosting") for k in f) and "m5_model_cap_usd" not in f

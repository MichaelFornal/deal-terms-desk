import json

from facts.m0 import GATE_AGREEMENTS, build_m0

FAM = ("equity_awards", "termination_fee", "contingent_consideration")


def measure(tmp_path, tech=150, present=(30, 29, 4), sample=30):
    m = {"search_docs": 9000, "ex21_docs": 4000, "ex2_bare_docs": 55, "candidates": 600, "fetched": 590, "missing": 10,
         "fetch_errors": 3, "not_merger": 20, "keyed": 540, "tech_targets": 140,
         "company_parsed": 560, "amendment_docs": 40, "orphan_restated": 7, "deals": 300, "deals_resolved": 240, "tech_deals": tech,
         "tech_multi_copy": 90, "tech_amended": 12, "sample": sample,
         "family_present": dict(zip(FAM, present)), "family_regex": dict(zip(FAM, (30, 30, 9))),
         "family_truncated": dict(zip(FAM, (1, 2, 3))), "press_unusable": 4,
         "press_fee": 28, "press_release": 27, "press_both": 26, "press_restated": 13,
         "passages_total": 40000, "passages_mean": 266.7, "passages_median": 250, "lead_model": "m"}
    (tmp_path / "measure.json").write_text(json.dumps(m))
    return tmp_path


def test_rates_and_the_gate(tmp_path):
    f = build_m0(measure(tmp_path))
    assert f["m0_target_resolved_rate"] == 0.8 and f["m0_duplicate_rate"] == 0.6
    assert f["m0_press_restated_share"] == 0.5
    assert f["m0_gate_count_ok"] is True and f["m0_gate_families_ok"] is False and f["m0_gate_pass"] is False
    assert f["m0_gate_agreements_min"] == GATE_AGREEMENTS
    assert all(k.startswith("m0_") for k in f)


def test_new_measure_keys_are_copied(tmp_path):
    f = build_m0(measure(tmp_path))
    assert (f["m0_keyed"], f["m0_not_merger"], f["m0_fetch_errors"], f["m0_tech_targets"],
            f["m0_press_unusable"]) == (540, 20, 3, 140, 4)
    assert f["m0_sample_termination_fee_truncated"] == 2


def test_gate_passes_when_both_conditions_hold(tmp_path):
    f = build_m0(measure(tmp_path, present=(30, 29, 15)))
    assert f["m0_gate_pass"] is True


def test_too_few_agreements_fail_the_gate(tmp_path):
    f = build_m0(measure(tmp_path, tech=GATE_AGREEMENTS - 1, present=(30, 30, 30)))
    assert f["m0_gate_count_ok"] is False and f["m0_gate_pass"] is False


def test_empty_sample_fails_families_without_dividing_by_zero(tmp_path):
    f = build_m0(measure(tmp_path, tech=0, present=(0, 0, 0), sample=0))
    assert f["m0_gate_families_ok"] is False and f["m0_sample_equity_awards_share"] is None


def test_index_estimate_uses_m2_bytes_per_passage(tmp_path):
    f = build_m0(measure(tmp_path), {"m2_index_bytes": 1000, "m2_vec_passages": 10})
    assert f["m0_estimate_index_bytes"] == 40000 * 100


def test_the_sec_access_record_comes_from_the_ledger(tmp_path):
    sec = tmp_path / "sec"
    sec.mkdir()
    rows = [{"url": "a", "status": "ok", "at": 100.0}, {"url": "b", "status": "missing", "at": 100.5004},
            {"url": "c", "status": "ok", "at": 101.6}]
    (sec / "ledger.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows) + '{"url": "d", "sta')
    (sec / "blocked_events.jsonl").write_text(json.dumps({"at": 102.0, "status": 403, "url": "d"}) + "\n")
    errs = [{"at": 99.0, "status": 500, "url": "a"}, {"at": 99.5, "status": 503, "url": "a"}]
    (sec / "server_errors.jsonl").write_text("".join(json.dumps(r) + "\n" for r in errs))
    f = build_m0(measure(tmp_path), sec_dir=sec)
    assert (f["m0_sec_requests"], f["m0_min_request_gap_s"], f["m0_blocked_events"]) == (3, 0.5, 1)
    assert f["m0_server_errors"] == 2


def test_the_access_record_without_refusals_or_a_second_request(tmp_path):
    sec = tmp_path / "sec"
    sec.mkdir()
    (sec / "ledger.jsonl").write_text(json.dumps({"url": "a", "status": "ok", "at": 1.0}) + "\n")
    f = build_m0(measure(tmp_path), sec_dir=sec)
    assert (f["m0_sec_requests"], f["m0_min_request_gap_s"], f["m0_blocked_events"]) == (1, None, 0)
    assert f["m0_server_errors"] == 0


def test_no_ledger_means_no_access_facts(tmp_path):
    f = build_m0(measure(tmp_path), sec_dir=tmp_path / "nowhere")
    assert "m0_sec_requests" not in f and "m0_sec_requests" not in build_m0(measure(tmp_path))

PENDING = "pending"


def _v(f, k) -> str:
    x = f.get(k)
    return PENDING if x is None else str(x)


def _ci(f, k) -> str:
    x = f.get(k)
    return PENDING if x is None else f"{x} ({_v(f, k + '_lo')} to {_v(f, k + '_hi')})"


def _pair(f, a, b) -> str:
    return f"{_v(f, a)} / {_v(f, b)}"


def _pn(f, a, b, n) -> str:
    return f"{_pair(f, a, b)} (n {_v(f, n)})"


def render_m5(f) -> str:
    return f"""# M5: the live desk

Generated from `facts.json` by `dtd report`; do not edit by hand. Numbers marked machine-built come from model passes, not lawyers. This is not legal advice.

## Live index

The service reads one file holding the index, the agreement texts and the links: {_v(f, 'm5_bundle_bytes')} bytes, {_v(f, 'm5_bundle_contracts')} agreements, {_v(f, 'm5_bundle_passages')} passages; sha256 `{_v(f, 'm5_bundle_sha')}`.

## The same path the evals measured

Machine-built check: re-preparing M4's answer items through the live code produced the same prompt for {_v(f, 'm5_prompt_parity_same')} of {_v(f, 'm5_prompt_parity_checked')} items. R7n over the live file (machine-built check) returned the same passages, in the same order, as over the evaluation index for {_v(f, 'm5_bundle_parity_same')} of {_v(f, 'm5_bundle_parity_checked')} questions.

| Index | R6n recall@5 on MAUD's questions (human-labelled (MAUD), report split) |
|---|---|
| MAUD agreements alone (the M4 measurement) | {_ci(f, 'm4_r6n_report_recall_at_5')} |
| The live index | {_ci(f, 'm5_bundle_r6n_report_recall_at_5')} |

Live-path retrieval on the development machine, p50 / p95 ms: R6n {_pair(f, 'm5_live_r6n_latency_ms_p50', 'm5_live_r6n_latency_ms_p95')}; R7n across all agreements {_pair(f, 'm5_live_t_r7n_corpus_latency_ms_p50', 'm5_live_t_r7n_corpus_latency_ms_p95')}.

## API calibration (machine-built)

These numbers are machine-built: model passes, not lawyers. {_v(f, 'm5_calibration_n')} tune-split questions were answered through the API with the live settings and compared with M4's command-line answers to the same questions. Stop rule: {_v(f, 'm5_calibration_stop_rule')}.

| Measure | API | Command-line tool |
|---|---|---|
| Answer state matches the other run (machine-built) | {_v(f, 'm5_calibration_state_agreement')} | — |
| MAUD answer accuracy on the sample (human-labelled (MAUD)) | {_v(f, 'm5_calibration_accuracy_api')} | {_v(f, 'm5_calibration_accuracy_cli')} |
| Claims kept by the citation gate (machine-built) | {_v(f, 'm5_calibration_gate_pass_api')} | {_v(f, 'm5_calibration_gate_pass_cli')} |
| Replies cut off at the output cap (machine-built) | {_v(f, 'm5_calibration_truncated')} | — |
| Input tokens per answer, mean / p95 (machine-built) | {_pair(f, 'm5_api_tokens_in_mean', 'm5_api_tokens_in_p95')} | — |
| Output tokens per answer, mean / p95 (machine-built) | {_pair(f, 'm5_api_tokens_out_mean', 'm5_api_tokens_out_p95')} | — |

The budget's worst-case estimate (machine-built) covered every calibrated call: {_v(f, 'm5_calibration_estimator_ok')}.

## Cost and budget

The cost figures from calibration are machine-built. Model {_v(f, 'm5_price_model')} at {_v(f, 'm5_price_input_per_mtok')} US dollars per million input tokens and {_v(f, 'm5_price_output_per_mtok')} per million output tokens (checked {_v(f, 'm5_price_checked')}; {_v(f, 'm5_price_source')}). Hosting costs {_v(f, 'm5_hosting_usd_month')} US dollars a month (checked {_v(f, 'm5_hosting_checked')}); the model budget is the rest of the monthly cap, US${_v(f, 'm5_model_cap_usd')}, with a daily ceiling of US${_v(f, 'm5_day_cap_usd')}. A new answer costs US${_v(f, 'm5_cost_per_answer_mean')} on average (p95 US${_v(f, 'm5_cost_per_answer_p95')}; machine-built), so a month covers {_v(f, 'm5_answers_per_month')} new answers. Cached answers and Search cost nothing.

## Server (machine-built)

Measured against the live service from the development machine. Server times are the service's own, without the network; end-to-end times include it.

| Request (machine-built) | Server p50 / p95 ms | End-to-end p50 / p95 ms |
|---|---|---|
| Search | {_pn(f, 'm5_server_search_latency_ms_p50', 'm5_server_search_latency_ms_p95', 'm5_server_search_n')} | {_pn(f, 'm5_e2e_search_latency_ms_p50', 'm5_e2e_search_latency_ms_p95', 'm5_e2e_search_n')} |
| Cached answer | {_pn(f, 'm5_server_ask_cached_latency_ms_p50', 'm5_server_ask_cached_latency_ms_p95', 'm5_server_ask_cached_n')} | {_pn(f, 'm5_e2e_ask_cached_latency_ms_p50', 'm5_e2e_ask_cached_latency_ms_p95', 'm5_e2e_ask_cached_n')} |
| New answer | {_pn(f, 'm5_server_ask_fresh_latency_ms_p50', 'm5_server_ask_fresh_latency_ms_p95', 'm5_server_ask_fresh_n')} | {_pn(f, 'm5_e2e_ask_fresh_latency_ms_p50', 'm5_e2e_ask_fresh_latency_ms_p95', 'm5_e2e_ask_fresh_n')} |

Requests that failed during the measurement: {_v(f, 'm5_server_errors')}. Peak memory of the service (machine-built): {_v(f, 'm5_server_rss_mb')} MB. The server's searches returned the same top passages as the development machine's for {_v(f, 'm5_server_embed_parity_n')} questions, a share of {_v(f, 'm5_server_embed_parity')} (query embeddings are computed on each machine).

## The cap trips (machine-built)

These results are machine-built. With the service restarted under a tiny cap: a new question got "budget reached": {_v(f, 'm5_cap_trip_budget_reached')}; a cached question was still answered as "budget reached, showing a cached answer": {_v(f, 'm5_cap_trip_budget_cached')}; the month's spend did not move: {_v(f, 'm5_cap_trip_ledger_unchanged')}. The same check runs in the test suite (`tests/test_desk.py`, `test_the_cap_trips`).
"""

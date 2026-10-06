# M5: the live desk

Generated from `facts.json` by `dtd report`; do not edit by hand. Numbers marked machine-built are judged by a model, not by lawyers; numbers marked human-labelled (MAUD) are scored against MAUD's lawyers' labels; the rest are plain measurements (sizes, counts, tokens, money, times). This is not legal advice.

## Live index

The service reads one file holding the index, the agreement texts and the links: 634859520 bytes, 406 agreements, 88628 passages; sha256 `162e56b9c68a142459953539465afb64c1e2fcf0f9d3561db24f68993de5a225`.

## The same path the evals measured

Re-preparing M4's answer items through the live code produced the same prompt for 9339 of 9339 items. R7n over the live file returned the same passages, in the same order, as over the evaluation index for 200 of 200 questions. Both are exact comparisons: no model or lawyer judges them.

| Index | R6n recall@5 on MAUD's questions (human-labelled (MAUD), report split) |
|---|---|
| MAUD agreements alone (the M4 measurement) | 0.5962 (0.5794 to 0.6116) |
| The live index | 0.5921 (0.573 to 0.6114) |

Live-path retrieval on the development machine, p50 / p95 ms: R6n 46.4 / 365.6; R7n across all agreements 55.94 / 516.66.

## API calibration

40 tune-split questions (39 model calls) were answered through the API with the live model settings; retrieval ran over the evaluation indexes, which the parity section above shows serve the same passages. The answers were compared with M4's command-line answers to the same questions. Stop rule: go. The live model answers with extended thinking, as the evaluation runs did, with up to 4096 tokens of thinking per answer; the evaluation runs used the command-line tool's own thinking default.

| Measure | API | Command-line tool |
|---|---|---|
| Answer state matches the other run (machine-built) | 0.9 | — |
| MAUD answer accuracy on the sample's MAUD questions (human-labelled (MAUD)) (n 20) | 0.6 | 0.6 |
| Claims kept by the citation gate | 0.8804 | 0.9333 |
| Replies cut off at the output cap | 0 | — |
| Input tokens per answer, mean / p95 | 4250.3 / 5818 | — |
| Output tokens per answer (including thinking), mean / p95 | 1325.7 / 2446 | — |

The budget's worst-case estimate covered every calibrated call: yes.

## Cost and budget

Model claude-haiku-4-5-20251001 at 1.0 US dollars per million input tokens and 5.0 per million output tokens (checked 2026-10-05; https://platform.claude.com/docs/en/about-claude/pricing). Hosting costs 7.09 US dollars a month (checked 2026-10-06); the model budget is the rest of the monthly cap, US$2.91, with a daily ceiling of US$0.29. A new answer costs US$0.010879 on average (p95 US$0.017477, from the calibration sample), so a month covers 267 new answers. Cached answers and Search cost nothing.

## Server

Measured against the live service from the development machine. Server times are the service's own, without the network; end-to-end times include it.

| Request | Server p50 / p95 ms | End-to-end p50 / p95 ms |
|---|---|---|
| Search | 76.6 / 120.9 (n 50) | 516.1 / 559.5 (n 50) |
| Cached answer | 77.0 / 105.2 (n 6) | 413.9 / 439.8 (n 6) |
| New answer | 17225.8 / 24998.1 (n 3) | 17554.5 / 25337.3 (n 3) |

Requests that failed, or were served other than meant, during the measurement: 0. Of these, new questions the cache served: 0; cached examples answered live, and billed: 0. Each answer is timed under what served it. Peak memory of the service: 528.7 MB. The server's searches returned the same top passages as the development machine's for 49 of 50 questions (a share of 0.98); query embeddings are computed on each machine.

## The cap trips

With the service restarted under a tiny cap: a new question got "budget reached": yes; a cached question was still answered as "budget reached, showing a cached answer": yes; the month's spend did not move: yes. The same check runs in the test suite (`tests/test_desk.py`, `test_the_cap_trips`).

The live kill test, which killed the service during new answers and read the month's spend before, after the restart and once the stale window had passed, is logged in `docs/m5/kill-test.log`.

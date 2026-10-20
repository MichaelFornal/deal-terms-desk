# Deal Terms Desk

Ask what a signed merger agreement says and get the clause quoted, with a link to the filing.

**Live:** [deals.forn.al](https://deals.forn.al) · **Results:** [deals.forn.al/results.html](https://deals.forn.al/results.html) · **Method:** [deals.forn.al/method.html](https://deals.forn.al/method.html)

The desk answers questions over 406 merger agreements: 88 from MAUD, whose answers lawyers labelled, and 318 acquisitions of technology companies filed with the SEC. The evaluation was built before the app, BM25 was the baseline to beat, and every result is published, including the ones that went badly. This is not legal advice.

## Results

Every number below comes from `facts.json`. Ranges in parentheses are bootstrap intervals, resampled by agreement. *Human-labelled* means scored against MAUD's lawyers' labels. *Machine-built* means the answer key came from model passes that no lawyer checked.

| What was measured | Result | Labels |
|---|---|---|
| Retrieval, BM25 baseline: recall@5 on 1,406 questions over 76 agreements | 0.49 | human-labelled |
| Retrieval, hybrid search plus a lexicon rewrite (R5) | 0.57 (0.55 to 0.59) | human-labelled |
| Retrieval, embeddings alone, same questions | 0.38 | human-labelled |
| Retrieval on 621 plain-language questions about the tech deals, BM25 vs embeddings | 0.17 vs 0.69 | machine-built |
| Live index returns the same passages as the evaluated index | 200 of 200 questions | exact comparison |
| Citation gate: claims whose quote matches the agreement word for word | 86% kept | exact comparison |
| Answer accuracy on MAUD's multiple-choice questions | 0.60, below the 0.75 of always picking the most common answer | human-labelled |
| Cost of a new answer, mean (p95) | $0.011 ($0.017) | measured |

The two retrieval results point in opposite directions, which is why both are measured. MAUD's questions use contract vocabulary, where keyword search is hard to beat. Visitors type everyday words, where embeddings win by a wide margin on the machine-built set. The live path uses both.

## How it works

1. **Corpus.** MAUD's agreement texts and the merger exhibits of `8-K` filings are normalised and split into section-aware passages. Amendments that name the section they change are linked to it, and an answer drawn from a changed section shows the amended text beside it.
2. **Retrieval ladder.** Each rung is measured against the rung below it on the same items:
   - R1: BM25 over SQLite FTS5.
   - R2: dense retrieval with `BAAI/bge-small-en-v1.5` in sqlite-vec.
   - R3: R1 and R2 fused by reciprocal rank.
   - R4: a cross-encoder reranker. It lowered recall slightly in M2 and M3, so the live path leaves it out.
   - R5: a lexicon rewrite that maps everyday words to contract vocabulary. The lexicon is machine-built.
   - R6: defined-term expansion.
3. **Answers.** Each question is scoped to one agreement. A question that names no deal, or a name that matches several, gets "which agreement?" and no model call. Claude (`claude-haiku-4-5-20251001`) answers with quoted support, and the citation gate drops every claim whose quote is not in the agreement word for word.
4. **Service.** FastAPI on one small server. A spend ledger reserves each call's worst-case cost before the call runs and settles the real cost after, so concurrent calls or a crash between the two cannot take spend past the month or day cap. Hosting costs $7.09 a month and the model budget is the remaining $2.91, with a daily ceiling of $0.29, which covers 267 new answers a month. Cached answers and Search cost nothing. A kill test of the live service in the middle of new answers left two reservations open; after the stale window they settled at their worst case, as designed (`docs/m5/kill-test.log`).

## Two kinds of labels

- **Human-labelled.** MAUD, by The Atticus Project: lawyers' answers to multiple-choice questions about merger agreements. Settings were chosen on a tune split of 24 agreements and 450 questions. Headline numbers come from a separate report split.
- **Machine-built.** For the tech deals, two independent model passes each read the agreement's outline, chose the sections to read, quoted the governing clause and answered. A question is kept only when both passes found the same clause. No lawyer checked these, and every number built on them is labelled machine-built, here and on the site.

## Limitations

- **Answering is the weak half.** On MAUD's multiple-choice questions the answerer is right 0.60 of the time, worse than always picking the most common answer (0.75). Retrieval improved. Answer accuracy has not caught up.
- **Unfiled schedules.** When the answer sits in a disclosure schedule that was never filed, the desk should decline. It declined correctly on 1 of 20 such questions (machine-built key) and answered anyway on the rest.
- **Recall.** Recall@5 of 0.57 still leaves the right passage outside the top five for many questions. Conditions to closing is the weakest family, at 0.24 under R5.
- **Scope.** US filings, technology targets plus MAUD's agreements, English only. It does not replace reading the agreement.

## Run it

```sh
uv sync --frozen
uv run pytest
```

The tests run offline, with no API key and no requests to sec.gov. Tests that download a real model are marked and skipped by default; `uv run pytest -m model` runs them. CI runs the suite and the facts check on every push (`.github/workflows/ci.yml`).

The pipeline is one command, `dtd` (`uv run dtd --help`). Fetching filings needs a contact address in `SEC_CONTACT` and follows the SEC's fair-access rules: one process, at most two requests a second, and a full stop on a `403`.

## Where the numbers come from

Every number on the site, in the reports and in this README comes from `facts.json`, which named queries in `facts/` produce. `dtd site --strict` refuses to build a page that prints a missing fact, and `dtd copycheck README.md` checks every number in this file against `facts.json`. Each milestone's report is in `docs/m0/` through `docs/m5/`, and the spec is `docs/PRD.md`.

## How this was built

I set the scope and the rules in `docs/PRD.md` and `CLAUDE.md`: the subject, the two kinds of labels, one hard monthly cap on hosting and model calls together, the evaluation before the app, every number from a named query, and every stage resumable and tested by killing it. Claude Code wrote the code under those rules, and its commits carry an `Assisted-by: Claude` trailer. The work was checked by the test suite, the facts gate, a kill test of the live service, and by publishing the results that went against the project as well as the ones that went for it.

## Licence

The code is MIT (`LICENSE`). MAUD is by The Atticus Project under `CC BY 4.0`; it is downloaded at build time and not redistributed here. EDGAR filings are public. Model and package licences are in `NOTICE.md`.

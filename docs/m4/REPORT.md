# M4: answers, the citation gate and abstention

Generated from `facts.json` by `dtd report`; do not edit by hand. Numbers marked machine-built come from model passes, not lawyers.

## Answer path

The answerer retrieves with R7n: R6 (hybrid search, lexicon rewrite, definitions) without the reranker, which lowered recall in M2 and M3, inside the deal the question names or the visitor picks. A question that names no deal, or a name matching several, gets "which agreement?" and no model call.

| Comparison (report split, recall@5) | Value | Change |
|---|---|---|
| T-human, R6n vs R6 | 0.5962 (0.5794 to 0.6116) | 0.0218 (0.007 to 0.038; helps) |
| T-machine (machine-built), R6n vs R6 | 0.6826 (0.6528 to 0.7111) | 0.1029 (0.0683 to 0.1381; helps) |
| T-machine (machine-built), corpus-wide R7n vs R7 | 0.7727 (0.7351 to 0.8071) | 0.0753 (0.0518 to 0.1008; helps) |

## T-human answers

On MAUD's lawyer-labelled questions the answerer is shown the question's answer options and must pick one, with quoted support. Accuracy here is how often it picks the option the lawyers chose. The baseline always picks the option most common on the tune split.

Scored 6307 of 6321 items on the report split; 0 have no answer yet (8319 items built in all; 0 left out because the label rows disagree, 199 because their question has too many options to list (2 questions), 4419 (agreement, question) pairs because their agreement has no contract text in the index: MAUD names agreements whose text files are missing).

| | Accuracy |
|---|---|
| Answerer (claude-haiku-4-5-20251001) | 0.6039 (0.5883 to 0.6181) |
| Answerer, counting only picks whose citations survived the gate | 0.5235 (0.5026 to 0.5415) |
| Majority-answer baseline | 0.7528 (0.7393 to 0.7665) |

Difference from the baseline: -0.1489 (-0.1698 to -0.1286; hurts).

By category (report split):

| Category | Accuracy | With surviving citations | Baseline |
|---|---|---|---|
| Conditions to Closing | 0.3355 (0.2932 to 0.3764) | 0.2135 (0.1684 to 0.2593) | 0.7887 (0.7462 to 0.8289) |
| Deal Protection and Related Provisions | 0.6403 (0.6182 to 0.6629) | 0.5584 (0.531 to 0.5844) | 0.6687 (0.6429 to 0.6931) |
| General Information | 0.8158 (0.7237 to 0.8947) | 0.7237 (0.6184 to 0.8158) | 0.6053 (0.4868 to 0.7105) |
| Knowledge | 0.6599 (0.5913 to 0.7222) | 0.5178 (0.441 to 0.5938) | 0.8071 (0.75 to 0.8599) |
| Material Adverse Effect | 0.5985 (0.5799 to 0.6178) | 0.5273 (0.5023 to 0.5517) | 0.8027 (0.7852 to 0.8193) |
| Operating and Efforts Covenant | 0.6359 (0.5931 to 0.6809) | 0.5634 (0.5164 to 0.6118) | 0.7562 (0.7216 to 0.7888) |
| Remedies | 0.8553 (0.7763 to 0.9342) | 0.8289 (0.75 to 0.9079) | 0.8553 (0.7763 to 0.9342) |

Replies with an answer outside the options: 260; failed calls left out: 14.

## T-machine answers (machine-built)

On the tech deals the question names the company, so the whole live path runs. A judge (claude-sonnet-5-5) compares each answer with the two kept machine-built answers. These numbers are machine-built: no lawyer checked them.

Agree: 0.037 (0.0226 to 0.0533); agree or partly: 0.7262 (0.6849 to 0.7681); judged 621 of 621 items. Declined to answer: 128; answered from the wrong deal: 0; judge reply unreadable: 0; answered but not yet judged: 0; no answer yet: 0; failed calls: 0.

| Family | Agree (machine-built) | Agree or partly (machine-built) |
|---|---|---|
| Employee equity awards | 0.0791 | 0.8047 |
| Termination (break-up) fee | 0.0095 | 0.5619 |
| Employees' pay and benefits after the deal | 0.0204 | 0.8163 |

## Abstention

Questions whose right answer is a decline: "not stated in this agreement" or "in a schedule that was not filed". The keys are machine-built.

| Group | Items | Missing | Correct decline (machine-built key) | False answer (machine-built key) |
|---|---|---|---|---|
| Lead question, both passes found no such clause | 36 | 0 | 0.6389* | 0.3056 |
| Earn-out question (one machine pass found none) | 30 | 0 | 0.7667 | 0.2 |
| Answer sits in an unfiled schedule (weakest key) | 20 | 0 | 0.05 | 0.95 |

\* For the lead question this cell is Correct (decline, or judged consistent with no such clause): an answer also counts as correct when the judge finds it matches the two machine passes. Unjudged answers are excluded: answered but not yet judged: 0; judge reply unreadable: 0.

### Which agreement?

These items are built from names the resolver cannot pin to one deal, so "which agreement?" holds by construction. They check the resolver path, not the model: no model call is made.

- A company name that matches no deal's aliases: "which agreement?" returned: 30 of 30
- A name matching several deals: "which agreement?" returned: 30 of 30

### Machine key contradicted by retrieval

These are kept out of the abstention figures above: the machine key says "not stated", but the key is likely wrong.

| Group | Items | Scored | Missing | Answered share (machine-built key) |
|---|---|---|---|---|
| Lead question where the machine passes saw only the section's title, and the answerer found the clause text | 7 | 7 | 0 | 0.8571 |

## Citation accuracy

Every claim must quote its passage word for word; a claim whose quote is not found is dropped before anyone sees it.

Claims kept by the gate on the report split: T-human 0.8605 (9836 of 11431); T-machine 0.9277 (1449 of 1562).

A second model, shown only a kept claim from the report split and its quote and told to refute it, failed to in 0.7421 of 11150 claims (machine-built; unreadable replies: 0).

## Model comparison

Two models answer the same tune-split questions; each model's mean covers the answers it completed. Tokens are per called answer. The citation gate figures above are for the answer model only. Token counts are as measured through the `claude -p` CLI, which include the CLI's own system prompt. They are an upper bound, not an API price; M5 measures API tokens.

| Model | T-human accuracy | T-machine agree (machine-built) | Tokens in | Tokens out |
|---|---|---|---|---|
| claude-haiku-4-5-20251001 | 0.6347 | 0.0566 | 13631.2 | 2574.3 |
| claude-sonnet-5-5 | 0.7387 | 0.1434 | 12423.2 | 397.2 |

The judge (claude-sonnet-5-5) is from the same model family as the comparison answerer (claude-sonnet-5-5), so a self-preference risk applies to the T-machine column.

Mean tokens per answer on the report split (answer model): in 13799.6, out 2541.3. These are CLI counts, an upper bound for pricing the live demo in M5.

This is not legal advice.

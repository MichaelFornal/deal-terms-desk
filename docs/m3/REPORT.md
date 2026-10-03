# M3: tech deals, deal scoping and the machine-built tier

Generated from `facts.json` by `dtd report`; do not edit by hand. Numbers marked machine-built come from model passes, not lawyers.

## Corpus

Of the 319 tech deals M0 found, 318 agreements were ingested. Left out because the document's own title is not a merger agreement: 1. The deals index holds 418 agreements (100 from MAUD) and 90291 passages, 67502 of them from the tech agreements, in 520470528 bytes.

31 amendments are linked to their deals. 10 name the sections they change in the explicit form ("Section … is hereby amended") and mark 248 passages as superseded; an answer drawn from one of them shows the amended text beside it. The other 21 are recorded but not linked to sections, because nothing in them says which section they change in a form a program can trust. 9603 passages refer to a disclosure letter or schedule, which is never filed.

## T-machine labels (machine-built)

Two independent passes (claude-opus-5-5 and claude-sonnet-5-5) each read the agreement's section outline, chose the sections to read, then quoted the governing clause and answered. Neither pass sees a retrieval result, so the labels do not favour any rung. An item is kept only when both passes found the clause and their quotes overlap or sit in the same section. 318 of 318 agreements are labelled, in 1271 model calls; 2 had no usable section numbering and were shown fixed-size chunks instead.

| Family | Kept | Both passes: absent | Passes disagree | One pass only | Agreement rate (machine-built) |
|---|---|---|---|---|---|
| Employee equity awards | 307 | 5 | 0 | 3 | 0.9903 |
| Termination (break-up) fee | 256 | 12 | 18 | 24 | 0.8591 |
| Employees' pay and benefits after the deal | 255 | 29 | 0 | 26 | 0.9075 |

Items both passes found absent are held for M4's abstention questions; they are not retrieval items.

## The ladder on T-machine (machine-built)

Report split: 571 machine-built items from 217 tech agreements, each asked as a lay question naming the target. Recall@5 with a bootstrap interval clustered by agreement; differences are paired.

| Rung | recall@5 | vs R1 | vs previous rung | p95 latency (ms) |
|---|---|---|---|---|
| R1 keyword | 0.1727 (0.1433 to 0.2045) |  |  | 28.75 |
| R2 dense | 0.6919 (0.6586 to 0.7244) | 0.5192 (0.4812 to 0.5573; helps) |  | 27.18 |
| R3 hybrid | 0.6598 (0.6257 to 0.6958) | 0.4871 (0.4505 to 0.5245; helps) | -0.032 (-0.0587 to -0.0052; hurts) | 64.13 |
| R4 rerank | 0.4911 (0.4529 to 0.5288) | 0.3184 (0.2784 to 0.3577; helps) | -0.1687 (-0.2072 to -0.1325; hurts) | 2291.81 |
| R5 lexicon rewrite | 0.5649 (0.5281 to 0.6025) | 0.3921 (0.3545 to 0.4309; helps) | 0.0737 (0.0537 to 0.0954; helps) | 1949.16 |
| R6 definitions | 0.5815 (0.5474 to 0.6175) | 0.4088 (0.3692 to 0.4476; helps) | 0.0167 (-0.0034 to 0.037; no measurable change) | 1704.99 |

| Rung | Employee equity awards | Termination (break-up) fee | Employees' pay and benefits after the deal |
|---|---|---|---|
| R1 keyword | 0.1549 | 0.1656 | 0.2015 |
| R2 dense | 0.5249 | 0.7679 | 0.8192 |
| R3 hybrid | 0.4927 | 0.7444 | 0.7787 |
| R4 rerank | 0.4495 | 0.5538 | 0.4788 |
| R5 lexicon rewrite | 0.4971 | 0.5538 | 0.6587 |
| R6 definitions | 0.5093 | 0.5686 | 0.6827 |

## R7: finding the deal from the question

Corpus-wide, over every agreement in the deals index, with a hit from another agreement counted as a miss (machine-built items): R6 0.0206 (0.0112 to 0.0315), R7 0.5074 (0.4686 to 0.5493); difference 0.4868 (0.446 to 0.528; helps). On the report split R7 resolved 500 questions to the right deal and 0 to a wrong one. 53 named a company shared by several deals, so R7 searched everything rather than guess, and 18 named no company it knew.

## Tier agreement (machine-built key against MAUD's lawyers)

The same two-pass procedure was run on MAUD's own deal points in 30 agreements from the report split (555 items), so those questions have two answer keys. Both passes agreed on 331. Of those, the machine-built span overlaps the lawyers' span in 0.9789 (0.9615 to 0.9937) of items. Kendall's tau between the rung ordering under the lawyers' key and under the machine-built key is 1.0 (0.7333 to 1.0). With six rungs, tau moves in coarse steps and its interval is wide, so both orderings are shown: lawyers' key R5 > R6 > R3 > R4 > R1 > R2; machine-built key R5 > R6 > R3 > R4 > R1 > R2. This is evidence for or against trusting T-machine, not proof.

| Rung | recall@5, lawyers' key | recall@5, machine-built key |
|---|---|---|
| R1 keyword | 0.508 | 0.498 |
| R2 dense | 0.3948 | 0.3765 |
| R3 hybrid | 0.5344 | 0.5227 |
| R4 rerank | 0.5296 | 0.5105 |
| R5 lexicon rewrite | 0.6156 | 0.5777 |
| R6 definitions | 0.6025 | 0.5738 |

## The LLM rewrite, appended

M2 compared the lexicon, which appends terms to the question, with an LLM rewrite that replaced the question. Appending the same cached rewrite instead gives recall@5 0.5665 (0.5478 to 0.5844) on T-human's report split: against R5 -0.0061 (-0.0207 to 0.0092; no measurable change); against the replacing rewrite 0.03 (0.0168 to 0.0428; helps).

This is not legal advice.

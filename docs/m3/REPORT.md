# M3: tech deals, deal scoping and the machine-built tier

Generated from `facts.json` by `dtd report`; do not edit by hand. Numbers marked machine-built come from model passes, not lawyers.

## Corpus

Of the 319 tech deals M0 found, 318 agreements were ingested. Left out because the document's own title is not a merger agreement: 1. The deals index holds 406 agreements (88 from MAUD) and 87540 passages, not counting table-of-contents passages, 67502 of them from the tech agreements, in 504971264 bytes. 12 agreements are both in MAUD and among the tech deals; the index keeps one copy of each, the tech one, so a question about one of them is not split between two copies.

31 amendments are linked to their deals. 10 name the sections they change in the explicit form ("Section … is hereby amended") and mark 248 passages as superseded; an answer drawn from one of them shows the amended text beside it. The other 21 are recorded but not linked to sections, because nothing in them says which section they change in a form a program can trust. 9257 passages refer to a disclosure letter or schedule, which is never filed.

## T-machine labels (machine-built)

Two independent passes (claude-opus-5-5 and claude-sonnet-5-5) each read the agreement's section outline, chose the sections to read, then quoted the governing clause and answered. Neither pass sees a retrieval result, so the labels do not favour any rung. An item is kept only when both passes found the clause and their quotes overlap or sit in the same section. 318 of 318 agreements are labelled, in 1625 ledgered model replies; 2 had no usable section numbering and were shown fixed-size chunks instead. In 95 agreements the sections chosen for the topics were too long to show in one request, so those topics were asked one at a time; 20 topic labels still had their own sections cut short at the limit.

| Family | Kept | Both passes: absent | Passes disagree | One pass only | Agreement rate (machine-built) |
|---|---|---|---|---|---|
| Employee equity awards | 307 | 6 | 0 | 3 | 0.9903 |
| Termination (break-up) fee | 299 | 10 | 1 | 1 | 0.9934 |
| Employees' pay and benefits after the deal | 280 | 27 | 0 | 4 | 0.9859 |

Items both passes found absent are held for M4's abstention questions; they are not retrieval items.

## The ladder on T-machine (machine-built)

Report split: 621 machine-built items from 216 tech agreements, each asked as a lay question naming the target. Recall@5 with a bootstrap interval clustered by agreement; differences are paired.

| Rung | recall@5 | vs R1 | vs previous rung | p95 latency (ms) | Context tokens per question (mean) |
|---|---|---|---|---|---|
| R1 keyword | 0.1672 (0.1391 to 0.1963) |  |  | 21.58 | 1928.1 |
| R2 dense | 0.6935 (0.6612 to 0.7247) | 0.5263 (0.489 to 0.561; helps) |  | 21.84 | 1859.6 |
| R3 hybrid | 0.6632 (0.6296 to 0.6956) | 0.496 (0.4603 to 0.5304; helps) | -0.0303 (-0.0562 to -0.0054; hurts) | 55.62 | 1866.8 |
| R4 rerank | 0.4893 (0.4524 to 0.5253) | 0.3221 (0.2852 to 0.3587; helps) | -0.1739 (-0.2088 to -0.1399; hurts) | 2166.38 | 1916.3 |
| R5 lexicon rewrite | 0.5594 (0.5242 to 0.5953) | 0.3922 (0.3572 to 0.4286; helps) | 0.07 (0.0516 to 0.0903; helps) | 1865.74 | 1902.0 |
| R6 definitions | 0.5797 (0.5451 to 0.6142) | 0.4125 (0.3762 to 0.4482; helps) | 0.0203 (0.001 to 0.0395; helps) | 1670.17 | 3177.6 |

| Rung | Employee equity awards | Termination (break-up) fee | Employees' pay and benefits after the deal |
|---|---|---|---|
| R1 keyword | 0.1551 | 0.159 | 0.1892 |
| R2 dense | 0.5178 | 0.7573 | 0.818 |
| R3 hybrid | 0.4873 | 0.7465 | 0.767 |
| R4 rerank | 0.4488 | 0.5418 | 0.4776 |
| R5 lexicon rewrite | 0.4965 | 0.5418 | 0.6471 |
| R6 definitions | 0.5062 | 0.5633 | 0.6778 |

### Same questions without the company name

The same items, asked without naming the target (machine-built). Inside one agreement the company's name is a word that appears everywhere, so it misleads keyword search toward passages that merely mention the company.

| Rung | recall@5 | vs the question naming the company | Context tokens per question (mean) |
|---|---|---|---|
| R1 keyword | 0.646 (0.6162 to 0.6759) | 0.4788 (0.4426 to 0.515; helps) | 1868.9 |
| R2 dense | 0.8377 (0.8161 to 0.8583) | 0.1442 (0.1177 to 0.1714; helps) | 1842.5 |
| R3 hybrid | 0.8487 (0.83 to 0.8672) | 0.1855 (0.1564 to 0.2169; helps) | 1882.7 |
| R4 rerank | 0.7666 (0.744 to 0.7895) | 0.2772 (0.2432 to 0.313; helps) | 1880.9 |
| R5 lexicon rewrite | 0.7827 (0.7587 to 0.805) | 0.2233 (0.1897 to 0.2566; helps) | 1896.2 |
| R6 definitions | 0.7945 (0.773 to 0.8152) | 0.2149 (0.1837 to 0.2458; helps) | 3437.3 |

## R7: finding the deal from the question

Corpus-wide, over every agreement in the deals index, with a hit from another agreement counted as a miss (machine-built items): R6 0.0229 (0.0134 to 0.0335), R7 0.7035 (0.6665 to 0.738); difference 0.6805 (0.6403 to 0.717; helps). On the report split R7 resolved 565 questions to the right deal and 0 to a wrong one. 36 named a company shared by several deals, so R7 searched everything rather than guess, and 20 named no company it knew. Once R7 has found the deal it drops the company's name from the question before searching inside that agreement, where the name only adds noise.

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

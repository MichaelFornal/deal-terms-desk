# Deal Terms Desk

The spec is `docs/PRD.md`. Read it before designing or building anything; it records decisions
already made (MAUD plus EDGAR tech deals, two eval tiers, fully live demo under a $10/month cap,
one small server). Don't re-litigate them without asking.

- Build order is the milestone table in PRD §9. M1 and M2 use MAUD only and do not wait on the
  SEC. M0 is a gate: later plans use its measured numbers, not guesses.
- sec.gov: one process, never parallel, at most 2 requests per second, stop on a 403. Never fan
  agents out against it. The contact comes from `SEC_CONTACT`; never write it into the repo.
- Every number the site or README prints comes from `facts.json`, produced by a named query in
  `facts/`. Never hard-code a digit in page copy. Machine-built numbers are labelled as such.
- Every stage is idempotent and resumable. Test resume by killing it, not by reasoning.
- The README and the launch post are written by Michael by hand. Never generate them.
- Commits carry an `Assisted-by: Claude` trailer.

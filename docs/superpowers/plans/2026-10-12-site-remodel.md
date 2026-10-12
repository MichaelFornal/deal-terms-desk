# Deal Terms Desk: full UX and UI remodel

## Context

deals.forn.al went live at M5 and public at M6 (main `bb90b9a`). Its four pages work, but they were built for
correctness, not for a reader. A look at the live site on 2026-10-12 found:

- **Ask:**
  - Six full-width example buttons sit between the form and the answer, so the answer lands below the fold and the
    page never scrolls to it.
  - The agreement picker is a native `<select>` of **406** deals.
  - A fresh answer takes about 17 s at the median (`m5_server_ask_fresh_latency_ms_p50`) and shows only "Reading
    the agreement…".
  - Every claim repeats the same agreement link.
- **Search:** ten full passages of up to about 2,300 characters each, so the page runs about 6,000 px. The API's
  `scope` (which agreement was searched) is never shown.
- **Results:** 15 tables in a 7,600 px page, with no summary or contents. **On a 390 px phone the whole page scrolls
  sideways (824 px).** Intervals and "helps/hurts" run inline in the numbers.
- **Everywhere:**
  - `/favicon.ico` returns 404;
  - there is no dark mode;
  - the brand wraps onto three lines on a phone.

The site is a hiring showcase (PRD §1). The goal is to make the tools easier to use, the first impression stronger
and the evidence scannable, all weighted evenly.

### Decisions (Michael, 2026-10-12)

1. **All of it, evenly:** the look, Ask and Search, and Results and Method.
2. **Follow forn.al's whole design system** (`https://forn.al/styles.css`), not only its fonts. Its rules:
   - no borders, boxes, shadows or radii;
   - no accent colour;
   - mono carries anything a machine produced, and serif is only for people's sentences;
   - the fonts are the same system stacks (`ui-monospace…`, `"Iowan Old Style", Palatino…`).

   There are no font files, so **the CSP and the Caddyfile do not change**. The mapping that follows: **the model's
   claim sentences are mono and the quoted contract text (lawyers' words) is serif.**
3. **Ask stays the home page and gets a strip of headline figures** from `facts.json`. Each figure sits under its
   tier label and links to its table on Results.
4. **No share links.** The address bar never changes, and nothing runs on page load.

### Unchanged

- The four pages and their URLs.
- `service/`, `retrieval/` and the API.
- `deploy/` (smoke checks only the status, the disclaimer and the CSP).
- The numbers contract: no digit typed into copy, and "machine-built" beside every machine-built fact.
- "This is not legal advice." on every page.
- Every piece of state copy pinned in `tests/test_site.py`, which encodes the honesty decisions:
  - "source text", not "filing";
  - the budget copy says "used up for now", never "next month";
  - "Search never spends model budget.";
  - the `STATES` and `NO_CANDIDATES` strings, word for word, in the same one-line, two-space format.
- The README and launch post are Michael's; this work does not touch them.

## Design

### 1. Design system: `site/static/style.css` (rewritten)

- **Tokens** come from forn.al verbatim:
  - colours: `--paper`, `--ink`, `--muted`, `--faint`, `--highlight`, `--bar`;
  - fonts: `--mono`, `--serif`;
  - widths: `--measure` (42rem), `--wide` (52rem);
  - spacing: `--s1` to `--s7`;
  - the same `prefers-color-scheme: dark` values, plus `<meta name="color-scheme" content="light dark">`;
  - the `prefers-reduced-motion` reset;
  - a print block, in which links show their URL.
- The header comment credits the forn.al system and lists **the desk's only exceptions**, each needed because forn.al
  has no forms:
  - **(a)** text fields get the `--highlight` paper shift as their background, and nothing else;
  - **(b)** the submit button is the one filled shape: `--ink` background, `--paper` text, square;
  - **(c)** focus is a 2px `--ink` outline everywhere;
  - **(d)** wide Results tables scroll inside their own region on narrow screens.
- **Type roles:**
  - **mono:** the base, UI, labels, the model's claims, figures, section paths, scores and tables;
  - **serif:** page ledes, Method prose, contract quotes and Search passages.
  - Headings are mono 600 (forn.al's `h1`/`h2`). Section labels use forn.al's `.label` (uppercase, tracked).
  - Tier labels use `--muted`, not `--faint`, because they carry meaning; forn.al's contrast note applies.
- **States carry no colour.** Today's `--warn` orange goes, and a state is carried by weight and words.
- **No digit-roll animation.** Splitting digits into spans would break `test_page_copy_has_no_hard_coded_digits`,
  because `visible()` would read "0 . 5". Each figure is one text node.
- A `.visually-hidden` utility for the skip link and screen-reader-only text. forn.al's `.sr` is scoped to `.tick`.

### 2. Shell: `site/templates/base.html` and `_page()` in `facts/site.py`

- The masthead follows forn.al's `.top`:
  - "Deal Terms Desk" is `.who` (uppercase, 600);
  - the nav is small and `--muted`, and the current page is in `--ink` with `aria-current`;
  - the nav has `min-width: 0` and wraps cleanly at 390 px.
- A "Skip to content" link.
- `<link rel="icon" href="/static/favicon.svg">`. The new `site/static/favicon.svg` is a mono glyph that uses SVG
  attributes only, with no `<style>` element and no media query, since the response carries `style-src 'self'`.
  - forn.al uses a `data:` URI, which the desk CSP's `img-src 'self'` blocks.
  - Browsers stop asking for `/favicon.ico` once the link exists. Some non-browser clients still ask, and stay a
    harmless 404. No binary `.ico` is generated.
- `<meta name="description">` plus `og:title` and `og:description` per page, so the launch post's link unfurls.
  These are text only, with no digits.
- The footer follows forn.al's `.foot`:
  - "This is not legal advice." in ink;
  - the existing numbers sentence;
  - links to the source repo and to forn.al.

### 3. Ask: `index.html` becomes a template with `{{examples}}` and `{{figures}}`

Top to bottom:

1. **h1 and serif lede.** The lede copy stays as it is: "…links to its source text."
2. **Form:**
   - "Your question" `<textarea id="question">`, two rows, with CSS `field-sizing: content` where the browser
     supports it.
     - Enter submits with `form.requestSubmit()`, so `required` still applies.
     - The key is ignored while `event.isComposing` is true (for input methods such as Japanese or Chinese).
     - Shift+Enter adds a new line.
   - **The agreement picker becomes a type-to-filter field.** It is `<input id="deal" list="deal-options"
     autocomplete="off">` with a `<datalist>`. `<label for="deal">Agreement (optional)` is kept. Details are under
     "Deal picker" below.
   - "Ask →" submit button.
3. **`#answer` (aria-live), directly under the form, before the examples.** After a reply, it scrolls into view with
   `block: "nearest"`; there is no smooth scrolling under reduced motion.
4. **Examples, rendered on the server** from `site/examples.json`:
   - a `.label` "Try one";
   - one group per family present, in `FAMILY_ORDER`, titled with `facts/report_m4.LABELS`. Missing families are
     allowed, because the markup test passes a single example;
   - text-style buttons carrying `data-question`, escaped with `html.escape(quote=True)`.

   **Clicking an example clears the picker, then asks,** as today. Warm caches the examples with no deal, so this
   keeps them free cache hits. The `/examples.json` fetch and the layout shift it causes both go. `render_site`
   stops writing `dist/examples.json`, which nothing reads any more: smoke and push read `site/examples.json`.
5. **Headline figures:** forn.al's `.tick` grid, under a `.label` "The live desk" and above "All results →". Each
   figure goes through the existing `CI` or `K` cells, so "pending" works in loose builds and strict builds refuse a
   missing fact. These are the figures for the path the live desk actually runs:
   - **`m5_bundle_r6n_report_recall_at_5`** (with its interval): "recall@5 on MAUD's questions: the live path over
     the live index". It is **human-labelled (MAUD)**, links to `/results.html#ladder_human`, and is the headline
     retrieval number from T-human (PRD §5.1).
   - **`m4_t_r7n_corpus_report_recall_at_5`** (with its interval): "recall@5 on the tech deals across all agreements:
     the live path, which scopes each question to the deal it names". It is **machine-built** and links to
     `#ladder_machine`.
   - **`m5_model_cap_usd`**: "US dollars a month of model budget, a hard cap, after `m5_hosting_usd_month` for
     hosting". It has no tier label and links to `#live`.
   - There is no "up from" wording. The before-and-after story sits in the Results charts, which carry their paired
     changes.

**Deal picker (shared by Ask and Search, in `app.js`):**

- `fillDeals` builds the `<datalist>` from `/api/deals`. Each label is `dealName(d)` plus " (signed)", and
  **`dealName`'s fallback to the id stays**. In `live.db`, four MAUD deals lack names or dates, and only the
  fallback keeps all 406 labels distinct. If two labels still collide, the id is appended to both.
- There are two maps, **label → id** and **id → label**. Lookup keys are trimmed and case-folded, with "-"
  normalised to "–".
- **On submit:**
  - an empty field means no deal;
  - a matching label sends that id;
  - anything else shows an inline note, "Pick an agreement from the list, or leave it empty.", and sends nothing.
  - This covers the datalist's differences between browsers: Safari matches by prefix, iOS shows a short list, and
    Firefox for Android barely supports it.
- **A candidate pick** (`which_deal`) fills the field from the id → label map, because a candidate's `name` has no
  date, then calls `ask(null, c.id)`.

**Answer rendering (`app.js`):**

- **Status line** (`.label` style): the state copy, unchanged.
- **Agreement header, once:**
  - the deal name in mono 600;
  - the signed date in muted;
  - a "source text ↗" link through `safeLink`.
- **Claims:** an `<ol>` with hanging numbers.
  - The claim text is mono (the model wrote it).
  - The quote is a serif `<blockquote>`, set apart by indentation, not a rule.
  - The meta line is mono and small:
    - `§ <section_path>`;
    - the amendment note and its link when there is one;
    - a per-claim source link **only when `c.link` differs from `data.deal.link`**.
- **Closing line:** after an answer with claims, "Every quote above was checked word for word against the passage
  it cites." This is Method's wording, and it holds for amendments too. "Served from the answer cache." stays.
- **`which_deal`:** candidate buttons, or the existing `NO_CANDIDATES` copy.
- **Loading:**
  - a `.label` "Reading the agreement" with an animated ellipsis (CSS, static under reduced motion);
  - a serif note: "A new answer takes a while: the model reads the passages, then every quote is checked against
    the agreement. A cached answer comes back at once." There are no digits, so no timer.

### 4. Search: `search.html`

- The same form layout: `<input id="q">` and the shared deal picker.
- **Result header** (`.label`): the hit count from `hits.length`, plus the scope. `scope.deal` is an id, so its name
  comes from the id → label map.
  - One deal: "inside <deal name>".
  - Candidates and no deal: "The name matches several agreements, so every agreement was searched." The candidates
    are named after it. R7 searches everything rather than guess, so this wording is accurate and "searched all of
    them: A, B" would not be.
  - Otherwise: "across all agreements".
- **Each hit:**
  - a mono header with the deal name, "source text ↗" and `§ path`;
  - **the serif passage, cut to about eight lines** with a CSS max-height. A "Show the whole passage" toggle button
    (`aria-expanded`, `classList`) appears only when the passage overflows, which is measured after the passage is in
    the page;
  - a mono, muted meta line: the fused score, the `stage()` outputs, and the definitions used.
- **No query-word emphasis.** The server rewrites lay words and searches embeddings too, so bold literal words would
  mislead about what matched.

### 5. Results: `results_main()` in `facts/site.py`

- The h1 and `RESULTS_INTRO`, then a **contents list** linking to an `id` on each section `h2`. The ids are slugged
  from the `SECTIONS` titles.
- **Two charts** at the top of "Retrieval", in forn.al's magnitude-bar style:
  - Each is a real `<table class="chart">`, so the values read as data.
  - Each row has a label, a bar and the value with its interval, rendered through `CI`.
  - **Bars are inline SVG** (`<svg viewBox="0 0 1000 12" preserveAspectRatio="none" aria-hidden="true"><rect
    width=…/><line …whisker/></svg>`). SVG attributes are not covered by `style-src`. Lengths come from the fact
    values; there are no axis ticks and no printed digits. A `None` value draws no bar, so the value cell reads
    "pending".
  - The new `Chart` dataclass carries `tier` the way `Table` does.
  - **Chart A** (human-labelled (MAUD)): recall@5 on MAUD's questions for R1 to R6 and R6n, with the paired R6
    vs R1 change, `D("m2_cmp_r6_vs_r1_recall_at_5")`, as its note.
  - **Chart B** (machine-built): recall@5 across all agreements:
    - R6 without scoping (`m3_t_r6_corpus_report_recall_at_5`);
    - R7 re-run (`m4_t_r7_corpus_report_recall_at_5`), because `test_r7n_follows_the_rerun_r7_row` pins R7n beside
      the re-run;
    - R7n, the live path (`m4_t_r7n_corpus_report_recall_at_5`).

    The note is the paired scoping gain, `D("m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5")`.
- **Tables, restyled with no borders:**
  - Headers are mono 0.75rem in `--muted`.
  - Columns whose cells are `K`, `CI`, `D` or `V` get `class="n"`: right-aligned, tabular numerals.
  - **`CI`, `D` and `V` cells** wrap the bracketed part in `<span class="ci">`, for example `0.4892 <span
    class="ci">(0.4666 to 0.5123)</span>` and `0.0851 <span class="ci">(0.064 to 0.1061; helps)</span>`.
    - In a browser the visible text is unchanged; `visible()` in the tests gains one space.
    - Inside tables, `.ci` breaks onto its own line in muted 0.75rem. In Method prose it stays inline.
  - Each table is wrapped in `<div class="scroll" role="region" tabindex="0" aria-labelledby="<id>-cap">`, and its
    caption gets `id="<id>-cap"`. `id="<table id>"` stays on the `<table>`.
  - Tier labels stay in the caption text.
- The page uses `--wide`, and the tables use 0.8125rem.

### 6. Method: `method_main()`

- A contents list and an id on each `h2`.
- Paragraphs are forn.al `.prose`: serif, `--measure`, oldstyle numerals.
- No copy changes. The tests pin several of these sentences.

### 7. `app.js` (rewritten, keeping every invariant the tests pin)

These stay:

- `el()`, and `safeLink()` with its exact first line.
- **`href` appears exactly once in the file, comments included.**
- `call()` with `catch (e) { return { status: 0`, and `busy()` with `disabled = on`.
- `++latest` and `mine !== latest`.
- `Object.hasOwn(STATES`; the `STATES` and `NO_CANDIDATES` strings word for word, one line each, two-space indent;
  `stateNote(data.state, data)` and `stateNote(outcome, data)`; `cached_state`.
- `outcome === "which_deal" && Array.isArray(data.candidates) && data.candidates.length`, and `ask(null, c.id)`.
- No `innerHTML`, `.style`, `eval` or `javascript:`, and **no digits in any string literal**. That rules out
  selectors such as `"h2"`.

New code:

- the shared deal picker and its two maps;
- Enter to submit (`isComposing`, `requestSubmit`);
- scroll into view;
- wiring for the server-rendered example buttons;
- the search scope line;
- the passage toggle;
- the answer header and the per-claim link rule.

### 8. `facts/site.py` changes, all through the existing `K`, `CI`, `D` and `V` cells and `render_cell`

- `FIGURES` defines the cells, tier and link of each headline figure. `render_figures(F)` and
  `render_examples(examples)` fill the `index.html` placeholders.
- `Chart`, `render_chart(F, chart)` and `results_charts()`. Bar geometry reads the fact value only when it is a
  number.
- `render_table`: the scroll wrapper, the caption id and the `n` column classes. `render_cell` and `_change` add the
  `.ci` span.
- `_slug()` and the contents list for Results and Method.
- `_page()` gains the description and og meta.
- `render_site` drops `dist/examples.json`.

### 9. Docs

A short note under PRD §9, "Site remodel decisions (2026-10-12)", recording decisions 2 to 4 above. The plan is
committed to `docs/superpowers/plans/2026-10-12-site-remodel.md`, as for every earlier milestone.

## Files

- **Rewritten:** `site/static/style.css`, `site/static/app.js`, `site/templates/base.html`,
  `site/templates/index.html`, `site/templates/search.html`.
- **New:** `site/static/favicon.svg`.
- **Edited:** `facts/site.py`, `tests/test_site.py`, `docs/PRD.md` (§9 note).
- **Reused:**
  - `facts.labels.tier_label`, `HUMAN` and `MACHINE`;
  - `facts.report_m4.LABELS` and `facts.site.FAMILY_ORDER`;
  - `Facts`, `cell_keys` and `render_cell`;
  - `stage()` and `dealName()` in `app.js`.

## Tests (`tests/test_site.py`)

Every existing assertion keeps its intent. The changes:

- **Lines 41, 43 and 184** (`examples.json` in dist): the file is no longer written. The escaping check moves to the
  examples rendered into `index.html`.
- **The markup test (lines 175–184)** also covers `index.html`. The evil example question must appear only
  escaped, including inside `data-question`.

New tests:

- every headline-figure and chart key sits under its `tier_label`, by the same method as
  `test_every_labelled_fact_sits_under_its_label`, and every `m5_` key sits under exactly its own label;
- loose builds with `m5_` facts missing or null render "pending" in the figures and charts, and strict builds raise
  `KeyError`. This extends the two existing tests to `index.html`;
- every Results and Method `h2` has an id, and the contents list links to each one;
- every Results table sits inside a `.scroll` region, and `id="<table id>"` is still present;
- the favicon link is on every page, the file is copied to `dist/static/`, and it contains no `<style`;
- chart B's R7n row follows the re-run R7 row;
- the no-digits and no-`style=` rules pass over the new templates and copy.

## Verification

1. `uv run pytest -q` (the full suite, about 972 tests) and `uv run dtd site --strict`.
2. **Local visual check with mocks:**
   - Serve `site/dist` with `python -m http.server`.
   - Drive it with Playwright, and route-mock `/api/deals`, `/api/ask` and `/api/search` from fixtures kept in the
     scratchpad, not the repo. The deals fixture includes a deal with no name and a deal with no date.
   - Mock every Ask state: answered, not_stated, unfiled_schedule, which_deal with and without candidates,
     budget_cached with `cached_state`, budget_reached, busy, error, 422, 429, a network failure, and an amended
     claim from another link.
   - Mock a search scoped to one deal, an unscoped one, and one with ambiguous-name candidates.
   - Take screenshots at 390 px and 1280 px, in light and dark (`emulateMedia`).
3. **Checks:**
   - `document.documentElement.scrollWidth === innerWidth` on all four pages at 390 px;
   - keyboard only: Tab order, Enter to submit, visible focus, picking a candidate;
   - reduced motion: no animated ellipsis, no smooth scroll;
   - the picker: typing "Xilinx" filters, an exact pick sends the id, and free text that matches no deal shows the
     note without a request;
   - an example click clears the picker;
   - the browser console has no CSP violations. Serving locally adds no CSP header, so this check is repeated live
     after deploy.
4. **Deploy only after Michael approves.** `deploy/push.sh` already runs `dtd site --strict`, warm and smoke.
   Afterwards, check live with Playwright:
   - example clicks (cached with no deal, so free);
   - a Search;
   - phone width;
   - the console, for CSP violations.

   Never type a fresh question on the live box.
5. Delete the `.playwright-mcp/` folder left in the repo by this planning session's screenshots.

## Execution

- Work on branch `site-remodel`.
- Commits carry `Assisted-by: Claude` and the Co-Authored-By trailer, as recent commits do.
- Order of work:
  1. the design system and shell;
  2. Results and Method (cells, tables, charts, contents);
  3. Ask (figures, examples, picker, answer);
  4. Search;
  5. the tests with each step, then the visual pass.
- Merge to `main` and push only when Michael says so.

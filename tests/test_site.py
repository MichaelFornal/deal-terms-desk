import html
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from evals.tmachine import FAMILIES
from facts.labels import MACHINE, is_machine_built, tier_label
from facts.site import K, METHOD, Facts, cell_keys, render_cell, render_site, render_table, results_tables
from retrieval.scope import Resolver

EXAMPLES = json.loads(Path("site/examples.json").read_text())
# Names, not figures: rung names, the BM25 algorithm, metric cut-offs (recall@5) and percentile names.
ALLOWED = re.compile(r"0\.5|\bR[1-7]n?\b|BM25|@\d+|\bp(?:50|95)\b")
STRING = re.compile(r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\'|`(?:[^`\\]|\\.)*`')


class Every(dict):
    """Any fact renders as a placeholder number, so the page copy is checked, not the data."""
    def __missing__(self, key):
        return 0.5


def facts() -> dict:
    return json.loads(Path("facts.json").read_text())


def visible(page: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", page))


def stray_digits(text: str) -> list[str]:
    return [line for line in text.splitlines() if re.search(r"\d", ALLOWED.sub("", line))]


def test_pages_render_from_the_committed_facts(tmp_path):
    written = render_site(facts(), tmp_path, EXAMPLES)
    assert {p.name for p in written} == {"index.html", "search.html", "results.html", "method.html", "examples.json"}
    assert (tmp_path / "static" / "app.js").exists() and (tmp_path / "static" / "style.css").exists()
    assert json.loads((tmp_path / "examples.json").read_text()) == EXAMPLES


def test_every_page_carries_the_disclaimer(tmp_path):
    for p in render_site(facts(), tmp_path, EXAMPLES)[:4]:
        assert "This is not legal advice." in p.read_text(), p.name


def test_page_copy_has_no_hard_coded_digits(tmp_path):
    for p in render_site(Every(), tmp_path, EXAMPLES)[:4]:
        assert stray_digits(visible(p.read_text())) == [], p.name


def test_templates_examples_and_app_strings_have_no_digits():
    for t in sorted(Path("site/templates").glob("*.html")):
        assert stray_digits(visible(re.sub(r"\{\{\w+\}\}", "", t.read_text()))) == [], t.name
    assert stray_digits("\n".join(e["question"] for e in EXAMPLES)) == []
    js = Path("site/static/app.js").read_text()
    assert stray_digits("\n".join(STRING.findall(js))) == []


def test_every_labelled_fact_sits_under_its_label():
    F = Facts(facts())
    for t in results_tables():
        rendered = render_table(F, t)
        cells = [(r, j, c) for r in t.rows for j, c in enumerate(r.cells)] + [(None, None, c) for c in t.note]
        for row, j, c in cells:
            col = t.head[j][1] if j is not None and j < len(t.head) else None
            effective = col or (row.tier if row is not None else None) or t.tier
            for key in cell_keys(c):
                want = tier_label(key)
                if want:
                    assert effective == want, (t.id, key, effective)
                    assert html.escape(want) in rendered, (t.id, want)


def test_method_paragraphs_with_machine_built_facts_say_so():
    F = Facts(facts())
    for _, paragraphs in METHOD:
        for para in paragraphs:
            if any(is_machine_built(k) for c in para for k in cell_keys(c)):
                assert MACHINE in "".join(render_cell(F, c) for c in para), para[0]


def test_missing_m5_facts_are_pending_unless_strict(tmp_path):
    f = {k: v for k, v in facts().items() if not k.startswith("m5_")}
    render_site(f, tmp_path / "loose", EXAMPLES)
    assert "pending" in (tmp_path / "loose" / "results.html").read_text()
    with pytest.raises(KeyError):
        render_site(f, tmp_path / "strict", EXAMPLES, strict=True)
    f.pop("m4_refute_claims")
    with pytest.raises(KeyError):  # any other missing fact is a bug, strict or not
        render_site(f, tmp_path / "broken", EXAMPLES)


def test_app_js_writes_text_never_markup():
    js = Path("site/static/app.js").read_text()
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", ".style",
                   "javascript:"):
        assert banned not in js, banned


def test_pages_have_no_inline_script_style_or_handlers(tmp_path):
    for p in render_site(facts(), tmp_path, EXAMPLES)[:4]:
        page = p.read_text()
        assert not re.search(r"<script(?![^>]*\bsrc=)", page), p.name
        assert "style=" not in page and not re.search(r"\son[a-z]+=", page), p.name


def test_results_page_shows_every_table(tmp_path):
    render_site(facts(), tmp_path, EXAMPLES)
    page = (tmp_path / "results.html").read_text()
    for t in results_tables():
        assert f'id="{t.id}"' in page


def test_examples_cover_each_lead_family_twice_and_name_one_deal():
    assert Counter(e["family"] for e in EXAMPLES) == {fam: 2 for fam in FAMILIES}
    db = Path("data/index/deals.db")
    if not db.exists():
        pytest.skip("deals index not built in this checkout")
    resolver = Resolver(sqlite3.connect(f"file:{db}?mode=ro", uri=True))
    assert all(resolver.resolve(e["question"]).contract_id for e in EXAMPLES)


def test_dtd_site_writes_the_pages(tmp_path, monkeypatch):
    from pipeline import cli
    monkeypatch.setattr(cli, "SITE_DIST", tmp_path / "dist")
    assert cli.entry(["site"]) == 0
    assert (tmp_path / "dist" / "index.html").exists() and (tmp_path / "dist" / "static" / "app.js").exists()


def test_app_js_shows_the_cached_outcome_under_a_spent_budget():
    js = Path("site/static/app.js").read_text()
    assert "cached_state" in js and "budget_cached" in js


def test_app_js_survives_network_errors_and_double_submits():
    js = Path("site/static/app.js").read_text()
    assert "catch (e) { return { status: 0" in js  # a rejected fetch becomes the error copy
    assert "disabled = on" in js and "++latest" in js and "mine !== latest" in js
    assert "ask(null, c.id)" in js  # a candidate pick does not go through the select
    assert "Object.hasOwn(STATES" in js and "STATES[data.state]" not in js


def test_every_href_goes_through_safe_link_and_it_demands_https():
    js = Path("site/static/app.js").read_text()
    assert js.count("href") == 1 and 'rel: "noopener noreferrer"' in js
    assert 'startsWith("https://")' in js
    assert re.search(r'function safeLink\(url, text\) \{\n  if \(typeof url !== "string" \|\| !url\.startsWith\("https://"\)\)', js)


def test_judge_sentence_follows_the_facts(tmp_path):
    base = {**facts(), "m3_tm_model_a": "alpha", "m3_tm_model_b": "beta"}
    for judge, want, unwanted in (("beta", "helped build", "separate model"), ("gamma", "separate model", "helped build")):
        render_site({**base, "m4_judge_model": judge}, tmp_path / judge, EXAMPLES)
        page = (tmp_path / judge / "method.html").read_text()
        assert want in page and unwanted not in page and "third model" not in page


def test_r7n_follows_the_rerun_r7_row():
    t = {t.id: t for t in results_tables()}["ladder_machine"]
    i = next(i for i, r in enumerate(t.rows) if r.cells[0].startswith("R7n"))
    assert t.rows[i - 1].cells[2].key == "m4_t_r7_corpus_report_recall_at_5"
    assert any(r.cells[2].key == "m3_t_r7_corpus_report_recall_at_5" for r in t.rows)


def test_booleans_render_as_yes_and_no():
    F = Facts({"a": True, "b": False})
    assert render_cell(F, K("a")) == "yes" and render_cell(F, K("b")) == "no"


def test_markup_in_facts_and_examples_is_escaped(tmp_path):
    evil = ['<script>alert(1)</script>', '"><img src=x onerror=1>']
    f = {**facts(), "m4_answer_model": evil[0], "m5_price_model": evil[1]}
    render_site(f, tmp_path, [{"family": "equity_awards", "question": evil[0]}])
    for name in ("method.html", "results.html"):
        page = (tmp_path / name).read_text()
        assert "<script>alert" not in page and "<img src=x" not in page, name
    assert html.escape(evil[0]) in (tmp_path / "method.html").read_text()
    assert html.escape(evil[1]) in (tmp_path / "results.html").read_text()
    assert json.loads((tmp_path / "examples.json").read_text())[0]["question"] == evil[0]  # data file, fetched as text


def test_every_m5_fact_sits_under_exactly_its_own_label():
    """M5 labels follow where the judgement comes from, and a plain measurement (a time, a price, a count) sits
    under no tier label: not even a table's."""
    for t in results_tables():
        cells = [(r, j, c) for r in t.rows for j, c in enumerate(r.cells)] + [(None, None, c) for c in t.note]
        for row, j, c in cells:
            col = t.head[j][1] if j is not None and j < len(t.head) else None
            effective = col or (row.tier if row is not None else None) or t.tier
            for key in cell_keys(c):
                if key.startswith("m5_"):
                    assert effective == tier_label(key), (t.id, key, effective)


def test_budget_copy_says_used_up_for_now_without_naming_one_cap():
    """Either cap trips the budget states, and the daily one trips first: the copy must not promise next month."""
    js = Path("site/static/app.js").read_text()
    for state in ("budget_cached", "budget_reached"):
        copy = re.search(rf'^  {state}: "([^"]*)",?$', js, re.M).group(1)
        assert "model budget is used up for now (a daily or monthly cap)" in copy, state
        assert "Cached answers and Search still work" in copy or "cached answers and Search still work" in copy
        assert "Monthly" not in copy and "next month" not in copy, state


def test_ask_and_search_copy_claim_only_what_is_true(tmp_path):
    """MAUD agreements link to their source text, not a filing; Search is rate-limited per address, but it never
    spends model budget."""
    index, search = (Path("site/templates") / n for n in ("index.html", "search.html"))
    assert "links to its source text" in index.read_text() and "filing" not in index.read_text()
    assert "Search never spends model budget." in search.read_text() and "capped" not in search.read_text()
    render_site(facts(), tmp_path, EXAMPLES)
    method = visible((tmp_path / "method.html").read_text())
    assert "never capped" not in method and "Search never spends model budget." in method
    assert "with a link to its source text" in method and "with a link to the filing" not in method


def test_method_counts_the_live_index_from_the_bundle(tmp_path):
    """The bundle's own counts, table-of-contents passages included; M3's passage count leaves those out."""
    keys = [k for _, paragraphs in METHOD for p in paragraphs for c in p for k in cell_keys(c)]
    assert "m5_bundle_passages" in keys and "m5_bundle_contracts" in keys and "m3_deals_passages" not in keys
    f = {k: v for k, v in facts().items() if not k.startswith("m5_")}
    render_site(f, tmp_path / "pending", EXAMPLES)
    assert "The live index holds pending agreements in pending passages" in visible(
        (tmp_path / "pending" / "method.html").read_text())
    render_site({**f, "m5_bundle_contracts": 406, "m5_bundle_passages": 88628}, tmp_path / "built", EXAMPLES)
    assert "The live index holds 406 agreements in 88628 passages" in visible(
        (tmp_path / "built" / "method.html").read_text())


def test_method_says_the_live_model_thinks_and_how_much(tmp_path):
    sentence = ("The live model answers with extended thinking, as the evaluation runs did, "
                "with up to {} tokens of thinking per answer.")
    render_site({**facts(), "m5_thinking_budget_tokens": 1234}, tmp_path / "a", EXAMPLES)
    assert sentence.format(1234) in visible((tmp_path / "a" / "method.html").read_text())
    f = {k: v for k, v in facts().items() if k != "m5_thinking_budget_tokens"}
    render_site(f, tmp_path / "b", EXAMPLES)
    assert sentence.format("pending") in visible((tmp_path / "b" / "method.html").read_text())

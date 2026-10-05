import html
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path

import pytest

from evals.tmachine import FAMILIES
from facts.labels import MACHINE, is_machine_built, tier_label
from facts.site import METHOD, Facts, cell_keys, render_cell, render_site, render_table, results_tables
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

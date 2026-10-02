"""Real sec.gov shapes recorded by the M0 probe; pinned so a change cannot silently break them."""
import json
from pathlib import Path

from pipeline.edgar_search import is_ex21, row
from pipeline.html_text import to_text
from pipeline.m0 import press_release_url
from pipeline.target import is_tech, preamble

FIX = Path(__file__).parent / "fixtures" / "sec"
PR_ROW = ('<tr><td>3</td><td>Press release</td><td><a href="/Archives/edgar/data/1/2/pr.htm">pr.htm</a></td>'
          '<td>EX-99.1</td><td>9</td></tr>')


def hits():
    return json.loads((FIX / "fts.json").read_text(encoding="utf-8"))["hits"]["hits"]


def test_real_preamble_keeps_plus_in_names():
    p = preamble(to_text((FIX / "ex21.htm").read_bytes(), "ex21.htm"))
    assert p.parent == "MANN+HUMMEL HOLDING GmbH"
    assert p.company == "AFFINIA GROUP HOLDINGS INC."
    assert p.amendment is True


def test_fts_rows_are_complete_and_aligned():
    for h in hits():
        r = row(h)
        assert r["adsh"] and r["filename"]
        assert len(r["ciks"]) == len(r["names"]) == len(r["sics"])


def test_fts_ex21_hit():
    assert any(is_ex21(row(h)["file_type"]) for h in hits() if h["_source"].get("file_type") == "EX-2.1")


def test_submissions_sic_is_str_and_handled():
    sic = json.loads((FIX / "submissions.json").read_text(encoding="utf-8"))["sic"]
    assert isinstance(sic, str)
    assert is_tech(sic) in (True, False)
    assert is_tech(sic) == is_tech(int(sic))


def test_press_release_url_on_real_index():
    html = (FIX / "index.htm").read_text(encoding="utf-8")
    assert press_release_url(html) is None
    with_pr = html.replace("</table>", PR_ROW + "</table>", 1)
    assert press_release_url(with_pr) == "https://www.sec.gov/Archives/edgar/data/1/2/pr.htm"

from pipeline.html_text import to_text

HTML = b"""<html><head><style>p{color:red}</style><script>var x=1;</script></head><body>
<p align="center"><b>AGREEMENT AND PLAN OF MERGER</b></p>
<p>This AGREEMENT AND PLAN OF MERGER, dated as of March&nbsp;1, 2016, by and among
Parent&#160;Inc., a Delaware corporation (&#8220;Parent&#8221;), and Acme Software, Inc. (the &ldquo;Company&rdquo;).</p>
<p style="text-align:center">- 2 -</p>
<div>ARTICLE I</div><table><tr><td>Section&nbsp;1.1</td><td>The Merger.</td></tr></table>
</body></html>"""


def test_html_becomes_lines_without_markup_scripts_or_page_numbers():
    text = to_text(HTML, "d1dex21.htm")
    assert "AGREEMENT AND PLAN OF MERGER\n" in text
    assert "dated as of March 1, 2016" in text
    assert "(“Parent”)" in text and "(the “Company”)" in text
    assert "color" not in text and "var x" not in text
    assert "- 2 -" not in text
    assert "\n\n\n" not in text and "  " not in text


def test_plain_text_passes_through_canonicalised():
    raw = "﻿AGREEMENT AND PLAN OF MERGER\r\n\r\n\r\n\r\nPage 3\r\nSection 1.1 The Merger.\r\n".encode()
    assert to_text(raw, "ex2-1.txt") == "AGREEMENT AND PLAN OF MERGER\n\nSection 1.1 The Merger.\n"


def test_html_detected_by_content_when_the_extension_is_txt():
    assert to_text(b"<HTML><BODY><P>Hello</P><P>World</P></BODY></HTML>", "x.txt").split() == ["Hello", "World"]


def test_cp1252_bytes_decode_to_curly_quotes():
    assert to_text(b"the \x93Company\x94", "x.txt") == "the “Company”\n"


def test_sgml_submission_keeps_only_the_text_block():
    sub = (b"<SEC-DOCUMENT>" + b"HEADER " * 500 + b"<DOCUMENT><TYPE>EX-2.1<TEXT><html><body><p>The Agreement</p>"
           b"</body></html></TEXT></DOCUMENT></SEC-DOCUMENT>")
    assert to_text(sub, "0001.txt") == "The Agreement\n"


def test_pre_keeps_newlines_and_title_is_dropped():
    t = to_text(b"<html><head><title>T!</title></head><body><pre>line one\nline two</pre></body></html>", "a.htm")
    assert t == "line one\nline two\n"


def test_an_html_exhibit_with_svg_text_is_not_cut_to_a_text_block():
    raw = b'<html><body><svg><text>Logo</text></svg><p>AGREEMENT AND PLAN OF MERGER</p></body></html>'
    assert "AGREEMENT AND PLAN OF MERGER" in to_text(raw, "d1dex21.htm")


def test_a_document_wrapper_is_cut_to_its_text_block_whatever_the_extension():
    raw = b"  <DOCUMENT>\n<TYPE>EX-2.1\n<TEXT>\n<html><body><p>The Agreement</p></body></html>\n</TEXT>\n</DOCUMENT>"
    assert to_text(raw, "d1dex21.htm") == "The Agreement\n"

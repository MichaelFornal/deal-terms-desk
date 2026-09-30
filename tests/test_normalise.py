from pipeline.normalise import canonical, load_contract, squash


def test_canonical_strips_bom_and_normalises_newlines():
    assert canonical("﻿A\r\nB\rC") == "A\nB\nC"


def test_canonical_keeps_inner_whitespace():
    assert canonical("2.6           Conversion") == "2.6           Conversion"


def test_load_contract_reads_utf8_with_bad_bytes(tmp_path):
    p = tmp_path / "c.txt"
    p.write_bytes(b"\xef\xbb\xbfSection 1.1 \xff Closing")
    text = load_contract(p)
    assert text.startswith("Section 1.1") and text.endswith("Closing")


def test_squash_maps_back_to_original_offsets():
    text = "a \n b\tc"
    squashed, index = squash(text)
    assert squashed == "abc"
    assert [text[i] for i in index] == ["a", "b", "c"]


def test_squash_of_whitespace_only_is_empty():
    assert squash(" \n\t") == ("", [])

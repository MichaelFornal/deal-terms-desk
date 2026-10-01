import sqlite3

from retrieval.index import build_index

DOC_A = (
    "TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 Merger 6  Section 2.1 Stock 9  Section 2.2 Options 9  Section 3.1 Fees 12\n\n"
    "Section 1.1 Closing. The closing shall occur.\n\n"
    "Section 1.2 Merger. “Effective Time” means the time of filing.\n\n"
    "Section 2.2 Options. Each Company Option shall vest in full at the Effective Time.\n"
)
DOC_B = "Section 1.1 Fees. The Company shall pay the Termination Fee of $50,000,000 to Parent.\n"


def test_build_writes_all_tables(tmp_path):
    db = tmp_path / "idx" / "maud.db"
    summary = build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    conn = sqlite3.connect(db)
    assert summary["contracts"] == conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0] == 2
    assert summary["passages"] == conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]
    assert summary["indexed"] == conn.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]
    assert summary["terms"] == conn.execute("SELECT COUNT(*) FROM terms").fetchone()[0] == 1
    toc = conn.execute("SELECT COUNT(*) FROM passages WHERE kind = 'toc'").fetchone()[0]
    assert toc >= 1 and summary["indexed"] == summary["passages"] - toc


def test_stored_offsets_recover_the_indexed_text(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_b": DOC_B})
    conn = sqlite3.connect(db)
    pid, s, e = conn.execute("SELECT passage_id, start_char, end_char FROM passages").fetchone()
    assert conn.execute("SELECT text FROM passages_fts WHERE rowid = ?", (pid,)).fetchone()[0] == DOC_B[s:e]


def test_rebuild_is_idempotent_and_leaves_no_temp_file(tmp_path):
    db = tmp_path / "maud.db"
    first = build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    second = build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    assert first == second
    assert sorted(p.name for p in tmp_path.iterdir()) == ["maud.db"]


def test_index_stores_section_paths(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    doc = "ARTICLE I\nTERMS\n\nSection 1.1 Closing. The closing occurs.\n\nSection 1.2 Merger. The merger occurs.\n"
    db = tmp_path / "i.db"
    build_index(db, {"c": doc})
    paths = [r[0] for r in sqlite3.connect(db).execute(
        "SELECT section_path FROM passages WHERE kind = 'section' ORDER BY ordinal")]
    assert paths == ["Article I › 1.1", "Article I › 1.2"]


def test_passages_carry_definitions_of_terms_they_use(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    parts = ["Section 1.1 Definitions. “Company Termination Fee” means an amount in cash equal to $50,000,000.\n\n",
             "Section 8.3 Fees. The Company shall pay the Company Termination Fee.\n\n"]
    parts += [f"Section 9.{i} Misc. Filler clause number {i}.\n\n" for i in range(1, 5)]
    doc = "".join(parts)
    db = tmp_path / "i.db"
    build_index(db, {"c": doc})
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT p.section_id, d.term FROM passage_defs d JOIN passages p USING (passage_id)").fetchall()
    assert rows == [("8.3", "Company Termination Fee")]
    [x] = conn.execute("SELECT x.text FROM passages_x_fts x JOIN passages p ON p.passage_id = x.rowid"
                       " WHERE p.section_id = '8.3'").fetchall()
    assert "amount in cash" in x[0]
    assert conn.execute("SELECT COUNT(*) FROM passages_x_fts").fetchone() == conn.execute(
        "SELECT COUNT(*) FROM passages_fts").fetchone()


def _defs_by_section(db):
    import sqlite3
    return sqlite3.connect(db).execute(
        "SELECT p.section_id, d.term FROM passage_defs d JOIN passages p USING (passage_id)"
        " ORDER BY p.ordinal, d.rank").fetchall()


def test_ubiquity_cutoff(tmp_path):
    from retrieval.index import build_index
    # 10 passages: the definitions one plus 9 others. Alpha used in 2 of 10 (20%): kept. Beta in 3 of 10: dropped.
    parts = ["Section 1.1 Definitions. “Alpha Term” means a. “Beta Term” means b.\n\n"]
    for i in range(2, 11):
        use = ""
        if i <= 3:
            use += " Alpha Term applies."
        if i <= 4:
            use += " Beta Term applies."
        parts.append(f"Section {i}.1 Misc.{use} Filler {i}.\n\n")
    db = tmp_path / "u.db"
    build_index(db, {"c": "".join(parts)})
    got = _defs_by_section(db)
    assert ("2.1", "Alpha Term") in got and ("3.1", "Alpha Term") in got
    assert not any(t == "Beta Term" for _, t in got)


def test_max_defs_caps_at_six_in_first_use_order(tmp_path):
    from retrieval.index import build_index
    names = ["Term " + c for c in "ABCDEFGH"]
    parts = ["Section 1.1 Definitions. " + " ".join(f"“{n}” means x." for n in names) + "\n\n"]
    parts.append("Section 2.1 Use. " + " ".join(f"{n} applies." for n in reversed(names)) + "\n\n")
    parts += [f"Section 3.{i} Misc. Filler {i}.\n\n" for i in range(1, 60)]
    db = tmp_path / "m.db"
    build_index(db, {"c": "".join(parts)})
    got = _defs_by_section(db)
    assert got == [("2.1", f"Term {c}") for c in "HGFEDC"]

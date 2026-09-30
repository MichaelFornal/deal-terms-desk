from evals.maud_labels import load_rows

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"


def write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def test_only_main_rows_with_real_contracts_are_loaded(tmp_path):
    p = write(
        tmp_path, "a.csv",
        'main,contract_1,"Section 2.6 text",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,1,General Information\n'
        "abridged,contract_1,short,All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,2,General Information\n"
        "rare_answers,<RARE_ANSWERS>,made up,Other,3,Type of Consideration-Answer,<NONE>,Type of Consideration,3,General Information\n",
    )
    rows = load_rows([p])
    assert len(rows) == 1
    r = rows[0]
    assert (r.contract_id, r.text, r.answer, r.text_type, r.category) == (
        "contract_1", "Section 2.6 text", "All Cash", "Type of Consideration", "General Information")


def test_duplicate_rows_across_files_are_removed(tmp_path):
    line = "main,contract_1,t,a,0,q,<NONE>,tt,1,c\n"
    rows = load_rows([write(tmp_path, "a.csv", line), write(tmp_path, "b.csv", line)])
    assert len(rows) == 1


def test_very_long_text_field_is_read(tmp_path):
    big = "x" * 300_000
    rows = load_rows([write(tmp_path, "a.csv", f"main,contract_1,{big},a,0,q,<NONE>,tt,1,c\n")])
    assert len(rows[0].text) == 300_000

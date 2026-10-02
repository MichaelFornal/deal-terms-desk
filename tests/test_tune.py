import json

from evals.bootstrap import split_of
from evals.run_rung import load_context
from evals.tune import GRID_DEPTH, GRID_K0, GRID_RERANK_DEPTH, tune
from retrieval.index import build_index
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder, FakeReranker

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
IDS = [f"contract_{i}" for i in range(60)]
TUNE = [c for c in IDS if split_of(c) == "tune"][:3]
REPORT = [c for c in IDS if split_of(c) == "report"][:2]
DOC = ("Section 1.1 Closing. The closing shall occur at the offices of counsel.\n\n"
       "Section 8.3 Termination Fee. The Company shall pay Parent a termination fee in cash.\n")


def setup(tmp_path, doc=DOC):
    cdir = tmp_path / "contracts"
    cdir.mkdir()
    texts = {c: doc for c in TUNE + REPORT}
    for c, t in texts.items():
        (cdir / f"{c}.txt").write_text(t, encoding="utf-8")
    fee = DOC.split("\n\n")[1].strip()
    body = "".join(f'main,{c},"{fee} (Page 70)",Yes,1,Termination Fee-Answer,<NONE>,Termination Fee,{i},'
                   f'Deal Protection and Related Provisions\n' for i, c in enumerate(texts))
    (tmp_path / "l.csv").write_text(HEADER + body, encoding="utf-8")
    db = tmp_path / "maud.db"
    build_index(db, texts)
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    return load_context(db, [tmp_path / "l.csv"], cdir), conn, emb


class Named(FakeReranker):
    def __init__(self, name, ms):
        super().__init__(ms)
        self.name = name


def test_tune_reads_only_the_tune_split_and_records_its_evidence(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    out = tmp_path / "settings.json"
    doc = tune(ctx, conn, emb, lambda name: Named(name, 5.0), tmp_path / "rr.db", out, rerankers=("a", "b"))
    assert json.loads(out.read_text()) == doc
    assert doc["tuned_on"] == {"split": "tune", "items": 3, "contracts": 3}
    assert len(doc["evidence"]["fusion"]) == len(GRID_DEPTH) * len(GRID_K0)
    assert [r["rerank_depth"] for r in doc["evidence"]["rerank_depth"]] == list(GRID_RERANK_DEPTH)
    assert doc["live_path_ok"] is True
    best = doc["settings"]
    assert (best["depth"], best["rrf_k0"]) == (20, 60)
    assert set(doc["load"]) == {"before", "after"}
    assert doc["evidence"]["probe_qualified"] is True


def test_progress_reports_every_configuration(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    lines = []
    tune(ctx, conn, emb, lambda name: Named(name, 5.0), tmp_path / "rr.db", tmp_path / "s.json",
         rerankers=("a", "b"), progress=lines.append)
    for d in GRID_DEPTH:
        for k0 in GRID_K0:
            assert any(f"R3 depth={d} k0={k0}" in x for x in lines)
    assert any("R4 a depth=20" in x for x in lines) and any("R4 b depth=20" in x for x in lines)
    assert all(any(f"R4 a depth={d}" in x or f"R4 b depth={d}" in x for x in lines) for d in GRID_RERANK_DEPTH)


class PerText(FakeReranker):
    def score(self, query, texts):
        scores, _ = super().score(query, texts)
        return scores, 250.0 * len(texts)


def test_final_live_path_flag_reflects_the_final_setting_not_the_probe(tmp_path):
    big = "".join(f"Section {i}.1 Item{i}. Clause number {i} about matters.\n\n" for i in range(40)) + DOC
    ctx, conn, emb = setup(tmp_path, big)
    doc = tune(ctx, conn, emb, lambda name: PerText(), tmp_path / "rr.db", tmp_path / "s.json", rerankers=("only",))
    assert doc["evidence"]["probe_qualified"] is False
    assert doc["settings"]["reranker"] == "only"
    assert doc["settings"]["rerank_depth"] == 10 and doc["live_path_ok"] is True


def test_a_reranker_over_the_latency_limit_is_not_chosen_while_another_qualifies(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    speeds = {"slow": 9000.0, "fast": 5.0}
    doc = tune(ctx, conn, emb, lambda name: Named(name, speeds[name]), tmp_path / "rr.db", tmp_path / "s.json",
               rerankers=("slow", "fast"))
    assert doc["settings"]["reranker"] == "fast"


def test_with_no_qualifying_reranker_the_fastest_is_kept_and_flagged(tmp_path):
    ctx, conn, emb = setup(tmp_path)
    speeds = {"slow": 9000.0, "slower": 12000.0}
    doc = tune(ctx, conn, emb, lambda name: Named(name, speeds[name]), tmp_path / "rr.db", tmp_path / "s.json",
               rerankers=("slow", "slower"))
    assert doc["settings"]["reranker"] == "slow" and doc["live_path_ok"] is False

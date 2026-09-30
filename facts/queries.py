import sqlite3
from typing import Callable


def _scalar(sql: str):
    return lambda conn, r1: conn.execute(sql).fetchone()[0]


def _metric(metric: str, field: str = "mean", split: str | None = None):
    def q(conn, r1):
        block = r1["by_split"][split] if split else r1["overall"]
        return round(block[metric][field], 4)
    return q


def _align_rate(conn, r1):
    a = r1["alignment"]
    return round((a["pieces_exact"] + a["pieces_anchored"]) / a["pieces"], 4)


def _section_share(conn, r1):
    total, with_id = conn.execute(
        "SELECT COUNT(*), SUM(section_id != '') FROM passages WHERE kind != 'toc'").fetchone()
    return round(with_id / total, 4)


QUERIES: dict[str, Callable[[sqlite3.Connection, dict], int | float]] = {
    "maud_contracts": _scalar("SELECT COUNT(*) FROM contracts"),
    "maud_chars": _scalar("SELECT SUM(n_chars) FROM contracts"),
    "maud_passages": _scalar("SELECT COUNT(*) FROM passages"),
    "maud_passages_indexed": _scalar("SELECT COUNT(*) FROM passages_fts"),
    "maud_passages_with_section_share": _section_share,
    "maud_terms": _scalar("SELECT COUNT(*) FROM terms"),
    "maud_label_rows_main": lambda conn, r1: r1["alignment"]["rows"],
    "eval_items": lambda conn, r1: r1["alignment"]["items"],
    "eval_items_scored": lambda conn, r1: r1["alignment"]["items_scored"],
    "eval_items_no_gold": lambda conn, r1: r1["alignment"]["items_no_gold"],
    "eval_items_missing_contract": lambda conn, r1: r1["alignment"]["items_missing_contract"],
    "align_pieces": lambda conn, r1: r1["alignment"]["pieces"],
    "align_piece_rate": _align_rate,
    "r1_recall_at_1": _metric("recall@1"),
    "r1_recall_at_5": _metric("recall@5"),
    "r1_recall_at_10": _metric("recall@10"),
    "r1_mrr_at_10": _metric("mrr@10"),
    "r1_ndcg_at_10": _metric("ndcg@10"),
    "r1_report_items": lambda conn, r1: r1["by_split"]["report"]["recall@5"]["n_items"],
    "r1_report_contracts": lambda conn, r1: r1["by_split"]["report"]["recall@5"]["n_clusters"],
    "r1_report_recall_at_1": _metric("recall@1", split="report"),
    "r1_report_recall_at_5": _metric("recall@5", split="report"),
    "r1_report_recall_at_5_lo": _metric("recall@5", "lo", split="report"),
    "r1_report_recall_at_5_hi": _metric("recall@5", "hi", split="report"),
    "r1_report_recall_at_10": _metric("recall@10", split="report"),
    "r1_report_mrr_at_10": _metric("mrr@10", split="report"),
    "r1_report_ndcg_at_10": _metric("ndcg@10", split="report"),
    "r1_latency_ms_p50": lambda conn, r1: round(r1["latency_ms"]["p50"], 2),
    "r1_latency_ms_p95": lambda conn, r1: round(r1["latency_ms"]["p95"], 2),
}

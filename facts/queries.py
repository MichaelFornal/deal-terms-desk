import sqlite3
from typing import Callable

# MAUD's deal-point categories, each with the slug its named facts use.
CATEGORIES = {
    "conditions": "Conditions to Closing",
    "deal_protection": "Deal Protection and Related Provisions",
    "general": "General Information",
    "knowledge": "Knowledge",
    "mae": "Material Adverse Effect",
    "covenants": "Operating and Efforts Covenant",
    "remedies": "Remedies",
}
REPORT_METRICS = {
    "recall_at_1": "recall@1",
    "recall_at_5": "recall@5",
    "recall_at_10": "recall@10",
    "mrr_at_10": "mrr@10",
    "ndcg_at_10": "ndcg@10",
}


def _scalar(sql: str):
    return lambda conn, r1, labels: conn.execute(sql).fetchone()[0]


def _metric(metric: str, field: str = "mean", split: str | None = None):
    def q(conn, r1, labels):
        block = r1["by_split"][split] if split else r1["overall"]
        return round(block[metric][field], 4)
    return q


def _category(name: str, field: str):
    """recall@5 for one category; a category with no scored items has no value and zero counts."""
    def q(conn, r1, labels):
        block = r1["by_category"].get(name)
        if block is None:
            return 0 if field.startswith("n_") else None
        value = block["recall@5"][field]
        return value if field.startswith("n_") else round(value, 4)
    return q


def _alignment(key: str):
    return lambda conn, r1, labels: r1["alignment"][key]


def _align_rate(conn, r1, labels):
    a = r1["alignment"]
    return round((a["pieces_exact"] + a["pieces_anchored"]) / a["pieces"], 4)


def _section_share(conn, r1, labels):
    total, with_id = conn.execute(
        "SELECT COUNT(*), SUM(section_id != '') FROM passages WHERE kind != 'toc'").fetchone()
    return round(with_id / total, 4)


def _label_contracts_with_text(conn, r1, labels):
    with_text = {r[0] for r in conn.execute("SELECT contract_id FROM contracts")}
    return len(labels["contracts"] & with_text)


QUERIES: dict[str, Callable[[sqlite3.Connection, dict, dict], int | float | None]] = {
    "maud_contracts": _scalar("SELECT COUNT(*) FROM contracts"),
    "maud_chars": _scalar("SELECT SUM(n_chars) FROM contracts"),
    "maud_passages": _scalar("SELECT COUNT(*) FROM passages"),
    "maud_passages_indexed": _scalar("SELECT COUNT(*) FROM passages_fts"),
    "maud_passages_with_section_share": _section_share,
    "maud_terms_defined": _scalar(
        "SELECT COUNT(*) FROM (SELECT DISTINCT contract_id, term FROM terms WHERE style IN ('means', 'paren'))"),
    "maud_terms_xref": _scalar("SELECT COUNT(*) FROM terms WHERE style = 'xref'"),
    "maud_label_rows_all": lambda conn, r1, labels: labels["rows"],
    "maud_label_contracts": lambda conn, r1, labels: len(labels["contracts"]),
    "maud_label_contracts_with_text": _label_contracts_with_text,
    "maud_question_types": lambda conn, r1, labels: len(labels["questions"]),
    "maud_label_rows_main": _alignment("rows"),
    "eval_items": _alignment("items"),
    "eval_items_scored": _alignment("items_scored"),
    "eval_items_no_gold": _alignment("items_no_gold"),
    "eval_items_missing_contract": _alignment("items_missing_contract"),
    "align_pieces": _alignment("pieces"),
    "align_pieces_short": _alignment("pieces_short"),
    "align_pieces_ambiguous": _alignment("pieces_ambiguous"),
    "align_pieces_toc_rescued": _alignment("pieces_toc_rescued"),
    "align_pieces_toc_only": _alignment("pieces_toc_only"),
    "align_piece_rate": _align_rate,
    "r1_recall_at_1": _metric("recall@1"),
    "r1_recall_at_5": _metric("recall@5"),
    "r1_recall_at_10": _metric("recall@10"),
    "r1_mrr_at_10": _metric("mrr@10"),
    "r1_ndcg_at_10": _metric("ndcg@10"),
    "r1_report_items": lambda conn, r1, labels: r1["by_split"]["report"]["recall@5"]["n_items"],
    "r1_report_contracts": lambda conn, r1, labels: r1["by_split"]["report"]["recall@5"]["n_clusters"],
    "r1_latency_ms_p50": lambda conn, r1, labels: round(r1["latency_ms"]["p50"], 2),
    "r1_latency_ms_p95": lambda conn, r1, labels: round(r1["latency_ms"]["p95"], 2),
}
for _name, _key in REPORT_METRICS.items():
    for _suffix, _field in (("", "mean"), ("_lo", "lo"), ("_hi", "hi")):
        QUERIES[f"r1_report_{_name}{_suffix}"] = _metric(_key, _field, split="report")
for _slug, _category_name in CATEGORIES.items():
    for _suffix, _field in (("_recall_at_5", "mean"), ("_recall_at_5_lo", "lo"), ("_recall_at_5_hi", "hi"),
                            ("_items", "n_items"), ("_contracts", "n_clusters")):
        QUERIES[f"r1_cat_{_slug}{_suffix}"] = _category(_category_name, _field)

import sqlite3

import sqlite_vec

from retrieval.bm25 import Hit


def search_dense(conn: sqlite3.Connection, qvec: list[float], contract_id: str | None = None, k: int = 10) -> list[Hit]:
    """Nearest passages by cosine. The contract filter is the vec0 partition key, so it runs inside the KNN."""
    where = "embedding MATCH ? AND k = ?"
    params: list = [sqlite_vec.serialize_float32(qvec), k]
    if contract_id is not None:
        where += " AND contract_id = ?"
        params.append(contract_id)
    sql = ("SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, 1.0 - v.distance"
           f" FROM (SELECT passage_id, distance FROM passages_vec WHERE {where}) v"
           " JOIN passages p ON p.passage_id = v.passage_id ORDER BY v.distance, p.passage_id")
    return [Hit(*row) for row in conn.execute(sql, params)]

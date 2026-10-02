import calendar
from datetime import date, timedelta
from urllib.parse import urlencode

FTS = "https://efts.sec.gov/LATEST/search-index"
PHRASE = '"agreement and plan of merger"'
PAGE = 100
CAP = 10000
START = date(2015, 1, 1)


def search_url(start: date, end: date, offset: int) -> str:
    return FTS + "?" + urlencode({"q": PHRASE, "forms": "8-K", "dateRange": "custom",
                                  "startdt": start.isoformat(), "enddt": end.isoformat(), "from": offset})


def months(start: date, end: date) -> list[tuple[date, date]]:
    out = []
    cur = start
    while cur <= end:
        last = date(cur.year, cur.month, calendar.monthrange(cur.year, cur.month)[1])
        out.append((cur, min(last, end)))
        cur = last + timedelta(days=1)
    return out


def row(hit: dict) -> dict:
    accession, _, filename = hit["_id"].partition(":")
    s = hit["_source"]
    return {"adsh": s.get("adsh", accession), "filename": filename, "file_type": s.get("file_type", ""),
            "file_date": s.get("file_date", ""), "form": s.get("form", ""), "ciks": s.get("ciks", []),
            "names": s.get("display_names", []), "sics": s.get("sics", [])}


def is_ex21(file_type: str) -> bool:
    return file_type.strip().upper() in ("EX-2.1", "EX-2.01")


def _folder(r: dict) -> str:
    return f"https://www.sec.gov/Archives/edgar/data/{int(r['ciks'][0])}/{r['adsh'].replace('-', '')}"


def doc_url(r: dict) -> str:
    return f"{_folder(r)}/{r['filename']}"


def index_url(r: dict) -> str:
    return f"{_folder(r)}/{r['adsh']}-index.htm"


def search_window(client, start: date, end: date) -> list[dict]:
    first = client.get_json(search_url(start, end, 0))
    total = first["hits"]["total"]
    over = total["relation"] != "eq" or total["value"] >= CAP
    if over and start < end:
        mid = start + (end - start) // 2
        return search_window(client, start, mid) + search_window(client, mid + timedelta(days=1), end)
    if over:
        raise ValueError(f"{start} alone reaches the {CAP}-result cap; narrow the query")
    hits = list(first["hits"]["hits"])
    for offset in range(PAGE, total["value"], PAGE):
        hits += client.get_json(search_url(start, end, offset))["hits"]["hits"]
    return [row(h) for h in hits]

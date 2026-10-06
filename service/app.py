import json
import math
import sys
import time

from fastapi import Body, FastAPI, Request
from fastapi.responses import JSONResponse

from answer.api_runner import make_api_runner
from retrieval.ladder import SETTINGS_PATH, load_settings
from retrieval.lexicon import LEXICON_PATH, load_lexicon
from retrieval.live import build_live_ladder
from retrieval.models import Embedder
from service.budget import Budget
from service.cache import AnswerCache
from service.config import Config, from_env
from service.desk import Desk
from service.limits import Buckets, Slots, client_key
from service.prices import load_prices


def build_desk(config: Config) -> Desk:
    """Everything the live service holds in memory, built once at startup."""
    embedder = Embedder(threads=2)
    embedder.embed_query("warm up")  # load the model now, not on the first visitor's question
    ladder = build_live_ladder(config.bundle, embedder, load_lexicon(LEXICON_PATH), load_settings(SETTINGS_PATH))
    config.state_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(config.state_dir / "budget.db", config.month_cap_usd, config.day_cap_usd,
                    load_prices(config.prices_path))
    runner = make_api_runner(config.max_tokens, timeout=config.api_timeout_s,
                             thinking_budget=config.thinking_budget or None)
    return Desk(ladder, runner, config, budget, AnswerCache(config.state_dir / "cache.db"),
                Buckets(config.fresh_per_hour, 3600.0), Slots(config.ask_slots))


def _log(rec: dict) -> None:
    """One line per request, to stderr (journald on the box). Never the visitor's address or question."""
    print(json.dumps(rec, sort_keys=True), file=sys.stderr, flush=True)


def _invalid(detail: str) -> JSONResponse:
    return JSONResponse({"error": "invalid", "detail": detail}, status_code=422)


def _limited(wait: float) -> JSONResponse:
    return JSONResponse({"error": "rate_limited"}, status_code=429,
                        headers={"Retry-After": str(max(1, math.ceil(wait)))})


def create_app(config: Config | None = None, desk: Desk | None = None) -> FastAPI:
    """With no arguments (`uvicorn --factory service.app:create_app`), config comes from the environment and the desk
    is built here; tests pass both."""
    if desk is None:
        config = config or from_env()
        desk = build_desk(config)
    config = config or desk.config
    asks, searches = Buckets(config.ask_per_hour, 3600.0), Buckets(config.search_per_minute, 60.0)
    app = FastAPI(title="Deal Terms Desk", docs_url=None, redoc_url=None, openapi_url=None)

    def who(request: Request) -> str:
        return client_key(request.client.host if request.client else "unknown")

    def problem(question) -> str | None:
        if not isinstance(question, str) or not question.strip():
            return "the question is empty"
        if len(question) > config.question_max_chars:
            return "the question is too long"
        return None

    @app.get("/api/health")
    def health():
        return desk.health()

    @app.get("/api/deals")
    def deals():
        return desk.deals()

    @app.get("/api/search")
    def search(request: Request, q: str = "", deal: str | None = None):
        t0 = time.perf_counter()
        bad = problem(q)
        if bad:
            return _invalid(bad)
        wait = searches.allow(who(request))
        if wait:
            return _limited(wait)
        try:
            got = desk.search(q, deal or None)
        except ValueError as e:
            return _invalid(str(e))
        _log({"route": "search", "status": 200, "hits": len(got["hits"]),
              "ms": round((time.perf_counter() - t0) * 1000.0, 1)})
        return got

    @app.post("/api/ask")
    def ask(request: Request, body: dict = Body(...)):
        t0 = time.perf_counter()
        question, deal = body.get("question"), body.get("deal")
        bad = problem(question) or (None if deal is None or isinstance(deal, str) else "the deal must be an id")
        if bad:
            return _invalid(bad)
        wait = asks.allow(who(request))
        if wait:
            return _limited(wait)
        try:
            got = desk.ask(question, deal or None)
        except ValueError as e:
            return _invalid(str(e))
        _log({"route": "ask", "status": 200, "state": got["state"], "served_from": got["served_from"],
              "tokens": got["tokens"], "ms": round((time.perf_counter() - t0) * 1000.0, 1)})
        return got

    return app

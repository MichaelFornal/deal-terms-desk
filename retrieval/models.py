import time

EMBED_MODEL = "BAAI/bge-small-en-v1.5"
EMBED_DIM = 384
MAX_TOKENS = 512
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
RERANKERS = ("BAAI/bge-reranker-base", "Xenova/ms-marco-MiniLM-L-6-v2", "jinaai/jina-reranker-v1-tiny-en")


class Embedder:
    def __init__(self, name: str = EMBED_MODEL, threads: int | None = None):
        self.name = name
        self._threads = threads
        self._model = None

    def _m(self):
        if self._model is None:
            from fastembed import TextEmbedding
            self._model = TextEmbedding(self.name, threads=self._threads)
        return self._model

    def embed_passages(self, texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in self._m().embed(texts, batch_size=16)]

    def embed_query(self, q: str) -> list[float]:
        return [float(x) for x in next(iter(self._m().embed([QUERY_PREFIX + q])))]

    def count_tokens(self, text: str) -> int:
        tok = self._m().model.tokenizer
        tok.no_truncation()
        try:
            return len(tok.encode(text).ids)
        finally:
            tok.enable_truncation(MAX_TOKENS)


class Reranker:
    def __init__(self, name: str, threads: int | None = None):
        self.name = name
        self._threads = threads
        self._model = None

    def score(self, query: str, texts: list[str]) -> tuple[list[float], float]:
        """Scores in input order and the milliseconds the model took."""
        if not texts:
            return [], 0.0
        if self._model is None:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            self._model = TextCrossEncoder(self.name, threads=self._threads)
        t0 = time.perf_counter()
        scores = [float(s) for s in self._model.rerank(query, texts, batch_size=len(texts))]
        return scores, (time.perf_counter() - t0) * 1000.0

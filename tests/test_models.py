import pytest

from retrieval.models import EMBED_DIM, MAX_TOKENS, Embedder

pytestmark = pytest.mark.model


def test_real_embedder_shapes_and_untruncated_token_count():
    e = Embedder()
    [v] = e.embed_passages(["The Company shall pay the Termination Fee."])
    assert len(v) == EMBED_DIM and len(e.embed_query("termination fee")) == EMBED_DIM
    assert e.count_tokens("fee " * 700) > MAX_TOKENS

"""Reranking: determinism, fallback, window logic, and the filter guarantee.

No test here loads the real cross-encoder or the embedding model: scoring is
injected or monkeypatched, and the index is keyword-only, so the suite is
deterministic and offline.
"""

from __future__ import annotations

import logging

import pytest

from engine.retrieval import rerank as rr
from engine.retrieval import search as search_mod
from engine.retrieval.corpus import load_corpus
from engine.retrieval.entities import Entities, extract_entities
from engine.retrieval.index import build_index, load_index
from engine.retrieval.layout import CorpusUnavailable


@pytest.fixture(autouse=True)
def _clean_rerank_state():
    rr.reset_for_tests()
    yield
    rr.reset_for_tests()


def _unavailable(*_a, **_k):
    raise rr.RerankUnavailable("no network, cannot load test model")


# --- rerank_candidates ------------------------------------------------------


def test_identical_input_gives_identical_order():
    texts = [f"t{i}" for i in range(10)]
    scorer = lambda q, ts: [float(len(t) % 3) for t in ts]  # many ties
    a = rr.rerank_candidates("q", texts, scorer=scorer)
    b = rr.rerank_candidates("q", texts, scorer=scorer)
    assert a.order == b.order and a.applied


def test_ties_keep_incoming_rrf_order():
    out = rr.rerank_candidates("q", ["a", "b", "c", "d"], scorer=lambda q, t: [1.0] * 4)
    assert out.order == [0, 1, 2, 3]


def test_higher_score_first_and_all_candidates_kept():
    out = rr.rerank_candidates("q", list("abcd"), scorer=lambda q, t: [0.1, 0.9, -2.0, 0.5])
    assert out.order == [1, 3, 0, 2]
    assert sorted(out.order) == [0, 1, 2, 3]


def test_unavailable_model_returns_identity_with_reason_and_logs(caplog):
    with caplog.at_level(logging.WARNING, logger="engine.retrieval.rerank"):
        out = rr.rerank_candidates("q", list("abc"), scorer=_unavailable)
    assert not out.applied
    assert out.order == [0, 1, 2]
    assert "cannot load test model" in out.reason
    assert any("cannot load test model" in r.getMessage() for r in caplog.records)


def test_model_load_failure_is_cached_not_retried(monkeypatch):
    calls = []

    class Boom:
        def __init__(self, *a, **k):
            calls.append(1)
            raise OSError("offline")

    import sentence_transformers

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Boom)
    for _ in range(3):
        out = rr.rerank_candidates("q", ["a", "b"])
        assert not out.applied and "offline" in out.reason
    assert len(calls) == 1


def test_model_loaded_once_across_queries(monkeypatch):
    loads = []

    class Fake:
        def __init__(self, name, **k):
            loads.append(name)

        def predict(self, pairs, **k):
            return [float(len(p[1])) for p in pairs]

    import sentence_transformers

    monkeypatch.setattr(sentence_transformers, "CrossEncoder", Fake)
    for q in ("one", "two", "three"):
        assert rr.rerank_candidates(q, ["aa", "b"]).applied
    assert loads == [rr.RERANK_MODEL]


def test_single_candidate_is_not_scored():
    out = rr.rerank_candidates("q", ["only"], scorer=_unavailable)
    assert not out.applied and out.order == [0]


# --- select_top / window logic ---------------------------------------------


def test_select_top_takes_first_k():
    assert rr.select_top([5, 3, 1, 0, 2, 4], 3) == [5, 3, 1]


def test_select_top_keeps_required_group_member():
    # Candidates 4 and 5 belong to the AD the query named; the reranker ranked
    # them last. The best of them must survive the cut, in reranked position.
    out = rr.select_top([0, 1, 2, 3, 4, 5], 3, required_groups=[[4, 5]])
    assert out == [0, 1, 4]


def test_select_top_ignores_group_already_represented_or_absent():
    assert rr.select_top([0, 1, 2, 3], 2, [[1], [99]]) == [0, 1]


def test_window_is_wider_than_k():
    assert rr.RERANK_WINDOW > 8


# --- search integration -----------------------------------------------------


@pytest.fixture(scope="module")
def keyword_index(tmp_path_factory):
    try:
        corpus = load_corpus()
    except CorpusUnavailable as exc:  # pragma: no cover - corpus is generated
        pytest.skip(f"corpus not built: {exc}")
    tmp = tmp_path_factory.mktemp("rerank_idx")
    build_index(corpus, db_path=tmp / "r.db", embeddings_path=tmp / "r.npy", dense=False)
    index = load_index(corpus, db_path=tmp / "r.db", embeddings_path=tmp / "r.npy")
    yield index
    index.close()


def _ents(index, text):
    return extract_entities(text, known_ad_numbers=index.corpus.ad_numbers)


def _reverse_scorer(query, texts):
    return [float(i) for i in range(len(texts))]  # reverses the RRF order


def test_search_rerank_off_is_unchanged_and_reports_off(keyword_index):
    q = "inspection of the wing"
    off = search_mod.search(keyword_index, q, _ents(keyword_index, q), rerank=False)
    assert off.rerank_status == "off"
    assert all(h.rerank_score is None for h in off.hits)


def test_search_default_flag_is_honoured(keyword_index, monkeypatch):
    monkeypatch.setattr(rr, "score_pairs", _reverse_scorer)
    monkeypatch.setattr(search_mod, "RERANK_DEFAULT", True)
    q = "inspection of the wing"
    res = search_mod.search(keyword_index, q, _ents(keyword_index, q))
    assert res.rerank_status == "applied"


def test_search_fallback_keeps_rrf_order_and_says_why(keyword_index, monkeypatch):
    q = "inspection of the wing"
    ents = _ents(keyword_index, q)
    base = search_mod.search(keyword_index, q, ents, rerank=False)
    monkeypatch.setattr(rr, "score_pairs", _unavailable)
    res = search_mod.search(keyword_index, q, ents, rerank=True)
    assert res.rerank_status == "fallback"
    assert "cannot load test model" in res.rerank_reason
    assert [h.paragraph_id for h in res.hits] == [h.paragraph_id for h in base.hits]
    assert res.top_cosine == base.top_cosine


def test_rerank_window_reaches_past_top_k(keyword_index, monkeypatch):
    """A reversing scorer must be able to pull in a paragraph RRF ranked > 8."""
    q = "inspection of the wing"
    ents = _ents(keyword_index, q)
    base = search_mod.search(keyword_index, q, ents, k=8, rerank=False)
    monkeypatch.setattr(rr, "score_pairs", _reverse_scorer)
    res = search_mod.search(keyword_index, q, ents, k=8, rerank=True)
    assert len(res.hits) == 8
    assert res.paragraph_ids() != base.paragraph_ids()
    assert all(h.rerank_score is not None for h in res.hits)


def test_rerank_never_leaves_the_graph_filter_set(keyword_index, monkeypatch):
    q = "what does AD 2026-21-13 require?"
    ents = _ents(keyword_index, q)
    assert ents.ad_numbers == ["2026-21-13"]
    monkeypatch.setattr(rr, "score_pairs", _reverse_scorer)
    res = search_mod.search(keyword_index, q, ents, rerank=True)
    allowed = set(search_mod.filter_candidates(keyword_index.corpus, ents).paragraph_ids)
    assert res.hits and res.paragraph_ids() <= allowed
    assert {h.ad_number for h in res.hits} == {"2026-21-13"}


def test_named_ad_survives_rerank_when_filter_does_not_narrow(keyword_index, monkeypatch):
    """Force an un-narrowed pool: a named AD present pre-rerank stays present."""
    q = "AD 2026-21-13 elevator tab cracks"
    ents = _ents(keyword_index, q)
    all_rows = search_mod.FilterResult(
        paragraph_ids=[p.paragraph_id for p in keyword_index.corpus.paragraphs]
    )
    base = search_mod.search(keyword_index, q, ents, prefiltered=all_rows, rerank=False)
    assert "2026-21-13" in {h.ad_number for h in base.hits}
    # Scorer that buries every paragraph of the named AD.
    def bury(query, texts):
        return [-1.0 if "elevator" in t.lower() else 1.0 for t in texts]

    monkeypatch.setattr(rr, "score_pairs", bury)
    res = search_mod.search(keyword_index, q, ents, prefiltered=all_rows, rerank=True)
    assert "2026-21-13" in {h.ad_number for h in res.hits}


def test_empty_candidate_set_does_not_invoke_model(keyword_index, monkeypatch):
    monkeypatch.setattr(rr, "score_pairs", _unavailable)
    empty = search_mod.FilterResult(paragraph_ids=[])
    res = search_mod.search(keyword_index, "anything", Entities(), prefiltered=empty, rerank=True)
    assert res.hits == [] and res.rerank_status == "off"

"""Citation numbering + citation-map unit tests.

Three concerns are proven here:

1. Numbered context: the LLM prompt built by the streaming pipeline numbers the
   retrieved sources as [1]..[N] (replacing the old `[Source: {path}]` prefix), so
   the model can cite [N] tied to the exact context order.

2. Citation-map parity: a citations dict {"1".."N"} is derived from the SAME
   enumerate() pass that builds the context, so citations[str(i+1)]["document_id"]
   equals sources[i]["document_id"] in answer_stream() (never
   build the map from a divergent ordering). Distinct document_ids per source make
   a mis-ordering detectable.

3. SSE citation event: answer_stream() emits exactly one {"type": "citation", ...}
   event strictly BEFORE the unchanged {"type": "done", ...} event, and a
   zero-source stream leaves the done contract byte-identical in shape.

Mock/synthetic only: no real Mistral call, no real embeddings.
"""

import asyncio
from unittest.mock import Mock, AsyncMock, patch

from mimir.rag_core.interfaces import SearchResult
from mimir.services.rag_service import _process_question_with_rag_stream


def _sr(chunk_id, document_id, text, source, score):
    return SearchResult(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        source=source,
        similarity_score=score,
        chunk_index=0,
        total_chunks=1,
        metadata={},
    )


def _base_mocks():
    """Common mock harness mirroring test_rag_service_hybrid.py's style."""
    mock_llm_service = AsyncMock()
    mock_vector_store = Mock()
    mock_document_repository = Mock()
    mock_rag_debug = Mock()

    mock_rag_debug.log_user_request = Mock()
    mock_rag_debug.log_vector_search = Mock()
    mock_rag_debug.log_context_building = Mock()
    mock_rag_debug.log_llm_generation = Mock()
    mock_rag_debug.log_error = Mock()

    # No fuzzy filename pre-inclusion matches (keeps the pipeline on the pure
    # dense retrieval path).
    mock_document_repository.get_all.return_value = []
    mock_document_repository.get_by_ids.side_effect = lambda ids: {
        i: Mock(filename="doc.pdf") for i in ids
    }

    mock_llm_service.embed.return_value = AsyncMock(
        embeddings=[[0.1] * 1024],
        usage_tokens=10,
        model="mistral-embed",
        prompt_tokens=10,
        completion_tokens=0,
    )
    mock_llm_service.generate.return_value = AsyncMock(
        content="Réponse synthétique [1].",
        model="mistral",
        usage_tokens=100,
        prompt_tokens=80,
        completion_tokens=20,
        finish_reason="stop",
    )
    return mock_llm_service, mock_vector_store, mock_document_repository, mock_rag_debug


def _dense_settings(mock_settings):
    """Realistic dense-mode settings (hybrid + pre-inclusion off)."""
    mock_settings.hybrid_search_enabled = False
    mock_settings.rrf_k = 60
    mock_settings.rrf_score_threshold = 0.015
    mock_settings.similarity_threshold = 0.5
    mock_settings.dynamic_filter_percentage = 0.15
    mock_settings.max_sources = 5
    mock_settings.min_sources = 1
    mock_settings.confidence_algorithm = "weighted"
    mock_settings.filename_pre_inclusion = False


def _two_source_pool():
    # Distinct document_ids so a citation<->source ordering drift is detectable.
    # Scores comfortably above the 0.5 cosine floor so both survive filtering.
    return [
        _sr(1, "10", "premier extrait pertinent", "a.txt", 0.80),
        _sr(2, "11", "second extrait pertinent", "b.txt", 0.75),
    ]


def _make_generate_stream(captured, chunks=("Réponse ", "[1].")):
    """Return an async-generator function standing in for llm.generate_stream.

    It records the kwargs it was called with (so the numbered system_prompt can
    be inspected) and yields the given text chunks.
    """

    async def _fake_stream(*args, **kwargs):
        captured.update(kwargs)
        for c in chunks:
            yield c

    return _fake_stream


async def _drain_stream(**kwargs):
    events = []
    async for event in _process_question_with_rag_stream(**kwargs):
        events.append(event)
    return events


# The done event keys expected by the frontend today — the citation event must
# NOT perturb this shape (regression guard for the existing SSE contract).
_EXPECTED_DONE_KEYS = {"type", "sources", "confidence_score", "cached"}


class TestStreamCitationEvent:
    """_process_question_with_rag_stream — citation SSE event before done."""

    def test_citation_event_emitted_before_done_with_parity(self):
        llm, vs, docs, dbg = _base_mocks()
        vs.query.return_value = _two_source_pool()
        captured = {}
        llm.generate_stream = _make_generate_stream(captured)

        with patch("mimir.services.rag_service.settings") as mock_settings:
            _dense_settings(mock_settings)
            events = asyncio.run(
                _drain_stream(
                    question="question stream",
                    context_limit=5,
                    include_sources=True,
                    session_id="cit_s_1",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                )
            )

        types = [e["type"] for e in events]
        # Exactly one citation event, strictly before the done event.
        assert types.count("citation") == 1
        assert types.count("done") == 1
        assert types.index("citation") < types.index("done")

        citation_event = next(e for e in events if e["type"] == "citation")
        done_event = next(e for e in events if e["type"] == "done")
        citations = citation_event["citations"]
        sources = done_event["sources"]

        # Map matches the numbered sources carried by the (unchanged) done event.
        assert set(citations.keys()) == {"1", "2"}
        for i in range(len(sources)):
            assert citations[str(i + 1)]["document_id"] == sources[i]["document_id"]

        # The streamed prompt was numbered [1]..[N].
        assert "[1]" in captured["system_prompt"]
        assert "[Source:" not in captured["system_prompt"]

        # Done contract is byte-identical in shape to today.
        assert set(done_event.keys()) == _EXPECTED_DONE_KEYS

    def test_zero_source_stream_keeps_done_shape_and_empty_map(self):
        llm, vs, docs, dbg = _base_mocks()
        vs.query.return_value = []
        captured = {}
        llm.generate_stream = _make_generate_stream(captured, chunks=("Aucune source.",))

        with patch("mimir.services.rag_service.settings") as mock_settings:
            _dense_settings(mock_settings)
            events = asyncio.run(
                _drain_stream(
                    question="stream sans source",
                    context_limit=5,
                    include_sources=True,
                    session_id="cit_s_0",
                    llm_service=llm,
                    vector_store=vs,
                    document_repository=docs,
                    rag_debug=dbg,
                )
            )

        types = [e["type"] for e in events]
        done_event = next(e for e in events if e["type"] == "done")

        # A citation event may be emitted with an empty map; if present it stays
        # before done and carries no entries.
        if "citation" in types:
            assert types.index("citation") < types.index("done")
            citation_event = next(e for e in events if e["type"] == "citation")
            assert citation_event["citations"] == {}

        # The done event is unchanged in shape and still carries an empty sources
        # list (byte-identical contract to today).
        assert done_event["sources"] == []
        assert set(done_event.keys()) == _EXPECTED_DONE_KEYS


class TestSystemPromptCitationRule:
    """MIMIR_SYSTEM_PROMPT carries the [N]-citation instruction."""

    def test_prompt_instructs_bracket_n_and_forbids_invented_numbers(self):
        from mimir.services.rag_service import MIMIR_SYSTEM_PROMPT

        assert "[N]" in MIMIR_SYSTEM_PROMPT
        # No-invented-number rule present (French wording per existing prompt).
        assert "inventez" in MIMIR_SYSTEM_PROMPT.lower()
        # Numbering is still interpolated into the context placeholder.
        assert "{context}" in MIMIR_SYSTEM_PROMPT

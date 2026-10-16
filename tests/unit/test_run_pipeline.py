"""Mock-based unit tests for the RAGAS run_pipeline harness.

Offline and network-free: these tests exercise run_pipeline's PURE helpers --
the golden-entry -> eval-row shaping (`_assemble_eval_row`), the JSONL boundary
writer (`_write_eval_rows`), and the throttled collection loop
(`_collect_eval_rows`) -- with a MOCKED RagService answer function. No Mistral
call, no real sleep, no ragas import (ragas lives in a separate venv). This
mirrors the discipline of test_golden_set_schema.py: the eval_input.jsonl file
is the venv boundary consumed by score_baseline.py, so its shape must be locked
by tests rather than discovered at run time.
"""

import asyncio
import json
from unittest.mock import AsyncMock, Mock, patch

from scripts.ragas_eval.golden_set_schema import ADVERSARIAL_REFERENCE, GoldenSetEntry
from scripts.ragas_eval.run_pipeline import (
    THROTTLE_SECONDS,
    _assemble_eval_row,
    _collect_eval_rows,
    _write_eval_rows,
    answer_via_stream,
)


def _corpus_entry() -> GoldenSetEntry:
    """A grounded (non-adversarial) golden set entry fixture."""
    return GoldenSetEntry(
        user_input="Quel est le coût estimé total du projet ?",
        reference="1,2 M€",
        reference_contexts=["- Coût estimé : 1,2 M€ (développement + infra)."],
        is_adversarial=False,
    )


def _adversarial_entry() -> GoldenSetEntry:
    """An out-of-corpus (adversarial) golden set entry fixture."""
    return GoldenSetEntry(
        user_input="Quelle est la capitale de l'Australie ?",
        reference=ADVERSARIAL_REFERENCE,
        reference_contexts=[],
        is_adversarial=True,
    )


def _rag_result(answer: str, chunk_texts):
    """Build a RagService.answer()-shaped result dict (mock, no network)."""
    return {
        "answer": answer,
        "sources": [{"document_id": 1, "filename": "f.pdf", "chunk_text": t} for t in chunk_texts],
        "confidence_score": 0.8,
        "session_id": "ragas-eval-0",
    }


class TestAssembleEvalRow:
    """The pure golden-entry + RagService-result -> eval-row mapping."""

    def test_maps_all_ragas_fields(self):
        entry = _corpus_entry()
        result = _rag_result("La réponse est 1,2 M€.", ["ctx A", "ctx B"])

        row = _assemble_eval_row(entry, result)

        assert row["user_input"] == entry.user_input
        assert row["response"] == "La réponse est 1,2 M€."
        assert row["retrieved_contexts"] == ["ctx A", "ctx B"]
        assert row["reference"] == entry.reference
        assert row["reference_contexts"] == entry.reference_contexts
        assert row["is_adversarial"] is False

    def test_empty_sources_yield_empty_retrieved_contexts(self):
        entry = _adversarial_entry()
        result = _rag_result("Information non présente.", [])

        row = _assemble_eval_row(entry, result)

        assert row["retrieved_contexts"] == []
        assert row["is_adversarial"] is True
        assert row["reference"] == ADVERSARIAL_REFERENCE

    def test_missing_sources_key_is_tolerated(self):
        # A defensive result (e.g. error fallback) may omit sources entirely.
        entry = _corpus_entry()
        row = _assemble_eval_row(entry, {"answer": "oops"})

        assert row["response"] == "oops"
        assert row["retrieved_contexts"] == []

    def test_row_is_json_serializable(self):
        entry = _corpus_entry()
        row = _assemble_eval_row(entry, _rag_result("x", ["c"]))
        # Must round-trip through JSON: it is written to the venv boundary file.
        assert json.loads(json.dumps(row)) == row


class TestWriteEvalRows:
    """The JSONL boundary format between the two venvs."""

    def test_writes_one_json_object_per_line(self, tmp_path):
        rows = [
            _assemble_eval_row(_corpus_entry(), _rag_result("a", ["c1"])),
            _assemble_eval_row(_adversarial_entry(), _rag_result("b", [])),
        ]
        out = tmp_path / "eval_input.jsonl"

        _write_eval_rows(rows, out)

        lines = out.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        parsed = [json.loads(line) for line in lines]
        assert parsed == rows

    def test_creates_parent_directory(self, tmp_path):
        out = tmp_path / "nested" / "dir" / "eval_input.jsonl"
        _write_eval_rows([], out)
        assert out.exists()


class TestThrottle:
    """The <= 1 call/sec Mistral free-tier throttle must be present and wired."""

    def test_throttle_seconds_respects_free_tier_ceiling(self):
        # >= 1.1s between calls keeps a real run under the 1 req/s hard limit.
        assert THROTTLE_SECONDS >= 1.1

    def test_collect_sleeps_between_calls_only(self):
        entries = [_corpus_entry(), _adversarial_entry(), _corpus_entry()]
        answer_fn = AsyncMock(
            side_effect=[
                _rag_result("r0", ["c0"]),
                _rag_result("r1", []),
                _rag_result("r2", ["c2"]),
            ]
        )

        with patch(
            "scripts.ragas_eval.run_pipeline.asyncio.sleep",
            new=AsyncMock(),
        ) as mock_sleep:
            rows = asyncio.run(
                _collect_eval_rows(entries, answer_fn, throttle_seconds=THROTTLE_SECONDS)
            )

        assert len(rows) == 3
        # One fewer sleep than calls (no sleep before the first question).
        assert mock_sleep.await_count == 2
        for call in mock_sleep.await_args_list:
            assert call.args[0] == THROTTLE_SECONDS


class TestCollectEvalRows:
    """The throttled collection loop over a mocked RagService answer function."""

    def test_collects_a_row_per_entry(self):
        entries = [_corpus_entry(), _adversarial_entry()]
        answer_fn = AsyncMock(
            side_effect=[
                _rag_result("grounded", ["ctx"]),
                _rag_result("abstain", []),
            ]
        )

        rows = asyncio.run(_collect_eval_rows(entries, answer_fn, throttle_seconds=0))

        assert answer_fn.await_count == 2
        assert [r["response"] for r in rows] == ["grounded", "abstain"]
        # Each call gets a distinct per-question session id.
        session_ids = [c.args[1] for c in answer_fn.await_args_list]
        assert len(set(session_ids)) == 2

    def test_none_result_stops_the_loop(self):
        # answer_fn returning None signals budget exhaustion -> stop early.
        entries = [_corpus_entry(), _adversarial_entry(), _corpus_entry()]
        answer_fn = AsyncMock(
            side_effect=[
                _rag_result("first", ["c"]),
                None,
                _rag_result("never", ["c"]),
            ]
        )

        rows = asyncio.run(_collect_eval_rows(entries, answer_fn, throttle_seconds=0))

        assert len(rows) == 1
        assert rows[0]["response"] == "first"

    def test_respects_limit_via_slicing(self):
        # The loop itself takes pre-sliced entries; verify it honors the count.
        entries = [_corpus_entry() for _ in range(2)]
        answer_fn = AsyncMock(
            side_effect=[
                _rag_result("a", ["c"]),
                _rag_result("b", ["c"]),
            ]
        )

        rows = asyncio.run(_collect_eval_rows(entries, answer_fn, throttle_seconds=0))

        assert len(rows) == 2


class TestAnswerViaStream:
    """The stream->dict adapter that feeds the eval harness from answer_stream()."""

    def test_reassembles_answer_and_sources_from_events(self):
        # A fake RagService whose answer_stream yields chunk*, citation, done --
        # the exact event sequence the live streaming pipeline emits.
        events = [
            {"type": "chunk", "content": "La réponse "},
            {"type": "chunk", "content": "est 1,2 M€."},
            {"type": "citation", "citations": {"1": {"document_id": 1}}},
            {
                "type": "done",
                "sources": [{"document_id": 1, "filename": "f.pdf", "chunk_text": "ctx A"}],
                "confidence_score": 0.83,
                "cached": False,
            },
        ]

        class _FakeRagService:
            async def answer_stream(self, **kwargs):
                for event in events:
                    yield event

        result = asyncio.run(
            answer_via_stream(
                _FakeRagService(),
                question="Quel est le coût ?",
                session_id="s0",
                document_repository=Mock(),
                reservation=Mock(),
                context_limit=5,
            )
        )

        # answer = concatenated chunk contents; sources + confidence from done.
        assert result["answer"] == "La réponse est 1,2 M€."
        assert result["sources"][0]["chunk_text"] == "ctx A"
        assert result["confidence_score"] == 0.83
        assert result["session_id"] == "s0"

    def test_error_event_yields_empty_answer_and_no_sources(self):
        # An error stream must degrade to an empty answer with no sources so
        # _assemble_eval_row still produces a valid (empty-context) row.
        class _FakeRagService:
            async def answer_stream(self, **kwargs):
                yield {"type": "error", "message": "boom"}

        result = asyncio.run(
            answer_via_stream(
                _FakeRagService(),
                question="q",
                session_id="s1",
                document_repository=Mock(),
                reservation=Mock(),
                context_limit=5,
            )
        )

        assert result["answer"] == ""
        assert result["sources"] == []
        assert result["session_id"] == "s1"

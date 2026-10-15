"""
Oracle (c): SSE event sequence of POST /api/v1/chat/stream.

For the ten fixed questions over the fixed corpus (default configuration:
hybrid retrieval and filename pre-inclusion enabled), the complete list of
SSE events is pinned: start, every chunk, citation map, done (sources,
confidence) or error. The fake LLM streams an answer derived from a hash of
the prompt it receives, so the assembled context is pinned too. Generated
session ids are neutralised.

Also pinned: the LLM calls made, the budget settlement sequence, the cache
replay of a repeated question and the error events of a failing pipeline.
"""

from typing import Any, Dict, List

import pytest

from tests.oracle.harness import QUESTIONS, assert_snapshot, normalize


def _run(env, question: str, clear_cache: bool = True) -> Dict[str, Any]:
    if clear_cache:
        env.chat_cache.invalidate_all()
    env.budget_guard.calls.clear()
    env.usage_tracker.calls.clear()
    generate_before = len(env.llm.generate_calls)
    events = env.stream(question)
    generate_calls = env.llm.generate_calls[generate_before:]
    return {
        "events": normalize(events, env.tmp_root),
        "llm_generate_calls": [
            {
                "prompt": call["prompt"],
                "max_tokens": call["max_tokens"],
                "temperature": call["temperature"],
            }
            for call in generate_calls
        ],
        "budget_calls": list(env.budget_guard.calls),
        "usage_records": normalize(env.usage_tracker.calls, env.tmp_root),
    }


@pytest.mark.parametrize("index", range(len(QUESTIONS)))
def test_stream_events_for_fixed_questions(oracle_corpus_env, index):
    result = _run(oracle_corpus_env, QUESTIONS[index])
    assert_snapshot(f"sse_question_{index:02d}", {"question": QUESTIONS[index], **result})


def test_stream_replays_cached_answer(oracle_corpus_env):
    env = oracle_corpus_env
    question = QUESTIONS[0]
    fresh = _run(env, question, clear_cache=True)
    replay = _run(env, question, clear_cache=False)
    env.chat_cache.invalidate_all()
    assert_snapshot("sse_cache_replay", {"fresh": fresh, "replay": replay})


def test_stream_error_events(oracle_corpus_env):
    env = oracle_corpus_env
    results: Dict[str, List[Any]] = {}
    env.llm.fail_embed = True
    try:
        results["embedding failure"] = _run(env, QUESTIONS[1])
    finally:
        env.llm.fail_embed = False
    env.llm.fail_after_first_chunk = True
    try:
        results["generation failure"] = _run(env, QUESTIONS[2])
    finally:
        env.llm.fail_after_first_chunk = False
    env.chat_cache.invalidate_all()
    assert_snapshot("sse_errors", results)


def test_stream_with_explicit_session_and_no_sources(oracle_corpus_env):
    env = oracle_corpus_env
    env.chat_cache.invalidate_all()
    events = env.stream(QUESTIONS[3], session_id="oracle-session", include_sources=False)
    env.chat_cache.invalidate_all()
    assert_snapshot("sse_no_sources", {"events": events})

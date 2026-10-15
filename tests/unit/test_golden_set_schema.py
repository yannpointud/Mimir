"""Structural unit tests for the versioned RAGAS golden set.

Mock-based and offline: these tests exercise the pydantic schema, the JSONL
loader/validator and the two pure generation helpers. They
NEVER hit the Mistral API nor the network -- generation responses are simulated
inline. This mirrors the MetadataPayload validation discipline (faiss_store.py,
ASVS V5 Input Validation): the golden set is ground truth consumed by the
run_pipeline harness, so a malformed file must be rejected at load time.
"""

import json

import pytest
from pydantic import ValidationError

from scripts.ragas_eval.generate_golden_set import (
    _build_generation_prompt,
    _parse_generation_response,
)
from scripts.ragas_eval.golden_set_schema import (
    ADVERSARIAL_REFERENCE,
    MAX_ENTRIES,
    MIN_ENTRIES,
    GoldenSetEntry,
    load_golden_set,
    validate_golden_set,
    write_golden_set,
)


def _make_entry(index: int = 0, adversarial: bool = False) -> GoldenSetEntry:
    """Build a single valid GoldenSetEntry fixture (no network)."""
    if adversarial:
        return GoldenSetEntry(
            user_input=f"Question hors-corpus numero {index} ?",
            reference=ADVERSARIAL_REFERENCE,
            reference_contexts=[],
            is_adversarial=True,
        )
    return GoldenSetEntry(
        user_input=f"Question corpus numero {index} ?",
        reference=f"Reponse de reference {index}.",
        reference_contexts=[f"Contexte source {index}."],
        is_adversarial=False,
    )


def _make_entries(count: int, adversarial_count: int = 1) -> list:
    """Build a list of `count` valid entries including `adversarial_count` adversarial ones."""
    entries = [_make_entry(i, adversarial=True) for i in range(adversarial_count)]
    entries += [_make_entry(i) for i in range(count - adversarial_count)]
    return entries


# --- Schema + loader + validator ------------------------------------------

class TestGoldenSetEntrySchema:
    def test_valid_entry_accepts_all_required_fields(self):
        entry = _make_entry(1)
        assert entry.user_input
        assert entry.reference
        assert entry.reference_contexts == ["Contexte source 1."]
        assert entry.is_adversarial is False

    def test_missing_reference_raises_validation_error(self):
        with pytest.raises(ValidationError):
            GoldenSetEntry(
                user_input="Question ?",
                reference_contexts=["ctx"],
                is_adversarial=False,
            )

    def test_missing_is_adversarial_raises_validation_error(self):
        with pytest.raises(ValidationError):
            GoldenSetEntry(
                user_input="Question ?",
                reference="ref",
                reference_contexts=["ctx"],
            )

    def test_empty_user_input_raises_validation_error(self):
        with pytest.raises(ValidationError):
            GoldenSetEntry(
                user_input="   ",
                reference="ref",
                reference_contexts=["ctx"],
                is_adversarial=False,
            )

    def test_adversarial_entry_uses_out_of_corpus_reference(self):
        entry = _make_entry(0, adversarial=True)
        assert entry.is_adversarial is True
        assert entry.reference == ADVERSARIAL_REFERENCE


class TestLoadGoldenSet:
    def test_jsonl_round_trip(self, tmp_path):
        entries = _make_entries(3)
        path = tmp_path / "gs.jsonl"
        write_golden_set(entries, path)

        loaded = load_golden_set(path)
        assert len(loaded) == 3
        assert [e.model_dump() for e in loaded] == [e.model_dump() for e in entries]

    def test_blank_lines_are_tolerated(self, tmp_path):
        path = tmp_path / "gs.jsonl"
        good = _make_entry(0).model_dump_json()
        path.write_text(f"{good}\n\n{good}\n", encoding="utf-8")
        assert len(load_golden_set(path)) == 2

    def test_invalid_json_line_reports_line_number(self, tmp_path):
        path = tmp_path / "gs.jsonl"
        good = _make_entry(0).model_dump_json()
        path.write_text(f"{good}\n{{ not json\n", encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            load_golden_set(path)
        assert "line 2" in str(exc.value)

    def test_schema_violation_line_reports_line_number(self, tmp_path):
        path = tmp_path / "gs.jsonl"
        good = _make_entry(0).model_dump_json()
        bad = json.dumps({"user_input": "q", "reference_contexts": ["c"]})  # missing fields
        path.write_text(f"{good}\n{bad}\n", encoding="utf-8")
        with pytest.raises(ValueError) as exc:
            load_golden_set(path)
        assert "line 2" in str(exc.value)


class TestValidateGoldenSet:
    def test_valid_set_passes(self):
        entries = _make_entries(MIN_ENTRIES)
        assert validate_golden_set(entries) is entries

    def test_below_minimum_rejected(self):
        with pytest.raises(ValueError):
            validate_golden_set(_make_entries(MIN_ENTRIES - 1))

    def test_above_maximum_rejected(self):
        with pytest.raises(ValueError):
            validate_golden_set(_make_entries(MAX_ENTRIES + 1))

    def test_no_adversarial_rejected(self):
        entries = [_make_entry(i) for i in range(MIN_ENTRIES)]  # zero adversarial
        with pytest.raises(ValueError):
            validate_golden_set(entries)


# --- Pure generation helpers (mock responses, zero network) ---------------

class TestBuildGenerationPrompt:
    def test_corpus_prompt_embeds_chunk_texts_as_data(self):
        chunks = ["Le RGPD impose la minimisation des donnees.", "Le DPO supervise la conformite."]
        prompt = _build_generation_prompt(chunks, adversarial=False)
        # Documentation context is carried into the prompt verbatim as DATA.
        for chunk in chunks:
            assert chunk in prompt

    def test_corpus_prompt_isolates_context_as_data_not_instruction(self):
        prompt = _build_generation_prompt(["Un chunk quelconque."], adversarial=False)
        lowered = prompt.lower()
        # The prompt must frame the passages as data to quote, not instructions
        # to follow (untrusted document content is never executed).
        assert "donnée" in lowered or "donnees" in lowered or "données" in lowered

    def test_adversarial_prompt_requests_out_of_corpus_marker(self):
        prompt = _build_generation_prompt(["Un chunk quelconque."], adversarial=True)
        assert ADVERSARIAL_REFERENCE in prompt


class TestParseGenerationResponse:
    def _valid_payload(self, is_adversarial=False):
        return {
            "user_input": "Quelle est la politique de sauvegarde ?",
            "reference": ADVERSARIAL_REFERENCE if is_adversarial else "Sauvegarde quotidienne.",
            "reference_contexts": [] if is_adversarial else ["Les sauvegardes sont quotidiennes."],
            "is_adversarial": is_adversarial,
        }

    def test_parses_valid_json_array(self):
        raw = json.dumps([self._valid_payload(), self._valid_payload(is_adversarial=True)])
        entries = _parse_generation_response(raw)
        assert len(entries) == 2
        assert all(isinstance(e, GoldenSetEntry) for e in entries)

    def test_flag_is_authoritative_from_caller_not_model(self):
        # The is_adversarial flag comes from the prompt (caller), NOT the model
        # output -- Mistral does not reliably self-report it. A model-declared
        # is_adversarial:true in a corpus batch must be overridden to False.
        raw = json.dumps([self._valid_payload(is_adversarial=True)])
        corpus_entries = _parse_generation_response(raw, adversarial=False)
        assert corpus_entries[0].is_adversarial is False

    def test_adversarial_batch_forces_out_of_corpus_contract(self):
        # A corpus-looking answer coming from an adversarial batch is forced onto
        # the out-of-corpus contract so a non-compliant model cannot poison it.
        raw = json.dumps([self._valid_payload(is_adversarial=False)])
        entries = _parse_generation_response(raw, adversarial=True)
        assert entries[0].is_adversarial is True
        assert entries[0].reference == ADVERSARIAL_REFERENCE
        assert entries[0].reference_contexts == []

    def test_tolerates_markdown_code_fence(self):
        raw = "```json\n" + json.dumps([self._valid_payload()]) + "\n```"
        entries = _parse_generation_response(raw)
        assert len(entries) == 1

    def test_rejects_invalid_entry_without_crashing(self):
        bad = {"user_input": "q", "reference_contexts": ["c"]}  # missing reference + flag
        raw = json.dumps([self._valid_payload(), bad])
        entries = _parse_generation_response(raw)
        # The malformed entry is dropped, the valid one survives.
        assert len(entries) == 1
        assert entries[0].reference == "Sauvegarde quotidienne."

    def test_garbage_response_returns_empty_list(self):
        assert _parse_generation_response("not json at all") == []

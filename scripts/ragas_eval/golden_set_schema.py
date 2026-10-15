"""Strict schema, loader and validator for the versioned RAGAS golden set.

Why this exists: the golden set (``golden_set_v1.jsonl``) is the frozen ground
truth every RAGAS baseline is measured against. It is consumed as data by the
run_pipeline evaluation harness, so it MUST be validated at load time -- exactly the
discipline applied to ``MetadataPayload`` in ``faiss_store.py`` (ASVS V5 Input
Validation). A malformed line is rejected with its line
number rather than silently defaulted.

This module is dependency-light on purpose (pydantic + stdlib only): it imports
nothing from the backend package so it can be reused by both the generation
script (venv principal) and the evaluation harness.
"""

import json
from pathlib import Path

from pydantic import BaseModel, ValidationError, field_validator

# Locked bounds: a versioned golden set of 50 to 200 questions, frozen
# before any baseline measurement.
MIN_ENTRIES = 50
MAX_ENTRIES = 200

# Canonical reference answer for an adversarial (out-of-corpus) question. The
# generation prompt asks Mistral to emit exactly this string so the harness can
# score abstention. Kept as a single source of truth reused by the prompt
# builder and the tests.
ADVERSARIAL_REFERENCE = "information non présente dans la documentation"


class GoldenSetEntry(BaseModel):
    """One golden set question with its expected answer and supporting context.

    All fields are required (no defaults) -- same strict-validation discipline
    as ``MetadataPayload``: a missing field is a hard error, never a
    silent default. ``user_input`` must additionally be a non-empty string.

    Fields:
        user_input: The question asked to the RAG system (non-empty).
        reference: The expected ground-truth answer. For an adversarial entry
            this is ``ADVERSARIAL_REFERENCE`` ("information non présente ...").
        reference_contexts: The source passages supporting the answer. May be
            an empty list for an adversarial (out-of-corpus) question.
        is_adversarial: True when the question targets information ABSENT from
            the corpus (tests the system's ability to abstain).
    """

    user_input: str
    reference: str
    reference_contexts: list[str]
    is_adversarial: bool

    @field_validator("user_input")
    @classmethod
    def _user_input_not_empty(cls, value: str) -> str:
        """Reject blank/whitespace-only questions (strict input validation)."""
        if not value or not value.strip():
            raise ValueError("user_input must be a non-empty string")
        return value


def load_golden_set(path: str | Path) -> list[GoldenSetEntry]:
    """Parse a JSONL golden set file, one ``GoldenSetEntry`` per line.

    Blank lines are tolerated. Any line that is not valid JSON, or that does
    not satisfy the ``GoldenSetEntry`` schema, raises a ``ValueError`` naming
    the offending line number -- so a corrupted ground-truth file fails loudly
    at load time rather than poisoning the baseline.

    Returns:
        The parsed entries in file order.

    Raises:
        ValueError: On any malformed or schema-violating line.
    """
    path = Path(path)
    entries: list[GoldenSetEntry] = []
    with open(path, encoding="utf-8") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            stripped = raw_line.strip()
            if not stripped:
                continue  # Tolerate blank separator lines.
            try:
                data = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number} of {path}: {exc}") from exc
            try:
                entries.append(GoldenSetEntry(**data))
            except (ValidationError, TypeError) as exc:
                raise ValueError(
                    f"Invalid golden set entry on line {line_number} of {path}: {exc}"
                ) from exc
    return entries


def validate_golden_set(entries: list[GoldenSetEntry]) -> list[GoldenSetEntry]:
    """Enforce the golden set invariants required before any baseline run.

    Invariants:
        - ``MIN_ENTRIES`` <= len(entries) <= ``MAX_ENTRIES``
        - at least one adversarial (out-of-corpus) entry is present

    Returns:
        The same ``entries`` list (for fluent use), when valid.

    Raises:
        ValueError: If a bound or the adversarial-presence rule is violated.
    """
    count = len(entries)
    if count < MIN_ENTRIES or count > MAX_ENTRIES:
        raise ValueError(
            f"Golden set must contain between {MIN_ENTRIES} and {MAX_ENTRIES} entries, got {count}"
        )
    if not any(entry.is_adversarial for entry in entries):
        raise ValueError("Golden set must contain at least one adversarial entry")
    return entries


def write_golden_set(entries: list[GoldenSetEntry], path: str | Path) -> None:
    """Write entries to a JSONL file, one entry per line (UTF-8).

    Creates the parent directory if needed. Used by the generation script to
    freeze ``golden_set_v1.jsonl``.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        for entry in entries:
            handle.write(entry.model_dump_json() + "\n")

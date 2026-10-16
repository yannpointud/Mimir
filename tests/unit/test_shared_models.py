"""
Tests of the API models and of the filename validation.
"""

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from mimir.shared.clock import utc_now
from mimir.shared.models import (
    DocumentResponse,
    DocumentStatus,
    ErrorResponse,
    PaginationModel,
    sanitize_filename,
    validate_filename,
)


def test_document_response_reads_orm_attributes():
    now = utc_now()
    row = SimpleNamespace(
        id=1,
        filename="a.pdf",
        path="/data/a.pdf",
        preserve=False,
        file_hash="a" * 64,
        status="indexed",
        error_message=None,
        chunk_count=3,
        created_at=now,
        indexed_at=None,
    )
    response = DocumentResponse.model_validate(row)
    assert response.status is DocumentStatus.INDEXED
    assert response.created_at == now


def test_pagination_bounds():
    assert PaginationModel().limit == 50
    with pytest.raises(ValidationError):
        PaginationModel(limit=0)
    with pytest.raises(ValidationError):
        PaginationModel(offset=-1)


def test_error_response_defaults():
    error = ErrorResponse(error_code="NOT_FOUND", error_message="missing")
    assert error.success is False
    assert error.details is None


@pytest.mark.parametrize("name", ["test.pdf", "document_2024.txt", "rapport été.md"])
def test_valid_filenames(name):
    assert validate_filename(name) is True


@pytest.mark.parametrize(
    "name",
    ["", "/etc/passwd", "../secret.txt", "a\x00b.txt", "a<b>.txt", "x" * 256],
)
def test_rejected_filenames(name):
    assert validate_filename(name) is False


def test_sanitize_replaces_dangerous_characters():
    assert sanitize_filename('  a<b>:"c|?*.txt  ') == "a_b___c___.txt"


def test_sanitize_caps_the_length_and_keeps_the_extension():
    sanitized = sanitize_filename("x" * 300 + ".pdf")
    assert len(sanitized) == 255
    assert sanitized.endswith(".pdf")

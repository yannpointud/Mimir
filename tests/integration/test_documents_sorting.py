"""
Sorting of GET /api/v1/documents/ (admin documents list).
"""

import pytest
from fastapi.testclient import TestClient

from mimir.auth.jwt_handler import jwt_handler
from mimir.database.repository import DocumentRepository

LIST_ROUTE = "/api/v1/documents/"


@pytest.fixture
def client(test_app, isolated_db_manager):
    """Client on a fresh database holding three documents."""
    with isolated_db_manager.get_session_context() as session:
        repo = DocumentRepository(session)
        for index, (filename, chunk_count) in enumerate([("b.pdf", 2), ("c.pdf", 9), ("a.pdf", 4)]):
            document = repo.create(filename, f"hash{index}")
            repo.update_status(document.id, "indexed", chunk_count=chunk_count)
    token = jwt_handler.create_access_token({"sub": "admin", "user_type": "admin"})
    return TestClient(test_app, headers={"Authorization": f"Bearer {token}"})


def _filenames(response):
    assert response.status_code == 200
    return [document["filename"] for document in response.json()["documents"]]


def test_sorts_on_the_requested_column_and_direction(client):
    by_name = client.get(LIST_ROUTE, params={"sort_by": "filename", "sort_order": "asc"})
    by_sections = client.get(LIST_ROUTE, params={"sort_by": "chunk_count", "sort_order": "desc"})

    assert _filenames(by_name) == ["a.pdf", "b.pdf", "c.pdf"]
    assert _filenames(by_sections) == ["c.pdf", "a.pdf", "b.pdf"]


@pytest.mark.parametrize(
    "params", [{"sort_by": "path"}, {"sort_order": "up"}], ids=["column", "direction"]
)
def test_rejects_an_unknown_sort(client, params):
    assert client.get(LIST_ROUTE, params=params).status_code == 422

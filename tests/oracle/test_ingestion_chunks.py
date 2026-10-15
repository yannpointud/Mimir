"""
Oracle (e): ingestion of a PDF, a DOCX, a TXT and a MD file.

Each fixture is uploaded through POST /api/v1/documents/upload and ingested by
the real IngestionProcessor (fake embeddings). Pinned per document: final
status and chunk count, the chunks served by GET /documents/{id}/full (index,
text, metadata), the extracted content, and the chunk records stored in the
vector index (text, index, total, metadata).
"""

from tests.oracle.harness import FIXTURES_DIR, assert_snapshot, normalize

FIXTURE_FILES = ["sample.pdf", "sample.docx", "sample.txt", "sample.md"]


def test_ingestion_chunks_per_format(oracle_env):
    env = oracle_env
    client = env.client
    ids = {}
    for name in FIXTURE_FILES:
        response = env.upload(FIXTURES_DIR / name)
        assert response.status_code == 200, response.text
        ids[name] = response.json()["id"]
    env.drain_ingestion()

    stored = {}
    for meta in env.vector_store.snapshot_active_chunks():
        stored.setdefault(str(meta["document_id"]), []).append({
            "chunk_index": meta["chunk_index"],
            "total_chunks": meta["total_chunks"],
            "text": meta["text"],
            "source": str(meta["source"]),
            "metadata": meta.get("metadata", {}),
        })

    result = {}
    for name, doc_id in ids.items():
        document = client.get(f"/api/v1/documents/{doc_id}", headers=env.admin_headers).json()
        full = client.get(f"/api/v1/documents/{doc_id}/full").json()
        result[name] = normalize({
            "status": document["status"],
            "chunk_count": document["chunk_count"],
            "error_message": document["error_message"],
            "mime_type": full["mime_type"],
            "file_size": full["file_size"],
            "content": full["content"],
            "chunks": [
                {"chunk_index": c["chunk_index"], "text": c["text"], "metadata": c["metadata"]}
                for c in full["chunks"]
            ],
            "indexed_chunks": sorted(
                stored.get(str(doc_id), []), key=lambda c: c["chunk_index"]
            ),
        }, env.tmp_root)
    assert_snapshot("ingestion_chunks", result)

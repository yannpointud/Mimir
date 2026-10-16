"""
Deletion of a document: database record, stored file and indexed chunks.
"""

import logging
import os
from http import HTTPStatus
from typing import Any

from mimir.rag_core.interfaces import VectorStoreConnectionError
from mimir.services.errors import RequestRejectedError
from mimir.services.index_maintenance import remove_document_from_indexes

logger = logging.getLogger(__name__)


async def delete_document_everywhere(
    document_id: int,
    *,
    force: bool,
    doc_repo: Any,
    audit_repo: Any,
    vector_store: Any,
    bm25_store: Any,
) -> str:
    """Delete a document from the database, the disk and both indexes.

    Returns the deleted document's filename. Once the database record is
    gone, failures on the file or the indexes are logged and never undo the
    deletion.
    """
    document = doc_repo.get_by_id(document_id)
    if not document:
        raise RequestRejectedError(
            HTTPStatus.NOT_FOUND, f"Document with ID {document_id} not found"
        )
    if document.preserve and not force:
        raise RequestRejectedError(
            HTTPStatus.FORBIDDEN,
            "Document is protected from deletion. Use force=true to override.",
        )

    filename = document.filename
    file_path = document.path
    if not doc_repo.delete(document_id, force=force):
        raise RequestRejectedError(
            HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to delete document from database"
        )

    _remove_stored_file(file_path)
    try:
        await remove_document_from_indexes(vector_store, bm25_store, document_id, filename)
    except (VectorStoreConnectionError, OSError) as e:
        # The database record is gone: an index write failure leaves orphan
        # chunks that the admin rebuild removes, it must not undo the deletion.
        logger.error(f"Error removing document from the indexes: {e}")

    audit_repo.create_log(
        user_type="admin",
        action="document_delete",
        details=f"Document deleted: {filename}",
        ip_address="system",
        success=True,
    )
    logger.info(f"Document deleted successfully: {filename} (ID: {document_id})")
    return filename


def _remove_stored_file(file_path: str | None) -> None:
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
            logger.debug(f"Deleted file: {file_path}")
        except OSError as e:
            logger.warning(f"Failed to delete file {file_path}: {e}")

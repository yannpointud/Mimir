"""
Upload pipeline of ``POST /documents/upload``: validate the file, read it,
reject duplicates, store it under a hash-prefixed name, create the database
record, audit the upload and queue it for ingestion.
"""

import hashlib
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy.exc import SQLAlchemyError

from mimir.database.models import Document
from mimir.database.repository import AuditLogRepository, DocumentRepository
from mimir.ingestion.processor import IngestionProcessor
from mimir.services.errors import RequestRejectedError
from mimir.shared.models import sanitize_filename, validate_filename

logger = logging.getLogger(__name__)

QUEUE_FULL_DETAIL = (
    "Ingestion queue is full. The system is currently processing many documents. "
    "Please try again later."
)


class UploadSource(Protocol):
    """The part of an uploaded file the pipeline uses (FastAPI's UploadFile)."""

    filename: str | None
    size: int | None

    async def read(self) -> bytes: ...


@dataclass(frozen=True)
class UploadPolicy:
    """Limits applied to an uploaded file."""

    upload_dir: str
    max_file_size_mb: int
    supported_extensions: Collection[str]


class DocumentUpload:
    """One file going through the upload pipeline.

    Every step raises RequestRejectedError with the client-facing status and
    message; any other exception is left to the route, which owns the
    generic 500 of its endpoint.
    """

    def __init__(self, file: UploadSource, policy: UploadPolicy) -> None:
        self.file = file
        self.policy = policy
        self.filename = ""
        # Target of the stored copy, set right before the content is written.
        self.stored_path: Path | None = None

    def check_name_and_size(self) -> None:
        """Validate and sanitize the filename, then check the declared size."""
        if not self.file.filename:
            raise RequestRejectedError(HTTPStatus.BAD_REQUEST, "No filename provided")
        if not validate_filename(self.file.filename):
            raise RequestRejectedError(HTTPStatus.BAD_REQUEST, "Invalid filename")
        self.filename = sanitize_filename(self.file.filename)

        # Checked before reading the content: a single unbounded read() of an
        # arbitrarily large file could exhaust memory.
        max_mb = self.policy.max_file_size_mb
        if self.file.size and self.file.size > max_mb * 1024 * 1024:
            raise RequestRejectedError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE, f"File too large. Maximum size: {max_mb}MB"
            )

    async def run(
        self,
        doc_repo: DocumentRepository,
        audit_repo: AuditLogRepository,
        ingestion_processor: IngestionProcessor,
        preserve: bool,
        current_user: Mapping[str, Any],
    ) -> Document:
        """Store the checked file, record, audit and queue it; returns the document."""
        self._check_extension(self.policy.supported_extensions)

        content, file_hash = await self._read_new_content(doc_repo)
        # Hash-prefixed name: two uploads sharing a sanitized name never
        # overwrite each other.
        file_path = self._upload_dir() / f"{file_hash}_{self.filename}"
        self.stored_path = file_path
        with open(file_path, "wb") as f:
            f.write(content)

        document = doc_repo.create(
            filename=self.filename, path=str(file_path), file_hash=file_hash, preserve=preserve
        )
        self._audit_upload(audit_repo, document, len(content), preserve)
        self._queue(ingestion_processor, doc_repo, document, file_path, current_user)
        return document

    def discard_stored_file(self) -> None:
        """Remove the stored file, if any (cleanup after an unexpected error)."""
        if self.stored_path is not None and self.stored_path.exists():
            self.stored_path.unlink(missing_ok=True)

    def _upload_dir(self) -> Path:
        upload_dir = Path(self.policy.upload_dir)
        upload_dir.mkdir(parents=True, exist_ok=True)
        return upload_dir

    def _check_extension(self, supported_extensions: Collection[str]) -> None:
        file_ext = Path(self.filename).suffix.lower()
        if file_ext not in supported_extensions:
            raise RequestRejectedError(HTTPStatus.BAD_REQUEST, f"Unsupported file type: {file_ext}")

    async def _read_new_content(self, doc_repo: DocumentRepository) -> tuple[bytes, str]:
        """Read the content and reject empty files and duplicates."""
        content = await self.file.read()
        if len(content) == 0:
            raise RequestRejectedError(HTTPStatus.BAD_REQUEST, "Empty file")

        file_hash = hashlib.sha256(content).hexdigest()
        existing_doc = doc_repo.get_by_hash(file_hash)
        if existing_doc:
            logger.warning(f"Duplicate file upload attempted: {self.filename}")
            raise RequestRejectedError(
                HTTPStatus.CONFLICT, f"File already exists: {existing_doc.filename}"
            )
        return content, file_hash

    def _audit_upload(
        self, audit_repo: AuditLogRepository, document: Document, size: int, preserve: bool
    ) -> None:
        audit_repo.create_log(
            user_type="admin",
            action="document_upload",
            details=f"File uploaded: {self.filename}",
            ip_address="system",
            success=True,
        )

    def _queue(
        self,
        ingestion_processor: IngestionProcessor,
        doc_repo: DocumentRepository,
        document: Document,
        file_path: Path,
        current_user: Mapping[str, Any],
    ) -> None:
        """Queue the document for ingestion: 503 when the queue is full."""
        queued = ingestion_processor.queue_document(
            file_path=str(file_path),
            document_id=str(document.id),
            metadata={"uploaded_by": current_user["sub"]},
        )
        if not queued:
            self._reject_queue_full(ingestion_processor, doc_repo, document, file_path)
        logger.info(f"Document queued for processing: {self.filename} (ID: {document.id})")

    def _reject_queue_full(
        self,
        ingestion_processor: IngestionProcessor,
        doc_repo: DocumentRepository,
        document: Document,
        file_path: Path,
    ) -> None:
        logger.warning(
            f"Ingestion queue is full, cannot queue document: {self.filename}",
            extra={
                "extra_fields": {
                    "document_id": document.id,
                    "filename": self.filename,
                    "queue_size": ingestion_processor.get_queue_size(),
                    "type": "queue_full_upload",
                }
            },
        )
        # Roll back the pending record and the stored file before answering
        # 503: otherwise any retry of the same file would hit 409 (get_by_hash
        # matches the orphaned pending record) and never be ingested.
        try:
            doc_repo.delete(document.id, force=True)
            file_path.unlink(missing_ok=True)
        except (SQLAlchemyError, OSError) as cleanup_error:
            logger.warning(
                f"Failed to clean up after queue-full rejection "
                f"(document_id={document.id}): {cleanup_error}"
            )
        raise RequestRejectedError(HTTPStatus.SERVICE_UNAVAILABLE, QUEUE_FULL_DETAIL)

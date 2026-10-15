"""
Upload pipeline shared by ``POST /documents/upload`` and
``POST /admin/documents/upload``.

Both routes validate the file, read it, reject duplicates, store it under a
hash-prefixed name, create the database record and queue it for ingestion.
The few client-visible differences between them are kept on purpose and
expressed by ``UploadPolicy`` (see docs/cleanup/DECISIONS.md, D0.4 and D3.x).
"""

import hashlib
import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path
from typing import Any, Protocol

from src.shared.models import sanitize_filename, validate_filename
from src.services.errors import RequestRejectedError

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
    """Route-specific behaviour of the upload pipeline."""

    upload_dir: str
    max_file_size_mb: int
    # 400 detail when validate_filename() rejects the name.
    invalid_filename_detail: str
    # Accepted extensions; None skips the check (the admin route accepts any).
    supported_extensions: Collection[str] | None = None
    # Log a warning before rejecting a duplicate (documents route only).
    warn_on_duplicate: bool = False
    # Create the upload directory before reading the file (admin route order).
    prepare_dir_first: bool = False


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
            raise RequestRejectedError(HTTPStatus.BAD_REQUEST, self.policy.invalid_filename_detail)
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
        doc_repo: Any,
        ingestion_processor: Any,
        preserve: bool,
        current_user: Mapping[str, Any],
        audit_repo: Any | None = None,
    ) -> Any:
        """Store the checked file, record it and queue it; returns the document.

        ``audit_repo`` is given by the documents route only, which records a
        ``document_upload`` audit event before queueing.
        """
        if self.policy.prepare_dir_first:
            self._upload_dir()
        if self.policy.supported_extensions is not None:
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
        if audit_repo is not None:
            self._audit_upload(audit_repo, document, len(content), preserve)
        self._queue(ingestion_processor, doc_repo, document, file_path, preserve, current_user)
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

    async def _read_new_content(self, doc_repo: Any) -> tuple[bytes, str]:
        """Read the content and reject empty files and duplicates."""
        content = await self.file.read()
        if len(content) == 0:
            raise RequestRejectedError(HTTPStatus.BAD_REQUEST, "Empty file")

        # SHA-256 on both routes, so deduplication works across them.
        file_hash = hashlib.sha256(content).hexdigest()
        existing_doc = doc_repo.get_by_hash(file_hash)
        if existing_doc:
            if self.policy.warn_on_duplicate:
                logger.warning(f"Duplicate file upload attempted: {self.filename}")
            raise RequestRejectedError(
                HTTPStatus.CONFLICT, f"File already exists: {existing_doc.filename}"
            )
        return content, file_hash

    def _audit_upload(self, audit_repo: Any, document: Any, size: int, preserve: bool) -> None:
        audit_repo.create_log(
            user_type="admin",
            action="document_upload",
            details=f"File uploaded: {self.filename}",
            ip_address="system",
            success=True,
            additional_data={
                "document_id": document.id,
                "filename": self.filename,
                "file_size": size,
                "preserve": preserve,
            },
        )

    def _queue(
        self,
        ingestion_processor: Any,
        doc_repo: Any,
        document: Any,
        file_path: Path,
        preserve: bool,
        current_user: Mapping[str, Any],
    ) -> None:
        """Queue the document for ingestion: 503 when the queue is full."""
        try:
            queued = ingestion_processor.queue_document(
                file_path=file_path,
                document_id=str(document.id),
                preserve=preserve,
                metadata={"uploaded_by": current_user.get("username", "unknown")},
            )
            if not queued:
                self._reject_queue_full(ingestion_processor, doc_repo, document, file_path)
            logger.info(f"Document queued for processing: {self.filename} (ID: {document.id})")
        except RequestRejectedError:
            raise
        except Exception as e:  # noqa: BLE001 - API boundary: a queueing failure becomes a 500
            logger.error(f"Error queuing document for processing: {e}")
            raise RequestRejectedError(
                HTTPStatus.INTERNAL_SERVER_ERROR, "Failed to queue document for processing"
            ) from e

    def _reject_queue_full(
        self, ingestion_processor: Any, doc_repo: Any, document: Any, file_path: Path
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
        except Exception as cleanup_error:  # noqa: BLE001 - best-effort cleanup: the client still gets the 503
            logger.warning(
                f"Failed to clean up after queue-full rejection "
                f"(document_id={document.id}): {cleanup_error}"
            )
        raise RequestRejectedError(HTTPStatus.SERVICE_UNAVAILABLE, QUEUE_FULL_DETAIL)

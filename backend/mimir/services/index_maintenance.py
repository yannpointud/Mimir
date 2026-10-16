"""
Maintenance of the retrieval indexes: FAISS (dense, source of truth) and the
BM25 lexical index derived from it.

Every blocking FAISS or BM25 call made from these coroutines is offloaded with
asyncio.to_thread so the event loop is never stalled; the FAISS store guards
its own state with an internal RLock.
"""

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy.exc import SQLAlchemyError

from mimir.cache.lru_cache import cache_service, chat_cache_service
from mimir.rag_core.implementations.validation_utils import VectorStoreValidator
from mimir.shared.models import ConsistencyValidationResponse

logger = logging.getLogger(__name__)

# Share of deleted vectors above which a deletion triggers an orphan cleanup.
_CLEANUP_DELETED_RATIO = 0.20


async def remove_document_from_indexes(
    vector_store: Any, bm25_store: Any, document_id: int, filename: str
) -> None:
    """Remove a document's chunks from FAISS, then rebuild BM25 from FAISS.

    FAISS compacts itself when deletions accumulate; BM25 is rebuilt from the
    resulting snapshot, so the chunk ids reflect any compaction.
    """
    vector_deleted = await asyncio.to_thread(vector_store.delete, str(document_id))
    if not vector_deleted:
        logger.warning(f"Failed to remove document chunks from vector store: {filename}")
        return
    logger.info(f"Document chunks removed from vector store: {filename} (ID: {document_id})")
    active_chunks = vector_store.snapshot_active_chunks()
    await asyncio.to_thread(bm25_store.rebuild, active_chunks)


@dataclass
class IndexRebuild:
    """Outcome of a forced rebuild of both indexes."""

    stats_before: dict[str, Any]
    stats_after: dict[str, Any]
    rebuild_result: dict[str, Any]
    duration_ms: float

    @property
    def orphans_cleaned(self) -> int:
        cleanup_result = self.rebuild_result.get("cleanup_result", {})
        return cleanup_result.get("cleaned_chunks", 0) if cleanup_result else 0

    @property
    def deleted_removed(self) -> int:
        return self.rebuild_result.get("deleted_chunks_removed", 0)

    def message(self) -> str:
        """Client-facing summary of the rebuild."""
        message_parts = ["Vector index rebuilt successfully."]
        if self.orphans_cleaned > 0:
            message_parts.append(f"Cleaned {self.orphans_cleaned} orphaned chunks.")
        if self.deleted_removed > 0:
            message_parts.append(f"Removed {self.deleted_removed} deleted chunks.")
        if self.rebuild_result.get("rebuild_performed", False):
            message_parts.append(
                f"Optimized from {self.stats_before['total_vectors']} "
                f"to {self.stats_after['total_vectors']} vectors."
            )
        message_parts.append(f"Completed in {self.duration_ms:.0f}ms.")
        return " ".join(message_parts)


async def rebuild_indexes(vector_store: Any, bm25_store: Any, document_repo: Any) -> IndexRebuild:
    """Force a FAISS rebuild with orphan cleanup, resync BM25 and clear caches."""
    stats_before = await asyncio.to_thread(vector_store.get_stats)
    start_time = time.time()

    rebuild_result = await asyncio.to_thread(
        vector_store.rebuild_vector_store,
        force_rebuild=True,
        cleanup_orphans=True,
        existing_document_ids={str(doc.id) for doc in document_repo.get_all()},
    )

    # Resync the BM25 lexical index from the freshly optimized FAISS snapshot
    # (anti-ghost): rebuilding FAISS alone would leave the lexical index with
    # the orphan chunks FAISS just dropped.
    active_chunks = await asyncio.to_thread(vector_store.snapshot_active_chunks)
    await asyncio.to_thread(bm25_store.rebuild, active_chunks)

    stats_after = await asyncio.to_thread(vector_store.get_stats)
    duration_ms = rebuild_result.get("duration_ms", (time.time() - start_time) * 1000)

    # Clear related caches to ensure fresh data
    cache_service.invalidate_all()
    chat_cache_service.invalidate_all()

    return IndexRebuild(stats_before, stats_after, rebuild_result, duration_ms)


def record_rebuild(audit_repo: Any, rebuild: IndexRebuild, admin_user: str) -> None:
    """Audit and log a successful rebuild."""
    before = rebuild.stats_before["total_vectors"]
    after = rebuild.stats_after["total_vectors"]
    audit_repo.create_log(
        user_type="admin",
        action="vector_index_rebuild",
        details=f"FAISS index rebuilt - vectors: {before} → {after}, orphans cleaned: {rebuild.orphans_cleaned}",
        ip_address="system",
        success=True,
    )
    logger.info(
        f"FAISS index rebuilt by admin {admin_user}: {before} → {after} vectors, "
        f"cleaned {rebuild.orphans_cleaned} orphans, removed {rebuild.deleted_removed} "
        f"deleted chunks in {rebuild.duration_ms:.1f}ms"
    )


def record_rebuild_failure(audit_repo: Any, error: Exception, admin_user: str) -> None:
    """Audit a failed rebuild; an audit failure is logged, never raised."""
    try:
        audit_repo.create_log(
            user_type="admin",
            action="vector_index_rebuild",
            details=f"FAISS index rebuild failed: {str(error)}",
            ip_address="system",
            success=False,
        )
    except SQLAlchemyError as audit_error:
        # The rebuild error itself propagates: do not replace it with this one
        logger.warning(f"Failed to write audit log for rebuild failure: {audit_error}")


def validate_index_consistency(
    vector_store: Any,
    doc_repo: Any,
    audit_repo: Any,
    *,
    fix_issues: bool,
    report_dir: Path | None,
    initiated_by: str,
) -> ConsistencyValidationResponse:
    """Compare SQLite and FAISS, optionally fix and save a report, and audit it.

    ``report_dir`` is None when no report is requested.
    """
    logger.info(f"Consistency validation initiated by {initiated_by}")
    validation_result = VectorStoreValidator(vector_store, doc_repo).validate_consistency(
        fix_issues=fix_issues
    )
    report_path = None
    if report_dir is not None:
        report_path = _save_validation_report(validation_result, report_dir)

    total_issues = validation_result.get("issues_found", {}).get("total_issues", 0)
    fixes_applied = len(validation_result.get("fixes_applied", []))
    audit_repo.create_log(
        user_type="admin",
        action="maintenance_consistency_validation",
        details=f"Consistency validation: {total_issues} issues found",
        ip_address="system",
        success=True,
    )

    consistency_score = validation_result.get("consistency_score", 1.0)
    logger.info(
        f"Consistency validation completed: {total_issues} issues found, "
        f"score: {consistency_score:.2%}, fixes applied: {fixes_applied}",
        extra={
            "extra_fields": {
                "validation_result": validation_result,
                "type": "consistency_validation",
            }
        },
    )
    return ConsistencyValidationResponse(
        success=True,
        message=f"Validation completed: {total_issues} issues found (consistency score: {consistency_score:.1%})",
        validation_result=validation_result,
        report_path=str(report_path) if report_path else None,
        timestamp=datetime.utcnow(),
    )


def _save_validation_report(validation_result: dict[str, Any], reports_dir: Path) -> Path | None:
    """Write the report as timestamped JSON; a failure never fails the validation.

    The path is returned as soon as it is chosen, so it is still reported when
    writing the file fails (existing behaviour).
    """
    report_path = None
    try:
        reports_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        report_path = reports_dir / f"consistency_validation_{timestamp}.json"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(validation_result, f, indent=2, default=str)
        logger.info(f"Validation report saved to {report_path}")
    except OSError as e:
        logger.warning(f"Failed to save validation report: {e}")
    return report_path


def record_validation_failure(audit_repo: Any, error: Exception, initiated_by: str) -> None:
    """Audit a failed consistency validation."""
    audit_repo.create_log(
        user_type="admin",
        action="maintenance_consistency_validation",
        details=f"Consistency validation failed: {str(error)}",
        ip_address="system",
        success=False,
    )

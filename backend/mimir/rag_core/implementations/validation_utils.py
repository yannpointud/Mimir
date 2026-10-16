"""
Validation utilities for detecting inconsistencies between SQLite and FAISS
"""

from typing import Any
from datetime import datetime
import logging

from mimir.shared.errors import RetrievalError

logger = logging.getLogger(__name__)


class VectorStoreValidator:
    """
    Validator for detecting inconsistencies between the SQLite database and FAISS.
    """

    def __init__(self, vector_store, document_repository):
        """
        Initialize the validator.

        Args:
            vector_store: FaissVectorStore instance
            document_repository: DocumentRepository instance
        """
        self.vector_store = vector_store
        self.doc_repo = document_repository
        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    def validate_consistency(self, fix_issues: bool = False) -> dict[str, Any]:
        """Validate consistency between SQLite and FAISS."""
        start_time = datetime.utcnow()

        self.logger.info("Starting comprehensive validation between SQLite and FAISS")

        try:
            # 1. Retrieve data from both sources
            db_documents = self._get_database_documents()
            vector_documents = self._get_vector_store_documents()

            # 2. Analyze inconsistencies
            issues = self._analyze_inconsistencies(db_documents, vector_documents)

            # 3. Fix inconsistencies if requested
            fixes_applied = []
            if fix_issues and issues["total_issues"] > 0:
                fixes_applied = self._apply_fixes(issues)

            # 4. Final statistics
            end_time = datetime.utcnow()
            duration = (end_time - start_time).total_seconds()

            validation_report = {
                "validation_timestamp": start_time.isoformat(),
                "duration_seconds": duration,
                "database_stats": {
                    "total_documents": len(db_documents),
                    "indexed_documents": len(
                        [d for d in db_documents.values() if d["status"] == "indexed"]
                    ),
                },
                "vector_store_stats": {
                    "total_documents": len(vector_documents),
                    "total_chunks": sum(len(chunks) for chunks in vector_documents.values()),
                    "active_chunks": sum(
                        len([c for c in chunks if not c.get("deleted", False)])
                        for chunks in vector_documents.values()
                    ),
                },
                "issues_found": issues,
                "fixes_applied": fixes_applied if fix_issues else [],
                "consistency_score": self._calculate_consistency_score(issues),
                "recommendations": self._generate_recommendations(issues),
            }

            self.logger.info(
                f"Validation completed in {duration:.1f}s: "
                f"{issues['total_issues']} issues found, "
                f"consistency score: {validation_report['consistency_score']:.2%}",
                extra={
                    "extra_fields": {
                        "validation_report": validation_report,
                        "type": "consistency_validation",
                    }
                },
            )

            return validation_report

        except Exception as e:  # noqa: BLE001 - any failure becomes RetrievalError("Validation failed: ...")
            error_msg = f"Validation failed: {str(e)}"
            self.logger.error(error_msg)
            raise RetrievalError(error_msg) from e

    def _get_database_documents(self) -> dict[str, dict[str, Any]]:
        try:
            documents = self.doc_repo.get_all()
            return {
                str(doc.id): {
                    "id": doc.id,
                    "filename": doc.filename,
                    "status": doc.status,
                    "chunk_count": doc.chunk_count or 0,
                    "created_at": doc.created_at,
                    "indexed_at": doc.indexed_at,
                    "preserve": doc.preserve,
                    "path": doc.path,
                }
                for doc in documents
            }
        except Exception as e:  # noqa: BLE001 - log any failure, then re-raise unchanged
            self.logger.error(f"Failed to get database documents: {e}")
            raise

    def _get_vector_store_documents(self) -> dict[str, list[dict[str, Any]]]:
        try:
            with self.vector_store._lock:
                vector_docs: dict[str, list[dict[str, Any]]] = {}

                # Iterate through all FAISS metadata
                for i, meta in enumerate(self.vector_store.metadata):
                    doc_id = meta.get("document_id")
                    if doc_id:
                        if doc_id not in vector_docs:
                            vector_docs[doc_id] = []

                        chunk_info = {
                            "chunk_id": meta.get("chunk_id", i),
                            "chunk_index": meta.get("chunk_index", 0),
                            "deleted": meta.get("deleted", False),
                            "indexed_at": meta.get("indexed_at"),
                            "text_length": len(meta.get("text", "")),
                            "metadata_keys": list(meta.get("metadata", {}).keys()),
                        }
                        vector_docs[doc_id].append(chunk_info)

                return vector_docs

        except Exception as e:  # noqa: BLE001 - log any failure, then re-raise unchanged
            self.logger.error(f"Failed to get vector store documents: {e}")
            raise

    def _analyze_inconsistencies(self, db_docs: dict, vector_docs: dict) -> dict[str, Any]:
        issues: dict[str, Any] = {
            # Chunks in FAISS without a document in DB
            "orphaned_chunks": _orphaned_chunks(db_docs, vector_docs),
            # Documents in DB without chunks in FAISS
            "missing_chunks": _missing_chunks(db_docs, vector_docs),
            # Inconsistent chunk count
            "chunk_count_mismatch": _chunk_count_mismatches(db_docs, vector_docs),
            # DB status vs presence in FAISS
            "status_inconsistency": _status_inconsistencies(db_docs, vector_docs),
            # Chunks marked as deleted but still referenced
            "ghost_chunks": self._ghost_chunks(vector_docs),
            # Missing or inconsistent metadata
            "metadata_issues": _metadata_issues(vector_docs),
        }
        issues["total_issues"] = sum(len(issues[key]) for key in issues if key != "total_issues")
        return issues

    def _ghost_chunks(self, vector_docs: dict) -> list[dict[str, Any]]:
        """Chunks still mapped to their document but marked as deleted."""
        ghost_chunks = []
        for doc_id, chunk_ids in self.vector_store.document_to_chunks.items():
            if doc_id not in vector_docs:
                continue
            for chunk_id in chunk_ids:
                chunk_meta = next(
                    (m for m in self.vector_store.metadata if m.get("chunk_id") == chunk_id), None
                )
                if chunk_meta and chunk_meta.get("deleted", False):
                    ghost_chunks.append(
                        {
                            "document_id": doc_id,
                            "chunk_id": chunk_id,
                            "details": "Chunk referenced in mapping but marked as deleted",
                        }
                    )
        return ghost_chunks

    def _apply_fixes(self, issues: dict[str, Any]) -> list[dict[str, Any]]:
        fixes = []

        try:
            # 1. Clean orphaned chunks
            if issues["orphaned_chunks"]:
                orphaned_doc_ids = [item["document_id"] for item in issues["orphaned_chunks"]]
                cleanup_result = self.vector_store.clean_orphans(
                    existing_document_ids=set(self._get_database_documents().keys()),
                    create_backup=True,
                )

                fixes.append(
                    {
                        "type": "orphaned_chunks_cleanup",
                        "description": f"Cleaned {cleanup_result.get('cleaned_chunks', 0)} orphaned chunks",
                        "affected_documents": orphaned_doc_ids,
                        "result": cleanup_result,
                    }
                )

            # 2. Fix ghost chunks (remove references)
            if issues["ghost_chunks"]:
                ghost_count = 0
                for ghost in issues["ghost_chunks"]:
                    doc_id = ghost["document_id"]
                    chunk_id = ghost["chunk_id"]

                    doc_chunks = self.vector_store.document_to_chunks
                    if doc_id in doc_chunks and chunk_id in doc_chunks[doc_id]:
                        doc_chunks[doc_id].remove(chunk_id)
                        ghost_count += 1

                if ghost_count > 0:
                    fixes.append(
                        {
                            "type": "ghost_chunks_cleanup",
                            "description": f"Removed {ghost_count} ghost chunk references",
                            "affected_chunks": ghost_count,
                        }
                    )

            # 3. Trigger optimization if needed
            if fixes:
                deleted_ratio = self.vector_store.get_stats().get("deleted_vectors", 0) / max(
                    self.vector_store.get_stats().get("total_vectors", 1), 1
                )

                if deleted_ratio > 0.15:  # More than 15% of chunks deleted
                    rebuild_result = self.vector_store.rebuild_vector_store(
                        force_rebuild=False,
                        cleanup_orphans=False,  # Already done
                    )

                    fixes.append(
                        {
                            "type": "vector_store_optimization",
                            "description": "Optimized vector store after cleanup",
                            "result": rebuild_result,
                        }
                    )

            # Save changes
            if fixes:
                self.vector_store.persist()

        except Exception as e:  # noqa: BLE001 - best effort: the failure is reported as a fix_error entry
            self.logger.error(f"Failed to apply fixes: {e}")
            fixes.append(
                {
                    "type": "fix_error",
                    "description": f"Error applying fixes: {str(e)}",
                    "error": str(e),
                }
            )

        return fixes

    def _calculate_consistency_score(self, issues: dict[str, Any]) -> float:
        """Calculate a consistency score (0.0 = inconsistent, 1.0 = perfect)."""

        # Weighting of error types (some are more severe)
        weighted_issues = (
            len(issues.get("orphaned_chunks", [])) * 3  # Critical
            + len(issues.get("missing_chunks", [])) * 3  # Critical
            + len(issues.get("status_inconsistency", [])) * 2  # Severe
            + len(issues.get("chunk_count_mismatch", [])) * 2  # Severe
            + len(issues.get("ghost_chunks", [])) * 1  # Moderate
            + len(issues.get("metadata_issues", [])) * 1  # Moderate
        )

        if weighted_issues == 0:
            return 1.0

        # Score based on weighted error count
        # Score degrades quickly with severe errors
        base_score = max(0.0, 1.0 - (weighted_issues / 100))

        return base_score

    def _generate_recommendations(self, issues: dict[str, Any]) -> list[str]:
        recommendations = []

        if issues.get("orphaned_chunks"):
            recommendations.append(
                "Execute orphan cleanup to remove chunks without corresponding database documents"
            )

        if issues.get("missing_chunks"):
            recommendations.append(
                "Reprocess documents marked as indexed but missing from vector store"
            )

        if issues.get("chunk_count_mismatch"):
            recommendations.append(
                "Verify chunking consistency and consider reprocessing affected documents"
            )

        if issues.get("status_inconsistency"):
            recommendations.append("Update document statuses to reflect actual vector store state")

        if issues.get("ghost_chunks"):
            recommendations.append(
                "Clean document-to-chunk mappings to remove deleted chunk references"
            )

        if issues.get("metadata_issues"):
            recommendations.append("Validate and repair chunk metadata for proper indexing")

        if issues.get("total_issues", 0) > 10:
            recommendations.append(
                "Consider a full vector store rebuild due to numerous inconsistencies"
            )

        if not recommendations:
            recommendations.append("System consistency is good - no immediate action required")

        return recommendations


def _active(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [c for c in chunks if not c.get("deleted", False)]


def _orphaned_chunks(db_docs: dict, vector_docs: dict) -> list[dict[str, Any]]:
    """Documents with active chunks in FAISS but no record in the database."""
    orphaned = []
    for doc_id, chunks in vector_docs.items():
        if doc_id not in db_docs:
            active_chunks = _active(chunks)
            if active_chunks:
                orphaned.append(
                    {
                        "document_id": doc_id,
                        "chunk_count": len(active_chunks),
                        "total_chunks": len(chunks),
                        "details": "Document exists in FAISS but not in database",
                    }
                )
    return orphaned


def _missing_chunks(db_docs: dict, vector_docs: dict) -> list[dict[str, Any]]:
    """Documents marked as indexed in the database but absent from FAISS."""
    return [
        {
            "document_id": doc_id,
            "filename": doc_info["filename"],
            "expected_chunks": doc_info["chunk_count"],
            "details": "Document marked as indexed but no chunks in FAISS",
        }
        for doc_id, doc_info in db_docs.items()
        if doc_info["status"] == "indexed" and doc_id not in vector_docs
    ]


def _chunk_count_mismatches(db_docs: dict, vector_docs: dict) -> list[dict[str, Any]]:
    """Documents whose database chunk count differs from their active FAISS chunks."""
    mismatches = []
    for doc_id in set(db_docs.keys()) & set(vector_docs.keys()):
        db_chunk_count = db_docs[doc_id]["chunk_count"]
        vector_active_chunks = len(_active(vector_docs[doc_id]))
        if db_chunk_count != vector_active_chunks:
            mismatches.append(
                {
                    "document_id": doc_id,
                    "filename": db_docs[doc_id]["filename"],
                    "db_chunk_count": db_chunk_count,
                    "vector_chunk_count": vector_active_chunks,
                    "difference": abs(db_chunk_count - vector_active_chunks),
                }
            )
    return mismatches


def _status_inconsistencies(db_docs: dict, vector_docs: dict) -> list[dict[str, Any]]:
    """Indexed documents present in FAISS without any active chunk.

    Indexed documents absent from FAISS are reported as missing chunks.
    """
    return [
        {
            "document_id": doc_id,
            "filename": doc_info["filename"],
            "db_status": doc_info["status"],
            "vector_status": "no_active_chunks",
            "details": "Document marked as indexed but no active chunks in FAISS",
        }
        for doc_id, doc_info in db_docs.items()
        if doc_info["status"] == "indexed"
        and doc_id in vector_docs
        and not _active(vector_docs[doc_id])
    ]


def _metadata_issues(vector_docs: dict) -> list[dict[str, Any]]:
    """Chunks missing their chunk_index or indexed_at metadata."""
    issues = []
    for doc_id, chunks in vector_docs.items():
        for chunk in chunks:
            missing_fields = []
            if not chunk.get("chunk_index") and chunk.get("chunk_index") != 0:
                missing_fields.append("chunk_index")
            if not chunk.get("indexed_at"):
                missing_fields.append("indexed_at")

            if missing_fields:
                issues.append(
                    {
                        "document_id": doc_id,
                        "chunk_id": chunk.get("chunk_id"),
                        "missing_fields": missing_fields,
                    }
                )
    return issues

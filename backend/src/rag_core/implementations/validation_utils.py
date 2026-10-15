"""
Validation utilities for detecting inconsistencies between SQLite and FAISS
"""

from typing import Any
from datetime import datetime
import logging
from pathlib import Path

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
        """
        Validate consistency between SQLite and FAISS.

        Args:
            fix_issues: If True, attempt to automatically fix inconsistencies

        Returns:
            Dict with detailed validation report
        """
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

        except Exception as e:
            error_msg = f"Validation failed: {str(e)}"
            self.logger.error(error_msg)
            raise Exception(error_msg) from e

    def _get_database_documents(self) -> dict[str, dict[str, Any]]:
        """Retrieve documents from SQLite."""
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
        except Exception as e:
            self.logger.error(f"Failed to get database documents: {e}")
            raise

    def _get_vector_store_documents(self) -> dict[str, list[dict[str, Any]]]:
        """Retrieve documents from FAISS."""
        try:
            with self.vector_store._lock:
                vector_docs = {}

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

        except Exception as e:
            self.logger.error(f"Failed to get vector store documents: {e}")
            raise

    def _analyze_inconsistencies(self, db_docs: dict, vector_docs: dict) -> dict[str, Any]:  # noqa: C901
        """Analyze inconsistencies between the two sources."""
        issues = {
            "orphaned_chunks": [],  # Chunks in FAISS without a document in DB
            "missing_chunks": [],  # Documents in DB without chunks in FAISS
            "chunk_count_mismatch": [],  # Inconsistent chunk count
            "status_inconsistency": [],  # DB status vs presence in FAISS
            "ghost_chunks": [],  # Chunks marked as deleted but still referenced
            "metadata_issues": [],  # Missing or inconsistent metadata
        }

        # 1. Find orphaned chunks (in FAISS but not in DB)
        for doc_id, chunks in vector_docs.items():
            if doc_id not in db_docs:
                active_chunks = [c for c in chunks if not c.get("deleted", False)]
                if active_chunks:
                    issues["orphaned_chunks"].append(
                        {
                            "document_id": doc_id,
                            "chunk_count": len(active_chunks),
                            "total_chunks": len(chunks),
                            "details": "Document exists in FAISS but not in database",
                        }
                    )

        # 2. Find documents without chunks (in DB but not in FAISS)
        for doc_id, doc_info in db_docs.items():
            if doc_info["status"] == "indexed" and doc_id not in vector_docs:
                issues["missing_chunks"].append(
                    {
                        "document_id": doc_id,
                        "filename": doc_info["filename"],
                        "expected_chunks": doc_info["chunk_count"],
                        "details": "Document marked as indexed but no chunks in FAISS",
                    }
                )

        # 3. Verify chunk count consistency
        for doc_id in set(db_docs.keys()) & set(vector_docs.keys()):
            db_chunk_count = db_docs[doc_id]["chunk_count"]
            vector_active_chunks = len(
                [c for c in vector_docs[doc_id] if not c.get("deleted", False)]
            )

            if db_chunk_count != vector_active_chunks:
                issues["chunk_count_mismatch"].append(
                    {
                        "document_id": doc_id,
                        "filename": db_docs[doc_id]["filename"],
                        "db_chunk_count": db_chunk_count,
                        "vector_chunk_count": vector_active_chunks,
                        "difference": abs(db_chunk_count - vector_active_chunks),
                    }
                )

        # 4. Verify status consistency
        for doc_id, doc_info in db_docs.items():
            if doc_info["status"] == "indexed":
                if doc_id not in vector_docs:
                    # Already captured in missing_chunks
                    continue

                active_chunks = [c for c in vector_docs[doc_id] if not c.get("deleted", False)]
                if not active_chunks:
                    issues["status_inconsistency"].append(
                        {
                            "document_id": doc_id,
                            "filename": doc_info["filename"],
                            "db_status": doc_info["status"],
                            "vector_status": "no_active_chunks",
                            "details": "Document marked as indexed but no active chunks in FAISS",
                        }
                    )

        # 5. Find ghost chunks (mapped but deleted)
        for doc_id, chunk_ids in self.vector_store.document_to_chunks.items():
            if doc_id in vector_docs:
                for chunk_id in chunk_ids:
                    # Find the chunk in metadata
                    chunk_meta = None
                    for meta in self.vector_store.metadata:
                        if meta.get("chunk_id") == chunk_id:
                            chunk_meta = meta
                            break

                    if chunk_meta and chunk_meta.get("deleted", False):
                        issues["ghost_chunks"].append(
                            {
                                "document_id": doc_id,
                                "chunk_id": chunk_id,
                                "details": "Chunk referenced in mapping but marked as deleted",
                            }
                        )

        # 6. Verify essential metadata
        for doc_id, chunks in vector_docs.items():
            for chunk in chunks:
                missing_fields = []
                if not chunk.get("chunk_index") and chunk.get("chunk_index") != 0:
                    missing_fields.append("chunk_index")
                if not chunk.get("indexed_at"):
                    missing_fields.append("indexed_at")

                if missing_fields:
                    issues["metadata_issues"].append(
                        {
                            "document_id": doc_id,
                            "chunk_id": chunk.get("chunk_id"),
                            "missing_fields": missing_fields,
                        }
                    )

        # Calculate total
        issues["total_issues"] = sum(len(issues[key]) for key in issues if key != "total_issues")

        return issues

    def _apply_fixes(self, issues: dict[str, Any]) -> list[dict[str, Any]]:
        """Apply possible automatic fixes."""
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

        except Exception as e:  # noqa: BLE001
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
        """Generate recommendations based on found issues."""
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


def create_validation_report(
    vector_store, document_repository, output_path: str = None
) -> dict[str, Any]:
    """
    Create a comprehensive validation report and optionally save it.

    Args:
        vector_store: FaissVectorStore instance
        document_repository: DocumentRepository instance
        output_path: Optional path to save the report

    Returns:
        Dict: Complete validation report
    """
    validator = VectorStoreValidator(vector_store, document_repository)
    report = validator.validate_consistency(fix_issues=False)

    if output_path:
        try:
            import json

            output_file = Path(output_path)
            output_file.parent.mkdir(parents=True, exist_ok=True)

            with open(output_file, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=2, default=str)

            logger.info(f"Validation report saved to {output_path}")

        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to save validation report: {e}")

    return report

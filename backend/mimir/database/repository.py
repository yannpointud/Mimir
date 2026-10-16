"""
Repository pattern for persistence abstraction
Implements CRUD operations with robust error handling
"""

from typing import Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import desc, asc, func, update
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from datetime import datetime, timedelta
import logging

from mimir.database.models import Document, Configuration, AuditLog, LlmUsage, LlmBudgetLedger


logger = logging.getLogger(__name__)


class BaseRepository:
    """Base repository with common operations"""

    def __init__(self, session: Session):
        self.session = session

    def _handle_db_error(self, e: Exception, operation: str) -> None:
        logger.error(f"Database error during {operation}: {e}")
        self.session.rollback()


class DocumentRepository(BaseRepository):
    """
    Repository for documents
    Handles document CRUD with integrated business logic
    """

    def create(
        self, filename: str, file_hash: str, path: str | None = None, preserve: bool = False
    ) -> Document:
        """Create a new document

        Raises:
            IntegrityError: If the hash already exists
        """
        try:
            document = Document(
                filename=filename,
                file_hash=file_hash,
                path=path,
                preserve=preserve,
                status="pending",
            )

            self.session.add(document)
            self.session.commit()
            self.session.refresh(document)

            logger.info(f"Document created: {filename} (id={document.id})")
            return document

        except IntegrityError as e:
            self._handle_db_error(e, f"create document {filename}")
            raise ValueError(f"Document with hash {file_hash} already exists") from e
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"create document {filename}")
            raise

    def get_by_id(self, doc_id: int) -> Document | None:
        """Retrieve a document by its ID"""
        try:
            return self.session.query(Document).filter_by(id=doc_id).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get document by id {doc_id}")
            raise

    def get_by_ids(self, doc_ids: list[int]) -> dict[int, Document]:
        """Retrieve multiple documents by ID in a single query.

        Returns a {id: Document} mapping so a caller can resolve many document
        ids without issuing one get_by_id() per id (avoids the N+1 the RAG
        citation loop used to trigger). Ids with no matching row are simply
        absent from the mapping. An empty input yields an empty mapping without
        touching the database (a `WHERE id IN ()` is invalid SQL).
        """
        if not doc_ids:
            return {}
        try:
            rows = self.session.query(Document).filter(Document.id.in_(doc_ids)).all()
            return {doc.id: doc for doc in rows}
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get documents by ids {doc_ids}")
            raise

    def get_by_hash(self, file_hash: str) -> Document | None:
        """Retrieve a document by its hash (to detect duplicates)"""
        try:
            return self.session.query(Document).filter_by(file_hash=file_hash).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get document by hash {file_hash}")
            raise

    def get_by_status(self, status: str) -> list[Document]:
        """Retrieve all documents with a given status"""
        try:
            return self.session.query(Document).filter_by(status=status).all()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get documents by status {status}")
            raise

    def get_all(
        self,
        limit: int | None = None,
        offset: int = 0,
        order_by: str = "created_at",
        desc_order: bool = True,
    ) -> list[Document]:
        """Retrieve all documents with pagination and sorting.

        ``order_by`` names a Document column (created_at if it does not exist).
        """
        try:
            query = self.session.query(Document)

            # Sorting
            order_field = getattr(Document, order_by, Document.created_at)
            if desc_order:
                query = query.order_by(desc(order_field))
            else:
                query = query.order_by(asc(order_field))

            # Pagination
            if offset > 0:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            return query.all()

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get all documents")
            raise

    def get_all_paginated(
        self,
        offset: int = 0,
        limit: int = 50,
        filters: dict[str, Any] | None = None,
        search: str | None = None,
    ) -> tuple[list["Document"], int]:
        """Retrieve documents (newest first) with pagination and the total count.

        Only the ``status`` key of ``filters`` is applied; ``search`` is a
        case-insensitive filename match. Returns (documents, total_count).
        """
        try:
            query = self.session.query(Document)

            # Apply filters
            if filters and "status" in filters:
                query = query.filter(Document.status == filters["status"])

            # Apply search
            if search:
                query = query.filter(Document.filename.ilike(f"%{search}%"))

            # Count total before pagination
            total_count = query.count()

            # Apply pagination and sorting
            query = query.order_by(desc(Document.created_at))
            if offset > 0:
                query = query.offset(offset)
            if limit:
                query = query.limit(limit)

            documents = query.all()

            return documents, total_count

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get all documents paginated")
            raise

    def update_status(
        self,
        doc_id: int,
        status: str,
        error_message: str | None = None,
        chunk_count: int | None = None,
    ) -> None:
        """Update a document's status"""
        try:
            document = self.get_by_id(doc_id)
            if not document:
                raise ValueError(f"Document {doc_id} not found")

            old_status = document.status
            document.status = status
            document.error_message = error_message

            if chunk_count is not None:
                document.chunk_count = chunk_count

            if status == "indexed":
                document.indexed_at = datetime.utcnow()

            self.session.commit()

            logger.info(f"Document {doc_id} status updated: {old_status} -> {status}")

        except SQLAlchemyError as e:
            self._handle_db_error(e, f"update document {doc_id} status")
            raise

    def update_preserve_status(self, doc_id: int, preserve: bool) -> Document:
        """Set whether a document is protected from deletion; returns the document.

        Raises:
            ValueError: If the document does not exist
        """
        try:
            document = self.get_by_id(doc_id)
            if not document:
                raise ValueError(f"Document {doc_id} not found")
            document.preserve = preserve
            self.session.commit()
            logger.info(f"Document {doc_id} preserve flag set to {preserve}")
            return document
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"update document {doc_id} preserve flag")
            raise

    def delete(self, doc_id: int, force: bool = False) -> bool:
        """Delete a document; return False if it does not exist.

        Raises:
            ValueError: If the document is protected and ``force`` is False.
        """
        try:
            document = self.get_by_id(doc_id)
            if not document:
                return False

            if document.preserve and not force:
                raise ValueError(f"Document {doc_id} is protected from deletion")

            self.session.delete(document)
            self.session.commit()

            logger.info(f"Document deleted: {document.filename} (id={doc_id})")
            return True

        except SQLAlchemyError as e:
            self._handle_db_error(e, f"delete document {doc_id}")
            raise

    def get_statistics(self) -> dict[str, Any]:
        """Return statistics about documents"""
        try:
            stats = {}

            # Counts by status
            for status in ["pending", "indexing", "indexed", "error"]:
                count = self.session.query(Document).filter_by(status=status).count()
                stats[f"count_{status}"] = count

            # Total count
            stats["total_documents"] = self.session.query(Document).count()

            # Total chunks
            total_chunks = (
                self.session.query(Document.chunk_count).filter(Document.status == "indexed").all()
            )
            stats["total_chunks"] = sum(count[0] for count in total_chunks if count[0])

            # Protected documents
            stats["protected_documents"] = (
                self.session.query(Document).filter_by(preserve=True).count()
            )

            return stats

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get document statistics")
            raise


class ConfigurationRepository(BaseRepository):
    """Repository for system configuration"""

    def get(self, key: str) -> Configuration | None:
        """Retrieve a configuration by key"""
        try:
            return self.session.query(Configuration).filter_by(key=key).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get configuration {key}")
            raise

    def get_value(self, key: str, default: str | None = None) -> str | None:
        """Retrieve the value of a configuration"""
        config = self.get(key)
        return config.value if config else default

    def set(self, key: str, value: str) -> Configuration:
        """Set or update a configuration"""
        try:
            config = self.get(key)
            if config:
                config.value = value
                config.updated_at = datetime.utcnow()
            else:
                config = Configuration(key=key, value=value)
                self.session.add(config)

            self.session.commit()
            self.session.refresh(config)

            logger.info(f"Configuration updated: {key}")
            return config

        except SQLAlchemyError as e:
            self._handle_db_error(e, f"set configuration {key}")
            raise

    def delete(self, key: str) -> bool:
        """Delete a configuration"""
        try:
            config = self.get(key)
            if config:
                self.session.delete(config)
                self.session.commit()
                logger.info(f"Configuration deleted: {key}")
                return True
            return False

        except SQLAlchemyError as e:
            self._handle_db_error(e, f"delete configuration {key}")
            raise

    def get_all(self) -> list[Configuration]:
        """Retrieve all configurations"""
        try:
            return self.session.query(Configuration).order_by(Configuration.key).all()
        except SQLAlchemyError as e:
            self._handle_db_error(e, "get all configurations")
            raise


class AuditLogRepository(BaseRepository):
    """Repository for audit logs"""

    def create_log(
        self,
        user_type: str,
        action: str,
        details: str | None = None,
        ip_address: str | None = None,
        user_agent: str | None = None,
        success: bool = True,
        additional_data: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Create a new audit log"""
        try:
            # Note: additional_data is accepted for compatibility but not persisted
            # In a future version, this field could be added to the model
            log_entry = AuditLog(
                user_type=user_type,
                action=action,
                details=details,
                ip_address=ip_address,
                user_agent=user_agent,
                success=success,
            )

            self.session.add(log_entry)
            self.session.commit()
            self.session.refresh(log_entry)

            return log_entry

        except SQLAlchemyError as e:
            self._handle_db_error(e, f"create audit log {action}")
            raise

    def get_logs(
        self,
        user_type: str | None = None,
        action: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[AuditLog]:
        """Retrieve audit logs with filters"""
        try:
            query = self.session.query(AuditLog)

            if user_type:
                query = query.filter_by(user_type=user_type)

            if action:
                query = query.filter(AuditLog.action.like(f"%{action}%"))

            query = query.order_by(desc(AuditLog.created_at))

            if offset > 0:
                query = query.offset(offset)

            return query.limit(limit).all()

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get audit logs")
            raise

    def get_logs_paginated(
        self, offset: int = 0, limit: int = 100, filters: dict[str, Any] | None = None
    ) -> tuple[list[AuditLog], int]:
        """Retrieve audit logs with pagination and total count.

        Supported ``filters`` keys:
            - action: partial match (LIKE %action%)
            - user_type: exact match
            - success: exact bool match
            - since_date: created_at >= since_date

        Returns:
            Tuple (entries, total_count) where total_count reflects the
            filtered set BEFORE pagination is applied.
        """
        try:
            query = self.session.query(AuditLog)

            if filters:
                if filters.get("action"):
                    query = query.filter(AuditLog.action.like(f"%{filters['action']}%"))
                if filters.get("user_type"):
                    query = query.filter_by(user_type=filters["user_type"])
                if filters.get("success") is not None:
                    query = query.filter(AuditLog.success == filters["success"])
                if filters.get("since_date") is not None:
                    query = query.filter(AuditLog.created_at >= filters["since_date"])

            # Count the filtered set before pagination
            total_count = query.count()

            query = query.order_by(desc(AuditLog.created_at))
            if offset > 0:
                query = query.offset(offset)

            entries = query.limit(limit).all()

            return entries, total_count

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get audit logs paginated")
            raise

    def cleanup_old_logs(self, days_to_keep: int = 90) -> int:
        """Delete audit logs older than ``days_to_keep`` days and return how many were deleted."""
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

            deleted_count = (
                self.session.query(AuditLog).filter(AuditLog.created_at < cutoff_date).delete()
            )

            self.session.commit()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old audit logs")

            return deleted_count

        except SQLAlchemyError as e:
            self._handle_db_error(e, "cleanup audit logs")
            raise


class UsageRepository(BaseRepository):
    """
    Repository for LLM usage accounting (llm_usage) and the daily budget
    ledger (llm_budget_ledger).

    Two distinct concerns live here:
      - CRUD/aggregates for llm_usage (dashboard-facing, cost accounting log)
      - Atomic reservation primitives for llm_budget_ledger (reserve/finalize/
        release), which make the daily cap race-free (anti-TOCTOU)
    """

    def create_usage_entry(
        self,
        call_type: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        cost_eur: float,
        estimated: bool = False,
        session_id: str | None = None,
    ) -> LlmUsage:
        """Create a new per-call usage log entry.

        ``estimated`` flags token counts/cost that are estimates (e.g. stream
        disconnect); ``session_id`` is a session or "doc:{id}" identifier for
        traceability.
        """
        try:
            usage_entry = LlmUsage(
                call_type=call_type,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                cost_eur=cost_eur,
                estimated=estimated,
                session_id=session_id,
            )

            self.session.add(usage_entry)
            self.session.commit()
            self.session.refresh(usage_entry)

            return usage_entry

        except SQLAlchemyError as e:
            self._handle_db_error(e, f"create usage entry {call_type}/{model}")
            raise

    def get_today_by_model(self) -> list[dict[str, Any]]:
        """
        Aggregate today's usage by model (dashboard "today by model" table).

        Returns:
            List of {model, calls, prompt_tokens, completion_tokens, total_tokens, cost_eur}
        """
        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")

            rows = (
                self.session.query(
                    LlmUsage.model,
                    func.count(LlmUsage.id).label("calls"),
                    func.sum(LlmUsage.prompt_tokens).label("prompt_tokens"),
                    func.sum(LlmUsage.completion_tokens).label("completion_tokens"),
                    func.sum(LlmUsage.total_tokens).label("total_tokens"),
                    func.sum(LlmUsage.cost_eur).label("cost_eur"),
                )
                .filter(func.date(LlmUsage.created_at) == today)
                .group_by(LlmUsage.model)
                .all()
            )

            return [
                {
                    "model": row.model,
                    "calls": row.calls,
                    "prompt_tokens": row.prompt_tokens or 0,
                    "completion_tokens": row.completion_tokens or 0,
                    "total_tokens": row.total_tokens or 0,
                    "cost_eur": row.cost_eur or 0.0,
                }
                for row in rows
            ]

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get today usage by model")
            raise

    def get_daily_history(self, days_back: int = 30) -> list[dict[str, Any]]:
        """Aggregate usage per day (and model) for the last `days_back` days,
        ordered by date (dashboard "30 day history" section).

        Returns:
            List of {date, model, calls, tokens, cost_eur}
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            date_col = func.date(LlmUsage.created_at)

            rows = (
                self.session.query(
                    date_col.label("date"),
                    LlmUsage.model,
                    func.count(LlmUsage.id).label("calls"),
                    func.sum(LlmUsage.total_tokens).label("tokens"),
                    func.sum(LlmUsage.cost_eur).label("cost_eur"),
                )
                .filter(LlmUsage.created_at >= cutoff_date)
                .group_by(date_col, LlmUsage.model)
                .order_by(date_col)
                .all()
            )

            return [
                {
                    "date": row.date,
                    "model": row.model,
                    "calls": row.calls,
                    "tokens": row.tokens or 0,
                    "cost_eur": row.cost_eur or 0.0,
                }
                for row in rows
            ]

        except SQLAlchemyError as e:
            self._handle_db_error(e, "get daily usage history")
            raise

    def get_today_ledger(self) -> LlmBudgetLedger | None:
        """Retrieve today's budget ledger row, or None if it does not exist yet."""
        try:
            today = datetime.utcnow().strftime("%Y-%m-%d")
            return self.session.query(LlmBudgetLedger).filter_by(date=today).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, "get today budget ledger")
            raise

    def cleanup_old_usage(self, days_to_keep: int = 90) -> int:
        """Purge llm_usage rows older than the retention window (aligned with
        the audit_log retention policy).

        Returns:
            Number of deleted rows
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)

            deleted_count = (
                self.session.query(LlmUsage).filter(LlmUsage.created_at < cutoff_date).delete()
            )

            self.session.commit()

            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old usage entries")

            return deleted_count

        except SQLAlchemyError as e:
            self._handle_db_error(e, "cleanup old usage entries")
            raise

    def reserve(self, today: str, estimate_eur: float, cap_eur: float) -> bool:
        """
        Attempt an atomic budget reservation for `today`.

        Ensures today's ledger row exists (idempotent insert-or-ignore), then
        performs a SINGLE conditional UPDATE incrementing spent_eur by
        estimate_eur only where spent_eur + estimate_eur <= cap_eur. The
        WHERE clause IS the anti-TOCTOU guard -- never read-then-decide in
        Python, the guard must live entirely in the UPDATE statement.

        Args:
            today: Ledger date key (YYYY-MM-DD)
            estimate_eur: Flat pre-call cost estimate to reserve
            cap_eur: Daily budget cap

        Returns:
            True iff the reservation was accepted (rowcount == 1)
        """
        try:
            # 1. Ensure today's row exists (idempotent, itself atomic)
            self.session.execute(
                sqlite_insert(LlmBudgetLedger)
                .values(date=today, spent_eur=0.0)
                .on_conflict_do_nothing(index_elements=["date"])
            )

            # 2. Atomic conditional increment -- the WHERE clause IS the
            # anti-TOCTOU check. No application lock needed: SQLite WAL
            # (busy_timeout already configured in connection.py) already
            # serializes writers at the file level.
            result = self.session.execute(
                update(LlmBudgetLedger)
                .where(LlmBudgetLedger.date == today)
                .where(LlmBudgetLedger.spent_eur + estimate_eur <= cap_eur)
                .values(spent_eur=LlmBudgetLedger.spent_eur + estimate_eur)
            )
            self.session.commit()

            return result.rowcount == 1

        except SQLAlchemyError as e:
            self._handle_db_error(e, "reserve budget")
            raise

    def finalize(self, today: str, delta_eur: float) -> None:
        """
        Apply the real-vs-estimate delta to today's ledger, with NO cap
        condition -- the call already happened, spent_eur may slightly
        exceed cap_eur (expected).

        Args:
            today: Ledger date key (YYYY-MM-DD)
            delta_eur: Real cost minus reserved estimate (may be negative)
        """
        try:
            self.session.execute(
                update(LlmBudgetLedger)
                .where(LlmBudgetLedger.date == today)
                .values(spent_eur=LlmBudgetLedger.spent_eur + delta_eur)
            )
            self.session.commit()

        except SQLAlchemyError as e:
            self._handle_db_error(e, "finalize budget")
            raise

    def release(self, today: str, estimate_eur: float) -> None:
        """
        Roll back a reservation whose call failed, subtracting the reserved
        estimate from today's ledger.

        Args:
            today: Ledger date key (YYYY-MM-DD)
            estimate_eur: The estimate amount previously reserved
        """
        try:
            self.session.execute(
                update(LlmBudgetLedger)
                .where(LlmBudgetLedger.date == today)
                .values(spent_eur=LlmBudgetLedger.spent_eur - estimate_eur)
            )
            self.session.commit()

        except SQLAlchemyError as e:
            self._handle_db_error(e, "release budget")
            raise


# Factory function to create repositories with a session


def create_repositories(session: Session) -> dict[str, Any]:
    """Factory to create all repositories with a given session"""
    return {
        "document": DocumentRepository(session),
        "config": ConfigurationRepository(session),
        "audit": AuditLogRepository(session),
        "usage": UsageRepository(session),
    }

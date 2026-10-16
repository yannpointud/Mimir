"""SQLAlchemy models for Mimir."""

from datetime import datetime
from typing import Any, Self

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from mimir.shared.clock import utc_now


class Base(DeclarativeBase):
    """Declarative base of the ORM models (SQLAlchemy 2.0 typed mapping).

    Every column keeps its explicit SQL type, nullability, default and index
    flags, so the schema is the one the Alembic migrations create.
    """


class Document(Base):
    """Indexed documents table, with status management and preservation."""

    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    file_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", index=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    preserve: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, index=True
    )
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Constraint on valid statuses
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'indexing', 'indexed', 'error')", name="check_document_status"
        ),
        Index("idx_document_status_created", "status", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "filename": self.filename,
            "path": self.path,
            "file_hash": self.file_hash,
            "status": self.status,
            "error_message": self.error_message,
            "chunk_count": self.chunk_count,
            "preserve": self.preserve,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "indexed_at": self.indexed_at.isoformat() if self.indexed_at else None,
        }

    def is_indexed(self) -> bool:
        return self.status == "indexed" and self.chunk_count > 0

    def is_processing(self) -> bool:
        return self.status in ["pending", "indexing"]

    def has_error(self) -> bool:
        return self.status == "error"

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename='{self.filename}', status='{self.status}')>"


class Configuration(Base):
    """
    System configuration table
    Key-value storage for dynamic parameters
    """

    __tablename__ = "configuration"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, onupdate=utc_now, nullable=False, index=True
    )

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "value": self.value, "updated_at": self.updated_at.isoformat()}

    @staticmethod
    def get_typed_value(value: str, value_type: str = "string") -> Any:
        """
        Convert a string value to the appropriate type
        Useful for retrieving typed configs
        """
        if value_type == "bool":
            return value.lower() in ("true", "1", "yes", "on")
        elif value_type == "int":
            return int(value)
        elif value_type == "float":
            return float(value)
        else:
            return value

    def __repr__(self) -> str:
        return f"<Configuration(key='{self.key}', updated_at='{self.updated_at}')>"


class AuditLog(Base):
    """Audit table tracing critical actions."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # Support IPv6
    user_agent: Mapped[str | None] = mapped_column(Text, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, index=True
    )

    # Constraint on valid user types
    __table_args__ = (
        CheckConstraint("user_type IN ('admin', 'user', 'system')", name="check_user_type"),
        Index("idx_audit_user_action_date", "user_type", "action", "created_at"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_type": self.user_type,
            "action": self.action,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "success": self.success,
            "created_at": self.created_at.isoformat(),
        }

    @classmethod
    def create_admin_action(
        cls,
        action: str,
        details: str | None = None,
        ip_address: str | None = None,
        success: bool = True,
    ) -> Self:
        return cls(
            user_type="admin",
            action=action,
            details=details,
            ip_address=ip_address,
            success=success,
        )

    @classmethod
    def create_user_action(
        cls,
        action: str,
        details: str | None = None,
        ip_address: str | None = None,
        success: bool = True,
    ) -> Self:
        return cls(
            user_type="user", action=action, details=details, ip_address=ip_address, success=success
        )

    @classmethod
    def create_system_action(
        cls, action: str, details: str | None = None, success: bool = True
    ) -> Self:
        return cls(user_type="system", action=action, details=details, success=success)

    def __repr__(self) -> str:
        return (
            f"<AuditLog(id={self.id}, user_type='{self.user_type}', "
            f"action='{self.action}', created_at='{self.created_at}')>"
        )


class LlmUsage(Base):
    """
    Per-call LLM usage log table
    One row per Mistral API call (chat or embedding), used for cost accounting
    """

    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=utc_now, nullable=False, index=True
    )
    call_type: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_eur: Mapped[float] = mapped_column(Float, nullable=False)
    estimated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    session_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # Constraint on valid call types
    __table_args__ = (
        CheckConstraint("call_type IN ('chat', 'embedding')", name="check_call_type"),
        Index("idx_usage_created_model", "created_at", "model"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "call_type": self.call_type,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "cost_eur": self.cost_eur,
            "estimated": self.estimated,
            "session_id": self.session_id,
        }

    def __repr__(self) -> str:
        return (
            f"<LlmUsage(id={self.id}, call_type='{self.call_type}', "
            f"model='{self.model}', cost_eur={self.cost_eur})>"
        )


class LlmBudgetLedger(Base):
    """
    Daily budget ledger table
    One row per day (primary key = date), tracks cumulative spend for the
    atomic reservation pattern (anti-TOCTOU conditional UPDATE)
    """

    __tablename__ = "llm_budget_ledger"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)  # YYYY-MM-DD
    spent_eur: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    def to_dict(self) -> dict[str, Any]:
        return {"date": self.date, "spent_eur": self.spent_eur}

    def __repr__(self) -> str:
        return f"<LlmBudgetLedger(date='{self.date}', spent_eur={self.spent_eur})>"


# Utility functions for models


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(bind=engine)


def drop_tables(engine: Engine) -> None:
    """Drop all tables from the database (for tests)"""
    Base.metadata.drop_all(bind=engine)

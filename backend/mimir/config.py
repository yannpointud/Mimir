"""
Application settings, loaded from the environment and the ``.env`` file of the
working directory.
"""

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Main configuration of the Mimir application."""

    model_config = SettingsConfigDict(env_file=".env", case_sensitive=False)

    # API
    api_version: str = Field(default="v1", description="API version prefix")
    api_host: str = Field(default="0.0.0.0", description="Development server host")
    api_port: int = Field(default=8000, description="Development server port")

    # Database
    database_url: str = Field(
        default="sqlite:///./data/sqlite/mimir.db", description="SQLAlchemy database URL"
    )
    sqlite_wal_mode: bool = Field(default=True, description="Enable SQLite WAL journaling")

    # LLM
    mistral_api_key: str = Field(default="", description="Mistral API key (required for chat)")
    mistral_model: str = Field(default="mistral-small-latest", description="Generation model")
    mistral_embedding_model: str = Field(default="mistral-embed", description="Embedding model")
    embedding_batch_size: int = Field(default=50, description="Maximum texts per embedding call")

    # Vector store
    faiss_index_path: str = Field(default="./data/faiss/index.bin", description="FAISS index")
    faiss_metadata_path: str = Field(
        default="./data/faiss/metadata.json", description="FAISS chunk metadata"
    )
    faiss_max_backups: int = Field(default=4, description="FAISS backup files kept (rotation)")
    embedding_dimension: int = Field(default=1024, description="Embedding vector dimension")

    # Sources and confidence
    similarity_threshold: float = Field(
        default=0.5, ge=0.0, le=1.0, description="Minimum cosine similarity of a dense source"
    )
    max_sources: int = Field(default=5, ge=1, le=20, description="Maximum sources returned")
    min_sources: int = Field(
        default=1, ge=1, le=10, description="Minimum sources returned when available"
    )
    confidence_algorithm: str = Field(
        default="weighted", description="Confidence algorithm: 'simple' or 'weighted'"
    )
    filename_boost: float = Field(
        default=1.3, gt=0.0, le=2.0, description="Similarity boost of a filename match"
    )
    dynamic_filter_percentage: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Maximum relative gap to the best score for a source to be kept",
    )

    # Hybrid search (BM25 + dense fused with RRF). Adopted on measured RAGAS
    # gains, see docs/adr/0002; False falls back to dense-only retrieval.
    hybrid_search_enabled: bool = Field(default=True, description="Enable hybrid retrieval")
    rrf_k: int = Field(default=60, ge=1, description="Reciprocal Rank Fusion constant")
    rrf_score_threshold: float = Field(
        default=0.015, ge=0.0, description="Minimum fused RRF score of a hybrid source"
    )
    bm25_index_path: str = Field(default="./data/bm25/index", description="BM25 index directory")

    # Chunking aligned on document headings, adopted on measured RAGAS gains
    structure_aware_chunking_enabled: bool = Field(
        default=True, description="Split documents along their headings"
    )

    # Filename pre-inclusion (fuzzy matching of the question against filenames)
    filename_pre_inclusion: bool = Field(
        default=True, description="Pre-include chunks of documents whose name matches"
    )
    filename_fuzzy_threshold: int = Field(
        default=70, ge=0, le=100, description="Minimum fuzzy score (0-100) of a filename match"
    )

    # Ingestion
    ingestion_queue_max_size: int = Field(
        default=50000, ge=1, le=100000, description="Maximum documents waiting for ingestion"
    )
    ingestion_max_retries: int = Field(
        default=5, ge=0, le=20, description="Retries of a failed document ingestion"
    )
    ingestion_retry_base_delay: float = Field(
        default=2.0, ge=0.0, le=60.0, description="Base delay (s) of the retry backoff"
    )
    ingestion_retry_max_delay: float = Field(
        default=60.0, ge=1.0, le=600.0, description="Maximum delay (s) of the retry backoff"
    )
    max_chunk_size: int = Field(default=1000, description="Maximum chunk size in characters")
    chunk_overlap: int = Field(default=200, description="Overlap between chunks in characters")
    max_chunks_per_doc: int = Field(default=2000, description="Maximum chunks per document")
    max_file_size_mb: int = Field(default=100, description="Maximum upload size in MB")
    supported_file_extensions: set[str] = Field(
        default={".pdf", ".docx", ".txt", ".md"}, description="Accepted upload extensions"
    )

    # File system
    data_dir: str = Field(default="./data", description="Root of the runtime data")
    upload_dir: str = Field(default="./data/documents", description="Uploaded files")
    sqlite_backup_dir: str = Field(default="./data/backups", description="SQLite backups")
    sqlite_backup_max_count: int = Field(default=14, description="SQLite backups kept (rotation)")

    # Email (escalations and alerts)
    smtp_host: str = Field(default="", description="SMTP host")
    smtp_port: int = Field(default=587, description="SMTP port")
    smtp_user: str = Field(default="", description="SMTP user")
    smtp_password: str = Field(default="", description="SMTP password")
    smtp_use_tls: bool = Field(default=True, description="Use STARTTLS")
    escalation_email: str = Field(default="", description="Recipient of escalations")

    # Security
    jwt_secret_key: str = Field(
        default="dev-secret-key-change-in-production-minimum-32-chars-long",
        description="JWT signing key; startup refuses this default in production",
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT signing algorithm")
    jwt_expiration_hours: int = Field(default=2, description="Access token lifetime in hours")
    admin_password_hash: str = Field(
        default="$2b$12$Kc32f7ibhcSNTkn/UkFOke32Q2A3XLNIG6RliCTq9.SnTj1/D2Eiy",
        description="Admin password hash (development default, refused in production)",
    )
    admin_password: str = Field(
        default="",
        description="Admin password in clear text, hashed at startup; takes precedence over "
        "admin_password_hash (container deployments)",
    )
    trusted_hosts: str = Field(
        default="*",
        description="Comma-separated allowed Host headers; '*' disables the check",
    )

    # Rate limiting (per client and per minute)
    rate_limit_enabled: bool = Field(default=True, description="Enable rate limiting")
    rate_limit_login_per_minute: int = Field(default=5, description="Login attempts")
    rate_limit_chat_per_minute: int = Field(default=20, description="Chat requests")
    rate_limit_upload_per_minute: int = Field(default=10, description="Document uploads")

    # Monitoring
    environment: str = Field(default="development", description="development or production")
    log_level: str = Field(default="INFO", description="Log level")
    alerting_enabled: bool = Field(
        default=True, description="Capture errors and send grouped SMTP alerts"
    )
    alert_throttle_seconds: int = Field(
        default=900, description="Deduplication window of an alert fingerprint, in seconds"
    )

    # AI budget: operator-tunable estimates; the reservation mechanism stays
    # fail-closed whatever their values (docs/adr/0001).
    daily_budget_eur: float = Field(default=20.0, description="Daily AI spend cap in euros")
    llm_price_table: dict[str, dict[str, float]] = Field(
        default={
            "mistral-small-latest": {"input": 0.10, "output": 0.30},
            "ministral-14b-latest": {"input": 0.20, "output": 0.20},
            "mistral-embed": {"input": 0.10, "output": 0.0},
        },
        description="Euro price per million tokens, per model (input/output)",
    )
    budget_reservation_chat_eur: float = Field(
        default=0.01, description="Budget reserved before a chat call"
    )
    budget_reservation_embedding_eur: float = Field(
        default=0.001, description="Budget reserved before an embedding call"
    )

    # RAG debug logging
    rag_debug_enabled: bool = Field(default=False, description="Log RAG interactions in detail")
    rag_debug_log_prompts: bool = Field(default=True, description="Log the full LLM prompts")
    rag_debug_log_context: bool = Field(default=True, description="Log the assembled context")
    rag_debug_log_responses: bool = Field(default=True, description="Log the full LLM answers")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def ensure_directories(self) -> None:
        """Create the runtime data directories."""
        for directory in (
            Path(self.data_dir),
            Path(self.upload_dir),
            Path(self.database_url.replace("sqlite:///", "")).parent,
            Path(self.faiss_index_path).parent,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()

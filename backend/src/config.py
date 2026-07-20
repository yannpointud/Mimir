"""
Centralized configuration for Mimir
Uses Pydantic for validation and type safety
"""

from pydantic import Field
from pydantic_settings import BaseSettings
from typing import Optional, Dict  # noqa: F401
import os
from pathlib import Path


class Settings(BaseSettings):
    """Main configuration for the Mimir application"""
    
    # API Configuration
    api_version: str = Field(default="v1", description="Version de l'API")
    api_host: str = Field(default="0.0.0.0", description="Host de l'API")
    api_port: int = Field(default=8000, description="Port de l'API")
    
    # Database Configuration
    database_url: str = Field(
        default="sqlite:///./data/sqlite/mimir.db",
        description="URL de connexion à la base de données"
    )
    sqlite_wal_mode: bool = Field(
        default=True,
        description="Active le mode WAL pour SQLite (meilleures performances concurrentes)"
    )
    
    # LLM Configuration
    llm_provider: str = Field(default="mistral", description="Fournisseur LLM")
    mistral_api_key: str = Field(default="", description="Clé API Mistral (requis pour le chat)")
    mistral_model: str = Field(
        default="mistral-small-latest",
        description="Modèle Mistral pour la génération"
    )
    mistral_embedding_model: str = Field(
        default="mistral-embed",
        description="Modèle Mistral pour les embeddings"
    )
    embedding_batch_size: int = Field(
        default=50,
        description="Nombre maximum de textes par batch pour la génération d'embeddings"
    )
    
    # Vector Store Configuration
    vector_store_type: str = Field(default="faiss", description="Type de vector store")
    faiss_index_path: str = Field(
        default="./data/faiss/index.bin",
        description="Chemin vers l'index FAISS"
    )
    faiss_metadata_path: str = Field(
        default="./data/faiss/metadata.json",
        description="Chemin vers les métadonnées FAISS"
    )
    faiss_max_backups: int = Field(
        default=4,
        description="Maximum number of FAISS backup files to keep (rotation)"
    )
    embedding_dimension: int = Field(
        default=1024,
        description="Dimension des vecteurs d'embedding"
    )

    # Sources and Confidence Configuration
    similarity_threshold: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Seuil minimal de similarité pour considérer une source pertinente"
    )
    max_sources: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Nombre maximum de sources à retourner"
    )
    min_sources: int = Field(
        default=1,
        ge=1,
        le=10,
        description="Nombre minimum de sources à retourner si disponibles"
    )
    confidence_algorithm: str = Field(
        default="weighted",
        description="Algorithme de calcul de confiance: 'simple' ou 'weighted'"
    )
    filename_boost: float = Field(
        default=1.3,
        gt=0.0,
        le=2.0,
        description="Facteur de boost pour la similarité avec le nom du fichier"
    )
    dynamic_filter_percentage: float = Field(
        default=0.15,
        ge=0.0,
        le=1.0,
        description="Pourcentage d'écart maximum par rapport au meilleur score pour filtrage dynamique"
    )

    # Hybrid Search / RRF Configuration (feature flags — the cosine semantics of
    # similarity_threshold above are left untouched; dense-only stays byte-identical
    # when hybrid_search_enabled is False, so this flag is fully reversible).
    # ADOPTED (06-07): measured on the frozen golden set, hybrid BM25+RRF beat
    # dense-only by +17.8% context_recall (0.679->0.800) and +14.2% context_precision
    # (0.579->0.661), NaN 0%, with NO exact-term regression -> flipped to True.
    hybrid_search_enabled: bool = Field(
        default=True,
        description="Active la recherche hybride BM25 + dense (RRF). Adopté en 06-07 (gain RAGAS net et marqué, sans régression terme-exact) ; repli dense-only sûr si mis à False"
    )
    rrf_k: int = Field(
        default=60,
        ge=1,
        description="Constante k de la Reciprocal Rank Fusion (fixée à 60 par le ROADMAP)"
    )
    rrf_score_threshold: float = Field(
        default=0.015,
        ge=0.0,
        description="Seuil de score RRF dédié au mode hybride (0.015 validé empiriquement en 06-07 : contextes non vides + recall +18% sur le golden set)"
    )
    bm25_index_path: str = Field(
        default="./data/bm25/index",
        description="Chemin de persistance de l'index lexical BM25"
    )

    # Structure-aware Chunking (RAG-05 — feature flag, reversible). ADOPTED (07-06):
    # default flipped False->True on a measured net RAGAS gain over the frozen corpus
    # (context_precision +7.3%, context_recall +3.4%, 60-question golden set). Reversible
    # to the byte-identical current splitter by setting this back to False.
    structure_aware_chunking_enabled: bool = Field(
        default=True,
        description="Active le chunking structure-aware (métadonnée section_title, découpe alignée sur les titres). Défaut True : adopté sur delta RAGAS net (precision +7.3%, recall +3.4%) mesuré en 07-06"
    )

    # Filename Pre-inclusion (fuzzy matching)
    filename_pre_inclusion: bool = Field(
        default=True,
        description="Active la pré-inclusion des chunks basée sur fuzzy matching du filename"
    )
    filename_fuzzy_threshold: int = Field(
        default=70,
        ge=0,
        le=100,
        description="Seuil minimum de fuzzy matching (0-100) pour pré-inclure un document"
    )

    # Ingestion Configuration
    ingestion_queue_max_size: int = Field(
        default=50000,
        ge=1,
        le=100000,
        description="Taille maximale de la queue d'ingestion (protection DoS, ~0.35MB RAM par 1000 docs)"
    )
    ingestion_max_retries: int = Field(
        default=5,
        ge=0,
        le=20,
        description="Nombre maximum de re-tentatives par document en cas d'échec d'ingestion (ex. 429 Mistral)"
    )
    ingestion_retry_base_delay: float = Field(
        default=2.0,
        ge=0.0,
        le=60.0,
        description="Délai de base (s) du backoff exponentiel avant re-tentative d'un document échoué"
    )
    ingestion_retry_max_delay: float = Field(
        default=60.0,
        ge=1.0,
        le=600.0,
        description="Plafond (s) du backoff exponentiel entre deux re-tentatives d'ingestion"
    )
    max_chunk_size: int = Field(
        default=1000,
        description="Taille maximale des chunks en caractères"
    )
    chunk_overlap: int = Field(
        default=200,
        description="Chevauchement entre chunks en caractères"
    )
    max_chunks_per_doc: int = Field(
        default=2000,
        description="Nombre maximum de chunks par document"
    )
    max_document_size_mb: int = Field(
        default=100,
        description="Taille maximale d'un document en MB"
    )
    max_file_size_mb: int = Field(
        default=100,
        description="Taille maximale d'un fichier uploadé en MB"
    )
    supported_file_extensions: set = Field(
        default={".pdf", ".docx", ".txt", ".md"},
        description="Extensions de fichiers supportées"
    )
    
    # File System Configuration
    data_dir: str = Field(default="./data", description="Répertoire principal des données")
    upload_dir: str = Field(
        default="./data/documents",
        description="Répertoire pour les uploads"
    )
    watch_folder: str = Field(
        default="./data/watch",
        description="Dossier surveillé pour ingestion automatique"
    )
    watch_enabled: bool = Field(
        default=True,
        description="Active la surveillance de dossier"
    )
    sqlite_backup_dir: str = Field(
        default="./data/backups",
        description="Répertoire des sauvegardes SQLite (rotation)"
    )
    sqlite_backup_max_count: int = Field(
        default=14,
        description="Nombre de sauvegardes SQLite conservées (rotation)"
    )

    # Cache Configuration
    cache_enabled: bool = Field(default=True, description="Active le cache LRU")
    cache_max_size: int = Field(
        default=100,
        description="Nombre maximum d'entrées dans le cache"
    )
    cache_ttl: int = Field(
        default=3600,
        description="TTL du cache en secondes"
    )
    
    # Email Configuration (for escalation)
    smtp_host: str = Field(default="", description="Host SMTP pour emails d'escalade")
    smtp_port: int = Field(default=587, description="Port SMTP")
    smtp_user: str = Field(default="", description="Utilisateur SMTP")
    smtp_password: str = Field(default="", description="Mot de passe SMTP")
    smtp_use_tls: bool = Field(default=True, description="Utilise TLS pour SMTP")
    escalation_email: str = Field(
        default="",
        description="Email de destination pour l'escalade"
    )
    
    # Security Configuration
    jwt_secret_key: str = Field(
        default="dev-secret-key-change-in-production-minimum-32-chars-long",
        description="Clé secrète JWT (obligatoire)"
    )
    jwt_algorithm: str = Field(default="HS256", description="Algorithme JWT")
    jwt_expiration_hours: int = Field(
        default=2,
        description="Durée d'expiration des tokens JWT en heures"
    )
    admin_password_hash: str = Field(
        default="$2b$12$Kc32f7ibhcSNTkn/UkFOke32Q2A3XLNIG6RliCTq9.SnTj1/D2Eiy",
        description="Hash bcrypt du mot de passe admin (override via .env ADMIN_PASSWORD_HASH)"
    )
    admin_password: str = Field(
        default="",
        description=(
            "Mot de passe admin en clair, haché au démarrage vers admin_password_hash "
            "(ADMIN_PASSWORD). Prioritaire sur ADMIN_PASSWORD_HASH. Destiné aux "
            "déploiements conteneurisés, où pré-calculer un hash à la main n'est pas "
            "praticable ; vide par défaut"
        )
    )
    trusted_hosts: str = Field(
        default="*",
        description="Hôtes autorisés (Host header) séparés par des virgules ; '*' désactive le filtre. En production, restreindre à vos domaines (ex: mimir.example.com,localhost)"
    )

    # Rate Limiting Configuration
    rate_limit_enabled: bool = Field(
        default=True,
        description="Active la limitation de débit"
    )
    rate_limit_per_minute: int = Field(
        default=20,
        description="Nombre maximum de requêtes par minute par IP"
    )
    rate_limit_login_per_minute: int = Field(
        default=5,
        description="Nombre maximum de tentatives de connexion par minute et par client"
    )
    rate_limit_chat_per_minute: int = Field(
        default=20,
        description="Nombre maximum de requêtes chat par minute et par client"
    )
    rate_limit_upload_per_minute: int = Field(
        default=10,
        description="Nombre maximum d'uploads de documents par minute et par client"
    )

    # Monitoring Configuration
    environment: str = Field(default="development", description="Environnement d'exécution")
    log_level: str = Field(default="INFO", description="Niveau de log")
    log_format: str = Field(default="json", description="Format des logs")
    health_check_interval: int = Field(
        default=60,
        description="Intervalle des health checks en secondes"
    )
    alerting_enabled: bool = Field(
        default=True,
        description="Active la capture d'erreurs et l'alerte SMTP groupée (OPS-05)"
    )
    alert_throttle_seconds: int = Field(
        default=900,
        description="Fenêtre de dédup des alertes SMTP par fingerprint, en secondes"
    )

    # Performance Configuration
    max_concurrent_requests: int = Field(
        default=50,
        description="Nombre maximum de requêtes simultanées"
    )
    request_timeout: int = Field(
        default=30,
        description="Timeout des requêtes en secondes"
    )

    # Cost/Budget Configuration
    # Values below are LOW-MEDIUM confidence defaults (see 03-RESEARCH.md Assumptions
    # Log A1): they are operator-configurable via .env and never hardcoded elsewhere
    # in business logic. The fail-closed reservation mechanism does not depend on
    # these exact values being correct.
    daily_budget_eur: float = Field(
        default=20.0,
        description="Plafond quotidien de dépense IA en euros"
    )
    llm_price_table: Dict[str, Dict[str, float]] = Field(
        default={
            "mistral-small-latest": {"input": 0.10, "output": 0.30},
            "mistral-embed": {"input": 0.10, "output": 0.0},
        },
        description="Grille de prix en euros par million de tokens, par modèle (input/output)"
    )
    budget_reservation_chat_eur: float = Field(
        default=0.01,
        description="Estimation forfaitaire de réservation budgétaire pour un appel chat"
    )
    budget_reservation_embedding_eur: float = Field(
        default=0.001,
        description="Estimation forfaitaire de réservation budgétaire pour un appel embedding"
    )

    # RAG Debug Configuration
    rag_debug_enabled: bool = Field(
        default=False,
        description="Active le logging détaillé des interactions RAG"
    )
    rag_debug_log_prompts: bool = Field(
        default=True,
        description="Log les prompts complets envoyés au LLM"
    )
    rag_debug_log_context: bool = Field(
        default=True,
        description="Log le contexte assemblé pour le RAG"
    )
    rag_debug_log_responses: bool = Field(
        default=True,
        description="Log les réponses complètes du LLM"
    )
    
    class Config:
        env_file = ".env"
        case_sensitive = False
        
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Create required directories
        self._ensure_directories()
    
    def _ensure_directories(self):
        """Create required directories if they do not exist"""
        directories = [
            self.data_dir,
            self.upload_dir,
            self.watch_folder,
            Path(self.database_url.replace("sqlite:///", "")).parent,
            Path(self.faiss_index_path).parent,
            Path(self.data_dir).parent / "logs"  # logs in the parent of data_dir
        ]
        
        for directory in directories:
            Path(directory).mkdir(parents=True, exist_ok=True)
    
    @property
    def database_url_sync(self) -> str:
        """Database URL for synchronous SQLAlchemy"""
        return self.database_url
    
    @property
    def is_production(self) -> bool:
        """Determine if we are in a production environment"""
        return self.environment.lower() == "production"


# Global singleton configuration instance.
# Fail fast on configuration errors: a malformed .env or out-of-range value
# must abort startup loudly instead of surfacing much later as an unrelated
# AttributeError on a None settings object.
try:
    settings = Settings()
except Exception as config_error:
    import sys

    if "pytest" in sys.modules or os.environ.get("PYTEST_CURRENT_TEST"):
        # Under pytest, keep the historical behavior: test fixtures
        # override settings, so a load failure must not break collection.
        settings = None
    else:
        import logging

        logging.getLogger(__name__).critical(
            f"Failed to load configuration: {config_error}"
        )
        raise
"""
Tests pour le module database/connection.py
Couvre la gestion de connexion, configuration SQLite et pattern Singleton
"""

import contextlib
import sqlite3

import pytest
from unittest.mock import Mock, patch

from sqlalchemy.exc import OperationalError

from backend.src.database.connection import (
    DatabaseManager,
    configure_sqlite_performance,
    db_manager,
    get_db_session,
    get_db_manager,
    init_database,
    reset_database,
)


class TestConfigureSqlitePerformance:
    """Tests pour la fonction configure_sqlite_performance"""

    def test_configure_sqlite_performance_with_wal_mode(self):
        """Test configuration SQLite avec mode WAL activé"""
        # Mock de la connexion SQLite
        mock_connection = Mock(spec=sqlite3.Connection)
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        # Mock des settings avec WAL activé
        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings.sqlite_wal_mode = True

            configure_sqlite_performance(mock_connection, None)

            # Vérifier que toutes les optimisations sont appliquées
            expected_calls = [
                "PRAGMA journal_mode=WAL",
                "PRAGMA synchronous=NORMAL",
                "PRAGMA cache_size=10000",
                "PRAGMA temp_store=MEMORY",
                "PRAGMA mmap_size=268435456",
                "PRAGMA busy_timeout=30000",
            ]

            actual_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
            for expected in expected_calls:
                assert expected in actual_calls

    def test_configure_sqlite_performance_without_wal_mode(self):
        """Test configuration SQLite sans mode WAL"""
        mock_connection = Mock(spec=sqlite3.Connection)
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings.sqlite_wal_mode = False

            configure_sqlite_performance(mock_connection, None)

            # Vérifier que WAL n'est pas activé mais autres optimisations oui
            actual_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
            assert "PRAGMA journal_mode=WAL" not in actual_calls
            assert "PRAGMA synchronous=NORMAL" in actual_calls

    def test_configure_sqlite_performance_no_settings(self):
        """Test configuration SQLite sans settings configuré"""
        mock_connection = Mock(spec=sqlite3.Connection)
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        with patch("backend.src.database.connection.config.settings", None):
            configure_sqlite_performance(mock_connection, None)

            # Vérifier que les optimisations de base sont appliquées
            actual_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
            assert "PRAGMA synchronous=NORMAL" in actual_calls

    def test_configure_sqlite_performance_non_sqlite_connection(self):
        """Test avec une connexion non-SQLite"""
        mock_connection = Mock()  # Pas de spec=sqlite3.Connection

        # Ne devrait pas lever d'erreur
        configure_sqlite_performance(mock_connection, None)


class TestDatabaseManager:
    """Tests pour la classe DatabaseManager"""

    def setup_method(self):
        """Reset singleton pour chaque test"""
        DatabaseManager._instance = None
        DatabaseManager._engine = None
        DatabaseManager._session_factory = None

    def test_singleton_pattern(self):
        """Test que DatabaseManager suit le pattern Singleton"""
        manager1 = DatabaseManager()
        manager2 = DatabaseManager()

        assert manager1 is manager2
        assert isinstance(manager1, DatabaseManager)

    @patch("backend.src.database.connection.create_engine")
    @patch("backend.src.database.connection.sessionmaker")
    @patch("backend.src.database.connection.event.listen")
    def test_initialize_database_success(self, mock_listen, mock_sessionmaker, mock_create_engine):
        """Test initialisation réussie de la base de données"""
        mock_engine = Mock()
        mock_create_engine.return_value = mock_engine
        mock_session_factory = Mock()
        mock_sessionmaker.return_value = mock_session_factory

        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings.database_url_sync = "sqlite:///test.db"

            DatabaseManager()

            # Vérifier la création du moteur
            mock_create_engine.assert_called_once()
            create_args = mock_create_engine.call_args
            assert create_args[0][0] == "sqlite:///test.db"

            # Vérifier que listen a été appelé (peut être appelé plusieurs fois pour différents événements)
            # Vérifier qu'au moins un appel contient configure_sqlite_performance
            configure_calls = [
                call
                for call in mock_listen.call_args_list
                if len(call[0]) >= 3 and call[0][2].__name__ == "configure_sqlite_performance"
            ]
            assert len(configure_calls) >= 1, "configure_sqlite_performance should be registered"

            # Vérifier la création de la session factory
            mock_sessionmaker.assert_called_once()

    @patch("backend.src.database.connection.create_engine")
    def test_initialize_database_failure(self, mock_create_engine):
        """Test échec d'initialisation de la base de données"""
        mock_create_engine.side_effect = Exception("Database connection failed")

        with pytest.raises(Exception, match="Database connection failed"):
            DatabaseManager()

    def test_engine_property_lazy_initialization(self):
        """Test initialisation paresseuse du moteur"""
        manager = DatabaseManager()

        with patch.object(manager, "_initialize_database") as mock_init:
            manager._engine = None

            # Accès à la propriété engine
            _ = manager.engine

            mock_init.assert_called_once()

    def test_get_session_lazy_initialization(self):
        """Test initialisation paresseuse pour get_session"""
        manager = DatabaseManager()
        mock_session_factory = Mock()

        with patch.object(manager, "_initialize_database") as mock_init:
            # Setup mock to simulate lazy initialization
            def side_effect():
                manager._session_factory = mock_session_factory

            mock_init.side_effect = side_effect

            manager._session_factory = None

            result = manager.get_session()

            assert result is mock_session_factory.return_value
            mock_init.assert_called_once()

    def test_get_session_context_success(self):
        """Test context manager de session réussi"""
        manager = DatabaseManager()
        mock_session = Mock()

        with patch.object(manager, "get_session", return_value=mock_session):
            with manager.get_session_context() as session:
                assert session is mock_session
                # Simuler une opération
                session.query(Mock())

            # Vérifier commit et close appelés
            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_session_context_with_exception(self):
        """Test context manager de session avec exception"""
        manager = DatabaseManager()
        mock_session = Mock()

        with patch.object(manager, "get_session", return_value=mock_session):
            with pytest.raises(ValueError), manager.get_session_context():
                raise ValueError("Test exception")

            # Vérifier rollback et close appelés
            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()

    @patch("backend.src.database.connection.Base.metadata.create_all")
    def test_create_tables_success(self, mock_create_all):
        """Test création réussie des tables"""
        manager = DatabaseManager()
        mock_engine = Mock()

        with patch.object(manager, "_engine", mock_engine):
            manager.create_tables()

            mock_create_all.assert_called_once_with(bind=mock_engine)

    @patch("backend.src.database.connection.Base.metadata.create_all")
    def test_create_tables_failure(self, mock_create_all):
        """Test échec de création des tables"""
        mock_create_all.side_effect = Exception("Table creation failed")

        manager = DatabaseManager()

        with pytest.raises(Exception, match="Table creation failed"):
            manager.create_tables()

    @patch("backend.src.database.connection.Base.metadata.drop_all")
    def test_drop_tables_success(self, mock_drop_all):
        """Test suppression réussie des tables"""
        manager = DatabaseManager()
        mock_engine = Mock()

        with patch.object(manager, "_engine", mock_engine):
            manager.drop_tables()

            mock_drop_all.assert_called_once_with(bind=mock_engine)

    def test_health_check_success(self):
        """Test health check réussi"""
        manager = DatabaseManager()
        mock_session = Mock()

        with patch.object(manager, "get_session_context") as mock_context:
            mock_context.return_value.__enter__.return_value = mock_session
            mock_context.return_value.__exit__.return_value = None

            result = manager.health_check()

            assert result is True
            mock_session.execute.assert_called_once()

    def test_health_check_failure(self):
        """Test health check échoué"""
        manager = DatabaseManager()

        with patch.object(manager, "get_session_context") as mock_context:
            mock_context.side_effect = OperationalError(
                "SELECT 1", {}, Exception("Database unreachable")
            )

            result = manager.health_check()

            assert result is False


class TestUtilityFunctions:
    """Tests pour les fonctions utilitaires"""

    def test_get_db_session_success(self):
        """Test get_db_session avec succès"""
        mock_session = Mock()

        with patch.object(db_manager, "get_session", return_value=mock_session):
            # Simuler l'usage du générateur
            session_gen = get_db_session()
            session = next(session_gen)

            assert session is mock_session

            # Fermer le générateur normalement
            with contextlib.suppress(StopIteration):
                next(session_gen)

            mock_session.commit.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_db_session_with_exception(self):
        """Test get_db_session avec exception"""
        mock_session = Mock()

        with patch.object(db_manager, "get_session", return_value=mock_session):
            session_gen = get_db_session()
            next(session_gen)

            # Simuler une exception
            with contextlib.suppress(ValueError):
                session_gen.throw(ValueError("Test error"))

            mock_session.rollback.assert_called_once()
            mock_session.close.assert_called_once()

    def test_get_db_manager(self):
        """Test get_db_manager retourne l'instance globale"""
        result = get_db_manager()
        assert result is db_manager


class TestInitializationFunctions:
    """Tests pour les fonctions d'initialisation"""

    @patch.object(db_manager, "create_tables")
    @patch.object(db_manager, "health_check")
    def test_init_database_success(self, mock_health_check, mock_create_tables):
        """Test initialisation réussie de la base de données"""
        mock_health_check.return_value = True

        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings._ensure_directories = Mock()

            init_database()

            mock_settings._ensure_directories.assert_called_once()
            mock_create_tables.assert_called_once()
            mock_health_check.assert_called_once()

    @patch.object(db_manager, "create_tables")
    @patch.object(db_manager, "health_check")
    def test_init_database_health_check_failure(self, mock_health_check, mock_create_tables):
        """Test initialisation avec échec du health check"""
        mock_health_check.return_value = False

        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings._ensure_directories = Mock()

            with pytest.raises(RuntimeError, match="Database health check failed"):
                init_database()

    def test_init_database_no_settings(self):
        """Test initialisation sans settings configuré"""
        with (
            patch("backend.src.database.connection.config.settings", None),
            patch.object(db_manager, "create_tables"),
            patch.object(db_manager, "health_check", return_value=True),
        ):
            # Ne devrait pas lever d'erreur
            init_database()

    @patch.object(db_manager, "drop_tables")
    @patch.object(db_manager, "create_tables")
    def test_reset_database_success(self, mock_create_tables, mock_drop_tables):
        """Test reset réussi de la base de données"""
        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings.is_production = False

            reset_database()

            mock_drop_tables.assert_called_once()
            mock_create_tables.assert_called_once()

    def test_reset_database_production_protection(self):
        """Test protection contre reset en production"""
        with patch("backend.src.database.connection.config.settings") as mock_settings:
            mock_settings.is_production = True

            with pytest.raises(RuntimeError, match="Database reset not allowed in production"):
                reset_database()

    def test_reset_database_no_settings(self):
        """Test reset sans settings configuré"""
        with (
            patch("backend.src.database.connection.config.settings", None),
            patch.object(db_manager, "drop_tables"),
            patch.object(db_manager, "create_tables"),
        ):
            # Ne devrait pas lever d'erreur
            reset_database()

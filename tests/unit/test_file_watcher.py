"""
Tests unitaires pour le module file_watcher/watcher.py

Ces tests couvrent la surveillance des fichiers et la gestion des événements du système de fichiers.
"""

import os
import time
import tempfile
import threading
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import pytest

from backend.src.file_watcher.watcher import DocumentFileHandler, FileWatcher


class TestDocumentFileHandler:
    """Tests pour DocumentFileHandler."""

    def test_init(self):
        """Test d'initialisation de DocumentFileHandler."""
        extensions = {'.pdf', '.docx', '.txt'}
        on_file_added = Mock()
        on_file_modified = Mock()

        handler = DocumentFileHandler(
            supported_extensions=extensions,
            on_file_added=on_file_added,
            on_file_modified=on_file_modified,
            ignore_hidden=True,
            ignore_temp=True
        )

        assert handler.supported_extensions == {'.pdf', '.docx', '.txt'}
        assert handler.on_file_added == on_file_added
        assert handler.on_file_modified == on_file_modified
        assert handler.ignore_hidden is True
        assert handler.ignore_temp is True
        assert handler._recently_processed == {}
        assert isinstance(handler._lock, type(threading.Lock()))

    def test_init_case_insensitive_extensions(self):
        """Test que les extensions sont converties en minuscules."""
        extensions = {'.PDF', '.DocX', '.TXT'}
        on_file_added = Mock()

        handler = DocumentFileHandler(extensions, on_file_added)

        assert handler.supported_extensions == {'.pdf', '.docx', '.txt'}

    def test_should_ignore_file_hidden(self):
        """Test d'ignorance des fichiers cachés."""
        handler = DocumentFileHandler({'.txt'}, Mock(), ignore_hidden=True)

        assert handler._should_ignore_file('/path/to/.hidden_file.txt') is True
        assert handler._should_ignore_file('/path/to/normal_file.txt') is False

    def test_should_ignore_file_hidden_disabled(self):
        """Test avec ignore_hidden désactivé."""
        handler = DocumentFileHandler({'.txt'}, Mock(), ignore_hidden=False)

        assert handler._should_ignore_file('/path/to/.hidden_file.txt') is False
        assert handler._should_ignore_file('/path/to/normal_file.txt') is False

    def test_should_ignore_file_temp_files(self):
        """Test d'ignorance des fichiers temporaires."""
        handler = DocumentFileHandler({'.docx', '.tmp'}, Mock(), ignore_temp=True)

        # Microsoft Office temp files
        assert handler._should_ignore_file('/path/to/~$document.docx') is True
        assert handler._should_ignore_file('/path/to/file.tmp') is True
        assert handler._should_ignore_file('/path/to/file.temp') is True
        assert handler._should_ignore_file('/path/to/file.part') is True
        assert handler._should_ignore_file('/path/to/file.crdownload') is True

        # Normal files should not be ignored
        assert handler._should_ignore_file('/path/to/document.docx') is False

    def test_should_ignore_file_temp_disabled(self):
        """Test avec ignore_temp désactivé."""
        handler = DocumentFileHandler({'.tmp'}, Mock(), ignore_temp=False)

        assert handler._should_ignore_file('/path/to/file.tmp') is False

    def test_should_ignore_file_unsupported_extension(self):
        """Test d'ignorance des extensions non supportées."""
        handler = DocumentFileHandler({'.pdf', '.docx'}, Mock())

        assert handler._should_ignore_file('/path/to/file.txt') is True
        assert handler._should_ignore_file('/path/to/file.pdf') is False
        assert handler._should_ignore_file('/path/to/file.DOCX') is False  # Case insensitive

    def test_should_ignore_file_no_extension(self):
        """Test avec des fichiers sans extension."""
        handler = DocumentFileHandler({'.pdf'}, Mock())

        assert handler._should_ignore_file('/path/to/file_without_extension') is True

    def test_is_recently_processed_first_time(self):
        """Test d'un fichier traité pour la première fois."""
        handler = DocumentFileHandler({'.txt'}, Mock())

        is_recent = handler._is_recently_processed('/path/to/file.txt', 'created')

        assert is_recent is False
        assert '/path/to/file.txt:created' in handler._recently_processed

    def test_is_recently_processed_duplicate(self):
        """Test de détection de duplication."""
        handler = DocumentFileHandler({'.txt'}, Mock())

        # Premier appel
        is_recent1 = handler._is_recently_processed('/path/to/file.txt', 'created')
        # Deuxième appel immédiat
        is_recent2 = handler._is_recently_processed('/path/to/file.txt', 'created')

        assert is_recent1 is False
        assert is_recent2 is True

    def test_is_recently_processed_cleanup(self):
        """Test du nettoyage des entrées anciennes."""
        handler = DocumentFileHandler({'.txt'}, Mock())

        # Ajouter une entrée ancienne manuellement
        old_time = time.time() - 10  # 10 secondes dans le passé
        handler._recently_processed['/old/file.txt:created'] = old_time

        # Traiter un nouveau fichier
        handler._is_recently_processed('/new/file.txt', 'created')

        # L'ancienne entrée devrait être supprimée
        assert '/old/file.txt:created' not in handler._recently_processed
        assert '/new/file.txt:created' in handler._recently_processed

    def test_is_recently_processed_different_events(self):
        """Test que différents types d'événements sont traités séparément."""
        handler = DocumentFileHandler({'.txt'}, Mock())

        is_recent_created = handler._is_recently_processed('/path/file.txt', 'created')
        is_recent_modified = handler._is_recently_processed('/path/file.txt', 'modified')

        assert is_recent_created is False
        assert is_recent_modified is False

    @patch('backend.src.file_watcher.watcher.time.sleep')
    @patch('backend.src.file_watcher.watcher.os.path.getsize')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_wait_for_file_stability_stable_file(self, mock_exists, mock_getsize, mock_sleep):
        """Test d'attente de stabilité pour un fichier stable."""
        mock_exists.return_value = True
        mock_getsize.side_effect = [100, 100]  # Taille constante

        handler = DocumentFileHandler({'.txt'}, Mock())
        handler._wait_for_file_stability('/path/file.txt')

        mock_sleep.assert_called_once_with(0.5)

    @patch('backend.src.file_watcher.watcher.time.sleep')
    @patch('backend.src.file_watcher.watcher.os.path.getsize')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_wait_for_file_stability_growing_file(self, mock_exists, mock_getsize, mock_sleep):
        """Test d'attente pour un fichier en cours de croissance."""
        mock_exists.return_value = True
        mock_getsize.side_effect = [100, 150, 200, 200]  # Fichier qui grandit puis se stabilise

        handler = DocumentFileHandler({'.txt'}, Mock())
        handler._wait_for_file_stability('/path/file.txt', max_wait=3)

        # Devrait attendre jusqu'à stabilisation
        assert mock_sleep.call_count >= 2

    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_wait_for_file_stability_nonexistent_file(self, mock_exists):
        """Test d'attente pour un fichier inexistant."""
        mock_exists.return_value = False

        handler = DocumentFileHandler({'.txt'}, Mock())
        handler._wait_for_file_stability('/path/nonexistent.txt')

        # Devrait retourner immédiatement

    @patch('backend.src.file_watcher.watcher.os.path.getsize')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_wait_for_file_stability_os_error(self, mock_exists, mock_getsize):
        """Test de gestion d'erreur OS."""
        mock_exists.return_value = True
        mock_getsize.side_effect = OSError("Permission denied")

        handler = DocumentFileHandler({'.txt'}, Mock())
        # Ne devrait pas lever d'exception
        handler._wait_for_file_stability('/path/file.txt')

    @patch.object(DocumentFileHandler, '_wait_for_file_stability')
    @patch.object(DocumentFileHandler, '_is_recently_processed')
    @patch.object(DocumentFileHandler, '_should_ignore_file')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_on_created_success(self, mock_exists, mock_ignore, mock_recent, mock_wait):
        """Test de gestion réussie d'un fichier créé."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = '/path/file.txt'

        mock_ignore.return_value = False
        mock_recent.return_value = False
        mock_exists.return_value = True

        on_file_added = Mock()
        handler = DocumentFileHandler({'.txt'}, on_file_added)

        handler.on_created(mock_event)

        mock_wait.assert_called_once_with('/path/file.txt')
        on_file_added.assert_called_once_with('/path/file.txt')

    def test_on_created_directory_event(self):
        """Test d'ignorance des événements de répertoire."""
        mock_event = Mock()
        mock_event.is_directory = True

        on_file_added = Mock()
        handler = DocumentFileHandler({'.txt'}, on_file_added)

        handler.on_created(mock_event)

        on_file_added.assert_not_called()

    @patch.object(DocumentFileHandler, '_should_ignore_file')
    def test_on_created_ignored_file(self, mock_ignore):
        """Test d'ignorance de fichier selon les critères."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = '/path/.hidden.txt'

        mock_ignore.return_value = True

        on_file_added = Mock()
        handler = DocumentFileHandler({'.txt'}, on_file_added)

        handler.on_created(mock_event)

        on_file_added.assert_not_called()

    @patch.object(DocumentFileHandler, '_is_recently_processed')
    @patch.object(DocumentFileHandler, '_should_ignore_file')
    def test_on_created_recently_processed(self, mock_ignore, mock_recent):
        """Test d'ignorance de fichier récemment traité."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = '/path/file.txt'

        mock_ignore.return_value = False
        mock_recent.return_value = True

        on_file_added = Mock()
        handler = DocumentFileHandler({'.txt'}, on_file_added)

        handler.on_created(mock_event)

        on_file_added.assert_not_called()

    @patch.object(DocumentFileHandler, '_wait_for_file_stability')
    @patch.object(DocumentFileHandler, '_is_recently_processed')
    @patch.object(DocumentFileHandler, '_should_ignore_file')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_on_created_file_deleted(self, mock_exists, mock_ignore, mock_recent, mock_wait):
        """Test avec fichier supprimé avant traitement."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = '/path/file.txt'

        mock_ignore.return_value = False
        mock_recent.return_value = False
        mock_exists.return_value = False  # Fichier supprimé

        on_file_added = Mock()
        handler = DocumentFileHandler({'.txt'}, on_file_added)

        handler.on_created(mock_event)

        on_file_added.assert_not_called()

    @patch.object(DocumentFileHandler, '_wait_for_file_stability')
    @patch.object(DocumentFileHandler, '_is_recently_processed')
    @patch.object(DocumentFileHandler, '_should_ignore_file')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_on_created_callback_error(self, mock_exists, mock_ignore, mock_recent, mock_wait):
        """Test de gestion d'erreur dans le callback."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = '/path/file.txt'

        mock_ignore.return_value = False
        mock_recent.return_value = False
        mock_exists.return_value = True

        on_file_added = Mock(side_effect=Exception("Callback error"))
        handler = DocumentFileHandler({'.txt'}, on_file_added)

        # Ne devrait pas lever d'exception
        handler.on_created(mock_event)

        on_file_added.assert_called_once()

    def test_on_modified_no_callback(self):
        """Test de modification sans callback défini."""
        mock_event = Mock()
        mock_event.is_directory = False

        handler = DocumentFileHandler({'.txt'}, Mock(), on_file_modified=None)

        handler.on_modified(mock_event)

        # Devrait retourner sans traitement

    @patch.object(DocumentFileHandler, '_wait_for_file_stability')
    @patch.object(DocumentFileHandler, '_is_recently_processed')
    @patch.object(DocumentFileHandler, '_should_ignore_file')
    @patch('backend.src.file_watcher.watcher.os.path.exists')
    def test_on_modified_success(self, mock_exists, mock_ignore, mock_recent, mock_wait):
        """Test de gestion réussie d'un fichier modifié."""
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = '/path/file.txt'

        mock_ignore.return_value = False
        mock_recent.return_value = False
        mock_exists.return_value = True

        on_file_modified = Mock()
        handler = DocumentFileHandler({'.txt'}, Mock(), on_file_modified=on_file_modified)

        handler.on_modified(mock_event)

        on_file_modified.assert_called_once_with('/path/file.txt')


class TestFileWatcher:
    """Tests pour FileWatcher."""

    @pytest.fixture
    def temp_dir(self):
        """Fixture pour créer un répertoire temporaire."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    def test_init(self, temp_dir):
        """Test d'initialisation de FileWatcher."""
        watch_dirs = [temp_dir]
        extensions = {'.pdf', '.txt'}
        on_file_added = Mock()
        on_file_modified = Mock()

        watcher = FileWatcher(
            watch_directories=watch_dirs,
            supported_extensions=extensions,
            on_file_added=on_file_added,
            on_file_modified=on_file_modified,
            recursive=True
        )

        assert len(watcher.watch_directories) == 1
        assert watcher.watch_directories[0].name == Path(temp_dir).name
        assert watcher.supported_extensions == extensions
        assert watcher.recursive is True
        assert watcher.is_running is False
        assert isinstance(watcher.handler, DocumentFileHandler)
        assert watcher.stats["files_processed"] == 0

    @patch('backend.src.file_watcher.watcher.Observer')
    def test_start_success(self, mock_observer_class, temp_dir):
        """Test de démarrage réussi du FileWatcher."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        result = watcher.start()

        assert result is True
        assert watcher.is_running is True
        assert watcher.stats["start_time"] is not None
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()

    def test_start_already_running(self, temp_dir):
        """Test de démarrage quand déjà en cours."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())
        watcher.is_running = True

        result = watcher.start()

        assert result is True

    def test_start_no_valid_directories(self):
        """Test de démarrage sans répertoires valides."""
        watcher = FileWatcher(['/nonexistent/path'], {'.txt'}, Mock())

        result = watcher.start()

        assert result is False

    @patch('backend.src.file_watcher.watcher.Observer')
    def test_start_observer_error(self, mock_observer_class, temp_dir):
        """Test de gestion d'erreur au démarrage de l'observer."""
        mock_observer = Mock()
        mock_observer.start.side_effect = Exception("Start failed")
        mock_observer_class.return_value = mock_observer

        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        result = watcher.start()

        assert result is False
        assert watcher.is_running is False

    def test_stop_not_running(self, temp_dir):
        """Test d'arrêt quand pas en cours."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())
        watcher.is_running = False

        result = watcher.stop()

        assert result is True

    @patch('backend.src.file_watcher.watcher.Observer')
    def test_stop_success(self, mock_observer_class, temp_dir):
        """Test d'arrêt réussi."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())
        watcher.is_running = True

        result = watcher.stop(timeout=5)

        assert result is True
        assert watcher.is_running is False
        mock_observer.stop.assert_called_once()
        mock_observer.join.assert_called_once_with(timeout=5)

    @patch('backend.src.file_watcher.watcher.Observer')
    def test_stop_error(self, mock_observer_class, temp_dir):
        """Test de gestion d'erreur à l'arrêt."""
        mock_observer = Mock()
        mock_observer.stop.side_effect = Exception("Stop failed")
        mock_observer_class.return_value = mock_observer

        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())
        watcher.is_running = True

        result = watcher.stop()

        assert result is False

    def test_get_stats(self, temp_dir):
        """Test de récupération des statistiques."""
        watcher = FileWatcher([temp_dir], {'.pdf', '.txt'}, Mock())
        watcher.stats["start_time"] = time.time() - 100  # 100 secondes d'activité

        stats = watcher.get_stats()

        assert stats["is_running"] is False
        assert stats["watched_directories"] == [temp_dir]
        assert set(stats["supported_extensions"]) == {'.pdf', '.txt'}
        assert "uptime_seconds" in stats
        assert stats["uptime_seconds"] > 90

    def test_get_stats_no_start_time(self, temp_dir):
        """Test de statistiques sans temps de démarrage."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        stats = watcher.get_stats()

        assert "uptime_seconds" not in stats

    def test_add_directory_success(self, temp_dir):
        """Test d'ajout réussi de répertoire."""
        watcher = FileWatcher([], {'.txt'}, Mock())

        result = watcher.add_directory(temp_dir)

        assert result is True
        assert Path(temp_dir).resolve() in watcher.watch_directories

    def test_add_directory_nonexistent(self):
        """Test d'ajout de répertoire inexistant."""
        watcher = FileWatcher([], {'.txt'}, Mock())

        result = watcher.add_directory('/nonexistent/path')

        assert result is False

    def test_add_directory_already_watched(self, temp_dir):
        """Test d'ajout de répertoire déjà surveillé."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        result = watcher.add_directory(temp_dir)

        assert result is True  # Succès mais pas de duplication

    @patch('backend.src.file_watcher.watcher.Observer')
    def test_add_directory_while_running(self, mock_observer_class, temp_dir):
        """Test d'ajout de répertoire pendant l'exécution."""
        mock_observer = Mock()
        mock_observer_class.return_value = mock_observer

        # Créer un deuxième répertoire temporaire
        with tempfile.TemporaryDirectory() as temp_dir2:
            watcher = FileWatcher([temp_dir], {'.txt'}, Mock())
            watcher.observer = mock_observer
            watcher.is_running = True

            result = watcher.add_directory(temp_dir2)

            assert result is True
            mock_observer.schedule.assert_called()

    def test_add_directory_error(self):
        """Test de gestion d'erreur lors d'ajout."""
        watcher = FileWatcher([], {'.txt'}, Mock())

        # Passer un objet qui lèvera une erreur lors de Path()
        with patch('backend.src.file_watcher.watcher.Path') as mock_path:
            mock_path.side_effect = Exception("Path error")

            result = watcher.add_directory("some_path")

            assert result is False

    def test_remove_directory_success(self, temp_dir):
        """Test de suppression réussie de répertoire."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        result = watcher.remove_directory(temp_dir)

        assert result is True
        assert Path(temp_dir).resolve() not in watcher.watch_directories

    def test_remove_directory_not_watched(self, temp_dir):
        """Test de suppression de répertoire non surveillé."""
        watcher = FileWatcher([], {'.txt'}, Mock())

        result = watcher.remove_directory(temp_dir)

        assert result is False

    def test_remove_directory_error(self, temp_dir):
        """Test de gestion d'erreur lors de suppression."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        with patch('backend.src.file_watcher.watcher.Path') as mock_path:
            mock_path.side_effect = Exception("Path error")

            result = watcher.remove_directory("some_path")

            assert result is False

    def test_scan_existing_files_success(self, temp_dir):
        """Test de scan réussi des fichiers existants."""
        # Créer quelques fichiers de test
        test_files = ['test1.txt', 'test2.pdf', 'ignored.exe']
        for filename in test_files:
            file_path = Path(temp_dir) / filename
            file_path.write_text("test content")

        watcher = FileWatcher([temp_dir], {'.txt', '.pdf'}, Mock(), recursive=False)

        existing_files = watcher.scan_existing_files()

        # Devrait trouver les fichiers .txt et .pdf, pas .exe
        assert len(existing_files) == 2
        file_names = [Path(f).name for f in existing_files]
        assert 'test1.txt' in file_names
        assert 'test2.pdf' in file_names
        assert 'ignored.exe' not in file_names

    def test_scan_existing_files_recursive(self, temp_dir):
        """Test de scan récursif."""
        # Créer une sous-structure
        subdir = Path(temp_dir) / "subdir"
        subdir.mkdir()

        (Path(temp_dir) / "root.txt").write_text("content")
        (subdir / "sub.txt").write_text("content")

        watcher = FileWatcher([temp_dir], {'.txt'}, Mock(), recursive=True)

        existing_files = watcher.scan_existing_files()

        assert len(existing_files) == 2

    def test_scan_existing_files_nonexistent_directory(self):
        """Test de scan avec répertoire inexistant."""
        watcher = FileWatcher(['/nonexistent'], {'.txt'}, Mock())

        existing_files = watcher.scan_existing_files()

        assert existing_files == []

    def test_scan_existing_files_error(self, temp_dir):
        """Test de gestion d'erreur lors du scan."""
        watcher = FileWatcher([temp_dir], {'.txt'}, Mock())

        with patch.object(Path, 'glob', side_effect=Exception("Glob error")):
            existing_files = watcher.scan_existing_files()

            assert existing_files == []


class TestIntegration:
    """Tests d'intégration pour le système complet."""

    @pytest.fixture
    def temp_dir(self):
        """Fixture pour créer un répertoire temporaire."""
        with tempfile.TemporaryDirectory() as temp_dir:
            yield temp_dir

    def test_file_handler_integration(self, temp_dir):
        """Test d'intégration complète du gestionnaire de fichiers."""
        on_file_added = Mock()
        on_file_modified = Mock()

        handler = DocumentFileHandler(
            supported_extensions={'.txt'},
            on_file_added=on_file_added,
            on_file_modified=on_file_modified
        )

        # Simuler un événement de création
        mock_event = Mock()
        mock_event.is_directory = False
        mock_event.src_path = os.path.join(temp_dir, 'test.txt')

        # Créer le fichier réellement
        with open(mock_event.src_path, 'w') as f:
            f.write("test content")

        handler.on_created(mock_event)

        on_file_added.assert_called_once_with(mock_event.src_path)

    def test_watcher_lifecycle(self, temp_dir):
        """Test du cycle de vie complet du FileWatcher."""
        on_file_added = Mock()

        watcher = FileWatcher([temp_dir], {'.txt'}, on_file_added)

        # Démarrer
        assert watcher.start() is True
        assert watcher.is_running is True

        # Obtenir les stats
        stats = watcher.get_stats()
        assert stats["is_running"] is True

        # Scanner les fichiers existants
        existing_files = watcher.scan_existing_files()
        assert isinstance(existing_files, list)

        # Arrêter
        assert watcher.stop() is True
        assert watcher.is_running is False
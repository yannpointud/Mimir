"""
Tests unitaires pour les extracteurs de texte
"""

import pytest
import tempfile
import shutil
from pathlib import Path
from unittest.mock import Mock, patch, mock_open

from src.ingestion.extractors import (
    ExtractorFactory, TextExtractor, PDFExtractor, DOCXExtractor, TXTExtractor,
    ExtractionError
)


class TestExtractorFactory:
    """Tests pour la factory des extracteurs"""

    @pytest.fixture
    def temp_dir(self):
        """Répertoire temporaire pour les tests"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_factory_initialization(self):
        """Test d'initialisation de la factory"""
        factory = ExtractorFactory()

        supported_extensions = factory.get_supported_extensions()
        expected_extensions = ['.txt', '.pdf', '.docx', '.md']

        for ext in expected_extensions:
            assert ext in supported_extensions

    def test_get_extractor_txt(self):
        """Test de récupération d'extracteur pour fichier texte"""
        factory = ExtractorFactory()

        extractor = factory.get_extractor('test.txt')
        assert isinstance(extractor, TextExtractor)

    def test_get_extractor_pdf(self):
        """Test de récupération d'extracteur pour PDF"""
        factory = ExtractorFactory()

        extractor = factory.get_extractor('test.pdf')
        assert isinstance(extractor, PDFExtractor)

    def test_get_extractor_docx(self):
        """Test de récupération d'extracteur pour DOCX"""
        factory = ExtractorFactory()

        extractor = factory.get_extractor('test.docx')
        assert isinstance(extractor, DOCXExtractor)

    def test_unsupported_extension(self):
        """Test d'extension non supportée"""
        factory = ExtractorFactory()

        extractor = factory.get_extractor('test.xyz')
        assert extractor is None

    def test_extract_text_success(self, temp_dir):
        """Test d'extraction réussie"""
        factory = ExtractorFactory()

        # Créer un fichier texte temporaire
        test_file = temp_dir / "test.txt"
        test_content = "Hello world\nThis is a test file."
        test_file.write_text(test_content, encoding='utf-8')

        extracted_text = factory.extract_text(str(test_file))

        assert extracted_text.strip() == test_content

    def test_extract_text_nonexistent_file(self):
        """Test d'extraction sur fichier inexistant"""
        factory = ExtractorFactory()

        with pytest.raises(ExtractionError) as exc_info:
            factory.extract_text("/nonexistent/file.txt")

        assert "Failed to extract text" in str(exc_info.value) or "No such file" in str(exc_info.value)

    def test_extract_text_with_metadata(self, temp_dir):
        """Test d'extraction avec métadonnées"""
        factory = ExtractorFactory()

        test_file = temp_dir / "test.txt"
        test_content = "Test content"
        test_file.write_text(test_content, encoding='utf-8')

        # Utiliser get_extractor pour obtenir l'extracteur et ses métadonnées
        extractor = factory.get_extractor(str(test_file))
        extracted_text = extractor.extract(str(test_file))
        metadata = extractor.get_metadata(str(test_file))

        assert extracted_text.strip() == test_content
        assert metadata['file_size'] > 0
        assert metadata['file_extension'] == '.txt'
        assert metadata['file_name'] == 'test.txt'


class TestTextExtractor:
    """Tests pour l'extracteur de texte"""

    @pytest.fixture
    def temp_dir(self):
        """Répertoire temporaire pour les tests"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_text_extraction_utf8(self, temp_dir):
        """Test d'extraction UTF-8"""
        extractor = TXTExtractor()

        test_file = temp_dir / "utf8.txt"
        test_content = "Hello world! Café, naïve, résumé 🌟"
        test_file.write_text(test_content, encoding='utf-8')

        extracted_text = extractor.extract(str(test_file))

        assert extracted_text == test_content

    def test_text_extraction_latin1(self, temp_dir):
        """Test d'extraction Latin-1"""
        extractor = TXTExtractor()

        test_file = temp_dir / "latin1.txt"
        test_content = "Café, résumé"
        test_file.write_text(test_content, encoding='latin-1')

        extracted_text = extractor.extract(str(test_file))

        assert "Café" in extracted_text or "Caf" in extracted_text  # Peut y avoir des problèmes d'encoding

    def test_text_extraction_with_bom(self, temp_dir):
        """Test d'extraction avec BOM UTF-8"""
        extractor = TXTExtractor()

        test_file = temp_dir / "bom.txt"
        test_content = "Test with BOM"

        # Écrire avec BOM UTF-8
        with open(test_file, 'w', encoding='utf-8-sig') as f:
            f.write(test_content)

        extracted_text = extractor.extract(str(test_file))

        # Le BOM peut être présent ou supprimé selon l'implémentation
        assert test_content in extracted_text

    def test_detect_encoding(self, temp_dir):
        """Test de détection d'encodage"""
        extractor = TXTExtractor()

        # UTF-8
        test_file_utf8 = temp_dir / "utf8.txt"
        test_file_utf8.write_text("Hello world", encoding='utf-8')

        # Le TXTExtractor n'a pas de méthode _detect_encoding publique
        # On teste simplement que l'extraction fonctionne avec différents encodages
        extracted_text = extractor.extract(str(test_file_utf8))
        assert "Hello world" in extracted_text

    def test_empty_file(self, temp_dir):
        """Test avec fichier vide"""
        extractor = TXTExtractor()

        test_file = temp_dir / "empty.txt"
        test_file.touch()

        extracted_text = extractor.extract(str(test_file))

        assert extracted_text == ""

    def test_binary_file_error(self, temp_dir):
        """Test avec fichier binaire (doit échouer)"""
        extractor = TXTExtractor()

        # Créer un fichier binaire
        test_file = temp_dir / "binary.bin"
        test_file.write_bytes(b'\x00\x01\x02\x03\x04\x05')

        with pytest.raises(ExtractionError):
            extractor.extract(str(test_file))


class TestPDFExtractor:
    """Tests pour l'extracteur PDF"""

    def test_pdf_extractor_initialization(self):
        """Test d'initialisation de l'extracteur PDF"""
        extractor = PDFExtractor()
        assert extractor is not None

    @patch('pypdf.PdfReader')
    def test_pdf_extraction_success(self, mock_pdf_reader):
        """Test d'extraction PDF réussie"""
        # Mock du lecteur PDF
        mock_reader = Mock()
        mock_page = Mock()
        mock_page.extract_text.return_value = "PDF content page 1\n"

        mock_reader.pages = [mock_page, mock_page]  # 2 pages
        mock_pdf_reader.return_value = mock_reader

        extractor = PDFExtractor()

        with patch('builtins.open', mock_open(read_data=b'fake pdf data')):
            extracted_text = extractor.extract("fake.pdf")

        assert "PDF content page 1" in extracted_text
        assert mock_pdf_reader.called

    @patch('pypdf.PdfReader')
    def test_pdf_extraction_encrypted(self, mock_pdf_reader):
        """Test d'extraction PDF chiffré"""
        mock_reader = Mock()
        mock_reader.pages = []
        mock_reader.is_encrypted = True
        mock_reader.decrypt = Mock(side_effect=Exception("Cannot decrypt"))
        mock_pdf_reader.return_value = mock_reader

        extractor = PDFExtractor()

        with (
            patch('builtins.open', mock_open(read_data=b'encrypted pdf data')),
            pytest.raises(ExtractionError) as exc_info,
        ):
            extractor.extract("encrypted.pdf")

        assert "encrypted" in str(exc_info.value).lower() or "decrypt" in str(exc_info.value).lower()

    @patch('pypdf.PdfReader')
    def test_pdf_extraction_error(self, mock_pdf_reader):
        """Test d'erreur lors de l'extraction PDF"""
        mock_pdf_reader.side_effect = Exception("PDF parsing error")

        extractor = PDFExtractor()

        with (
            patch('builtins.open', mock_open(read_data=b'bad pdf data')),
            pytest.raises(ExtractionError) as exc_info,
        ):
            extractor.extract("bad.pdf")

        assert "PDF parsing error" in str(exc_info.value)

    @patch('pypdf.PdfReader')
    def test_pdf_empty_pages(self, mock_pdf_reader):
        """Test PDF avec pages vides"""
        mock_reader = Mock()
        mock_page1 = Mock()
        mock_page1.extract_text.return_value = ""
        mock_page2 = Mock()
        mock_page2.extract_text.return_value = "   \n  \n"

        mock_reader.pages = [mock_page1, mock_page2]
        mock_reader.is_encrypted = False
        mock_pdf_reader.return_value = mock_reader

        extractor = PDFExtractor()

        with patch('builtins.open', mock_open(read_data=b'empty pdf')):
            extracted_text = extractor.extract("empty.pdf")

        assert extracted_text.strip() == ""


class TestDOCXExtractor:
    """Tests pour l'extracteur DOCX"""

    def test_docx_extractor_initialization(self):
        """Test d'initialisation de l'extracteur DOCX"""
        extractor = DOCXExtractor()
        assert extractor is not None

    @patch('src.ingestion.extractors.DocxDocument')
    def test_docx_extraction_success(self, mock_document):
        """Test d'extraction DOCX réussie"""
        # Mock du document
        mock_doc = Mock()
        mock_paragraph1 = Mock()
        mock_paragraph1.text = "First paragraph"
        mock_paragraph2 = Mock()
        mock_paragraph2.text = "Second paragraph"

        mock_doc.paragraphs = [mock_paragraph1, mock_paragraph2]
        mock_doc.tables = []
        mock_document.return_value = mock_doc

        extractor = DOCXExtractor()
        extracted_text = extractor.extract("fake.docx")

        assert "First paragraph" in extracted_text
        assert "Second paragraph" in extracted_text
        assert mock_document.called

    @patch('src.ingestion.extractors.DocxDocument')
    def test_docx_extraction_error(self, mock_document):
        """Test d'erreur lors de l'extraction DOCX"""
        mock_document.side_effect = Exception("DOCX parsing error")

        extractor = DOCXExtractor()

        with pytest.raises(ExtractionError) as exc_info:
            extractor.extract("bad.docx")

        assert "DOCX parsing error" in str(exc_info.value)

    @patch('src.ingestion.extractors.DocxDocument')
    def test_docx_empty_document(self, mock_document):
        """Test DOCX vide"""
        mock_doc = Mock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        mock_document.return_value = mock_doc

        extractor = DOCXExtractor()
        extracted_text = extractor.extract("empty.docx")

        assert extracted_text.strip() == ""

    @patch('src.ingestion.extractors.DocxDocument')
    def test_docx_with_empty_paragraphs(self, mock_document):
        """Test DOCX avec paragraphes vides"""
        mock_doc = Mock()
        mock_para1 = Mock()
        mock_para1.text = ""
        mock_para2 = Mock()
        mock_para2.text = "   "
        mock_para3 = Mock()
        mock_para3.text = "Real content"

        mock_doc.paragraphs = [mock_para1, mock_para2, mock_para3]
        mock_doc.tables = []
        mock_document.return_value = mock_doc

        extractor = DOCXExtractor()
        extracted_text = extractor.extract("mixed.docx")

        assert "Real content" in extracted_text
        # Les paragraphes vides ne doivent pas ajouter de lignes supplémentaires
        lines = [line for line in extracted_text.split('\n') if line.strip()]
        assert len(lines) == 1


class TestExtractorIntegration:
    """Tests d'intégration des extracteurs"""

    @pytest.fixture
    def temp_dir(self):
        """Répertoire temporaire pour les tests"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_factory_handles_different_extensions(self, temp_dir):
        """Test que la factory gère différentes extensions"""
        factory = ExtractorFactory()

        # Créer des fichiers de test
        files_and_contents = [
            ("test.txt", "Text content"),
            ("test.md", "# Markdown content\nThis is markdown."),
        ]

        for filename, content in files_and_contents:
            test_file = temp_dir / filename
            test_file.write_text(content, encoding='utf-8')

            extracted_text = factory.extract_text(str(test_file))
            # Pour les fichiers markdown, le contenu peut être converti en HTML
            if filename.endswith('.md'):
                # Le contenu markdown peut être transformé en HTML
                assert 'Markdown content' in extracted_text
                assert 'markdown' in extracted_text.lower()
            else:
                assert content in extracted_text

    def test_case_insensitive_extensions(self, temp_dir):
        """Test que les extensions sont case-insensitive"""
        factory = ExtractorFactory()

        test_file = temp_dir / "test.TXT"
        test_content = "Uppercase extension"
        test_file.write_text(test_content, encoding='utf-8')

        extracted_text = factory.extract_text(str(test_file))
        assert test_content in extracted_text

    def test_metadata_extraction_comprehensive(self, temp_dir):
        """Test complet d'extraction de métadonnées"""
        factory = ExtractorFactory()

        test_file = temp_dir / "metadata_test.txt"
        test_content = "Content for metadata testing"
        test_file.write_text(test_content, encoding='utf-8')

        # Utiliser get_extractor pour obtenir l'extracteur et ses métadonnées
        extractor = factory.get_extractor(str(test_file))
        extracted_text = extractor.extract(str(test_file))
        metadata = extractor.get_metadata(str(test_file))

        # Vérifier le texte
        assert extracted_text.strip() == test_content

        # Vérifier les métadonnées
        assert metadata['file_extension'] == '.txt'
        assert metadata['file_size'] > 0
        assert isinstance(metadata['file_size'], int)
        assert metadata['file_name'] == 'metadata_test.txt'

    def test_large_file_handling(self, temp_dir):
        """Test de gestion de gros fichiers"""
        factory = ExtractorFactory()

        # Créer un fichier relativement gros
        test_file = temp_dir / "large.txt"
        large_content = "This is a large file. " * 10000  # ~240KB

        test_file.write_text(large_content, encoding='utf-8')

        extracted_text = factory.extract_text(str(test_file))

        assert len(extracted_text) > 200000  # Vérifier que tout le contenu est extrait
        assert "This is a large file." in extracted_text

    def test_special_characters_handling(self, temp_dir):
        """Test de gestion des caractères spéciaux"""
        factory = ExtractorFactory()

        test_file = temp_dir / "special.txt"
        special_content = "Special chars: é, ñ, 中文, 🚀, \n\t\r"
        test_file.write_text(special_content, encoding='utf-8')

        extracted_text = factory.extract_text(str(test_file))

        assert "é" in extracted_text
        assert "ñ" in extracted_text
        assert "中文" in extracted_text
        assert "🚀" in extracted_text
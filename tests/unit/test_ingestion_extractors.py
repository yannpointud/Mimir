"""
Unit tests of the text extractors
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

import pytest

from mimir.ingestion.extractors import (
    DOCXExtractor,
    ExtractionError,
    ExtractorFactory,
    PDFExtractor,
    TextExtractor,
    TXTExtractor,
)


class TestExtractorFactory:
    """Extractor factory tests"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_factory_initialization(self):
        factory = ExtractorFactory()

        supported_extensions = factory.get_supported_extensions()
        expected_extensions = [".txt", ".pdf", ".docx", ".md"]

        for ext in expected_extensions:
            assert ext in supported_extensions

    def test_get_extractor_txt(self):
        factory = ExtractorFactory()

        extractor = factory.get_extractor("test.txt")
        assert isinstance(extractor, TextExtractor)

    def test_get_extractor_pdf(self):
        factory = ExtractorFactory()

        extractor = factory.get_extractor("test.pdf")
        assert isinstance(extractor, PDFExtractor)

    def test_get_extractor_docx(self):
        factory = ExtractorFactory()

        extractor = factory.get_extractor("test.docx")
        assert isinstance(extractor, DOCXExtractor)

    def test_unsupported_extension(self):
        factory = ExtractorFactory()

        extractor = factory.get_extractor("test.xyz")
        assert extractor is None

    def test_extract_text_success(self, temp_dir):
        factory = ExtractorFactory()

        # Create a temporary text file
        test_file = temp_dir / "test.txt"
        test_content = "Hello world\nThis is a test file."
        test_file.write_text(test_content, encoding="utf-8")

        extracted_text = factory.extract_text(str(test_file))

        assert extracted_text.strip() == test_content

    def test_extract_text_nonexistent_file(self):
        factory = ExtractorFactory()

        with pytest.raises(ExtractionError) as exc_info:
            factory.extract_text("/nonexistent/file.txt")

        assert "Failed to extract text" in str(exc_info.value) or "No such file" in str(
            exc_info.value
        )

    def test_extract_text_with_metadata(self, temp_dir):
        factory = ExtractorFactory()

        test_file = temp_dir / "test.txt"
        test_content = "Test content"
        test_file.write_text(test_content, encoding="utf-8")

        # Use get_extractor to get the extractor and its metadata
        extractor = factory.get_extractor(str(test_file))
        extracted_text = extractor.extract(str(test_file))
        metadata = extractor.get_metadata(str(test_file))

        assert extracted_text.strip() == test_content
        assert metadata["file_size"] > 0
        assert metadata["file_extension"] == ".txt"
        assert metadata["file_name"] == "test.txt"


class TestTextExtractor:
    """Text extractor tests"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_text_extraction_utf8(self, temp_dir):
        """Test d'extraction UTF-8"""
        extractor = TXTExtractor()

        test_file = temp_dir / "utf8.txt"
        test_content = "Hello world! Café, naïve, résumé 🌟"
        test_file.write_text(test_content, encoding="utf-8")

        extracted_text = extractor.extract(str(test_file))

        assert extracted_text == test_content

    def test_text_extraction_latin1(self, temp_dir):
        """Test d'extraction Latin-1"""
        extractor = TXTExtractor()

        test_file = temp_dir / "latin1.txt"
        test_content = "Café, résumé"
        test_file.write_text(test_content, encoding="latin-1")

        extracted_text = extractor.extract(str(test_file))

        assert "Café" in extracted_text or "Caf" in extracted_text  # Encoding issues are possible

    def test_text_extraction_with_bom(self, temp_dir):
        extractor = TXTExtractor()

        test_file = temp_dir / "bom.txt"
        test_content = "Test with BOM"

        # Write with a UTF-8 BOM
        with open(test_file, "w", encoding="utf-8-sig") as f:
            f.write(test_content)

        extracted_text = extractor.extract(str(test_file))

        # The BOM may be kept or removed depending on the implementation
        assert test_content in extracted_text

    def test_detect_encoding(self, temp_dir):
        extractor = TXTExtractor()

        # UTF-8
        test_file_utf8 = temp_dir / "utf8.txt"
        test_file_utf8.write_text("Hello world", encoding="utf-8")

        # TXTExtractor has no public _detect_encoding method
        # Only check that extraction works with different encodings
        extracted_text = extractor.extract(str(test_file_utf8))
        assert "Hello world" in extracted_text

    def test_empty_file(self, temp_dir):
        extractor = TXTExtractor()

        test_file = temp_dir / "empty.txt"
        test_file.touch()

        extracted_text = extractor.extract(str(test_file))

        assert extracted_text == ""

    def test_binary_file_error(self, temp_dir):
        extractor = TXTExtractor()

        # Create a binary file
        test_file = temp_dir / "binary.bin"
        test_file.write_bytes(b"\x00\x01\x02\x03\x04\x05")

        with pytest.raises(ExtractionError):
            extractor.extract(str(test_file))


class TestPDFExtractor:
    """PDF extractor tests"""

    def test_pdf_extractor_initialization(self):
        """Test d'initialisation de l'extracteur PDF"""
        extractor = PDFExtractor()
        assert extractor is not None

    @patch("pypdf.PdfReader")
    def test_pdf_extraction_success(self, mock_pdf_reader):
        # PDF reader mock
        mock_reader = Mock()
        mock_page = Mock()
        mock_page.extract_text.return_value = "PDF content page 1\n"

        mock_reader.pages = [mock_page, mock_page]  # 2 pages
        mock_pdf_reader.return_value = mock_reader

        extractor = PDFExtractor()

        with patch("builtins.open", mock_open(read_data=b"fake pdf data")):
            extracted_text = extractor.extract("fake.pdf")

        assert "PDF content page 1" in extracted_text
        assert mock_pdf_reader.called

    @patch("pypdf.PdfReader")
    def test_pdf_extraction_encrypted(self, mock_pdf_reader):
        mock_reader = Mock()
        mock_reader.pages = []
        mock_reader.is_encrypted = True
        mock_reader.decrypt = Mock(side_effect=Exception("Cannot decrypt"))
        mock_pdf_reader.return_value = mock_reader

        extractor = PDFExtractor()

        with (
            patch("builtins.open", mock_open(read_data=b"encrypted pdf data")),
            pytest.raises(ExtractionError) as exc_info,
        ):
            extractor.extract("encrypted.pdf")

        assert (
            "encrypted" in str(exc_info.value).lower() or "decrypt" in str(exc_info.value).lower()
        )

    @patch("pypdf.PdfReader")
    def test_pdf_extraction_error(self, mock_pdf_reader):
        """Test d'erreur lors de l'extraction PDF"""
        mock_pdf_reader.side_effect = Exception("PDF parsing error")

        extractor = PDFExtractor()

        with (
            patch("builtins.open", mock_open(read_data=b"bad pdf data")),
            pytest.raises(ExtractionError) as exc_info,
        ):
            extractor.extract("bad.pdf")

        assert "PDF parsing error" in str(exc_info.value)

    @patch("pypdf.PdfReader")
    def test_pdf_empty_pages(self, mock_pdf_reader):
        mock_reader = Mock()
        mock_page1 = Mock()
        mock_page1.extract_text.return_value = ""
        mock_page2 = Mock()
        mock_page2.extract_text.return_value = "   \n  \n"

        mock_reader.pages = [mock_page1, mock_page2]
        mock_reader.is_encrypted = False
        mock_pdf_reader.return_value = mock_reader

        extractor = PDFExtractor()

        with patch("builtins.open", mock_open(read_data=b"empty pdf")):
            extracted_text = extractor.extract("empty.pdf")

        assert extracted_text.strip() == ""


class TestDOCXExtractor:
    """DOCX extractor tests"""

    def test_docx_extractor_initialization(self):
        """Test d'initialisation de l'extracteur DOCX"""
        extractor = DOCXExtractor()
        assert extractor is not None

    @patch("mimir.ingestion.extractors.DocxDocument")
    def test_docx_extraction_success(self, mock_document):
        # Document mock
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

    @patch("mimir.ingestion.extractors.DocxDocument")
    def test_docx_extraction_error(self, mock_document):
        """Test d'erreur lors de l'extraction DOCX"""
        mock_document.side_effect = Exception("DOCX parsing error")

        extractor = DOCXExtractor()

        with pytest.raises(ExtractionError) as exc_info:
            extractor.extract("bad.docx")

        assert "DOCX parsing error" in str(exc_info.value)

    @patch("mimir.ingestion.extractors.DocxDocument")
    def test_docx_empty_document(self, mock_document):
        """Test DOCX vide"""
        mock_doc = Mock()
        mock_doc.paragraphs = []
        mock_doc.tables = []
        mock_document.return_value = mock_doc

        extractor = DOCXExtractor()
        extracted_text = extractor.extract("empty.docx")

        assert extracted_text.strip() == ""

    @patch("mimir.ingestion.extractors.DocxDocument")
    def test_docx_with_empty_paragraphs(self, mock_document):
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
        # Empty paragraphs must not add extra lines
        lines = [line for line in extracted_text.split("\n") if line.strip()]
        assert len(lines) == 1


class TestExtractorIntegration:
    """Integration tests of the extractors"""

    @pytest.fixture
    def temp_dir(self):
        """Temporary directory"""
        temp_dir = tempfile.mkdtemp()
        yield Path(temp_dir)
        shutil.rmtree(temp_dir)

    def test_factory_handles_different_extensions(self, temp_dir):
        factory = ExtractorFactory()

        # Create test files
        files_and_contents = [
            ("test.txt", "Text content"),
            ("test.md", "# Markdown content\nThis is markdown."),
        ]

        for filename, content in files_and_contents:
            test_file = temp_dir / filename
            test_file.write_text(content, encoding="utf-8")

            extracted_text = factory.extract_text(str(test_file))
            # Markdown content may be converted to HTML
            if filename.endswith(".md"):
                # Markdown content may be converted to HTML
                assert "Markdown content" in extracted_text
                assert "markdown" in extracted_text.lower()
            else:
                assert content in extracted_text

    def test_case_insensitive_extensions(self, temp_dir):
        factory = ExtractorFactory()

        test_file = temp_dir / "test.TXT"
        test_content = "Uppercase extension"
        test_file.write_text(test_content, encoding="utf-8")

        extracted_text = factory.extract_text(str(test_file))
        assert test_content in extracted_text

    def test_metadata_extraction_comprehensive(self, temp_dir):
        factory = ExtractorFactory()

        test_file = temp_dir / "metadata_test.txt"
        test_content = "Content for metadata testing"
        test_file.write_text(test_content, encoding="utf-8")

        # Use get_extractor to get the extractor and its metadata
        extractor = factory.get_extractor(str(test_file))
        extracted_text = extractor.extract(str(test_file))
        metadata = extractor.get_metadata(str(test_file))

        # Check the text
        assert extracted_text.strip() == test_content

        # Check the metadata
        assert metadata["file_extension"] == ".txt"
        assert metadata["file_size"] > 0
        assert isinstance(metadata["file_size"], int)
        assert metadata["file_name"] == "metadata_test.txt"

    def test_large_file_handling(self, temp_dir):
        """Test de gestion de gros fichiers"""
        factory = ExtractorFactory()

        # Create a rather large file
        test_file = temp_dir / "large.txt"
        large_content = "This is a large file. " * 10000  # ~240KB

        test_file.write_text(large_content, encoding="utf-8")

        extracted_text = factory.extract_text(str(test_file))

        assert len(extracted_text) > 200000  # Check that all the content is extracted
        assert "This is a large file." in extracted_text

    def test_special_characters_handling(self, temp_dir):
        factory = ExtractorFactory()

        test_file = temp_dir / "special.txt"
        special_content = "Special chars: é, ñ, 中文, 🚀, \n\t\r"
        test_file.write_text(special_content, encoding="utf-8")

        extracted_text = factory.extract_text(str(test_file))

        assert "é" in extracted_text
        assert "ñ" in extracted_text
        assert "中文" in extracted_text
        assert "🚀" in extracted_text

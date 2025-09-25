"""
Smart text chunking with sentence boundaries and overlap
Provides intelligent text segmentation for optimal RAG performance
"""

import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from ..monitoring.logger import setup_logger

logger = setup_logger(__name__)

@dataclass
class ChunkingConfig:
    """Configuration for chunking strategy"""
    chunk_size: int = 1000  # Target chunk size in characters
    overlap: int = 120      # Overlap between chunks in characters (optimized: 12%)
    min_chunk_size: int = 100  # Minimum viable chunk size
    max_chunk_size: int = 3000  # Maximum chunk size before force split (augmenté pour CV)
    preserve_sentences: bool = True  # Try to keep sentences intact
    preserve_paragraphs: bool = True  # Try to keep paragraphs intact

class ChunkingStrategy:
    """Smart text chunking with sentence and paragraph boundaries"""

    def __init__(self, config: Optional[ChunkingConfig] = None):
        """
        Initialize chunking strategy

        Args:
            config: Chunking configuration, uses defaults if None
        """
        self.config = config or ChunkingConfig()
        logger.debug(f"Chunking strategy initialized: {self.config}")

    def chunk_text(self, text: str, source: str = "") -> List[Dict[str, Any]]:
        """
        Chunk text into smaller segments with overlap

        Args:
            text: Input text to chunk
            source: Source identifier for logging

        Returns:
            List of chunk dictionaries with text and metadata
        """
        if not text or not text.strip():
            logger.warning(f"Empty text provided for chunking from source: {source}")
            return []

        # Clean and normalize text
        cleaned_text = self._clean_text(text)

        if len(cleaned_text) <= self.config.chunk_size:
            # Text is small enough to be one chunk
            return [{
                'text': cleaned_text,
                'chunk_index': 0,
                'total_chunks': 1,
                'start_char': 0,
                'end_char': len(cleaned_text),
                'word_count': len(cleaned_text.split()),
                'char_count': len(cleaned_text)
            }]

        chunks = []

        if self.config.preserve_paragraphs:
            # First try to chunk by paragraphs
            chunks = self._chunk_by_paragraphs(cleaned_text)
        else:
            # Direct sentence-based chunking
            chunks = self._chunk_by_sentences(cleaned_text)

        # Add metadata to chunks
        for i, chunk_data in enumerate(chunks):
            chunk_data.update({
                'chunk_index': i,
                'total_chunks': len(chunks),
                'word_count': len(chunk_data['text'].split()),
                'char_count': len(chunk_data['text'])
            })

        logger.info(
            f"Chunked text into {len(chunks)} chunks (avg: {sum(len(c['text']) for c in chunks) // len(chunks)} chars)",
            extra={'extra_fields': {
                'source': source,
                'original_chars': len(cleaned_text),
                'chunk_count': len(chunks),
                'avg_chunk_size': sum(len(c['text']) for c in chunks) // len(chunks),
                'type': 'text_chunking'
            }}
        )

        return chunks

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text for chunking

        Args:
            text: Raw input text

        Returns:
            Cleaned text
        """
        # Remove excessive whitespace but preserve paragraph breaks
        lines = text.split('\n')
        cleaned_lines = []

        for line in lines:
            # Remove excessive spaces within lines
            cleaned_line = re.sub(r'\s+', ' ', line.strip())
            cleaned_lines.append(cleaned_line)

        # Join lines and normalize paragraph breaks
        result = '\n'.join(cleaned_lines)

        # Remove excessive newlines (more than 2 consecutive)
        result = re.sub(r'\n{3,}', '\n\n', result)

        # Remove leading/trailing whitespace
        result = result.strip()

        return result

    def _chunk_by_paragraphs(self, text: str) -> List[Dict[str, Any]]:
        """
        Chunk text by paragraphs with sentence awareness

        Args:
            text: Cleaned input text

        Returns:
            List of chunk data dictionaries
        """
        paragraphs = re.split(r'\n\s*\n', text)
        chunks = []
        current_chunk = ""
        current_start = 0

        for paragraph in paragraphs:
            paragraph = paragraph.strip()
            if not paragraph:
                continue

            # If adding this paragraph would exceed chunk size
            if current_chunk and len(current_chunk) + len(paragraph) + 2 > self.config.chunk_size:
                # Finalize current chunk
                if current_chunk:
                    chunks.append({
                        'text': current_chunk.strip(),
                        'start_char': current_start,
                        'end_char': current_start + len(current_chunk)
                    })

                # Start new chunk with overlap
                overlap_text = self._get_overlap_text(current_chunk, self.config.overlap)
                current_chunk = overlap_text + paragraph
                current_start = current_start + len(current_chunk) - len(overlap_text) - len(paragraph)
            else:
                # Add paragraph to current chunk
                if current_chunk:
                    current_chunk += "\n\n" + paragraph
                else:
                    current_chunk = paragraph

        # Add final chunk
        if current_chunk:
            chunks.append({
                'text': current_chunk.strip(),
                'start_char': current_start,
                'end_char': current_start + len(current_chunk)
            })

        # Handle oversized paragraphs
        final_chunks = []
        for chunk_data in chunks:
            if len(chunk_data['text']) > self.config.max_chunk_size:
                # Split oversized chunk by sentences
                sentence_chunks = self._chunk_by_sentences(chunk_data['text'], chunk_data['start_char'])
                final_chunks.extend(sentence_chunks)
            else:
                final_chunks.append(chunk_data)

        return final_chunks

    def _chunk_by_sentences(self, text: str, start_offset: int = 0) -> List[Dict[str, Any]]:
        """
        Chunk text by sentences

        Args:
            text: Input text
            start_offset: Starting character offset

        Returns:
            List of chunk data dictionaries
        """
        sentences = self._split_sentences(text)
        if not sentences:
            return []

        chunks = []
        current_chunk = ""
        current_start = start_offset
        sentence_start = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            # If adding this sentence would exceed chunk size
            if current_chunk and len(current_chunk) + len(sentence) + 1 > self.config.chunk_size:
                # Finalize current chunk if it's substantial enough
                if len(current_chunk) >= self.config.min_chunk_size:
                    chunks.append({
                        'text': current_chunk.strip(),
                        'start_char': current_start,
                        'end_char': current_start + len(current_chunk)
                    })

                    # Start new chunk with overlap
                    overlap_text = self._get_overlap_text(current_chunk, self.config.overlap)
                    current_chunk = overlap_text + sentence
                    current_start = current_start + len(current_chunk) - len(overlap_text) - len(sentence)
                else:
                    # Current chunk is too small, just add the sentence
                    current_chunk += " " + sentence if current_chunk else sentence
            else:
                # Add sentence to current chunk
                current_chunk += " " + sentence if current_chunk else sentence

            sentence_start += len(sentence) + 1  # +1 for space

        # Add final chunk
        if current_chunk and len(current_chunk) >= self.config.min_chunk_size:
            chunks.append({
                'text': current_chunk.strip(),
                'start_char': current_start,
                'end_char': current_start + len(current_chunk)
            })

        # Handle edge case: if no substantial chunks were created
        if not chunks and text.strip():
            # Force create one chunk even if it's small
            chunks.append({
                'text': text.strip(),
                'start_char': start_offset,
                'end_char': start_offset + len(text)
            })

        return chunks

    def _split_sentences(self, text: str) -> List[str]:
        """
        Split text into sentences using regex patterns

        Args:
            text: Input text

        Returns:
            List of sentences
        """
        # Advanced sentence splitting pattern
        # Handles common abbreviations and edge cases
        sentence_pattern = r'''
        (?<![A-Z][a-z]\.)    # Not after abbreviations like "Mr."
        (?<![A-Z]\.)         # Not after single letter abbreviations
        (?<!Dr\.)            # Not after "Dr."
        (?<!Prof\.)          # Not after "Prof."
        (?<!Inc\.)           # Not after "Inc."
        (?<!Ltd\.)           # Not after "Ltd."
        (?<!etc\.)           # Not after "etc."
        (?<!vs\.)            # Not after "vs."
        (?<!i\.e\.)          # Not after "i.e."
        (?<!e\.g\.)          # Not after "e.g."
        [.!?]+               # One or more sentence terminators
        \s+                  # Followed by whitespace
        (?=[A-Z]|["\'„«])    # Followed by capital letter or quote
        '''

        sentences = re.split(sentence_pattern, text, flags=re.VERBOSE)

        # Clean up sentences
        cleaned_sentences = []
        for sentence in sentences:
            sentence = sentence.strip()
            if sentence:
                cleaned_sentences.append(sentence)

        # Fallback: if regex splitting failed, split by simple patterns
        if len(cleaned_sentences) <= 1 and len(text) > self.config.chunk_size:
            # Simple fallback splitting
            sentences = re.split(r'[.!?]+\s+', text)
            cleaned_sentences = [s.strip() for s in sentences if s.strip()]

        return cleaned_sentences

    def _get_overlap_text(self, text: str, overlap_size: int) -> str:
        """
        Get overlap text from the end of current chunk

        Args:
            text: Source text
            overlap_size: Desired overlap size in characters

        Returns:
            Overlap text
        """
        if not text or overlap_size <= 0:
            return ""

        # Try to get overlap that ends at sentence boundary
        if self.config.preserve_sentences and overlap_size < len(text):
            # Look for sentence endings in the overlap region
            start_pos = max(0, len(text) - overlap_size - 100)  # Look back a bit more
            overlap_region = text[start_pos:]

            # Find last sentence boundary in overlap region
            sentence_endings = []
            for match in re.finditer(r'[.!?]+\s+', overlap_region):
                sentence_endings.append(match.end())

            if sentence_endings:
                # Use the last sentence boundary
                boundary_pos = sentence_endings[-1]
                actual_start = start_pos + boundary_pos
                if actual_start < len(text):
                    return text[actual_start:] + " "

        # Fallback: simple character-based overlap
        if overlap_size >= len(text):
            return text + " "
        else:
            return text[-overlap_size:] + " "

    def get_chunk_statistics(self, chunks: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Calculate statistics for chunked text

        Args:
            chunks: List of chunk data dictionaries

        Returns:
            Statistics dictionary
        """
        if not chunks:
            return {
                'total_chunks': 0,
                'total_characters': 0,
                'total_words': 0,
                'avg_chunk_size': 0,
                'min_chunk_size': 0,
                'max_chunk_size': 0
            }

        chunk_sizes = [len(chunk['text']) for chunk in chunks]
        word_counts = [chunk.get('word_count', len(chunk['text'].split())) for chunk in chunks]

        return {
            'total_chunks': len(chunks),
            'total_characters': sum(chunk_sizes),
            'total_words': sum(word_counts),
            'avg_chunk_size': sum(chunk_sizes) / len(chunk_sizes),
            'min_chunk_size': min(chunk_sizes),
            'max_chunk_size': max(chunk_sizes),
            'avg_words_per_chunk': sum(word_counts) / len(word_counts),
            'config': self.config.__dict__
        }
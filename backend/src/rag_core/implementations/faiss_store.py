"""
FAISS Vector Store Implementation
Provides high-performance vector similarity search using Facebook AI Similarity Search (FAISS)
"""

import faiss
import numpy as np
import pickle
import threading
import time
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

from ..interfaces import (
    AbstractVectorStore,
    Chunk,
    SearchResult,
    VectorStoreException,
    VectorStoreConnectionError,
    VectorStoreOperationError
)
from ...monitoring.logger import setup_logger

logger = setup_logger(__name__)

class FaissVectorStore(AbstractVectorStore):
    """
    FAISS-based vector store implementation with persistence and thread safety
    """

    def __init__(self,
                 dimension: int,
                 index_path: str,
                 metadata_path: str,
                 similarity_threshold: float = 0.5,
                 index_type: str = "FlatL2"):
        """
        Initialize FAISS vector store

        Args:
            dimension: Embedding vector dimension
            index_path: Path to FAISS index file
            metadata_path: Path to metadata pickle file
            similarity_threshold: Minimum similarity score threshold
            index_type: FAISS index type ("FlatL2", "HNSW", "IVFFlat")
        """
        self.dimension = dimension
        self.index_path = Path(index_path)
        self.metadata_path = Path(metadata_path)
        self.similarity_threshold = similarity_threshold
        self.index_type = index_type

        # Thread safety
        self._lock = threading.RLock()

        # FAISS index and metadata storage
        self.index: Optional[faiss.Index] = None
        self.metadata: List[Dict[str, Any]] = []
        self.document_to_chunks: Dict[str, List[int]] = {}  # document_id -> chunk_ids

        # Statistics
        self._stats = {
            'total_vectors': 0,
            'total_documents': 0,
            'last_updated': None
        }

        # Create directories if needed
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize or load index
        self._initialize_index()

        logger.info(
            f"FAISS vector store initialized: {self.index_type}, "
            f"dim={dimension}, threshold={similarity_threshold}"
        )

    def _initialize_index(self):
        """Initialize or load existing FAISS index"""
        try:
            if self.index_path.exists() and self.metadata_path.exists():
                # Load existing index
                logger.info("Loading existing FAISS index...")
                self.load()
            else:
                # Create new index
                logger.info(f"Creating new FAISS index: {self.index_type}")
                self._create_new_index()

        except Exception as e:
            logger.error(f"Failed to initialize FAISS index: {str(e)}")
            # Fallback: create new index
            self._create_new_index()

    def _create_new_index(self):
        """Create a new FAISS index"""
        with self._lock:
            try:
                if self.index_type == "FlatL2":
                    # Simple brute-force search (good for small datasets)
                    self.index = faiss.IndexFlatL2(self.dimension)

                elif self.index_type == "HNSW":
                    # Hierarchical Navigable Small World (good for large datasets)
                    # M: number of connections, larger = better quality but more memory
                    M = 32
                    self.index = faiss.IndexHNSWFlat(self.dimension, M)
                    self.index.hnsw.efConstruction = 200  # Construction parameter
                    self.index.hnsw.efSearch = 50  # Search parameter

                elif self.index_type == "IVFFlat":
                    # Inverted File Index (good balance, requires training)
                    # For now, use FlatL2 as it doesn't require training data
                    logger.warning("IVFFlat requires training data, falling back to FlatL2")
                    self.index = faiss.IndexFlatL2(self.dimension)

                else:
                    logger.warning(f"Unknown index type {self.index_type}, using FlatL2")
                    self.index = faiss.IndexFlatL2(self.dimension)

                # Reset metadata
                self.metadata = []
                self.document_to_chunks = {}
                self._update_stats()

                logger.info(f"Created new {self.index_type} index with dimension {self.dimension}")

            except Exception as e:
                error_msg = f"Failed to create FAISS index: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreConnectionError(error_msg)

    def upsert(self, chunks: List[Chunk]) -> bool:
        """
        Insert or update chunks in the vector store

        Args:
            chunks: List of chunks with embeddings to store

        Returns:
            True if successful

        Raises:
            VectorStoreOperationError: If upsert operation fails
        """
        if not chunks:
            logger.warning("No chunks provided for upsert")
            return True

        start_time = time.time()

        with self._lock:
            try:
                # For true UPSERT: delete existing chunks for these documents first
                document_ids_to_upsert = set()
                for chunk in chunks:
                    document_ids_to_upsert.add(chunk.document_id)

                # Delete existing chunks for all documents being upserted
                for document_id in document_ids_to_upsert:
                    if document_id in self.document_to_chunks:
                        self.delete(document_id)
                        logger.debug(f"Deleted existing chunks for document {document_id} before upsert")

                # Convert embeddings to float32 numpy array
                embeddings = []
                chunk_metadata = []

                for chunk in chunks:
                    # Validate embedding
                    if chunk.embedding is None or len(chunk.embedding) != self.dimension:
                        raise VectorStoreOperationError(
                            f"Invalid embedding dimension: expected {self.dimension}, "
                            f"got {len(chunk.embedding) if chunk.embedding is not None else 'None'}"
                        )

                    embedding = np.array(chunk.embedding, dtype=np.float32)
                    embeddings.append(embedding)

                    # Prepare metadata
                    metadata = {
                        'document_id': chunk.document_id,
                        'text': chunk.text,  # No truncation - already handled by chunking
                        'source': chunk.source,
                        'chunk_index': chunk.chunk_index,
                        'total_chunks': chunk.total_chunks,
                        'preserve': chunk.preserve,
                        'indexed_at': datetime.utcnow().isoformat(),
                        'metadata': chunk.metadata
                    }
                    chunk_metadata.append(metadata)

                # Convert to numpy array
                embeddings_array = np.array(embeddings, dtype=np.float32)

                # Add to FAISS index
                start_idx = self.index.ntotal
                self.index.add(embeddings_array)

                # Update metadata
                for i, meta in enumerate(chunk_metadata):
                    chunk_id = start_idx + i
                    meta['chunk_id'] = chunk_id
                    self.metadata.append(meta)

                    # Track document -> chunks mapping
                    document_id = meta['document_id']
                    if document_id not in self.document_to_chunks:
                        self.document_to_chunks[document_id] = []
                    self.document_to_chunks[document_id].append(chunk_id)

                # Update statistics
                self._update_stats()

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"Upserted {len(chunks)} chunks in {duration_ms:.1f}ms. "
                    f"Total vectors: {self.index.ntotal}",
                    extra={'extra_fields': {
                        'chunk_count': len(chunks),
                        'duration_ms': duration_ms,
                        'total_vectors': self.index.ntotal,
                        'type': 'vector_upsert'
                    }}
                )

                return True

            except Exception as e:
                error_msg = f"Failed to upsert chunks: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)

    def query(self,
              vector: np.ndarray,
              top_k: int = 5,
              filter_dict: Optional[Dict[str, Any]] = None) -> List[SearchResult]:
        """
        Search for similar vectors

        Args:
            vector: Query embedding vector
            top_k: Maximum number of results to return
            filter_dict: Optional metadata filters

        Returns:
            List of search results ordered by similarity

        Raises:
            VectorStoreOperationError: If query operation fails
        """
        if self.index is None or self.index.ntotal == 0:
            logger.warning("Vector store is empty")
            return []

        start_time = time.time()

        with self._lock:
            try:
                # Validate query vector
                query_vector = np.array(vector, dtype=np.float32)
                if len(query_vector) != self.dimension:
                    raise VectorStoreOperationError(
                        f"Query vector dimension mismatch: expected {self.dimension}, "
                        f"got {len(query_vector)}"
                    )

                # Ensure vector is 2D for FAISS
                if query_vector.ndim == 1:
                    query_vector = query_vector.reshape(1, -1)

                # Search
                k = min(top_k * 2, self.index.ntotal)  # Get more results for filtering
                distances, indices = self.index.search(query_vector, k)

                # Process results
                results = []
                for dist, idx in zip(distances[0], indices[0]):
                    # Skip invalid indices
                    if idx < 0 or idx >= len(self.metadata):
                        continue

                    # Convert distance to similarity score
                    # For L2 distance, similarity = 1 / (1 + distance)
                    # Alternative: similarity = max(0, 1 - distance/2) for normalized vectors
                    similarity = max(0, 1 - dist / 2)

                    # Apply similarity threshold
                    if similarity < self.similarity_threshold:
                        continue

                    # Get metadata
                    meta = self.metadata[idx]

                    # Skip deleted chunks (fix for ghost chunks issue)
                    if meta.get('deleted', False):
                        continue

                    # Apply filters if provided
                    if filter_dict and not self._matches_filter(meta, filter_dict):
                        continue

                    # Create search result
                    result = SearchResult(
                        chunk_id=meta['chunk_id'],
                        document_id=meta['document_id'],
                        text=meta['text'],
                        source=meta['source'],
                        similarity_score=similarity,
                        chunk_index=meta['chunk_index'],
                        total_chunks=meta['total_chunks'],
                        metadata=meta.get('metadata', {})
                    )
                    results.append(result)

                    # Stop if we have enough results
                    if len(results) >= top_k:
                        break

                # Sort by similarity (highest first)
                results.sort(key=lambda x: x.similarity_score, reverse=True)

                duration_ms = (time.time() - start_time) * 1000

                logger.debug(
                    f"Query returned {len(results)} results in {duration_ms:.1f}ms",
                    extra={'extra_fields': {
                        'results_count': len(results),
                        'duration_ms': duration_ms,
                        'top_k': top_k,
                        'type': 'vector_query'
                    }}
                )

                return results

            except Exception as e:
                error_msg = f"Failed to query vectors: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)

    def _matches_filter(self, metadata: Dict[str, Any], filter_dict: Dict[str, Any]) -> bool:
        """Check if metadata matches filter conditions"""
        for key, value in filter_dict.items():
            if key not in metadata:
                return False
            if metadata[key] != value:
                return False
        return True

    def delete(self, document_id: str) -> bool:
        """
        Delete all chunks for a document

        Args:
            document_id: Document identifier

        Returns:
            True if successful

        Note: FAISS doesn't support efficient deletion, so we mark as deleted
        and rebuild index periodically or on demand
        """
        with self._lock:
            try:
                if document_id not in self.document_to_chunks:
                    logger.warning(f"Document {document_id} not found for deletion")
                    return False

                chunk_ids = self.document_to_chunks[document_id]

                # Mark chunks as deleted in metadata
                deleted_count = 0
                for chunk_id in chunk_ids:
                    if chunk_id < len(self.metadata):
                        self.metadata[chunk_id]['deleted'] = True
                        self.metadata[chunk_id]['deleted_at'] = datetime.utcnow().isoformat()
                        deleted_count += 1

                # Remove from document mapping
                del self.document_to_chunks[document_id]

                # Update statistics
                self._update_stats()

                logger.info(
                    f"Marked {deleted_count} chunks as deleted for document: {document_id}",
                    extra={'extra_fields': {
                        'document_id': document_id,
                        'deleted_count': deleted_count,
                        'type': 'vector_delete'
                    }}
                )

                # Check if we should trigger optimization (when >25% of vectors are deleted)
                deleted_count = sum(1 for meta in self.metadata if meta.get('deleted', False))
                total_count = len(self.metadata)

                if total_count > 0 and (deleted_count / total_count) > 0.25:
                    logger.info(f"Triggering automatic optimization: {deleted_count}/{total_count} vectors deleted")
                    try:
                        self.optimize()
                    except Exception as e:
                        logger.warning(f"Automatic optimization failed: {e}")
                        # Don't fail the delete operation if optimization fails

                return True

            except Exception as e:
                error_msg = f"Failed to delete document {document_id}: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)

    def get_stats(self) -> Dict[str, Any]:
        """Get vector store statistics"""
        with self._lock:
            active_vectors = sum(1 for meta in self.metadata if not meta.get('deleted', False))
            deleted_vectors = sum(1 for meta in self.metadata if meta.get('deleted', False))

            return {
                'total_vectors': self.index.ntotal if self.index else 0,
                'active_vectors': active_vectors,
                'deleted_vectors': deleted_vectors,
                'total_documents': len(self.document_to_chunks),
                'index_type': self.index_type,
                'dimension': self.dimension,
                'similarity_threshold': self.similarity_threshold,
                'last_updated': self._stats.get('last_updated'),
                'memory_usage_mb': self._estimate_memory_usage()
            }

    def _estimate_memory_usage(self) -> float:
        """Estimate memory usage in MB"""
        if not self.index:
            return 0.0

        # Rough estimation: vectors + metadata
        vector_memory = self.index.ntotal * self.dimension * 4  # float32 = 4 bytes
        metadata_memory = len(self.metadata) * 1000  # ~1KB per metadata entry
        return (vector_memory + metadata_memory) / (1024 * 1024)

    def health_check(self) -> bool:
        """Check if vector store is healthy and accessible"""
        try:
            with self._lock:
                # Check if index exists
                if self.index is None:
                    return False

                # Check if we can perform a basic operation
                if self.index.ntotal > 0:
                    # Try a simple query
                    test_vector = np.random.rand(self.dimension).astype(np.float32)
                    test_vector = test_vector.reshape(1, -1)
                    self.index.search(test_vector, 1)

                return True

        except Exception as e:
            logger.error(f"Vector store health check failed: {str(e)}")
            return False

    def persist(self) -> bool:
        """Persist current state to disk"""
        try:
            with self._lock:
                start_time = time.time()

                # Save FAISS index
                faiss.write_index(self.index, str(self.index_path))

                # Save metadata
                persist_data = {
                    'metadata': self.metadata,
                    'document_to_chunks': self.document_to_chunks,
                    'stats': self._stats,
                    'version': '1.0',
                    'saved_at': datetime.utcnow().isoformat()
                }

                with open(self.metadata_path, 'wb') as f:
                    pickle.dump(persist_data, f, protocol=pickle.HIGHEST_PROTOCOL)

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"Persisted FAISS index and metadata in {duration_ms:.1f}ms",
                    extra={'extra_fields': {
                        'vectors': self.index.ntotal,
                        'duration_ms': duration_ms,
                        'type': 'vector_persist'
                    }}
                )

                return True

        except Exception as e:
            error_msg = f"Failed to persist vector store: {str(e)}"
            logger.error(error_msg)
            raise VectorStoreConnectionError(error_msg)

    def load(self) -> bool:
        """Load state from disk"""
        try:
            with self._lock:
                start_time = time.time()

                # Load FAISS index
                self.index = faiss.read_index(str(self.index_path))

                # Load metadata
                with open(self.metadata_path, 'rb') as f:
                    persist_data = pickle.load(f)

                self.metadata = persist_data.get('metadata', [])
                self.document_to_chunks = persist_data.get('document_to_chunks', {})
                self._stats = persist_data.get('stats', {})

                # Update statistics
                self._update_stats()

                duration_ms = (time.time() - start_time) * 1000

                logger.info(
                    f"Loaded FAISS index with {self.index.ntotal} vectors in {duration_ms:.1f}ms",
                    extra={'extra_fields': {
                        'vectors': self.index.ntotal,
                        'documents': len(self.document_to_chunks),
                        'duration_ms': duration_ms,
                        'type': 'vector_load'
                    }}
                )

                return True

        except Exception as e:
            error_msg = f"Failed to load vector store: {str(e)}"
            logger.error(error_msg)
            raise VectorStoreConnectionError(error_msg)

    def _update_stats(self):
        """Update internal statistics"""
        self._stats.update({
            'total_vectors': self.index.ntotal if self.index else 0,
            'total_documents': len(self.document_to_chunks),
            'last_updated': datetime.utcnow().isoformat()
        })

    def clean_orphans(self, existing_document_ids: set = None, create_backup: bool = True) -> Dict[str, Any]:
        """
        Clean orphaned chunks whose documents no longer exist in the database.

        Args:
            existing_document_ids: Set of document_ids existing in DB (optional)
            create_backup: Create a backup before cleanup

        Returns:
            Dict with cleanup statistics

        Raises:
            VectorStoreOperationError: If cleanup fails
        """
        with self._lock:
            try:
                start_time = time.time()
                
                # Initial statistics
                initial_stats = {
                    'total_chunks': len(self.metadata),
                    'active_chunks': sum(1 for meta in self.metadata if not meta.get('deleted', False)),
                    'deleted_chunks': sum(1 for meta in self.metadata if meta.get('deleted', False)),
                    'total_documents': len(self.document_to_chunks)
                }
                
                logger.info(f"Starting orphan cleanup - Initial state: {initial_stats}")
                
                # Create backup if requested
                if create_backup:
                    backup_timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                    try:
                        self._create_backup(backup_timestamp)
                        logger.info(f"Backup created: {backup_timestamp}")
                    except Exception as e:
                        logger.warning(f"Backup creation failed: {e}")
                        # Continue despite backup failure
                
                # If no document_ids provided, retrieve from DB
                if existing_document_ids is None:
                    existing_document_ids = self._get_existing_document_ids()
                    
                # Identify orphaned chunks
                orphaned_chunks = []
                orphaned_docs = set()
                
                for meta in self.metadata:
                    doc_id = meta.get('document_id')
                    if doc_id and doc_id not in existing_document_ids:
                        if not meta.get('deleted', False):  # Not yet marked as deleted
                            orphaned_chunks.append(meta)
                            orphaned_docs.add(doc_id)
                
                if not orphaned_chunks:
                    logger.info("No orphaned chunks found")
                    return {
                        'orphaned_chunks_found': 0,
                        'orphaned_documents': 0,
                        'cleaned_chunks': 0,
                        'optimization_triggered': False,
                        'duration_ms': (time.time() - start_time) * 1000,
                        'initial_stats': initial_stats,
                        'final_stats': initial_stats  # Pas de changement
                    }
                
                logger.info(f"Found {len(orphaned_chunks)} orphaned chunks from {len(orphaned_docs)} documents")
                
                # Mark orphaned chunks as deleted
                cleaned_count = 0
                for meta in orphaned_chunks:
                    if not meta.get('deleted', False):
                        meta['deleted'] = True
                        meta['deleted_at'] = datetime.utcnow().isoformat()
                        meta['deletion_reason'] = 'orphan_cleanup'
                        cleaned_count += 1
                
                # Clean document_to_chunks mapping for orphaned documents
                for doc_id in orphaned_docs:
                    if doc_id in self.document_to_chunks:
                        del self.document_to_chunks[doc_id]
                        logger.debug(f"Removed orphaned document mapping: {doc_id}")
                
                # Determine whether to trigger optimization
                total_chunks_after = len(self.metadata)
                deleted_chunks_after = sum(1 for meta in self.metadata if meta.get('deleted', False))
                optimization_triggered = False
                
                if total_chunks_after > 0 and (deleted_chunks_after / total_chunks_after) > 0.25:
                    logger.info(f"Triggering optimization after cleanup: {deleted_chunks_after}/{total_chunks_after} chunks deleted")
                    try:
                        self.optimize()
                        optimization_triggered = True
                    except Exception as e:
                        logger.warning(f"Optimization failed after cleanup: {e}")
                        # Don't fail the cleanup if optimization fails
                
                # Save changes
                try:
                    self.persist()
                    logger.info("Orphan cleanup changes persisted successfully")
                except Exception as e:
                    logger.error(f"Failed to persist cleanup changes: {e}")
                    raise VectorStoreOperationError(f"Cleanup persistence failed: {e}")
                
                # Final statistics
                final_stats = {
                    'total_chunks': len(self.metadata),
                    'active_chunks': sum(1 for meta in self.metadata if not meta.get('deleted', False)),
                    'deleted_chunks': sum(1 for meta in self.metadata if meta.get('deleted', False)),
                    'total_documents': len(self.document_to_chunks)
                }
                
                duration_ms = (time.time() - start_time) * 1000
                
                result = {
                    'orphaned_chunks_found': len(orphaned_chunks),
                    'orphaned_documents': len(orphaned_docs),
                    'cleaned_chunks': cleaned_count,
                    'optimization_triggered': optimization_triggered,
                    'duration_ms': duration_ms,
                    'initial_stats': initial_stats,
                    'final_stats': final_stats
                }
                
                logger.info(
                    f"Orphan cleanup completed in {duration_ms:.1f}ms: "
                    f"cleaned {cleaned_count} chunks from {len(orphaned_docs)} orphaned documents",
                    extra={'extra_fields': {
                        'cleanup_result': result,
                        'type': 'orphan_cleanup'
                    }}
                )
                
                return result
                
            except Exception as e:
                error_msg = f"Orphan cleanup failed: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)
    
    def _create_backup(self, timestamp: str):
        """Create a FAISS backup with timestamp and rotate old backups"""
        try:
            import shutil

            backup_index_path = self.index_path.with_suffix(f".backup_{timestamp}")
            backup_metadata_path = self.metadata_path.with_suffix(f".backup_{timestamp}")

            if self.index_path.exists():
                shutil.copy2(self.index_path, backup_index_path)

            if self.metadata_path.exists():
                shutil.copy2(self.metadata_path, backup_metadata_path)

            logger.debug(f"Backup created: {backup_index_path}, {backup_metadata_path}")

            # Rotate old backups
            self._rotate_backups()

        except Exception as e:
            logger.error(f"Backup creation failed: {e}")
            raise

    def _rotate_backups(self):
        """Remove old backups beyond the configured max_backups limit"""
        try:
            from ...config import settings
            max_backups = settings.faiss_max_backups if settings else 4

            backup_dir = self.index_path.parent

            # Collect index backups sorted by modification time (newest first)
            index_backups = sorted(
                backup_dir.glob("index*.backup_*"),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )

            # Collect metadata backups sorted by modification time (newest first)
            metadata_backups = sorted(
                backup_dir.glob("metadata*.backup_*"),
                key=lambda f: f.stat().st_mtime,
                reverse=True
            )

            # Remove excess backups
            removed = 0
            for old_backup in index_backups[max_backups:]:
                old_backup.unlink()
                removed += 1
            for old_backup in metadata_backups[max_backups:]:
                old_backup.unlink()
                removed += 1

            if removed > 0:
                logger.info(f"Backup rotation: removed {removed} old backup files (max_backups={max_backups})")

        except Exception as e:
            logger.warning(f"Backup rotation failed: {e}")
    
    def _get_existing_document_ids(self) -> set:
        """Retrieve existing document_ids from the database."""
        try:
            # Dynamic import to avoid circular dependencies
            from ...database.connection import DatabaseManager
            from ...database.repository import DocumentRepository
            
            # Use get_session() directly rather than get_db_session() which is a generator
            db_manager = DatabaseManager()
            session = db_manager.get_session()
            try:
                doc_repo = DocumentRepository(session)
                documents = doc_repo.get_all()  # Retrieve all documents
                return {str(doc.id) for doc in documents}
            finally:
                session.close()
                
        except Exception as e:
            logger.error(f"Failed to get existing document IDs from database: {e}")
            # Fallback: use IDs present in the FAISS mapping
            return set(self.document_to_chunks.keys())

    def optimize(self):
        """
        Optimize the index by removing deleted entries (rebuild)
        This is an expensive operation and should be done periodically
        """
        with self._lock:
            if not self.index or self.index.ntotal == 0:
                logger.info("No vectors to optimize")
                return

            # Count deleted vectors
            deleted_count = sum(1 for meta in self.metadata if meta.get('deleted', False))

            if deleted_count == 0:
                logger.info("No deleted vectors to remove - optimization not needed")
                return

            logger.info(f"Starting index optimization - removing {deleted_count} deleted vectors out of {len(self.metadata)}")

            # Extract active (non-deleted) entries
            active_entries = []
            active_vectors = []

            for i, meta in enumerate(self.metadata):
                if not meta.get('deleted', False):
                    active_entries.append(meta)
                    # Get the vector from FAISS
                    if i < self.index.ntotal:
                        vector = self.index.reconstruct(i)
                        active_vectors.append(vector)

            # Create new index
            new_index = faiss.IndexFlatL2(self.dimension)

            if active_vectors:
                # Add all active vectors to new index
                vectors_array = np.array(active_vectors, dtype=np.float32)
                new_index.add(vectors_array)

                # Update chunk IDs in metadata to match new index positions
                for i, meta in enumerate(active_entries):
                    meta['chunk_id'] = i

            # Replace old index and metadata
            old_total = self.index.ntotal
            self.index = new_index
            self.metadata = active_entries

            # Clear document mapping for deleted documents
            docs_to_remove = []
            for doc_id, chunk_ids in self.document_to_chunks.items():
                # Check if any chunks for this document still exist
                remaining_chunks = [
                    cid for cid in chunk_ids
                    if any(meta.get('chunk_id') == cid and not meta.get('deleted', False)
                          for meta in self.metadata)
                ]
                if remaining_chunks:
                    self.document_to_chunks[doc_id] = remaining_chunks
                else:
                    docs_to_remove.append(doc_id)

            for doc_id in docs_to_remove:
                del self.document_to_chunks[doc_id]

            # Save optimized index
            try:
                self.persist()
                logger.info(
                    f"Index optimization completed: {old_total} → {self.index.ntotal} vectors "
                    f"({deleted_count} deleted vectors removed)"
                )
            except Exception as e:
                logger.error(f"Failed to save optimized index: {e}")
                raise VectorStoreOperationError(f"Index optimization save failed: {e}")

    def rebuild_vector_store(self, force_rebuild: bool = False, cleanup_orphans: bool = True) -> Dict[str, Any]:
        """
        Completely rebuild the vector store with optional orphan cleanup.

        Args:
            force_rebuild: Force rebuild even without deleted chunks
            cleanup_orphans: Clean orphaned chunks before rebuild

        Returns:
            Dict with rebuild statistics
        """
        with self._lock:
            try:
                start_time = time.time()
                
                logger.info(f"Starting vector store rebuild (force={force_rebuild}, cleanup_orphans={cleanup_orphans})")
                
                # Initial statistics
                initial_stats = self.get_stats()
                
                # Orphan cleanup if requested
                cleanup_result = None
                if cleanup_orphans:
                    try:
                        cleanup_result = self.clean_orphans(create_backup=True)
                        logger.info(f"Orphan cleanup completed: {cleanup_result['cleaned_chunks']} chunks cleaned")
                    except Exception as e:
                        logger.warning(f"Orphan cleanup failed during rebuild: {e}")
                        # Continue rebuild even if cleanup fails
                
                # Check if rebuild is needed
                deleted_count = sum(1 for meta in self.metadata if meta.get('deleted', False))
                total_count = len(self.metadata)
                
                rebuild_needed = force_rebuild or (total_count > 0 and deleted_count > 0)
                
                if not rebuild_needed:
                    logger.info("Rebuild not needed - no deleted chunks found")
                    duration_ms = (time.time() - start_time) * 1000
                    return {
                        'rebuild_performed': False,
                        'reason': 'no_deleted_chunks',
                        'cleanup_result': cleanup_result,
                        'duration_ms': duration_ms,
                        'initial_stats': initial_stats,
                        'final_stats': self.get_stats()
                    }
                
                # Execute optimization (rebuild)
                self.optimize()
                
                # Final statistics
                final_stats = self.get_stats()
                duration_ms = (time.time() - start_time) * 1000
                
                result = {
                    'rebuild_performed': True,
                    'cleanup_result': cleanup_result,
                    'deleted_chunks_removed': deleted_count,
                    'duration_ms': duration_ms,
                    'initial_stats': initial_stats,
                    'final_stats': final_stats
                }
                
                logger.info(
                    f"Vector store rebuild completed in {duration_ms:.1f}ms: "
                    f"removed {deleted_count} deleted chunks",
                    extra={'extra_fields': {
                        'rebuild_result': result,
                        'type': 'vector_rebuild'
                    }}
                )
                
                return result
                
            except Exception as e:
                error_msg = f"Vector store rebuild failed: {str(e)}"
                logger.error(error_msg)
                raise VectorStoreOperationError(error_msg)

    def get_document_chunks(self, document_id: str) -> List[Chunk]:
        """
        Get all chunks for a specific document

        Args:
            document_id: Document ID to retrieve chunks for

        Returns:
            List[Chunk]: List of chunks for the document
        """
        try:
            with self._lock:
                chunk_ids = self.document_to_chunks.get(document_id, [])
                chunks = []

                for chunk_id in chunk_ids:
                    # Find metadata for this chunk
                    for i, meta in enumerate(self.metadata):
                        if (meta.get('chunk_id') == chunk_id and
                            not meta.get('deleted', False) and
                            meta.get('document_id') == document_id):

                            # Retrieve the vector from FAISS
                            if i < self.index.ntotal:
                                vector = self.index.reconstruct(i)

                                # Create the Chunk object
                                chunk = Chunk(
                                    text=meta.get('text', ''),
                                    embedding=vector,
                                    document_id=document_id,
                                    chunk_index=meta.get('chunk_index', 0),
                                    total_chunks=len(chunk_ids),
                                    source=meta.get('source', ''),
                                    metadata=meta.get('metadata', {}),
                                    preserve=meta.get('preserve', False)
                                )
                                chunks.append(chunk)
                            break

                # Sort by chunk_index
                chunks.sort(key=lambda x: x.chunk_index)

                logger.debug(f"Retrieved {len(chunks)} chunks for document {document_id}")
                return chunks

        except Exception as e:
            logger.error(f"Failed to get chunks for document {document_id}: {e}")
            return []
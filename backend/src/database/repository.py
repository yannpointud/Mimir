"""
Repository pattern for persistence abstraction
Implements CRUD operations with robust error handling
"""

from typing import List, Optional, Dict, Any
from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError, IntegrityError
from sqlalchemy import and_, or_, desc, asc
from datetime import datetime, timedelta
import logging

from .models import Document, Configuration, AuditLog
from ..config import settings


logger = logging.getLogger(__name__)


class BaseRepository:
    """Base repository with common operations"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def _handle_db_error(self, e: Exception, operation: str):
        """Centralized database error handling"""
        logger.error(f"Database error during {operation}: {e}")
        self.session.rollback()


class DocumentRepository(BaseRepository):
    """
    Repository for documents
    Handles document CRUD with integrated business logic
    """
    
    def create(self, filename: str, file_hash: str, path: str = None, 
               preserve: bool = False) -> Document:
        """
        Create a new document

        Args:
            filename: File name
            file_hash: SHA-256 hash of the file
            path: Optional path
            preserve: Protection against automatic deletion

        Returns:
            Created document

        Raises:
            IntegrityError: If the hash already exists
        """
        try:
            document = Document(
                filename=filename,
                file_hash=file_hash,
                path=path,
                preserve=preserve,
                status='pending'
            )
            
            self.session.add(document)
            self.session.commit()
            self.session.refresh(document)
            
            logger.info(f"Document created: {filename} (id={document.id})")
            return document
            
        except IntegrityError as e:
            self._handle_db_error(e, f"create document {filename}")
            raise ValueError(f"Document with hash {file_hash} already exists")
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"create document {filename}")
            raise
    
    def get_by_id(self, doc_id: int) -> Optional[Document]:
        """Retrieve a document by its ID"""
        try:
            return self.session.query(Document).filter_by(id=doc_id).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get document by id {doc_id}")
            raise
    
    def get_by_hash(self, file_hash: str) -> Optional[Document]:
        """Retrieve a document by its hash (to detect duplicates)"""
        try:
            return self.session.query(Document).filter_by(file_hash=file_hash).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get document by hash {file_hash}")
            raise
    
    def get_by_status(self, status: str) -> List[Document]:
        """Retrieve all documents with a given status"""
        try:
            return self.session.query(Document).filter_by(status=status).all()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get documents by status {status}")
            raise
    
    def get_all(self, limit: int = None, offset: int = 0, 
                order_by: str = 'created_at', desc_order: bool = True) -> List[Document]:
        """
        Retrieve all documents with pagination and sorting

        Args:
            limit: Maximum number of results
            offset: Offset for pagination
            order_by: Sort field ('created_at', 'filename', 'status')
            desc_order: Descending order if True
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

    def get_all_paginated(self, offset: int = 0, limit: int = 50,
                         filters: dict = None, search: str = None) -> tuple[List['Document'], int]:
        """
        Retrieve all documents with pagination and total count

        Args:
            offset: Offset for pagination
            limit: Maximum number of results
            filters: Filters to apply (e.g., {"status": "indexed"})
            search: Search term in the filename

        Returns:
            Tuple (documents, total_count)
        """
        try:
            query = self.session.query(Document)

            # Apply filters
            if filters:
                if "status" in filters:
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

    def update_status(self, doc_id: int, status: str,
                     error_message: str = None, chunk_count: int = None):
        """
        Update a document's status

        Args:
            doc_id: Document ID
            status: New status
            error_message: Optional error message
            chunk_count: Number of chunks if indexed
        """
        try:
            document = self.get_by_id(doc_id)
            if not document:
                raise ValueError(f"Document {doc_id} not found")
            
            old_status = document.status
            document.status = status
            document.error_message = error_message
            
            if chunk_count is not None:
                document.chunk_count = chunk_count
            
            if status == 'indexed':
                document.indexed_at = datetime.utcnow()
            
            self.session.commit()
            
            logger.info(f"Document {doc_id} status updated: {old_status} -> {status}")
            
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"update document {doc_id} status")
            raise
    
    def delete(self, doc_id: int, force: bool = False) -> bool:
        """
        Delete a document

        Args:
            doc_id: Document ID
            force: Force deletion even if protected

        Returns:
            True if deleted, False otherwise
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
    
    def get_statistics(self) -> Dict[str, Any]:
        """Return statistics about documents"""
        try:
            stats = {}
            
            # Counts by status
            for status in ['pending', 'indexing', 'indexed', 'error']:
                count = self.session.query(Document).filter_by(status=status).count()
                stats[f'count_{status}'] = count
            
            # Total count
            stats['total_documents'] = self.session.query(Document).count()
            
            # Total chunks
            total_chunks = self.session.query(Document.chunk_count).filter(
                Document.status == 'indexed'
            ).all()
            stats['total_chunks'] = sum(count[0] for count in total_chunks if count[0])
            
            # Protected documents
            stats['protected_documents'] = self.session.query(Document).filter_by(
                preserve=True
            ).count()
            
            return stats
            
        except SQLAlchemyError as e:
            self._handle_db_error(e, "get document statistics")
            raise


class ConfigurationRepository(BaseRepository):
    """Repository for system configuration"""
    
    def get(self, key: str) -> Optional[Configuration]:
        """Retrieve a configuration by key"""
        try:
            return self.session.query(Configuration).filter_by(key=key).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get configuration {key}")
            raise
    
    def get_value(self, key: str, default: str = None) -> Optional[str]:
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
    
    def get_all(self) -> List[Configuration]:
        """Retrieve all configurations"""
        try:
            return self.session.query(Configuration).order_by(Configuration.key).all()
        except SQLAlchemyError as e:
            self._handle_db_error(e, "get all configurations")
            raise


class AuditLogRepository(BaseRepository):
    """Repository for audit logs"""
    
    def create_log(self, user_type: str, action: str, details: str = None,
                   ip_address: str = None, user_agent: str = None,
                   success: bool = True, additional_data: dict = None) -> AuditLog:
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
                success=success
            )
            
            self.session.add(log_entry)
            self.session.commit()
            self.session.refresh(log_entry)
            
            return log_entry
            
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"create audit log {action}")
            raise
    
    def get_logs(self, user_type: str = None, action: str = None,
                 limit: int = 100, offset: int = 0) -> List[AuditLog]:
        """
        Retrieve audit logs with filters

        Args:
            user_type: Filter by user type
            action: Filter by action
            limit: Maximum number of results
            offset: Offset for pagination
        """
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
    
    def cleanup_old_logs(self, days_to_keep: int = 90) -> int:
        """
        Clean up old audit logs

        Args:
            days_to_keep: Number of days to retain

        Returns:
            Number of deleted logs
        """
        try:
            cutoff_date = datetime.utcnow() - timedelta(days=days_to_keep)
            
            deleted_count = self.session.query(AuditLog).filter(
                AuditLog.created_at < cutoff_date
            ).delete()
            
            self.session.commit()
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} old audit logs")
            
            return deleted_count
            
        except SQLAlchemyError as e:
            self._handle_db_error(e, "cleanup audit logs")
            raise


# Factory function to create repositories with a session

def create_repositories(session: Session) -> Dict[str, Any]:
    """
    Factory to create all repositories with a given session

    Returns:
        Dictionary containing all repositories
    """
    return {
        'document': DocumentRepository(session),
        'config': ConfigurationRepository(session),
        'audit': AuditLogRepository(session)
    }
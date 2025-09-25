"""
Pattern Repository pour l'abstraction de la persistance
Implémente les opérations CRUD avec gestion d'erreurs robuste
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
    """Repository de base avec opérations communes"""
    
    def __init__(self, session: Session):
        self.session = session
    
    def _handle_db_error(self, e: Exception, operation: str):
        """Gestion centralisée des erreurs de base de données"""
        logger.error(f"Database error during {operation}: {e}")
        self.session.rollback()


class DocumentRepository(BaseRepository):
    """
    Repository pour les documents
    Gère le CRUD des documents avec logique métier intégrée
    """
    
    def create(self, filename: str, file_hash: str, path: str = None, 
               preserve: bool = False) -> Document:
        """
        Crée un nouveau document
        
        Args:
            filename: Nom du fichier
            file_hash: Hash SHA-256 du fichier
            path: Chemin optionnel
            preserve: Protection contre suppression automatique
            
        Returns:
            Document créé
            
        Raises:
            IntegrityError: Si le hash existe déjà
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
        """Récupère un document par son ID"""
        try:
            return self.session.query(Document).filter_by(id=doc_id).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get document by id {doc_id}")
            raise
    
    def get_by_hash(self, file_hash: str) -> Optional[Document]:
        """Récupère un document par son hash (pour détecter doublons)"""
        try:
            return self.session.query(Document).filter_by(file_hash=file_hash).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get document by hash {file_hash}")
            raise
    
    def get_by_status(self, status: str) -> List[Document]:
        """Récupère tous les documents d'un statut donné"""
        try:
            return self.session.query(Document).filter_by(status=status).all()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get documents by status {status}")
            raise
    
    def get_all(self, limit: int = None, offset: int = 0, 
                order_by: str = 'created_at', desc_order: bool = True) -> List[Document]:
        """
        Récupère tous les documents avec pagination et tri
        
        Args:
            limit: Nombre maximum de résultats
            offset: Décalage pour pagination
            order_by: Champ de tri ('created_at', 'filename', 'status')
            desc_order: Tri descendant si True
        """
        try:
            query = self.session.query(Document)
            
            # Tri
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
        Récupère tous les documents avec pagination et compte total

        Args:
            offset: Décalage pour pagination
            limit: Nombre maximum de résultats
            filters: Filtres à appliquer (ex: {"status": "indexed"})
            search: Terme de recherche dans le nom de fichier

        Returns:
            Tuple (documents, total_count)
        """
        try:
            query = self.session.query(Document)

            # Appliquer les filtres
            if filters:
                if "status" in filters:
                    query = query.filter(Document.status == filters["status"])

            # Appliquer la recherche
            if search:
                query = query.filter(Document.filename.ilike(f"%{search}%"))

            # Compter le total avant pagination
            total_count = query.count()

            # Appliquer la pagination et le tri
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
        Met à jour le statut d'un document
        
        Args:
            doc_id: ID du document
            status: Nouveau statut
            error_message: Message d'erreur optionnel
            chunk_count: Nombre de chunks si indexé
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
        Supprime un document
        
        Args:
            doc_id: ID du document
            force: Force la suppression même si protégé
            
        Returns:
            True si supprimé, False sinon
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
        """Retourne des statistiques sur les documents"""
        try:
            stats = {}
            
            # Comptes par statut
            for status in ['pending', 'indexing', 'indexed', 'error']:
                count = self.session.query(Document).filter_by(status=status).count()
                stats[f'count_{status}'] = count
            
            # Total
            stats['total_documents'] = self.session.query(Document).count()
            
            # Total des chunks
            total_chunks = self.session.query(Document.chunk_count).filter(
                Document.status == 'indexed'
            ).all()
            stats['total_chunks'] = sum(count[0] for count in total_chunks if count[0])
            
            # Documents protégés
            stats['protected_documents'] = self.session.query(Document).filter_by(
                preserve=True
            ).count()
            
            return stats
            
        except SQLAlchemyError as e:
            self._handle_db_error(e, "get document statistics")
            raise


class ConfigurationRepository(BaseRepository):
    """Repository pour la configuration système"""
    
    def get(self, key: str) -> Optional[Configuration]:
        """Récupère une configuration par clé"""
        try:
            return self.session.query(Configuration).filter_by(key=key).first()
        except SQLAlchemyError as e:
            self._handle_db_error(e, f"get configuration {key}")
            raise
    
    def get_value(self, key: str, default: str = None) -> Optional[str]:
        """Récupère la valeur d'une configuration"""
        config = self.get(key)
        return config.value if config else default
    
    def set(self, key: str, value: str) -> Configuration:
        """Définit ou met à jour une configuration"""
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
        """Supprime une configuration"""
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
        """Récupère toutes les configurations"""
        try:
            return self.session.query(Configuration).order_by(Configuration.key).all()
        except SQLAlchemyError as e:
            self._handle_db_error(e, "get all configurations")
            raise


class AuditLogRepository(BaseRepository):
    """Repository pour les logs d'audit"""
    
    def create_log(self, user_type: str, action: str, details: str = None,
                   ip_address: str = None, user_agent: str = None,
                   success: bool = True, additional_data: dict = None) -> AuditLog:
        """Crée un nouveau log d'audit"""
        try:
            # Note: additional_data est accepté pour compatibilité mais non persisté
            # Dans une future version, on pourrait ajouter ce champ au modèle
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
        Récupère les logs d'audit avec filtres
        
        Args:
            user_type: Filtrer par type d'utilisateur
            action: Filtrer par action
            limit: Nombre maximum de résultats
            offset: Décalage pour pagination
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
        Nettoie les anciens logs d'audit
        
        Args:
            days_to_keep: Nombre de jours à conserver
            
        Returns:
            Nombre de logs supprimés
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


# Factory function pour créer les repositories avec session

def create_repositories(session: Session) -> Dict[str, Any]:
    """
    Factory pour créer tous les repositories avec une session donnée
    
    Returns:
        Dictionnaire contenant tous les repositories
    """
    return {
        'document': DocumentRepository(session),
        'config': ConfigurationRepository(session),
        'audit': AuditLogRepository(session)
    }
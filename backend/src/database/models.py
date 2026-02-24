"""
SQLAlchemy models for Mimir
Defines table structure according to LLD specifications
"""

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Text, 
    ForeignKey, CheckConstraint, Index
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime
from typing import Dict, Any, Optional


Base = declarative_base()


class Document(Base):
    """
    Indexed documents table
    Follows the schema defined in the LLD with status management and preservation
    """
    __tablename__ = 'documents'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    filename = Column(String(255), nullable=False, index=True)
    path = Column(String(500), nullable=True)
    file_hash = Column(String(64), unique=True, nullable=False, index=True)
    status = Column(
        String(20), 
        nullable=False, 
        default='pending',
        index=True
    )
    error_message = Column(Text, nullable=True)
    chunk_count = Column(Integer, default=0, nullable=False)
    preserve = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    indexed_at = Column(DateTime, nullable=True)
    
    # Constraint on valid statuses
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'indexing', 'indexed', 'error')",
            name='check_document_status'
        ),
        Index('idx_document_status_created', 'status', 'created_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a dictionary for serialization"""
        return {
            'id': self.id,
            'filename': self.filename,
            'path': self.path,
            'file_hash': self.file_hash,
            'status': self.status,
            'error_message': self.error_message,
            'chunk_count': self.chunk_count,
            'preserve': self.preserve,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'indexed_at': self.indexed_at.isoformat() if self.indexed_at else None
        }
    
    def is_indexed(self) -> bool:
        """Check if the document is successfully indexed"""
        return self.status == 'indexed' and self.chunk_count > 0
    
    def is_processing(self) -> bool:
        """Check if the document is being processed"""
        return self.status in ['pending', 'indexing']
    
    def has_error(self) -> bool:
        """Check if the document has an error"""
        return self.status == 'error'
    
    def __repr__(self):
        return f"<Document(id={self.id}, filename='{self.filename}', status='{self.status}')>"


class Configuration(Base):
    """
    System configuration table
    Key-value storage for dynamic parameters
    """
    __tablename__ = 'configuration'
    
    key = Column(String(100), primary_key=True)
    value = Column(Text, nullable=False)
    updated_at = Column(
        DateTime, 
        default=datetime.utcnow, 
        onupdate=datetime.utcnow, 
        nullable=False,
        index=True
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a dictionary"""
        return {
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat()
        }
    
    @staticmethod
    def get_typed_value(value: str, value_type: str = 'string'):
        """
        Convert a string value to the appropriate type
        Useful for retrieving typed configs
        """
        if value_type == 'bool':
            return value.lower() in ('true', '1', 'yes', 'on')
        elif value_type == 'int':
            return int(value)
        elif value_type == 'float':
            return float(value)
        else:
            return value
    
    def __repr__(self):
        return f"<Configuration(key='{self.key}', updated_at='{self.updated_at}')>"


class AuditLog(Base):
    """
    Audit table for action traceability
    Follows security specifications with logging of critical actions
    """
    __tablename__ = 'audit_log'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_type = Column(String(20), nullable=False, index=True)
    action = Column(String(100), nullable=False, index=True)
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)  # Support IPv6
    user_agent = Column(Text, nullable=True)
    success = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Constraint on valid user types
    __table_args__ = (
        CheckConstraint(
            "user_type IN ('admin', 'user', 'system')",
            name='check_user_type'
        ),
        Index('idx_audit_user_action_date', 'user_type', 'action', 'created_at'),
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert the model to a dictionary"""
        return {
            'id': self.id,
            'user_type': self.user_type,
            'action': self.action,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'success': self.success,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def create_admin_action(cls, action: str, details: str = None, 
                          ip_address: str = None, success: bool = True):
        """Factory method to create admin action logs"""
        return cls(
            user_type='admin',
            action=action,
            details=details,
            ip_address=ip_address,
            success=success
        )
    
    @classmethod
    def create_user_action(cls, action: str, details: str = None, 
                         ip_address: str = None, success: bool = True):
        """Factory method to create user action logs"""
        return cls(
            user_type='user',
            action=action,
            details=details,
            ip_address=ip_address,
            success=success
        )
    
    @classmethod
    def create_system_action(cls, action: str, details: str = None, 
                           success: bool = True):
        """Factory method to create system action logs"""
        return cls(
            user_type='system',
            action=action,
            details=details,
            success=success
        )
    
    def __repr__(self):
        return (f"<AuditLog(id={self.id}, user_type='{self.user_type}', "
                f"action='{self.action}', created_at='{self.created_at}')>")


# Utility functions for models

def create_tables(engine):
    """Create all tables in the database"""
    Base.metadata.create_all(bind=engine)


def drop_tables(engine):
    """Drop all tables from the database (for tests)"""
    Base.metadata.drop_all(bind=engine)
# -*- coding: utf-8 -*-
"""
021kp.com GEO System - Custom Exception Hierarchy
============================================================

Design:
    - All business errors inherit from GEOError (root)
    - Each module has its own specific exception type
    - Error codes enable programmatic handling (not string matching)

Usage:
    from exceptions import DatabaseError, ConfigurationError
    
    try:
        db.connect()
    except DatabaseError.ConnectionFailed as e:
        logger.error(f"DB连接失败: {e.error_code}")
"""

from typing import Optional, Any


class GEOError(Exception):
    """
    Root exception for all GEO Pipeline errors.
    
    Attributes:
        error_code: Machine-readable error code (e.g., "DB-001")
        message: Human-readable error description
        details: Optional additional context dict
    """
    
    error_code = "GEO-000"
    
    def __init__(self, message: str = "", error_code: Optional[str] = None, 
                 details: Optional[dict] = None):
        self.message = message or "未知错误"
        self.error_code = error_code or self.error_code
        self.details = details or {}
        super().__init__(self.message)
    
    def to_dict(self) -> dict:
        """Serialize to API-friendly dict format"""
        return {
            "error": self.__class__.__name__,
            "error_code": self.error_code,
            "message": self.message,
            **({"details": self.details} if self.details else {})
        }


# ==================== Database Errors ====================

class DatabaseError(GEOError):
    """Database operation failure base class"""
    error_code = "DB-000"


class ConnectionFailedError(DatabaseError):
    """Cannot establish database connection"""
    error_code = "DB-001"


class QueryExecutionError(DatabaseError):
    """SQL query execution failed"""
    error_code = "DB-002"


class TransactionRollbackError(DatabaseError):
    """Transaction rolled back due to constraint violation or deadlock"""
    error_code = "DB-003"


# ==================== Configuration Errors ====================

class ConfigurationError(GEOError):
    """Invalid or missing configuration"""
    error_code = "CFG-000"


class ConfigFileNotFoundError(ConfigurationError):
    """Required configuration file not found"""
    error_code = "CFG-001"


class ConfigValidationError(ConfigurationError):
    """Configuration value fails validation rules"""
    error_code = "CFG-002"


# ==================== Compliance Errors ====================

class ComplianceError(GEOError):
    """Compliance gate check failed"""
    error_code = "CMP-000"


class BanWordDetectedError(ComplianceError):
    """Content contains prohibited keywords"""
    error_code = "CMP-001"


# ==================== API & Routing Errors ====================

class APIError(GEOError):
    """Platform API call failure base class"""
    error_code = "API-000"


class RateLimitedError(APIError):
    """Request rate limit exceeded"""
    error_code = "API-001"


class AuthenticationError(APIError):
    """Platform authentication/credential failure"""
    error_code = "API-002"


class CircuitOpenError(APIError):
    """Circuit breaker is open - platform unavailable"""
    error_code = "API-003"


# ==================== Validation Errors ====================

class ValidationError(GEOError):
    """Input data validation failure"""
    error_code = "VAL-000"


class InvalidJobDataError(ValidationError):
    """Job record data is invalid or incomplete"""
    error_code = "VAL-001"


class InvalidParameterError(ValidationError):
    """API parameter is invalid or out of range"""
    error_code = "VAL-002"

"""
Custom exceptions for the Real-Time Data Collection and Monitoring System.

Provides specific exception types for better error handling and debugging.
"""

from typing import Any, Optional


class SensorDataError(Exception):
    """Base exception for sensor data related errors."""

    pass


class DatabaseError(SensorDataError):
    """Exception raised for database-related errors."""

    def __init__(self, message: str, original_error: Optional[Exception] = None) -> None:
        super().__init__(message)
        self.original_error = original_error
        self.message = message


class ValidationError(SensorDataError):
    """Exception raised for data validation errors."""

    def __init__(
        self, message: str, field: Optional[str] = None, value: Any = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.field = field
        self.value = value


class ServiceConnectionError(SensorDataError):
    """Exception raised for connection-related errors."""

    def __init__(self, message: str, service: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.service = service


class ConfigurationError(SensorDataError):
    """Exception raised for configuration-related errors."""

    def __init__(self, message: str, config_key: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.config_key = config_key

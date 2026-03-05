"""
Structured logging configuration for the Real-Time Data Collection and Monitoring System.

Provides JSON-formatted logging with request ID tracking and log levels.
"""

import logging
import json
import sys
import os
from datetime import datetime
from typing import Any, Dict
import uuid
from contextvars import ContextVar

# Request ID context variable
request_id_var: ContextVar[str] = ContextVar('request_id', default='')


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'logger': record.name,
            'message': record.getMessage(),
            'module': record.module,
            'function': record.funcName,
            'line': record.lineno,
        }

        # Add request ID if available
        request_id = request_id_var.get()
        if request_id:
            log_data['request_id'] = request_id

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        # Add extra fields
        if hasattr(record, 'extra_fields'):
            log_data.update(record.extra_fields)

        return json.dumps(log_data)


def setup_logging(
    level: str = None,
    format_type: str = 'json',
    enable_request_id: bool = True,
) -> None:
    """
    Set up logging configuration.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        format_type: Log format ('json' or 'text')
        enable_request_id: Whether to enable request ID tracking
    """
    log_level = level or os.getenv('LOG_LEVEL', 'INFO').upper()
    
    # Get root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, log_level, logging.INFO))

    # Remove existing handlers
    root_logger.handlers.clear()

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, log_level, logging.INFO))

    # Set formatter
    if format_type == 'json':
        formatter = JSONFormatter()
    else:
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # Set levels for third-party libraries
    logging.getLogger('uvicorn').setLevel(logging.WARNING)
    logging.getLogger('uvicorn.access').setLevel(logging.WARNING)
    logging.getLogger('asyncpg').setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger instance.

    Args:
        name: Logger name

    Returns:
        Logger instance
    """
    return logging.getLogger(name)


def set_request_id(request_id: str = None) -> str:
    """
    Set request ID for current context.

    Args:
        request_id: Request ID (generates new if None)

    Returns:
        Request ID
    """
    if request_id is None:
        request_id = str(uuid.uuid4())
    request_id_var.set(request_id)
    return request_id


def get_request_id() -> str:
    """
    Get current request ID.

    Returns:
        Request ID or empty string
    """
    return request_id_var.get()


class RequestIDMiddleware:
    """Middleware to add request ID to logs."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] == 'http':
            # Generate request ID
            request_id = set_request_id()
            
            # Add request ID to response headers
            async def send_wrapper(message):
                if message['type'] == 'http.response.start':
                    message.setdefault('headers', [])
                    message['headers'].append([b'x-request-id', request_id.encode()])
                await send(message)

            await self.app(scope, receive, send_wrapper)
        else:
            await self.app(scope, receive, send)

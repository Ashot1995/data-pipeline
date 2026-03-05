"""
Prometheus metrics for the Real-Time Data Collection and Monitoring System.

Exposes metrics for monitoring API performance, database operations, and system health.
"""

import re
import time
from typing import Optional
from prometheus_client import Counter, Histogram, Gauge, generate_latest, REGISTRY
from fastapi import Response
from fastapi.responses import PlainTextResponse

# Request metrics
http_requests_total = Counter(
    'http_requests_total',
    'Total number of HTTP requests',
    ['method', 'endpoint', 'status']
)

http_request_duration_seconds = Histogram(
    'http_request_duration_seconds',
    'HTTP request duration in seconds',
    ['method', 'endpoint'],
    buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 2.5, 5.0, 10.0]
)

# Database metrics
db_operations_total = Counter(
    'db_operations_total',
    'Total number of database operations',
    ['operation', 'status']
)

db_operation_duration_seconds = Histogram(
    'db_operation_duration_seconds',
    'Database operation duration in seconds',
    ['operation'],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 2.0]
)

db_connection_pool_size = Gauge(
    'db_connection_pool_size',
    'Database connection pool size',
    ['state']  # active, idle, total
)

# Data ingestion metrics
sensor_data_ingested_total = Counter(
    'sensor_data_ingested_total',
    'Total number of sensor data records ingested',
    ['sensor_type']
)

sensor_data_latency_ms = Histogram(
    'sensor_data_latency_ms',
    'Sensor data ingestion latency in milliseconds',
    buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000]
)

# Cache metrics
cache_operations_total = Counter(
    'cache_operations_total',
    'Total number of cache operations',
    ['operation', 'status']  # hit, miss, error
)

cache_operation_duration_seconds = Histogram(
    'cache_operation_duration_seconds',
    'Cache operation duration in seconds',
    ['operation']
)

# System metrics
active_connections = Gauge(
    'active_connections',
    'Number of active connections'
)

data_generator_status = Gauge(
    'data_generator_status',
    'Data generator status (1 = running, 0 = stopped)'
)


class MetricsMiddleware:
    """Middleware to track HTTP request metrics."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            await self.app(scope, receive, send)
            return

        method = scope['method']
        path = scope['path']
        
        # Normalize path for metrics (remove IDs)
        endpoint = self._normalize_path(path)
        
        start_time = time.time()
        status_code = 200

        async def send_wrapper(message):
            nonlocal status_code
            if message['type'] == 'http.response.start':
                status_code = message['status']
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.time() - start_time
            http_requests_total.labels(method=method, endpoint=endpoint, status=status_code).inc()
            http_request_duration_seconds.labels(method=method, endpoint=endpoint).observe(duration)

    @staticmethod
    def _normalize_path(path: str) -> str:
        """Normalize path by replacing IDs with placeholders."""
        # Replace numeric IDs
        path = re.sub(r'/\d+', '/{id}', path)
        # Replace UUIDs
        path = re.sub(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', '/{uuid}', path)
        return path


def record_db_operation(operation: str, duration: float, status: str = 'success'):
    """Record a database operation metric."""
    db_operations_total.labels(operation=operation, status=status).inc()
    db_operation_duration_seconds.labels(operation=operation).observe(duration)


def record_sensor_data_ingestion(latency_ms: Optional[float] = None):
    """Record sensor data ingestion metric."""
    sensor_data_ingested_total.labels(sensor_type='combined').inc()
    if latency_ms is not None:
        sensor_data_latency_ms.observe(latency_ms)


def record_cache_operation(operation: str, status: str, duration: float):
    """Record a cache operation metric."""
    cache_operations_total.labels(operation=operation, status=status).inc()
    cache_operation_duration_seconds.labels(operation=operation).observe(duration)


def update_connection_pool_metrics(active: int, idle: int, total: int):
    """Update connection pool metrics."""
    db_connection_pool_size.labels(state='active').set(active)
    db_connection_pool_size.labels(state='idle').set(idle)
    db_connection_pool_size.labels(state='total').set(total)


def get_metrics_response() -> Response:
    """Get Prometheus metrics response."""
    return PlainTextResponse(content=generate_latest(REGISTRY), media_type='text/plain')

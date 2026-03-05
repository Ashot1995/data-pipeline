"""
FastAPI application for Real-Time Data Collection and Monitoring System.

Provides REST API endpoints for sensor data ingestion, retrieval, and latency tracking.
Integrates MQTT subscriber, Kafka consumer, Redis caching, and Prometheus metrics.
"""

import asyncio
import csv
import io
import json
import logging
import math
import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

import asyncpg
import numpy as np
from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from anomaly_detection import detect_anomalies as run_anomaly_detection, get_anomaly_detector
from auth import (
    JWT_EXPIRATION_HOURS,
    generate_jwt_token,
    get_current_user,
    verify_password,
    hash_password,
)
from cache import (
    cache_aggregated_data,
    cache_recent_data,
    close_redis,
    get_cached_aggregated_data,
    get_cached_recent_data,
    invalidate_data_cache,
)
from database import (
    close_db,
    get_aggregated_data,
    get_devices,
    get_export_data,
    get_latency_stats,
    get_recent_data,
    init_db,
    insert_sensor_data,
    update_pool_metrics,
)
from exceptions import DatabaseError, ValidationError, ServiceConnectionError
from logging_config import RequestIDMiddleware, get_request_id, setup_logging
from metrics import MetricsMiddleware, get_metrics_response, record_sensor_data_ingestion
from rate_limit import check_rate_limit

setup_logging()
logger = logging.getLogger(__name__)


def _to_python(obj):
    """Recursively convert numpy scalar types to Python native types for JSON serialisation."""
    if isinstance(obj, dict):
        return {k: _to_python(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_python(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    return obj

# Demo users for /auth/token endpoint (in production, store in DB with hashed passwords)
_DEMO_USERS = {
    "admin": hash_password("admin"),
    "user": hash_password("password"),
}


# ── WebSocket connection manager ───────────────────────────────────────────────

class _ConnectionManager:
    """Manages active WebSocket connections for the live data stream."""

    def __init__(self) -> None:
        self._active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._active.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        self._active.discard(ws)

    async def broadcast(self, payload: Dict[str, Any]) -> None:
        dead: Set[WebSocket] = set()
        for ws in self._active:
            try:
                await ws.send_json(payload)
            except Exception:
                dead.add(ws)
        self._active -= dead


_ws_manager = _ConnectionManager()

# Kafka thread executor
_kafka_executor: Optional[ThreadPoolExecutor] = None


def _make_sensor_payload_handler(loop: asyncio.AbstractEventLoop):
    """Return a sync callback that schedules async DB inserts on the given event loop."""

    def handler(payload: dict):
        try:
            temperature = float(payload.get("temperature", 0.0))
            humidity = float(payload.get("humidity", 0.0))
            gas = float(payload.get("gas", 0.0))
            sent_ts = payload.get("sent_timestamp")
            received_ts = datetime.now().isoformat()
            asyncio.run_coroutine_threadsafe(
                insert_sensor_data(
                    temperature=temperature,
                    humidity=humidity,
                    gas=gas,
                    sent_timestamp=sent_ts,
                    received_timestamp=received_ts,
                ),
                loop,
            )
        except Exception as exc:
            logger.error("Error scheduling DB insert from message: %s", exc)

    return handler


@asynccontextmanager
async def lifespan(app: FastAPI) -> Any:
    """Application lifespan manager."""
    global _kafka_executor
    _pool_metrics_task: Optional[asyncio.Task] = None

    # ── Startup ──────────────────────────────────────────────────────────────
    logger.info("Starting application...")
    try:
        await init_db()
        logger.info("Database initialised")
    except Exception as exc:
        logger.error("Failed to initialise database: %s", exc, exc_info=True)
        raise

    loop = asyncio.get_running_loop()
    payload_handler = _make_sensor_payload_handler(loop)

    # MQTT subscriber (optional)
    if os.getenv("MQTT_ENABLED", "false").lower() == "true":
        try:
            from mqtt_client import initialize_mqtt
            initialize_mqtt(message_callback=payload_handler)
            logger.info("MQTT subscriber started (topic: %s)", os.getenv("MQTT_TOPIC", "sensors/data"))
        except Exception as exc:
            logger.warning("MQTT startup failed (non-fatal): %s", exc)

    # Kafka consumer (optional, runs in a background thread)
    if os.getenv("KAFKA_ENABLED", "false").lower() == "true":
        try:
            from kafka_client import initialize_kafka_consumer, KAFKA_TOPIC
            consumer = initialize_kafka_consumer(
                topics=[KAFKA_TOPIC],
                message_callback=payload_handler,
            )
            _kafka_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="kafka-consumer")
            loop.run_in_executor(_kafka_executor, consumer.start)
            logger.info("Kafka consumer started (topic: %s)", KAFKA_TOPIC)
        except Exception as exc:
            logger.warning("Kafka startup failed (non-fatal): %s", exc)

    # Background task: update DB connection pool metrics for Prometheus
    async def _pool_metrics_loop() -> None:
        while True:
            try:
                await update_pool_metrics()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.debug("Pool metrics loop: %s", exc)
            await asyncio.sleep(15)

    _pool_metrics_task = asyncio.create_task(_pool_metrics_loop())
    logger.info("Application started successfully")
    yield

    # ── Shutdown ─────────────────────────────────────────────────────────────
    logger.info("Shutting down application...")

    if os.getenv("MQTT_ENABLED", "false").lower() == "true":
        try:
            from mqtt_client import stop_mqtt
            stop_mqtt()
        except Exception:
            pass

    if os.getenv("KAFKA_ENABLED", "false").lower() == "true":
        try:
            from kafka_client import stop_kafka
            stop_kafka()
        except Exception:
            pass

    if _kafka_executor:
        _kafka_executor.shutdown(wait=False)

    if _pool_metrics_task and not _pool_metrics_task.done():
        _pool_metrics_task.cancel()
        try:
            await _pool_metrics_task
        except asyncio.CancelledError:
            pass

    await close_db()
    await close_redis()
    logger.info("Application shut down")


app = FastAPI(
    title="Real-Time Data Collection and Monitoring System API",
    description="API for collecting and monitoring sensor data (temperature, humidity, gas)",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(MetricsMiddleware)


# ── Pydantic Models ───────────────────────────────────────────────────────────

class SensorDataInput(BaseModel):
    """Input model for sensor data ingestion (spec §4.2)."""
    device_id: str = Field(..., min_length=1, max_length=64, description="Unique device identifier")
    timestamp: str = Field(..., description="ISO 8601 timestamp of the measurement")
    temperature: float = Field(..., ge=-50.0, le=100.0, description="Temperature in Celsius")
    humidity: float = Field(..., ge=0.0, le=100.0, description="Humidity percentage")
    gas_level: float = Field(..., ge=0.0, le=1000.0, description="Gas concentration in PPM")
    sent_timestamp: Optional[str] = Field(None, description="ISO 8601 timestamp when data was sent")

    @field_validator("temperature", "humidity", "gas_level")
    @classmethod
    def validate_finite(cls, v):
        if math.isnan(v):
            raise ValueError("Value cannot be NaN")
        if math.isinf(v):
            raise ValueError("Value cannot be infinity")
        return v


class SensorDataResponse(BaseModel):
    id: int
    device_id: Optional[str]
    temperature: float
    humidity: float
    gas: float  # database column name remains 'gas'
    sent_timestamp: Optional[str]
    received_timestamp: Optional[str]
    stored_timestamp: str
    latency_ms: Optional[float]


class AggregatedDataResponse(BaseModel):
    time_bucket: Optional[str]
    avg_temperature: Optional[float]
    avg_humidity: Optional[float]
    avg_gas: Optional[float]
    count: int


class HealthResponse(BaseModel):
    status: str
    database: str


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


# ── Core Endpoints ────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    """API information endpoint."""
    return {
        "name": "Real-Time Data Collection and Monitoring System API",
        "version": "1.0.0",
        "description": "API for collecting and monitoring sensor data",
        "endpoints": {
            "health": "/health",
            "ingest": "POST /api/data",
            "recent": "GET /api/data/recent",
            "aggregated": "GET /api/data/aggregated",
            "latency_stats": "GET /api/latency/stats",
            "anomaly_stats": "GET /api/anomaly/stats",
            "mqtt_status": "GET /api/mqtt/status",
            "mqtt_publish": "POST /api/mqtt/publish",
            "kafka_status": "GET /api/kafka/status",
            "kafka_publish": "POST /api/kafka/publish",
            "metrics": "GET /metrics",
            "auth_token": "POST /auth/token",
        },
    }


@app.get("/health")
async def health_check():
    """Health check endpoint. Returns 200 when healthy, 503 when unhealthy."""
    try:
        from database import db_pool
        if db_pool and not db_pool.is_closing():
            async with db_pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return JSONResponse(
                status_code=200,
                content={"status": "healthy", "database": "connected"},
            )
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": "not_connected"},
        )
    except Exception as exc:
        logger.error("Health check failed: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=503,
            content={"status": "unhealthy", "database": f"error: {exc}"},
        )


@app.post("/api/data", response_model=dict)
async def receive_sensor_data(data: SensorDataInput, request: Request):
    """Receive sensor data from Arduino, data generator, or MQTT/Kafka bridge."""
    request_id = get_request_id()

    if os.getenv("ENABLE_RATE_LIMITING", "false").lower() == "true":
        check_rate_limit(request)

    received_at = datetime.now(tz=timezone.utc)
    received_timestamp = received_at.isoformat()

    # Compute latency_ms from sent_timestamp → received_at
    latency_ms: Optional[float] = None
    if data.sent_timestamp:
        try:
            sent_dt = datetime.fromisoformat(data.sent_timestamp.replace("Z", "+00:00"))
            # Ensure both are timezone-aware (UTC) before subtraction
            if sent_dt.tzinfo is None:
                sent_dt = sent_dt.replace(tzinfo=timezone.utc)
            latency_ms = (received_at - sent_dt).total_seconds() * 1000
        except Exception as exc:
            logger.warning("Could not calculate latency: %s", exc)

    try:
        record_id = await insert_sensor_data(
            temperature=data.temperature,
            humidity=data.humidity,
            gas=data.gas_level,
            sent_timestamp=data.sent_timestamp,
            received_timestamp=received_timestamp,
            latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
            device_id=data.device_id,
        )
        record_sensor_data_ingestion(latency_ms=latency_ms)
        await invalidate_data_cache()

        stored_at = datetime.now(tz=timezone.utc)
        stored_timestamp = stored_at.isoformat()

        anomaly_result = None
        try:
            anomaly_result = _to_python(run_anomaly_detection(
                temperature=data.temperature,
                humidity=data.humidity,
                gas=data.gas_level,
            ))
            if any(anomaly_result["anomalies"].values()):
                logger.warning("Anomaly detected: %s", anomaly_result["anomalies"])
        except Exception as exc:
            logger.warning("Anomaly detection failed (non-fatal): %s", exc)

        # Structured JSON log per ingestion attempt (FR-1.4)
        logger.info(
            "ingestion",
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "device_id": data.device_id,
                    "status_code": 200,
                    "latency_ms": round(latency_ms, 3) if latency_ms is not None else None,
                    "record_id": record_id,
                }
            },
        )

        response_payload = {
            "status": "success",
            "id": record_id,
            "device_id": data.device_id,
            "data": {
                "temperature": data.temperature,
                "humidity": data.humidity,
                "gas_level": data.gas_level,
            },
            "timestamps": {
                "client": data.sent_timestamp,
                "received": received_timestamp,
                "stored": stored_timestamp,
                "latency_ms": round(latency_ms, 2) if latency_ms is not None else None,
            },
            "anomaly_detection": anomaly_result,
        }

        # Broadcast to any connected WebSocket clients (non-blocking, best-effort)
        asyncio.create_task(_ws_manager.broadcast(response_payload))

        return response_payload
    except asyncpg.PostgresError as exc:
        # Structured log for DB errors (FR-1.4)
        logger.error(
            "ingestion_db_error",
            exc_info=True,
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "device_id": data.device_id,
                    "status_code": 500,
                    "latency_ms": None,
                    "error": str(exc),
                }
            },
        )
        raise HTTPException(status_code=500, detail="Database error: Failed to store data")
    except Exception as exc:
        logger.error(
            "ingestion_unexpected_error",
            exc_info=True,
            extra={
                "extra_fields": {
                    "request_id": request_id,
                    "device_id": data.device_id,
                    "status_code": 500,
                    "latency_ms": None,
                    "error": str(exc),
                }
            },
        )
        raise HTTPException(status_code=500, detail=f"Failed to store data: {exc}")


@app.get("/api/data/recent", response_model=List[SensorDataResponse])
async def get_recent_sensor_data(limit: int = 100):
    """Get recent sensor data records."""
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 1000")
    try:
        cached = await get_cached_recent_data(limit)
        if cached:
            return [SensorDataResponse(**r) for r in cached]

        data = await get_recent_data(limit=limit)
        response_data = [SensorDataResponse(**r) for r in data]
        await cache_recent_data(limit, [r.model_dump() for r in response_data])
        return response_data
    except DatabaseError as exc:
        logger.error("Database error retrieving recent data: %s", exc.message, exc_info=True)
        raise HTTPException(status_code=503, detail=f"Database error: {exc.message}")
    except Exception as exc:
        logger.error("Unexpected error retrieving recent data: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/data/aggregated", response_model=List[AggregatedDataResponse])
async def get_aggregated_sensor_data(
    interval_minutes: int = 5, limit: int = 100, hours_back: int = 24
):
    """Get aggregated sensor data using time buckets."""
    if interval_minutes < 1:
        raise HTTPException(status_code=422, detail="interval_minutes must be at least 1")
    if limit < 1 or limit > 1000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 1000")
    if hours_back < 1 or hours_back > 8760:
        raise HTTPException(status_code=422, detail="hours_back must be between 1 and 8760")
    try:
        cached = await get_cached_aggregated_data(interval_minutes, limit)
        if cached:
            return [AggregatedDataResponse(**r) for r in cached]

        data = await get_aggregated_data(
            interval_minutes=interval_minutes, limit=limit, hours_back=hours_back
        )
        response_data = [AggregatedDataResponse(**r) for r in data]
        await cache_aggregated_data(interval_minutes, limit, [r.model_dump() for r in response_data])
        return response_data
    except DatabaseError as exc:
        logger.error("Database error retrieving aggregated data: %s", exc.message, exc_info=True)
        raise HTTPException(status_code=503, detail=f"Database error: {exc.message}")
    except Exception as exc:
        logger.error("Unexpected error retrieving aggregated data: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@app.get("/api/latency/stats")
async def get_latency_statistics(limit: int = 1000):
    """Get latency statistics from recent records."""
    try:
        return await get_latency_stats(limit=limit)
    except Exception as exc:
        logger.error("Error retrieving latency stats: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retrieve latency stats: {exc}")


@app.get("/api/anomaly/stats")
async def get_anomaly_stats():
    """Get current anomaly detector sliding-window statistics."""
    detector = get_anomaly_detector()
    return {
        "window_size": detector.window_size,
        "current_samples": len(detector.temperature_window),
        "statistics": detector.get_statistics(),
    }


@app.get("/metrics")
async def metrics():
    """Prometheus metrics endpoint."""
    return get_metrics_response()


# ── Authentication Endpoints ──────────────────────────────────────────────────

@app.post("/auth/token", response_model=TokenResponse)
async def get_token(credentials: LoginRequest):
    """
    Obtain a JWT bearer token.

    Demo users: admin/admin, user/password
    Use the token in the Authorization header: Bearer <token>
    """
    hashed = _DEMO_USERS.get(credentials.username)
    if not hashed or not verify_password(credentials.password, hashed):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = generate_jwt_token(credentials.username, credentials.username)
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        expires_in=JWT_EXPIRATION_HOURS * 3600,
    )


@app.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    """Return current authenticated user info (requires Bearer token)."""
    return {"user_id": current_user.get("user_id"), "username": current_user.get("username")}


# ── MQTT Endpoints ────────────────────────────────────────────────────────────

@app.get("/api/mqtt/status")
async def mqtt_status():
    """Get MQTT connection status."""
    enabled = os.getenv("MQTT_ENABLED", "false").lower() == "true"
    if not enabled:
        return {"enabled": False, "connected": False, "message": "MQTT is disabled"}

    try:
        from mqtt_client import get_mqtt_client
        client = get_mqtt_client()
        connected = client is not None and client.connected
        return {
            "enabled": True,
            "connected": connected,
            "broker": os.getenv("MQTT_BROKER", "mosquitto"),
            "port": int(os.getenv("MQTT_PORT", "1883")),
            "topic": os.getenv("MQTT_TOPIC", "sensors/data"),
        }
    except Exception as exc:
        return {"enabled": True, "connected": False, "error": str(exc)}


@app.post("/api/mqtt/publish")
async def mqtt_publish(data: SensorDataInput):
    """Publish sensor data to MQTT topic (for testing the MQTT pipeline)."""
    if os.getenv("MQTT_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="MQTT is disabled")

    try:
        from mqtt_client import get_mqtt_client
        client = get_mqtt_client()
        if client is None or not client.connected:
            raise HTTPException(status_code=503, detail="MQTT broker not connected")

        topic = os.getenv("MQTT_TOPIC", "sensors/data")
        payload = {
            "temperature": data.temperature,
            "humidity": data.humidity,
            "gas_level": data.gas_level,
            "sent_timestamp": data.sent_timestamp or datetime.now().isoformat(),
        }
        client.publish(topic, payload)
        return {"status": "published", "topic": topic, "payload": payload}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("MQTT publish error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"MQTT publish failed: {exc}")


# ── Kafka Endpoints ───────────────────────────────────────────────────────────

@app.get("/api/kafka/status")
async def kafka_status():
    """Get Kafka connection status."""
    enabled = os.getenv("KAFKA_ENABLED", "false").lower() == "true"
    if not enabled:
        return {"enabled": False, "connected": False, "message": "Kafka is disabled"}

    try:
        from kafka_client import get_kafka_producer, KAFKA_BROKER, KAFKA_TOPIC
        producer = get_kafka_producer()
        return {
            "enabled": True,
            "connected": producer is not None,
            "broker": KAFKA_BROKER,
            "topic": KAFKA_TOPIC,
        }
    except Exception as exc:
        return {"enabled": True, "connected": False, "error": str(exc)}


@app.post("/api/kafka/publish")
async def kafka_publish(data: SensorDataInput):
    """Publish sensor data to Kafka topic (for testing the Kafka pipeline)."""
    if os.getenv("KAFKA_ENABLED", "false").lower() != "true":
        raise HTTPException(status_code=503, detail="Kafka is disabled")

    try:
        from kafka_client import get_kafka_producer, initialize_kafka_producer, KAFKA_TOPIC
        producer = get_kafka_producer()
        if producer is None:
            producer = initialize_kafka_producer()

        payload = {
            "temperature": data.temperature,
            "humidity": data.humidity,
            "gas_level": data.gas_level,
            "sent_timestamp": data.sent_timestamp or datetime.now().isoformat(),
        }
        producer.produce(topic=KAFKA_TOPIC, key="sensor", value=payload)
        producer.flush(timeout=5.0)
        return {"status": "published", "topic": KAFKA_TOPIC, "payload": payload}
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Kafka publish error: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Kafka publish failed: {exc}")


# ── Device Registry Endpoints ─────────────────────────────────────────────────

@app.get("/api/devices")
async def list_devices():
    """
    List all devices that have submitted data, with record counts and timestamps.
    """
    try:
        return await get_devices()
    except DatabaseError as exc:
        logger.error("Database error retrieving devices: %s", exc.message, exc_info=True)
        raise HTTPException(status_code=503, detail=f"Database error: {exc.message}")
    except Exception as exc:
        logger.error("Unexpected error retrieving devices: %s", exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


# ── Batch Ingestion Endpoint ──────────────────────────────────────────────────

@app.post("/api/data/batch")
async def receive_sensor_data_batch(records: List[SensorDataInput], request: Request):
    """
    Ingest multiple sensor readings in a single request.

    Accepts 1–100 records. Each record is validated and stored independently;
    a per-record result (id or error) is returned so callers know which records
    succeeded and which failed.
    """
    if not records:
        raise HTTPException(status_code=422, detail="records list must not be empty")
    if len(records) > 100:
        raise HTTPException(status_code=422, detail="Maximum 100 records per batch")

    received_at = datetime.now(tz=timezone.utc)
    received_timestamp = received_at.isoformat()
    results = []

    for data in records:
        latency_ms: Optional[float] = None
        if data.sent_timestamp:
            try:
                sent_dt = datetime.fromisoformat(data.sent_timestamp.replace("Z", "+00:00"))
                if sent_dt.tzinfo is None:
                    sent_dt = sent_dt.replace(tzinfo=timezone.utc)
                latency_ms = (received_at - sent_dt).total_seconds() * 1000
            except Exception:
                pass

        try:
            record_id = await insert_sensor_data(
                temperature=data.temperature,
                humidity=data.humidity,
                gas=data.gas_level,
                sent_timestamp=data.sent_timestamp,
                received_timestamp=received_timestamp,
                latency_ms=round(latency_ms, 2) if latency_ms is not None else None,
                device_id=data.device_id,
            )
            record_sensor_data_ingestion(latency_ms=latency_ms)
            results.append({"device_id": data.device_id, "id": record_id, "status": "ok"})
        except Exception as exc:
            logger.error("Batch record failed for device %s: %s", data.device_id, exc)
            results.append({"device_id": data.device_id, "id": None, "status": "error",
                            "detail": str(exc)})

    await invalidate_data_cache()
    ok_count = sum(1 for r in results if r["status"] == "ok")
    return {"stored": ok_count, "total": len(records), "results": results}


# ── Data Export Endpoint ──────────────────────────────────────────────────────

@app.get("/api/data/export")
async def export_sensor_data(
    hours_back: int = 24,
    limit: int = 10000,
    device_id: Optional[str] = None,
    fmt: str = "csv",
):
    """
    Export sensor data as CSV or JSON.

    Query parameters:
    - hours_back: How many hours of data to include (default 24, max 8760)
    - limit: Maximum rows (default 10 000)
    - device_id: Filter by device (optional)
    - fmt: "csv" (default) or "json"
    """
    if hours_back < 1 or hours_back > 8760:
        raise HTTPException(status_code=422, detail="hours_back must be between 1 and 8760")
    if limit < 1 or limit > 10000:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 10000")
    if fmt not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="fmt must be 'csv' or 'json'")

    try:
        rows = await get_export_data(limit=limit, device_id=device_id, hours_back=hours_back)
    except DatabaseError as exc:
        raise HTTPException(status_code=503, detail=f"Database error: {exc.message}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    if fmt == "json":
        return rows

    # Build CSV in memory
    output = io.StringIO()
    if rows:
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    csv_bytes = output.getvalue().encode()

    return StreamingResponse(
        io.BytesIO(csv_bytes),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="sensor_export_{hours_back}h.csv"'},
    )


# ── WebSocket Real-Time Stream ────────────────────────────────────────────────

@app.websocket("/ws/live")
async def websocket_live(ws: WebSocket):
    """
    WebSocket endpoint that streams every ingested data point in real time.

    Connect to ws://localhost:8001/ws/live (or wss:// in production).
    Each message is the same JSON object returned by POST /api/data.
    The connection stays open until the client disconnects.
    """
    await _ws_manager.connect(ws)
    try:
        # Keep connection alive; messages are pushed by _ws_manager.broadcast()
        while True:
            await ws.receive_text()  # accept ping/pong or any client message
    except WebSocketDisconnect:
        pass
    finally:
        _ws_manager.disconnect(ws)

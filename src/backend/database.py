"""
Database operations for sensor data storage.

Handles PostgreSQL connection pooling, schema creation, and data operations
with TimescaleDB support for time-series optimization.
"""

import asyncpg
import logging
import time
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

from exceptions import DatabaseError, ServiceConnectionError, ConfigurationError

logger = logging.getLogger(__name__)


def _record_db_metric(operation: str, duration_sec: float, status: str = "success") -> None:
    """Record DB operation metric (deferred import to avoid circular dependency)."""
    try:
        from metrics import record_db_operation
        record_db_operation(operation, duration_sec, status)
    except Exception:
        pass

# Global connection pool
db_pool: Optional[asyncpg.Pool] = None


async def init_db() -> None:
    """Initialize database connection pool and create schema if needed."""
    global db_pool
    
    import os
    
    db_host = os.getenv("DB_HOST", "db")
    db_port = int(os.getenv("DB_PORT", "5432"))
    db_name = os.getenv("DB_NAME", "sensor_db")
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "postgres")
    
    if db_pool is None:
        try:
            db_pool = await asyncpg.create_pool(
                host=db_host,
                port=db_port,
                database=db_name,
                user=db_user,
                password=db_password,
                min_size=2,
                max_size=10
            )
            
            # Create schema
            async with db_pool.acquire() as conn:
                # Enable TimescaleDB extension FIRST (must exist before create_hypertable)
                try:
                    await conn.execute("CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;")
                    logger.info("TimescaleDB extension enabled")
                except Exception as e:
                    logger.warning("Could not enable TimescaleDB extension: %s", e)

                # Create sensor_data table
                await conn.execute("""
                    CREATE TABLE IF NOT EXISTS sensor_data (
                        id SERIAL PRIMARY KEY,
                        device_id VARCHAR(64),
                        temperature DOUBLE PRECISION NOT NULL,
                        humidity DOUBLE PRECISION NOT NULL,
                        gas DOUBLE PRECISION NOT NULL,
                        sent_timestamp TIMESTAMP,
                        received_timestamp TIMESTAMP,
                        stored_timestamp TIMESTAMP NOT NULL DEFAULT NOW(),
                        latency_ms DOUBLE PRECISION
                    );
                """)

                # Add device_id column to existing tables (idempotent migration)
                await conn.execute("""
                    ALTER TABLE sensor_data
                    ADD COLUMN IF NOT EXISTS device_id VARCHAR(64);
                """)

                # Create hypertable (migrate_data handles non-empty tables)
                try:
                    await conn.execute("""
                        SELECT create_hypertable(
                            'sensor_data', 'stored_timestamp',
                            if_not_exists => TRUE,
                            migrate_data => TRUE
                        );
                    """)
                    logger.info("Hypertable created/verified successfully")
                except Exception as e:
                    logger.warning("Could not create hypertable: %s", e)

                # Continuous aggregate: 5-minute buckets for dashboards and downsampling
                try:
                    await conn.execute("""
                        CREATE MATERIALIZED VIEW IF NOT EXISTS sensor_data_5m
                        WITH (timescaledb.continuous) AS
                        SELECT
                            time_bucket('5 minutes', stored_timestamp) AS bucket,
                            AVG(temperature) AS avg_temperature,
                            AVG(humidity) AS avg_humidity,
                            AVG(gas) AS avg_gas,
                            AVG(latency_ms) AS avg_latency_ms,
                            COUNT(*) AS count
                        FROM sensor_data
                        GROUP BY 1;
                    """)
                    await conn.execute("""
                        SELECT add_continuous_aggregate_policy('sensor_data_5m',
                            start_offset => INTERVAL '1 hour',
                            end_offset => INTERVAL '5 minutes',
                            schedule_interval => INTERVAL '5 minutes',
                            if_not_exists => TRUE);
                    """)
                    logger.info("Continuous aggregate sensor_data_5m created")
                except Exception as e:
                    logger.warning("Could not create continuous aggregate: %s", e)

                # Compression: compress chunks older than 7 days
                try:
                    await conn.execute("""
                        ALTER TABLE sensor_data SET (
                            timescaledb.compress,
                            timescaledb.compress_segmentby = '',
                            timescaledb.compress_orderby = 'stored_timestamp DESC'
                        );
                    """)
                    await conn.execute("""
                        SELECT add_compression_policy('sensor_data', INTERVAL '7 days');
                    """)
                    logger.info("Compression policy added on sensor_data")
                except Exception as e:
                    logger.warning("Could not add compression: %s", e)

                # Retention: drop raw data older than 90 days (optional; disable if not desired)
                try:
                    await conn.execute("""
                        SELECT add_retention_policy('sensor_data', INTERVAL '90 days');
                    """)
                    logger.info("Retention policy (90 days) added on sensor_data")
                except Exception as e:
                    logger.warning("Could not add retention policy: %s", e)

            logger.info("Database initialized successfully")
        except asyncpg.exceptions.PostgresError as e:
            error_msg = f"PostgreSQL error during initialization: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise DatabaseError(error_msg, original_error=e) from e
        except Exception as e:
            error_msg = f"Failed to initialize database: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise DatabaseError(error_msg, original_error=e) from e


async def close_db() -> None:
    """Close database connection pool."""
    global db_pool
    if db_pool:
        await db_pool.close()
        db_pool = None
        logger.info("Database connection pool closed")


async def update_pool_metrics() -> None:
    """Update Prometheus gauges for connection pool (active, idle, total)."""
    if db_pool is None or db_pool.is_closing():
        return
    try:
        from metrics import update_connection_pool_metrics
        total = db_pool.get_size()
        async with db_pool.acquire() as conn:
            active = await conn.fetchval(
                "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
        active = active or 0
        idle = max(0, total - active)
        update_connection_pool_metrics(active=active, idle=idle, total=total)
    except Exception as e:
        logger.debug("Could not update pool metrics: %s", e)


async def get_pool() -> asyncpg.Pool:
    """Get database connection pool."""
    if db_pool is None:
        await init_db()
    if db_pool is None:
        raise ServiceConnectionError(
            "Database connection pool not initialized", service="database"
        )
    return db_pool


async def insert_sensor_data(
    temperature: float,
    humidity: float,
    gas: float,
    sent_timestamp: Optional[str] = None,
    received_timestamp: Optional[str] = None,
    latency_ms: Optional[float] = None,
    device_id: Optional[str] = None,
) -> int:
    """
    Insert sensor data into the database.

    Latency is computed once in the API layer and passed in directly to avoid
    any inconsistency from computing it a second time here.

    Args:
        temperature: Temperature reading
        humidity: Humidity reading
        gas: Gas concentration reading
        sent_timestamp: ISO format timestamp when data was sent (optional)
        received_timestamp: ISO format timestamp when data was received (optional)
        latency_ms: Pre-computed latency in milliseconds (optional)

    Returns:
        ID of inserted record
    """
    pool = await get_pool()
    async with pool.acquire() as conn:
        # Normalize ISO timestamp strings to naive UTC datetimes for asyncpg
        # TIMESTAMP (no timezone) columns.
        sent_dt = None
        received_dt = None

        if sent_timestamp:
            try:
                sent_dt = datetime.fromisoformat(sent_timestamp.replace('Z', '+00:00'))
                if sent_dt.tzinfo is not None:
                    sent_dt = sent_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception as e:
                logger.warning("Could not parse sent_timestamp: %s", e)

        if received_timestamp:
            try:
                received_dt = datetime.fromisoformat(received_timestamp.replace('Z', '+00:00'))
                if received_dt.tzinfo is not None:
                    received_dt = received_dt.astimezone(timezone.utc).replace(tzinfo=None)
            except Exception as e:
                logger.warning("Could not parse received_timestamp: %s", e)

        stored_timestamp = datetime.now(timezone.utc).replace(tzinfo=None)

        t0 = time.perf_counter()
        try:
            record = await conn.fetchrow("""
                INSERT INTO sensor_data (
                    device_id, temperature, humidity, gas,
                    sent_timestamp, received_timestamp, stored_timestamp, latency_ms
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id;
            """,
                device_id, temperature, humidity, gas,
                sent_dt, received_dt, stored_timestamp, latency_ms
            )
            _record_db_metric("insert", time.perf_counter() - t0, "success")
            return record['id']
        except Exception as e:
            _record_db_metric("insert", time.perf_counter() - t0, "error")
            raise


async def get_recent_data(limit: int = 100) -> List[Dict[str, Any]]:
    """
    Get recent sensor data records.
    
    Args:
        limit: Maximum number of records to return
        
    Returns:
        List of sensor data records
    """
    pool = await get_pool()
    t0 = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    id, device_id, temperature, humidity, gas,
                    sent_timestamp, received_timestamp, stored_timestamp, latency_ms
                FROM sensor_data
                ORDER BY stored_timestamp DESC
                LIMIT $1;
            """, limit)

            result = [
                {
                    "id": row["id"],
                    "device_id": row["device_id"],
                    "temperature": row["temperature"],
                    "humidity": row["humidity"],
                    "gas": row["gas"],
                    "sent_timestamp": row["sent_timestamp"].isoformat() if row["sent_timestamp"] else None,
                    "received_timestamp": row["received_timestamp"].isoformat() if row["received_timestamp"] else None,
                    "stored_timestamp": row["stored_timestamp"].isoformat(),
                    "latency_ms": float(row["latency_ms"]) if row["latency_ms"] else None
                }
                for row in rows
            ]
        _record_db_metric("get_recent", time.perf_counter() - t0, "success")
        return result
    except Exception as e:
        _record_db_metric("get_recent", time.perf_counter() - t0, "error")
        raise


async def get_aggregated_data(
    interval_minutes: int = 5,
    limit: int = 100,
    hours_back: int = 24,
) -> List[Dict[str, Any]]:
    """
    Get aggregated sensor data using time buckets.

    Args:
        interval_minutes: Time bucket interval in minutes
        limit: Maximum number of buckets to return
        hours_back: How many hours back to include (default 24)

    Returns:
        List of aggregated data records
    """
    pool = await get_pool()
    t0 = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    time_bucket(make_interval(mins => $1), stored_timestamp) AS time_bucket,
                    AVG(temperature) AS avg_temperature,
                    AVG(humidity) AS avg_humidity,
                    AVG(gas) AS avg_gas,
                    COUNT(*) AS count
                FROM sensor_data
                WHERE stored_timestamp >= NOW() - make_interval(hours => $3)
                GROUP BY time_bucket
                ORDER BY time_bucket DESC
                LIMIT $2;
            """, interval_minutes, limit, hours_back)

            result = [
                {
                    "time_bucket": row["time_bucket"].isoformat() if row["time_bucket"] else None,
                    "avg_temperature": float(row["avg_temperature"]) if row["avg_temperature"] else None,
                    "avg_humidity": float(row["avg_humidity"]) if row["avg_humidity"] else None,
                    "avg_gas": float(row["avg_gas"]) if row["avg_gas"] else None,
                    "count": row["count"]
                }
                for row in rows
            ]
        _record_db_metric("get_aggregated", time.perf_counter() - t0, "success")
        return result
    except Exception as e:
        _record_db_metric("get_aggregated", time.perf_counter() - t0, "error")
        raise


async def get_latency_stats(limit: int = 1000) -> Dict[str, Any]:
    """
    Get latency statistics from recent records.
    
    Args:
        limit: Number of recent records to analyze
        
    Returns:
        Dictionary with latency statistics
    """
    pool = await get_pool()
    t0 = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            # Get total count
            total_count = await conn.fetchval("SELECT COUNT(*) FROM sensor_data;")

            # Get records with latency
            rows_with_latency = await conn.fetch("""
                SELECT latency_ms
                FROM sensor_data
                WHERE latency_ms IS NOT NULL
                ORDER BY stored_timestamp DESC
                LIMIT $1;
            """, limit)

            if not rows_with_latency:
                _record_db_metric("get_latency_stats", time.perf_counter() - t0, "success")
                return {
                    "total_records": total_count,
                    "records_with_latency": 0,
                    "avg_latency_ms": None,
                    "min_latency_ms": None,
                    "max_latency_ms": None,
                    "median_latency_ms": None,
                    "p95_latency_ms": None,
                    "p99_latency_ms": None
                }

            latencies = [float(row["latency_ms"]) for row in rows_with_latency]
            latencies_sorted = sorted(latencies)
            n = len(latencies_sorted)

            def percentile(sorted_data: list, pct: float) -> float:
                """Return the value at the given percentile (0-100) using nearest-rank."""
                idx = max(0, min(n - 1, int(pct / 100.0 * n + 0.5) - 1))
                return sorted_data[idx]

            result = {
                "total_records": total_count,
                "records_with_latency": n,
                "avg_latency_ms": sum(latencies) / n,
                "min_latency_ms": min(latencies),
                "max_latency_ms": max(latencies),
                "median_latency_ms": percentile(latencies_sorted, 50),
                "p95_latency_ms": percentile(latencies_sorted, 95),
                "p99_latency_ms": percentile(latencies_sorted, 99),
            }
        _record_db_metric("get_latency_stats", time.perf_counter() - t0, "success")
        return result
    except Exception:
        _record_db_metric("get_latency_stats", time.perf_counter() - t0, "error")
        raise


async def get_devices() -> List[Dict[str, Any]]:
    """
    Return a summary of all known devices.

    Returns:
        List of dicts with device_id, record_count, first_seen, last_seen.
    """
    pool = await get_pool()
    t0 = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT
                    device_id,
                    COUNT(*) AS record_count,
                    MIN(stored_timestamp) AS first_seen,
                    MAX(stored_timestamp) AS last_seen
                FROM sensor_data
                WHERE device_id IS NOT NULL
                GROUP BY device_id
                ORDER BY last_seen DESC;
            """)
            result = [
                {
                    "device_id": row["device_id"],
                    "record_count": row["record_count"],
                    "first_seen": row["first_seen"].isoformat() if row["first_seen"] else None,
                    "last_seen": row["last_seen"].isoformat() if row["last_seen"] else None,
                }
                for row in rows
            ]
        _record_db_metric("get_devices", time.perf_counter() - t0, "success")
        return result
    except Exception:
        _record_db_metric("get_devices", time.perf_counter() - t0, "error")
        raise


async def get_export_data(
    limit: int = 10000,
    device_id: Optional[str] = None,
    hours_back: int = 24,
) -> List[Dict[str, Any]]:
    """
    Return raw sensor records for CSV export.

    Args:
        limit: Maximum number of records (capped at 10 000 to protect memory)
        device_id: Filter by specific device (None = all devices)
        hours_back: Only include records from the last N hours

    Returns:
        List of record dicts ordered by stored_timestamp ascending.
    """
    pool = await get_pool()
    t0 = time.perf_counter()
    try:
        async with pool.acquire() as conn:
            if device_id:
                rows = await conn.fetch("""
                    SELECT
                        id, device_id, temperature, humidity, gas,
                        sent_timestamp, received_timestamp, stored_timestamp, latency_ms
                    FROM sensor_data
                    WHERE stored_timestamp >= NOW() - make_interval(hours => $1)
                      AND device_id = $2
                    ORDER BY stored_timestamp ASC
                    LIMIT $3;
                """, hours_back, device_id, limit)
            else:
                rows = await conn.fetch("""
                    SELECT
                        id, device_id, temperature, humidity, gas,
                        sent_timestamp, received_timestamp, stored_timestamp, latency_ms
                    FROM sensor_data
                    WHERE stored_timestamp >= NOW() - make_interval(hours => $1)
                    ORDER BY stored_timestamp ASC
                    LIMIT $2;
                """, hours_back, limit)

            result = [
                {
                    "id": row["id"],
                    "device_id": row["device_id"] or "",
                    "temperature": row["temperature"],
                    "humidity": row["humidity"],
                    "gas": row["gas"],
                    "sent_timestamp": row["sent_timestamp"].isoformat() if row["sent_timestamp"] else "",
                    "received_timestamp": row["received_timestamp"].isoformat() if row["received_timestamp"] else "",
                    "stored_timestamp": row["stored_timestamp"].isoformat(),
                    "latency_ms": float(row["latency_ms"]) if row["latency_ms"] else "",
                }
                for row in rows
            ]
        _record_db_metric("get_export", time.perf_counter() - t0, "success")
        return result
    except Exception:
        _record_db_metric("get_export", time.perf_counter() - t0, "error")
        raise

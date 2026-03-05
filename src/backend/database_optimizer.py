"""
Database optimization utilities for the Real-Time Data Collection and Monitoring System.

Provides query optimization, connection pool tuning, and performance monitoring.
"""

import asyncpg
import logging
import time
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

logger = logging.getLogger(__name__)


class QueryOptimizer:
    """Query optimization utilities."""

    @staticmethod
    async def analyze_table(pool: asyncpg.Pool, table_name: str) -> Dict[str, Any]:
        """
        Analyze table statistics.

        Args:
            pool: Database connection pool
            table_name: Name of table to analyze

        Returns:
            Dictionary with table statistics
        """
        async with pool.acquire() as conn:
            stats = await conn.fetchrow("""
                SELECT 
                    schemaname,
                    tablename,
                    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
                    n_live_tup AS row_count,
                    n_dead_tup AS dead_rows,
                    last_vacuum,
                    last_autovacuum,
                    last_analyze,
                    last_autoanalyze
                FROM pg_stat_user_tables
                WHERE tablename = $1;
            """, table_name)

            if stats:
                return dict(stats)
            return {}

    @staticmethod
    async def get_index_usage(pool: asyncpg.Pool, table_name: str) -> List[Dict[str, Any]]:
        """
        Get index usage statistics.

        Args:
            pool: Database connection pool
            table_name: Name of table

        Returns:
            List of index usage statistics
        """
        async with pool.acquire() as conn:
            indexes = await conn.fetch("""
                SELECT
                    indexname,
                    idx_scan AS index_scans,
                    idx_tup_read AS tuples_read,
                    idx_tup_fetch AS tuples_fetched
                FROM pg_stat_user_indexes
                WHERE tablename = $1
                ORDER BY idx_scan DESC;
            """, table_name)

            return [dict(idx) for idx in indexes]

    @staticmethod
    async def get_slow_queries(pool: asyncpg.Pool, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Get slow query statistics (requires pg_stat_statements extension).

        Args:
            pool: Database connection pool
            limit: Maximum number of queries to return

        Returns:
            List of slow query statistics
        """
        async with pool.acquire() as conn:
            try:
                queries = await conn.fetch("""
                    SELECT
                        query,
                        calls,
                        total_exec_time,
                        mean_exec_time,
                        max_exec_time
                    FROM pg_stat_statements
                    ORDER BY mean_exec_time DESC
                    LIMIT $1;
                """, limit)
                return [dict(q) for q in queries]
            except Exception as e:
                logger.warning(f"Could not get slow queries (pg_stat_statements may not be enabled): {e}")
                return []


@asynccontextmanager
async def query_timer():
    """
    Context manager to time database queries.

    Usage:
        async with query_timer() as timer:
            result = await conn.fetch("SELECT ...")
        print(f"Query took {timer['duration']}ms")
    """
    start = time.time()
    timer = {"start": start, "duration": None}
    try:
        yield timer
    finally:
        timer["duration"] = (time.time() - start) * 1000  # Convert to milliseconds


async def optimize_connection_pool(
    pool: asyncpg.Pool,
    min_size: int = 2,
    max_size: int = 10,
    max_queries: int = 50000,
    max_inactive_connection_lifetime: float = 300.0,
) -> None:
    """
    Optimize connection pool settings.

    Args:
        pool: Database connection pool
        min_size: Minimum pool size
        max_size: Maximum pool size
        max_queries: Maximum queries per connection
        max_inactive_connection_lifetime: Max inactive connection lifetime in seconds
    """
    # Note: asyncpg pools don't support runtime reconfiguration
    # This is for documentation/logging purposes
    logger.info(
        f"Connection pool settings: min={min_size}, max={max_size}, "
        f"max_queries={max_queries}, max_inactive={max_inactive_connection_lifetime}s"
    )


_ALLOWED_TABLES = frozenset({"sensor_data"})


async def vacuum_table(pool: asyncpg.Pool, table_name: str, analyze: bool = True) -> None:
    """
    Vacuum a table to reclaim space and update statistics.

    Args:
        pool: Database connection pool
        table_name: Name of table to vacuum
        analyze: Whether to run ANALYZE after VACUUM
    """
    if table_name not in _ALLOWED_TABLES:
        raise ValueError(f"Table '{table_name}' is not in the allowed list")
    # table_name is now safe to interpolate (validated against allowlist)
    async with pool.acquire() as conn:
        if analyze:
            await conn.execute(f"VACUUM ANALYZE {table_name};")
            logger.info(f"Vacuumed and analyzed table: {table_name}")
        else:
            await conn.execute(f"VACUUM {table_name};")
            logger.info(f"Vacuumed table: {table_name}")

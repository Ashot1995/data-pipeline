"""
Database Persistence Tests - TEST-INFRA-3

Tests for data insertion, retrieval, and persistence in the database.
"""

import pytest
from datetime import datetime

# Try to import asyncpg
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None  # type: ignore

pytestmark = pytest.mark.database


@pytest.mark.integration
class TestDataInsertion:
    """Tests for inserting data into the database."""

    @pytest.mark.asyncio
    async def test_insert_sensor_data(self, db_pool, clean_test_db):
        """Test inserting sensor data."""
        async with db_pool.acquire() as conn:
            record_id = await conn.fetchval(
                """
                INSERT INTO sensor_data (temperature, humidity, gas, stored_timestamp)
                VALUES ($1, $2, $3, NOW())
                RETURNING id;
            """,
                23.5,
                45.0,
                175.0,
            )

            assert record_id is not None
            assert isinstance(record_id, int)

    @pytest.mark.asyncio
    async def test_insert_with_timestamps(self, db_pool, clean_test_db):
        """Test inserting data with sent and received timestamps."""
        sent_ts = datetime.now()
        received_ts = datetime.now()

        async with db_pool.acquire() as conn:
            record = await conn.fetchrow(
                """
                INSERT INTO sensor_data (
                    temperature, humidity, gas,
                    sent_timestamp, received_timestamp, stored_timestamp, latency_ms
                )
                VALUES ($1, $2, $3, $4, $5, NOW(), $6)
                RETURNING id, sent_timestamp, received_timestamp, latency_ms;
            """,
                23.5,
                45.0,
                175.0,
                sent_ts,
                received_ts,
                45.5,
            )

            assert record is not None
            assert record["sent_timestamp"] == sent_ts
            assert record["received_timestamp"] == received_ts
            assert abs(float(record["latency_ms"]) - 45.5) < 0.1

    @pytest.mark.asyncio
    async def test_latency_calculation(self, db_pool, clean_test_db):
        """Test that latency is calculated correctly."""
        sent_ts = datetime(2024, 1, 1, 12, 0, 0)
        received_ts = datetime(2024, 1, 1, 12, 0, 0, 50000)  # 50ms later

        async with db_pool.acquire() as conn:
            record = await conn.fetchrow(
                """
                INSERT INTO sensor_data (
                    temperature, humidity, gas,
                    sent_timestamp, received_timestamp, stored_timestamp
                )
                VALUES ($1, $2, $3, $4, $5, NOW())
                RETURNING
                    EXTRACT(EPOCH FROM (received_timestamp - sent_timestamp)) * 1000 AS calculated_latency;
            """,
                23.5,
                45.0,
                175.0,
                sent_ts,
                received_ts,
            )

            calculated_latency = float(record["calculated_latency"])
            assert abs(calculated_latency - 50.0) < 1.0  # Allow small floating point error


@pytest.mark.integration
class TestDataRetrieval:
    """Tests for retrieving data from the database."""

    @pytest.mark.asyncio
    async def test_retrieve_recent_data(self, db_pool, clean_test_db):
        """Test retrieving recent data."""
        # Insert multiple records
        async with db_pool.acquire() as conn:
            for i in range(5):
                await conn.execute(
                    """
                    INSERT INTO sensor_data (temperature, humidity, gas, stored_timestamp)
                    VALUES ($1, $2, $3, NOW() - make_interval(secs => $4))
                """,
                    23.5 + i,
                    45.0 + i,
                    175.0 + i,
                    float((4 - i) * 10),  # i=0 is oldest (40s ago), i=4 is most recent (0s ago)
                )

        # Retrieve recent data
        async with db_pool.acquire() as conn:
            records = await conn.fetch(
                """
                SELECT id, temperature, humidity, gas, stored_timestamp
                FROM sensor_data
                ORDER BY stored_timestamp DESC
                LIMIT 3
            """
            )

            assert len(records) == 3
            assert records[0]["temperature"] == 23.5 + 4  # Most recent

    @pytest.mark.asyncio
    async def test_aggregated_data_query(self, db_pool, clean_test_db):
        """Test aggregated data query."""
        # Insert data with different timestamps
        async with db_pool.acquire() as conn:
            for i in range(10):
                await conn.execute(
                    """
                    INSERT INTO sensor_data (temperature, humidity, gas, stored_timestamp)
                    VALUES ($1, $2, $3, NOW() - make_interval(mins => $4))
                """,
                    23.5,
                    45.0,
                    175.0,
                    i * 2,
                )

        # Query aggregated data
        async with db_pool.acquire() as conn:
            try:
                # Try TimescaleDB time_bucket function
                records = await conn.fetch(
                    """
                    SELECT
                        time_bucket('5 minutes', stored_timestamp) AS time_bucket,
                        AVG(temperature) AS avg_temp,
                        COUNT(*) AS count
                    FROM sensor_data
                    WHERE stored_timestamp >= NOW() - INTERVAL '1 hour'
                    GROUP BY time_bucket
                    ORDER BY time_bucket DESC
                    LIMIT 10
                """
                )

                assert len(records) > 0
                assert "avg_temp" in records[0]
                assert "count" in records[0]
            except asyncpg.UndefinedFunctionError:
                # Fallback to standard PostgreSQL DATE_TRUNC
                records = await conn.fetch(
                    """
                    SELECT
                        DATE_TRUNC('minute', stored_timestamp) AS time_bucket,
                        AVG(temperature) AS avg_temp,
                        COUNT(*) AS count
                    FROM sensor_data
                    WHERE stored_timestamp >= NOW() - INTERVAL '1 hour'
                    GROUP BY time_bucket
                    ORDER BY time_bucket DESC
                    LIMIT 10
                """
                )

                assert len(records) > 0


@pytest.mark.integration
class TestConcurrentInserts:
    """Tests for concurrent data insertion."""

    @pytest.mark.asyncio
    async def test_concurrent_inserts(self, db_pool, clean_test_db):
        """Test that concurrent inserts work correctly."""
        import asyncio

        async def insert_record(i):
            async with db_pool.acquire() as conn:
                return await conn.fetchval(
                    """
                    INSERT INTO sensor_data (temperature, humidity, gas, stored_timestamp)
                    VALUES ($1, $2, $3, NOW())
                    RETURNING id;
                """,
                    23.5 + i,
                    45.0 + i,
                    175.0 + i,
                )

        # Insert 10 records concurrently
        tasks = [insert_record(i) for i in range(10)]
        record_ids = await asyncio.gather(*tasks)

        # Verify all inserts succeeded
        assert len(record_ids) == 10
        assert all(rid is not None for rid in record_ids)

        # Verify all records exist
        async with db_pool.acquire() as conn:
            count = await conn.fetchval("SELECT COUNT(*) FROM sensor_data")
            # The data generator may insert additional records concurrently
            assert count >= 10

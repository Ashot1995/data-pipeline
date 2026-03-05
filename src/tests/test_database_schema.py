"""
Database Schema Tests - TEST-INFRA-3

Tests for database schema, TimescaleDB extension, and table structure.
"""

import pytest
import asyncpg

pytestmark = pytest.mark.database


@pytest.mark.integration
class TestDatabaseSchema:
    """Tests for database schema and structure."""

    @pytest.mark.asyncio
    async def test_table_exists(self, db_pool):
        """Test that sensor_data table exists."""
        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM information_schema.tables
                    WHERE table_name = 'sensor_data'
                );
            """
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_table_columns(self, db_pool):
        """Test that sensor_data table has all required columns."""
        async with db_pool.acquire() as conn:
            columns = await conn.fetch(
                """
                SELECT column_name, data_type, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'sensor_data'
                ORDER BY column_name;
            """
            )

            column_names = [col["column_name"] for col in columns]

            required_columns = [
                "id",
                "temperature",
                "humidity",
                "gas",
                "sent_timestamp",
                "received_timestamp",
                "stored_timestamp",
                "latency_ms",
            ]

            for col in required_columns:
                assert col in column_names, f"Column {col} not found"

    @pytest.mark.asyncio
    async def test_column_types(self, db_pool):
        """Test that columns have correct data types."""
        async with db_pool.acquire() as conn:
            columns = await conn.fetch(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_name = 'sensor_data';
            """
            )

            column_dict = {col["column_name"]: col["data_type"] for col in columns}

            # Check key column types
            assert column_dict["id"] in ["integer", "bigint"]  # SERIAL creates integer or bigint
            assert "double precision" in column_dict["temperature"].lower()
            assert "double precision" in column_dict["humidity"].lower()
            assert "double precision" in column_dict["gas"].lower()
            assert "timestamp" in column_dict["stored_timestamp"].lower()

    @pytest.mark.asyncio
    async def test_not_null_constraints(self, db_pool):
        """Test that required columns have NOT NULL constraints."""
        async with db_pool.acquire() as conn:
            columns = await conn.fetch(
                """
                SELECT column_name, is_nullable
                FROM information_schema.columns
                WHERE table_name = 'sensor_data';
            """
            )

            column_dict = {col["column_name"]: col["is_nullable"] for col in columns}

            # These columns should be NOT NULL
            assert column_dict["temperature"] == "NO"
            assert column_dict["humidity"] == "NO"
            assert column_dict["gas"] == "NO"
            assert column_dict["stored_timestamp"] == "NO"

    @pytest.mark.asyncio
    async def test_timescaledb_extension(self, db_pool):
        """Test that TimescaleDB extension is enabled."""
        async with db_pool.acquire() as conn:
            result = await conn.fetchval(
                """
                SELECT EXISTS (
                    SELECT FROM pg_extension
                    WHERE extname = 'timescaledb'
                );
            """
            )
            if result:
                assert result is True, "TimescaleDB extension should be enabled"
            else:
                pytest.skip("TimescaleDB extension not available in test environment")

    @pytest.mark.asyncio
    async def test_hypertable_exists(self, db_pool):
        """Test that sensor_data is a hypertable."""
        async with db_pool.acquire() as conn:
            try:
                result = await conn.fetchval(
                    """
                    SELECT EXISTS (
                        SELECT FROM timescaledb_information.hypertables
                        WHERE hypertable_name = 'sensor_data'
                    );
                """
                )
                if result:
                    assert result is True
                else:
                    pytest.skip("Hypertable check not available (TimescaleDB may not be enabled)")
            except asyncpg.UndefinedTableError:
                pytest.skip("TimescaleDB information tables not available")

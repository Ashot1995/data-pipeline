"""
Pytest configuration and fixtures for testing.

Provides shared fixtures for database connections, API clients, and test data.
"""

import pytest
import asyncio
import os
import sys
from typing import AsyncGenerator, Generator

# Ensure backend package is importable when tests run from the src/ directory
_backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if _backend_path not in sys.path:
    sys.path.insert(0, _backend_path)

# Try to import asyncpg (may not be installed in local environment)
try:
    import asyncpg

    ASYNCPG_AVAILABLE = True
except ImportError:
    ASYNCPG_AVAILABLE = False
    asyncpg = None  # type: ignore

# Try to import httpx
try:
    import httpx

    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False
    httpx = None  # type: ignore

# Try to import FastAPI test client
try:
    from fastapi.testclient import TestClient

    TESTCLIENT_AVAILABLE = True
except ImportError:
    TESTCLIENT_AVAILABLE = False
    TestClient = None  # type: ignore

# Try to import backend modules
try:
    from main import app  # noqa: F401
    from database import init_db, close_db, get_pool  # noqa: F401

    BACKEND_AVAILABLE = True
except ImportError:
    BACKEND_AVAILABLE = False
    app = None


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def db_pool():
    """
    Create a database connection pool for testing.

    Note: Requires database to be running. Use docker compose up db first.
    """
    if not ASYNCPG_AVAILABLE or asyncpg is None:
        pytest.skip(
            "asyncpg not available - install dependencies: pip install -r requirements-dev.txt"
        )

    db_host = os.getenv("TEST_DB_HOST", os.getenv("DB_HOST", "localhost"))
    db_port = int(os.getenv("TEST_DB_PORT", os.getenv("DB_PORT", "5433")))
    db_name = os.getenv("TEST_DB_NAME", os.getenv("DB_NAME", "sensor_db"))
    db_user = os.getenv("TEST_DB_USER", os.getenv("DB_USER", "postgres"))
    db_password = os.getenv("TEST_DB_PASSWORD", os.getenv("DB_PASSWORD", "postgres"))

    try:
        pool = await asyncpg.create_pool(
            host=db_host,
            port=db_port,
            database=db_name,
            user=db_user,
            password=db_password,
            min_size=1,
            max_size=5,
        )
        yield pool
        await pool.close()
    except Exception as e:
        pytest.skip(f"Database not available: {e}")


@pytest.fixture
async def clean_test_db(db_pool):
    """Clean test database before each test."""
    if not ASYNCPG_AVAILABLE or asyncpg is None:
        pytest.skip("asyncpg not available")
    async with db_pool.acquire() as conn:
        # Truncate sensor_data table
        await conn.execute("TRUNCATE TABLE sensor_data RESTART IDENTITY CASCADE;")
    yield
    # Cleanup after test
    async with db_pool.acquire() as conn:
        await conn.execute("TRUNCATE TABLE sensor_data RESTART IDENTITY CASCADE;")


@pytest.fixture
def api_client() -> Generator:
    """
    Create a test client for the FastAPI application.

    Note: Requires backend modules to be importable.
    """
    if not BACKEND_AVAILABLE or app is None or not TESTCLIENT_AVAILABLE:
        pytest.skip("Backend application or TestClient not available")

    with TestClient(app) as client:
        yield client


@pytest.fixture
async def async_api_client() -> AsyncGenerator:
    """
    Create an async HTTP client for testing.

    Useful for testing async endpoints directly.
    """
    if not HTTPX_AVAILABLE:
        pytest.skip(
            "httpx not available - install dependencies: pip install -r requirements-dev.txt"
        )

    base_url = os.getenv("TEST_BACKEND_URL", "http://localhost:8001")

    async with httpx.AsyncClient(base_url=base_url, timeout=10.0) as client:
        yield client


@pytest.fixture
def sample_sensor_data():
    """Sample sensor data for testing (all required fields per spec §4.2)."""
    return {
        "device_id": "test-sensor-001",
        "timestamp": "2024-01-15T10:30:00Z",
        "temperature": 23.5,
        "humidity": 45.0,
        "gas_level": 175.0,
    }


@pytest.fixture
def sample_sensor_data_with_timestamp():
    """Sample sensor data with sent_timestamp for latency testing."""
    from datetime import datetime, timezone

    return {
        "device_id": "test-sensor-001",
        "timestamp": "2024-01-15T10:30:00Z",
        "temperature": 23.5,
        "humidity": 45.0,
        "gas_level": 175.0,
        "sent_timestamp": datetime.now(tz=timezone.utc).isoformat(),
    }

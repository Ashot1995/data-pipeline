"""
Backend API Tests - TEST-INFRA-2

Tests for FastAPI backend endpoints including data ingestion, retrieval, and validation.
"""

import pytest
from fastapi.testclient import TestClient

try:
    from main import app

    BACKEND_AVAILABLE = True
except ImportError:
    BACKEND_AVAILABLE = False
    app = None


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestRootEndpoint:
    """Tests for GET / endpoint."""

    def test_root_endpoint(self, api_client: TestClient):
        """Test root endpoint returns API information."""
        response = api_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestHealthEndpoint:
    """Tests for GET /health endpoint."""

    def test_health_endpoint(self, api_client: TestClient):
        """Test health endpoint returns healthy status."""
        response = api_client.get("/health")
        assert response.status_code in [200, 503]  # May be 503 if DB not connected
        data = response.json()
        assert "status" in data
        assert "database" in data


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestDataIngestion:
    """Tests for POST /api/data endpoint."""

    def test_post_valid_data(self, api_client: TestClient, sample_sensor_data):
        """Test posting valid sensor data."""
        response = api_client.post("/api/data", json=sample_sensor_data)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "id" in data
        assert "data" in data
        assert "timestamps" in data

    def test_post_data_with_timestamp(
        self, api_client: TestClient, sample_sensor_data_with_timestamp
    ):
        """Test posting data with sent_timestamp."""
        response = api_client.post("/api/data", json=sample_sensor_data_with_timestamp)
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "timestamps" in data
        assert "latency_ms" in data["timestamps"]

    def test_post_data_missing_field(self, api_client: TestClient):
        """Test posting data with missing required field."""
        invalid_data = {"temperature": 23.5, "humidity": 45.0}
        response = api_client.post("/api/data", json=invalid_data)
        assert response.status_code == 422

    def test_post_data_invalid_type(self, api_client: TestClient):
        """Test posting data with invalid type."""
        invalid_data = {"temperature": "not a number", "humidity": 45.0, "gas": 175.0}
        response = api_client.post("/api/data", json=invalid_data)
        assert response.status_code == 422

    def test_post_data_out_of_range(self, api_client: TestClient):
        """Test posting data with out-of-range values."""
        invalid_data = {"temperature": 150.0, "humidity": 45.0, "gas": 175.0}
        response = api_client.post("/api/data", json=invalid_data)
        assert response.status_code == 422


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestDataRetrieval:
    """Tests for GET /api/data/recent endpoint."""

    def test_get_recent_data_default_limit(self, api_client: TestClient, sample_sensor_data):
        """Test getting recent data with default limit."""
        # Insert some data first
        api_client.post("/api/data", json=sample_sensor_data)

        response = api_client.get("/api/data/recent")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            assert "id" in data[0]
            assert "temperature" in data[0]
            assert "humidity" in data[0]
            assert "gas" in data[0]

    def test_get_recent_data_custom_limit(self, api_client: TestClient, sample_sensor_data):
        """Test getting recent data with custom limit."""
        # Insert some data first
        for _ in range(5):
            api_client.post("/api/data", json=sample_sensor_data)

        response = api_client.get("/api/data/recent?limit=3")
        assert response.status_code == 200
        data = response.json()
        assert len(data) <= 3


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestAggregatedData:
    """Tests for GET /api/data/aggregated endpoint."""

    def test_get_aggregated_data(self, api_client: TestClient, sample_sensor_data):
        """Test getting aggregated data."""
        # Insert some data first
        for _ in range(5):
            api_client.post("/api/data", json=sample_sensor_data)

        response = api_client.get("/api/data/aggregated?interval_minutes=5&limit=10")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if len(data) > 0:
            assert "time_bucket" in data[0]
            assert "avg_temperature" in data[0]
            assert "avg_humidity" in data[0]
            assert "avg_gas" in data[0]
            assert "count" in data[0]


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestLatencyStats:
    """Tests for GET /api/latency/stats endpoint."""

    def test_get_latency_stats(self, api_client: TestClient, sample_sensor_data_with_timestamp):
        """Test getting latency statistics."""
        # Insert some data with timestamps first
        for _ in range(5):
            api_client.post("/api/data", json=sample_sensor_data_with_timestamp)

        response = api_client.get("/api/latency/stats?limit=100")
        assert response.status_code == 200
        data = response.json()
        assert "total_records" in data
        assert "records_with_latency" in data
        assert "avg_latency_ms" in data
        assert "min_latency_ms" in data
        assert "max_latency_ms" in data


@pytest.mark.skipif(not BACKEND_AVAILABLE, reason="Backend not available")
@pytest.mark.api
class TestAnomalyStats:
    """Tests for GET /api/anomaly/stats endpoint."""

    def test_get_anomaly_stats_returns_200(self, api_client: TestClient):
        """Test that anomaly stats endpoint returns 200."""
        response = api_client.get("/api/anomaly/stats")
        assert response.status_code == 200

    def test_get_anomaly_stats_has_required_keys(self, api_client: TestClient):
        """Test that response contains window_size, current_samples, statistics."""
        response = api_client.get("/api/anomaly/stats")
        data = response.json()
        assert "window_size" in data
        assert "current_samples" in data
        assert "statistics" in data

    def test_get_anomaly_stats_statistics_structure(
        self, api_client: TestClient, sample_sensor_data
    ):
        """Test that statistics has per-sensor entries after posting data."""
        # Populate detector with some samples
        for _ in range(3):
            api_client.post("/api/data", json=sample_sensor_data)

        response = api_client.get("/api/anomaly/stats")
        data = response.json()
        stats = data["statistics"]
        for sensor in ("temperature", "humidity", "gas"):
            assert sensor in stats
            assert "mean" in stats[sensor]
            assert "std" in stats[sensor]
            assert "min" in stats[sensor]
            assert "max" in stats[sensor]
            assert "count" in stats[sensor]

    def test_post_data_response_includes_anomaly_detection(
        self, api_client: TestClient, sample_sensor_data
    ):
        """Test that POST /api/data response includes anomaly_detection key."""
        response = api_client.post("/api/data", json=sample_sensor_data)
        assert response.status_code == 200
        data = response.json()
        assert "anomaly_detection" in data

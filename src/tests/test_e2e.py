"""
End-to-End Tests - TEST-INFRA-4

Tests for full system integration including generator → backend → database flow.
"""

import pytest
import time
import requests
from datetime import datetime

pytestmark = pytest.mark.e2e


@pytest.mark.integration
class TestEndToEndFlow:
    """Tests for end-to-end data flow."""

    @pytest.fixture
    def backend_url(self):
        """Backend URL for testing."""
        return "http://localhost:8001"

    def test_backend_health(self, backend_url):
        """Test that backend is healthy."""
        try:
            response = requests.get(f"{backend_url}/health", timeout=5)
            assert response.status_code in [200, 503]  # 503 if DB not connected
        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running. Start with: docker compose up")

    def test_data_ingestion_flow(self, backend_url):
        """Test full data ingestion flow."""
        try:
            # Send test data
            test_data = {
                "temperature": 25.0,
                "humidity": 50.0,
                "gas": 200.0,
                "sent_timestamp": datetime.now().isoformat(),
            }

            response = requests.post(f"{backend_url}/api/data", json=test_data, timeout=10)

            assert response.status_code == 200
            result = response.json()
            assert result["status"] == "success"
            assert "id" in result
            assert "timestamps" in result

        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running")

    def test_data_retrieval_flow(self, backend_url):
        """Test data retrieval after ingestion."""
        try:
            # Insert data
            test_data = {"temperature": 24.0, "humidity": 48.0, "gas": 180.0}
            requests.post(f"{backend_url}/api/data", json=test_data, timeout=10)

            # Wait a bit for processing
            time.sleep(0.5)

            # Retrieve data
            response = requests.get(f"{backend_url}/api/data/recent?limit=5", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
            assert len(data) > 0

        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running")

    def test_latency_tracking_flow(self, backend_url):
        """Test latency tracking end-to-end."""
        try:
            # Send data with timestamp
            sent_time = datetime.now()
            test_data = {
                "temperature": 23.5,
                "humidity": 45.0,
                "gas": 175.0,
                "sent_timestamp": sent_time.isoformat(),
            }

            response = requests.post(f"{backend_url}/api/data", json=test_data, timeout=10)

            assert response.status_code == 200
            result = response.json()

            # Check latency was calculated
            timestamps = result.get("timestamps", {})
            if "latency_ms" in timestamps and timestamps["latency_ms"] is not None:
                latency = timestamps["latency_ms"]
                assert latency >= 0
                assert latency < 10000  # Should be reasonable (< 10 seconds)

        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running")

    def test_aggregated_data_flow(self, backend_url):
        """Test aggregated data retrieval."""
        try:
            # Insert multiple data points
            for i in range(5):
                test_data = {"temperature": 23.0 + i, "humidity": 45.0 + i, "gas": 175.0 + i}
                requests.post(f"{backend_url}/api/data", json=test_data, timeout=10)
                time.sleep(0.1)

            # Get aggregated data
            response = requests.get(
                f"{backend_url}/api/data/aggregated?interval_minutes=5&limit=10", timeout=10
            )

            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)

        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running")

    def test_multiple_data_points(self, backend_url):
        """Test sending multiple data points."""
        try:
            sent_count = 0
            for i in range(10):
                test_data = {
                    "temperature": 23.0 + (i * 0.5),
                    "humidity": 45.0 + (i * 1.0),
                    "gas": 175.0 + (i * 2.0),
                }
                response = requests.post(f"{backend_url}/api/data", json=test_data, timeout=10)
                if response.status_code == 200:
                    sent_count += 1
                time.sleep(0.1)

            assert sent_count > 0

            # Verify data was stored
            response = requests.get(f"{backend_url}/api/data/recent?limit=20", timeout=10)
            assert response.status_code == 200
            data = response.json()
            assert len(data) >= sent_count

        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running")

    def test_error_handling(self, backend_url):
        """Test error handling for invalid data."""
        try:
            # Test invalid data
            invalid_data = {"temperature": 150.0, "humidity": 45.0, "gas": 175.0}
            response = requests.post(f"{backend_url}/api/data", json=invalid_data, timeout=10)

            # Should return 422 for validation error
            assert response.status_code == 422

        except requests.exceptions.ConnectionError:
            pytest.skip("Backend not running")

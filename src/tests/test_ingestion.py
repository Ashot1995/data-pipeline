"""
Ingestion endpoint tests (spec §4.2, §4.3, FR-1.2).

Tests POST /api/data against a running backend container via BACKEND_URL.
All tests carry the pytest.mark.ingestion marker.

Run inside the test container:
    pytest -m ingestion tests/test_ingestion.py
"""

import os

import httpx
import pytest

BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000")

# ---------------------------------------------------------------------------
# Canonical valid payload (all required + optional fields present)
# ---------------------------------------------------------------------------
VALID_PAYLOAD = {
    "device_id": "test-ingestion-sensor",
    "timestamp": "2024-01-15T10:30:00Z",
    "temperature": 23.5,
    "humidity": 45.2,
    "gas_level": 175.0,
    "sent_timestamp": "2024-01-15T10:30:00.100Z",
}

# Apply the marker to every test in this module
pytestmark = pytest.mark.ingestion


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _post(payload: dict) -> httpx.Response:
    """POST payload to /api/data synchronously."""
    with httpx.Client(base_url=BACKEND_URL, timeout=10.0) as client:
        return client.post("/api/data", json=payload)


# ---------------------------------------------------------------------------
# Test 1 — Valid payload: HTTP 200 with correct response shape
# ---------------------------------------------------------------------------


def test_valid_payload_returns_200_with_correct_shape():
    """
    A fully-valid payload must return HTTP 200.
    Response body must match spec §4.3:
      status, id (int), device_id, data{}, timestamps{}.
    """
    response = _post(VALID_PAYLOAD)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    body = response.json()

    # Top-level required keys
    assert (
        body.get("status") == "success"
    ), f"body['status'] should be 'success', got: {body.get('status')}"
    assert isinstance(
        body.get("id"), int
    ), f"body['id'] must be an int, got: {type(body.get('id'))}"
    assert (
        body.get("device_id") == "test-ingestion-sensor"
    ), f"body['device_id'] mismatch: {body.get('device_id')}"

    # data sub-object
    assert "data" in body, "Response must contain 'data' sub-object"
    data_obj = body["data"]
    assert "temperature" in data_obj
    assert "humidity" in data_obj
    assert "gas_level" in data_obj

    # timestamps sub-object
    assert "timestamps" in body, "Response must contain 'timestamps' sub-object"
    ts = body["timestamps"]
    assert "client" in ts, "'timestamps.client' key missing"
    assert "received" in ts, "'timestamps.received' key missing"
    assert "stored" in ts, "'timestamps.stored' key missing"
    assert "latency_ms" in ts, "'timestamps.latency_ms' key missing"

    # anomaly_detection key must be present (may be null if detector unavailable)
    assert "anomaly_detection" in body, "'anomaly_detection' key missing from response"


# ---------------------------------------------------------------------------
# Test 2 — temperature out of range → HTTP 422
# ---------------------------------------------------------------------------


def test_temperature_out_of_range_returns_422():
    """
    temperature=150.0 exceeds the allowed maximum of 100.0.
    Must return HTTP 422 with 'temperature' mentioned in the response.
    """
    payload = {**VALID_PAYLOAD, "temperature": 150.0}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    body_text = response.text.lower()
    assert (
        "temperature" in body_text
    ), f"'temperature' not mentioned in 422 response: {response.text}"


# ---------------------------------------------------------------------------
# Test 3 — missing device_id → HTTP 422
# ---------------------------------------------------------------------------


def test_missing_device_id_returns_422():
    """Omitting the required 'device_id' field must return HTTP 422."""
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "device_id"}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 4 — null temperature → HTTP 422
# ---------------------------------------------------------------------------


def test_null_temperature_returns_422():
    """
    Sending temperature=null (Python None → JSON null) must return HTTP 422
    because the field is required and must be a float.
    """
    payload = {**VALID_PAYLOAD, "temperature": None}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 5 — string temperature → HTTP 422
# ---------------------------------------------------------------------------


def test_string_temperature_returns_422():
    """temperature='hot' (non-numeric string) must be rejected with HTTP 422."""
    payload = {**VALID_PAYLOAD, "temperature": "hot"}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 6 — NaN temperature → HTTP 422
#
# JSON does not support NaN as a literal value, so we send `null` (None) to
# represent a missing/invalid numeric — which must also be rejected.
# If the server's JSON parser is configured to accept bare NaN tokens, a
# separate raw-JSON test would be needed; this covers the practical case.
# ---------------------------------------------------------------------------


def test_nan_encoded_as_null_returns_422():
    """
    JSON has no native NaN literal.  Sending null for a required float field
    (the closest encodable equivalent) must return HTTP 422.
    Note: the model validator also explicitly rejects math.nan should a
    non-standard client send it via a custom serialiser.
    """
    payload = {**VALID_PAYLOAD, "temperature": None}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 7 — gas_level out of range → HTTP 422
# ---------------------------------------------------------------------------


def test_gas_level_out_of_range_returns_422():
    """gas_level=1500.0 exceeds the allowed maximum of 1000.0 → HTTP 422."""
    payload = {**VALID_PAYLOAD, "gas_level": 1500.0}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    body_text = response.text.lower()
    assert (
        "gas_level" in body_text or "gas" in body_text
    ), f"'gas_level' not mentioned in 422 response: {response.text}"


# ---------------------------------------------------------------------------
# Test 8 — humidity out of range → HTTP 422
# ---------------------------------------------------------------------------


def test_humidity_out_of_range_returns_422():
    """humidity=110.0 exceeds the allowed maximum of 100.0 → HTTP 422."""
    payload = {**VALID_PAYLOAD, "humidity": 110.0}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
    body_text = response.text.lower()
    assert "humidity" in body_text, f"'humidity' not mentioned in 422 response: {response.text}"


# ---------------------------------------------------------------------------
# Test 9 — device_id too long (65 chars) → HTTP 422
# ---------------------------------------------------------------------------


def test_device_id_too_long_returns_422():
    """A device_id of 65 characters exceeds max_length=64 → HTTP 422."""
    long_id = "x" * 65
    payload = {**VALID_PAYLOAD, "device_id": long_id}
    response = _post(payload)

    assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"


# ---------------------------------------------------------------------------
# Test 10 — sent_timestamp omitted → HTTP 200, latency_ms is null
# ---------------------------------------------------------------------------


def test_omitted_sent_timestamp_returns_200_with_null_latency():
    """
    When sent_timestamp is not provided the endpoint must still return HTTP 200
    and timestamps.latency_ms must be null (None).
    """
    payload = {k: v for k, v in VALID_PAYLOAD.items() if k != "sent_timestamp"}
    response = _post(payload)

    assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    body = response.json()
    assert body.get("status") == "success"
    ts = body.get("timestamps", {})
    assert "latency_ms" in ts, "'timestamps.latency_ms' key missing"
    assert (
        ts["latency_ms"] is None
    ), f"timestamps.latency_ms should be null when sent_timestamp is omitted, got: {ts['latency_ms']}"

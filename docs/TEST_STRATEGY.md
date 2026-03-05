# Test Strategy

Audience: QA engineers and developers writing or reviewing tests.

---

## 1. Test Architecture

All tests run **inside Docker containers** — never on the host machine.
The test container (`profile: test`) mounts nothing from the host; it talks to live services over the `sensor_network` bridge.

```
[test container]
     │
     ├── POST /api/data ──▶ [backend :8000] ──▶ [db :5432]
     │                                     ──▶ [redis :6379]
     └── YAML/config checks (no live services needed)
```

### Prerequisites

```bash
cd src/
cp .env.example .env          # set JWT_SECRET_KEY
docker compose up --build -d  # start all services
make test                     # run full suite
```

---

## 2. Test Matrix

| File                           | Marker        | Services required          | Count (approx) |
|--------------------------------|---------------|----------------------------|----------------|
| `test_ingestion.py`            | `ingestion`   | backend, db                | 10             |
| `test_backend_api.py`          | `api`         | backend, db                | ~8             |
| `test_database_schema.py`      | `database`    | db                         | ~5             |
| `test_database_persistence.py` | `database`    | db                         | ~5             |
| `test_e2e.py`                  | `e2e`         | backend, db, redis         | ~5             |
| `test_docker_compose.py`       | `docker`      | none (parses YAML)         | ~5             |
| `conftest.py`                  | —             | provides fixtures           | —              |

Run a specific subset:

```bash
# Inside container
docker compose --profile test run --rm test python -m pytest -m ingestion -v
docker compose --profile test run --rm test python -m pytest -m "not integration" -v
```

---

## 3. Ingestion Tests (`test_ingestion.py`)

Full coverage of `POST /api/data` per spec §4.2–§4.3.

| Test | Input | Expected |
|------|-------|----------|
| `test_valid_payload_returns_200_with_correct_shape` | All required + optional fields | HTTP 200; `status=success`; `id` (int); `data`; `timestamps`; `anomaly_detection` |
| `test_temperature_out_of_range_returns_422` | `temperature=150.0` | HTTP 422; `"temperature"` in body |
| `test_missing_device_id_returns_422` | No `device_id` | HTTP 422 |
| `test_null_temperature_returns_422` | `temperature=null` | HTTP 422 |
| `test_string_temperature_returns_422` | `temperature="hot"` | HTTP 422 |
| `test_nan_encoded_as_null_returns_422` | `temperature=null` | HTTP 422 |
| `test_gas_level_out_of_range_returns_422` | `gas_level=1500.0` | HTTP 422; `"gas_level"` or `"gas"` in body |
| `test_humidity_out_of_range_returns_422` | `humidity=110.0` | HTTP 422; `"humidity"` in body |
| `test_device_id_too_long_returns_422` | `device_id` = 65 chars | HTTP 422 |
| `test_omitted_sent_timestamp_returns_200_with_null_latency` | No `sent_timestamp` | HTTP 200; `timestamps.latency_ms=null` |

### Valid payload shape (canonical)

```json
{
  "device_id": "test-ingestion-sensor",
  "timestamp": "2024-01-15T10:30:00Z",
  "temperature": 23.5,
  "humidity": 45.2,
  "gas_level": 175.0,
  "sent_timestamp": "2024-01-15T10:30:00.100Z"
}
```

---

## 4. Field Validation Boundaries

| Field       | Type   | Min    | Max    | Required |
|-------------|--------|--------|--------|----------|
| `device_id` | string | len≥1  | len≤64 | yes      |
| `timestamp` | string | —      | —      | yes (ISO 8601) |
| `temperature` | float | −50.0 | 100.0  | yes      |
| `humidity`  | float  | 0.0    | 100.0  | yes      |
| `gas_level` | float  | 0.0    | 1000.0 | yes      |
| `sent_timestamp` | string | — | —   | no       |

Additional validator: `temperature`, `humidity`, `gas_level` reject NaN and ±Infinity.

---

## 5. Response Schema Assertions

Every successful `POST /api/data` response **must** contain:

```
status          string   "success"
id              integer
device_id       string   echoes input
data            object
  temperature   float
  humidity      float
  gas_level     float
timestamps      object
  client        string|null   echoes sent_timestamp
  received      string        ISO 8601
  stored        string        ISO 8601
  latency_ms    float|null    null when sent_timestamp omitted
anomaly_detection  object|null
```

---

## 6. Database Tests

### Schema checks (`test_database_schema.py`)
- Table `sensor_data` exists.
- All expected columns present with correct types.
- Hypertable check: `sensor_data` is a TimescaleDB hypertable.
- `stored_timestamp` has a `NOT NULL DEFAULT NOW()` constraint.

### Persistence checks (`test_database_persistence.py`)
- Inserted record is retrievable via `GET /api/data/recent`.
- `latency_ms` is computed and stored correctly.
- `stored_timestamp` is within 5 s of insertion time.
- Records older than 24 h are excluded from aggregated queries.

---

## 7. End-to-End Tests (`test_e2e.py`)

Full pipeline validation:
1. POST sensor data with `sent_timestamp`.
2. Assert HTTP 200 and `latency_ms > 0`.
3. GET `/api/data/recent` — assert record appears.
4. GET `/api/data/aggregated` — assert aggregated bucket contains the record.
5. GET `/api/latency/stats` — assert non-zero records.

---

## 8. Known Gaps and Risks

| Gap | Severity | Tracking |
|-----|----------|----------|
| Data generator sends wrong field names (`gas` instead of `gas_level`, missing `device_id` and `timestamp`) → 422 on every send | **HIGH** | TASKS.md DX-02 |
| No auth endpoint tests (auth module exists but is opt-in) | Medium | — |
| No rate-limit tests | Medium | TASKS.md S-02/S-03 |
| No Redis failover test (Redis reconnect gap) | Medium | TASKS.md R-02 |
| No load / throughput test | Low | — |
| No negative test for `GET /api/data/aggregated` with invalid `interval_minutes` | Low | — |

---

## 9. Regression Checklist

Before merging any backend change:

- [ ] `make test` passes with 0 failures.
- [ ] `make lint` reports 0 errors (warnings acceptable).
- [ ] `make format-check` passes.
- [ ] New endpoint or model change: ingestion tests updated.
- [ ] DB schema change: schema and persistence tests updated.
- [ ] `GET /health` returns HTTP 200 (healthy stack) / HTTP 503 (db down).

---

## 10. Running Individual Tests

```bash
# All tests
make test

# Specific marker
docker compose --profile test run --rm test \
  python -m pytest -m ingestion -v --tb=short

# Single file
docker compose --profile test run --rm test \
  python -m pytest test_backend_api.py -v

# Single test function
docker compose --profile test run --rm test \
  python -m pytest test_ingestion.py::test_valid_payload_returns_200_with_correct_shape -v

# Show skipped test reasons
docker compose --profile test run --rm test \
  python -m pytest -v -rs
```

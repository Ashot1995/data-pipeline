# Project Status

Audience: project managers, stakeholders, and tech leads.
Last updated: 2026-03-03.

---

## 1. Summary

| Metric | Value |
|--------|-------|
| Test suite | **10 passed, 43 skipped, 0 failed** |
| Lint | Clean (flake8, max-line-length=120) |
| Format | Passing (black, line-length=100) |
| Stack health | All 6 core services healthy |
| Open critical bugs | **0** |
| Open high-priority tasks | 3 |

---

## 2. Feature Implementation Status

### Core Pipeline (Spec §4.1–§4.3)

| Feature | Status | Notes |
|---------|--------|-------|
| Sensor data ingestion (`POST /api/data`) | **Done** | Validates all fields; returns full structured response |
| Field validation (temperature, humidity, gas_level) | **Done** | Range and NaN/Infinity checks |
| `device_id` stored to database | **Done** | Added column + idempotent migration (F-01) |
| Timestamp tracking (sent → received → stored) | **Done** | All three stored; latency_ms computed once in API layer |
| Anomaly detection (Z-score sliding window) | **Done** | In-process; non-fatal if it fails |
| Recent data endpoint (`GET /api/data/recent`) | **Done** | Redis-cached, configurable limit, includes device_id |
| Aggregated data endpoint (`GET /api/data/aggregated`) | **Done** | `hours_back` parameter configurable (A-02) |
| Latency statistics (`GET /api/latency/stats`) | **Done** | Avg, min, max, median, p95, p99 |
| Health check (`GET /health`) | **Done** | Returns 503 when DB unavailable |
| Device list endpoint (`GET /api/devices`) | **Done** | Lists all devices with record count and first/last seen (F-02) |
| Batch ingestion (`POST /api/data/batch`) | **Done** | Up to 100 records per request; per-record result (F-03) |
| Export endpoint (`GET /api/data/export`) | **Done** | CSV or JSON; up to 10 000 rows; device_id + hours_back filters (F-04) |
| Real-time WebSocket (`GET /ws/live`) | **Done** | Pushes every ingestion to connected clients (F-05) |

### Data Generator

| Feature | Status | Notes |
|---------|--------|-------|
| Generates temperature, humidity, gas readings | **Done** | Realistic random walk with configurable base values |
| Sends data via HTTP POST | **Done** | Sends `gas_level`, `device_id`, `timestamp`; all POSTs return 201 |
| Retry with exponential backoff | **Done** | 3 retries, 1.5× backoff |
| MQTT publish (optional) | **Done** | Requires `--profile mqtt` |

### Arduino Sketch

| Feature | Status | Notes |
|---------|--------|-------|
| Sends `gas_level` (was `gas`) | **Done** | Renamed to match API schema (F-07) |
| Sends `device_id` | **Done** | Configurable constant `deviceId` (F-07) |
| Sends ISO 8601 UTC timestamp via NTP | **Done** | Uses `NTPClient` library; strftime to ISO 8601Z (F-07) |
| Reconnect on Wi-Fi drop | **Done** | `ensureWiFi()` helper with 10 s timeout |

### Infrastructure

| Feature | Status | Notes |
|---------|--------|-------|
| PostgreSQL 15 + TimescaleDB hypertable | **Done** | Auto-provisioned on first boot |
| Redis 7 cache | **Done** | TTL configurable via `CACHE_TTL`; reconnect on drop (R-02) |
| Grafana dashboards (pre-provisioned) | **Done** | 6 stat panels, device variable, `$__timeFilter` SQL, P95 latency (F-06) |
| Prometheus metrics + scrape config | **Done** | Requests and latency histograms |
| Prometheus healthcheck | **Done** | `docker-compose.yml` healthcheck added (R-04) |
| Prometheus alert rules | **Partial** | Rules defined; no Alertmanager configured (TASKS R-03) |
| MQTT broker (Mosquitto) | **Done** | Opt-in via `--profile mqtt` |
| Kafka + Zookeeper | **Done** | Opt-in via `--profile kafka` |
| Docker Compose test profile | **Done** | `make test` runs full suite in container |
| Auth (JWT + API key) | **Done** | Opt-in via `ENABLE_AUTH=true`; disabled by default |
| Rate limiting | **Done** | Opt-in via `ENABLE_RATE_LIMITING=true`; disabled by default |
| GitHub Actions CI | **Done** | Builds, starts stack, runs tests, lints on push/PR (DX-01) |

### Security

| Feature | Status | Notes |
|---------|--------|-------|
| JWT Bearer auth | Done (opt-in) | |
| API key auth | Done (opt-in) | |
| Password hashing | **Done** | bcrypt with random salt (replaced SHA-256) — S-01 |
| Rate limiting | Done (opt-in) | Uses TCP peer address only; X-Forwarded-For not trusted (S-02) |
| Real `Retry-After` header | **Done** | Reflects actual token-bucket reset time (S-03) |
| JWT_SECRET_KEY required on startup | **Done** | Raises ValueError if not set |

---

## 3. Known Bugs

No open critical or high bugs at this time.

| ID | Severity | Description | Status |
|----|----------|-------------|--------|
| BUG-01 | ~~HIGH~~ | Data generator sent invalid payloads (wrong field names, missing device_id) | **Resolved** — DX-02 |

---

## 4. Open Tasks by Priority

### High

| ID | Task |
|----|------|
| A-03 | Introduce Alembic for DB migrations |
| R-03 | Wire Prometheus alerts to Alertmanager |
| D-01 | Arduino hardware wiring guide |

### Low / Backlog

| ID | Task |
|----|------|
| DX-03 | Dev container (`.devcontainer/`) |
| D-02 | API versioning strategy (`/api/v1/`) |

Full details in [TASKS.md](../TASKS.md).

---

## 5. Spec Compliance Matrix

Based on `context/spec/001-sensor-monitoring-system/functional-spec.md`.

| Spec Requirement | Implemented | Gap |
|------------------|-------------|-----|
| FR-1.1: Accept sensor data via HTTP POST | Yes | — |
| FR-1.2: Validate temperature, humidity, gas_level ranges | Yes | — |
| FR-1.3: Store all sensor readings with timestamps | Yes | device_id now stored (F-01) |
| FR-1.4: Structured JSON logging per ingestion | Yes | — |
| FR-2.1: Return recent readings | Yes | — |
| FR-2.2: Return time-bucketed aggregations | Yes | hours_back configurable (A-02) |
| FR-2.3: Return latency statistics | Yes | — |
| FR-3.1: Anomaly detection on ingest | Yes | — |
| FR-4.1: Health check endpoint | Yes | Returns 503 on DB failure |
| FR-5.1: Grafana dashboards provisioned | Yes | Redesigned with stat panels and `$__timeFilter` (F-06) |
| FR-5.2: Per-device data queries | Yes | device_id filter on all read endpoints; `/api/devices` (F-02) |

---

## 6. Architecture Decisions (for reference)

See [docs/architecture.md](architecture.md) for full detail.

Key decisions that affect roadmap:
- `device_id` column added to the hypertable with an idempotent `ADD COLUMN IF NOT EXISTS` migration. No Alembic yet — TASKS A-03.
- DB column is named `gas`; API field is named `gas_level`. Renaming the column requires a migration.
- Auth and rate-limiting are complete but **opt-in**. Production deployment must enable them.
- WebSocket connections are tracked in-process (`_ConnectionManager`). Does not survive horizontal scaling — a Redis pub/sub layer would be needed for multi-replica deployments.

# Architecture

## Overview

Six containerized services on a private Docker bridge network (`sensor_network`).
No host software is required beyond Docker and Docker Compose.

## Tech Stack

| Component     | Technology                   | Purpose                                        |
|---------------|------------------------------|------------------------------------------------|
| Backend       | FastAPI + Python 3.11        | REST API, data ingestion, aggregation          |
| Database      | PostgreSQL 15 + TimescaleDB  | Time-series storage with hypertable queries    |
| Cache         | Redis 7                      | Short-lived query cache (default TTL: 60 s)    |
| Visualization | Grafana                      | Pre-provisioned sensor dashboards              |
| Metrics       | Prometheus                   | Backend request counts and latency histograms  |
| Simulator     | Python 3.11                  | Generates realistic sensor readings            |

Optional profiles:

| Component      | Technology        | Profile        |
|----------------|-------------------|----------------|
| Message broker | Mosquitto (MQTT)  | `--profile mqtt`  |
| Event stream   | Apache Kafka 3.7  | `--profile kafka` |

## Service Topology

```
Arduino / Simulator ──POST /api/data──▶ [backend :8000]
                                               │
                          ┌────────────────────┤
                          │                    │
                   [redis :6379]        [db :5432]
                   (cache)              (TimescaleDB)
                                               │
                   [grafana :3000] ────reads───┘
                   [prometheus :9090] ──scrapes /metrics── [backend :8000]
```

Host ports (all configurable via `src/.env`):

| Service    | Host Port | Container Port |
|------------|-----------|----------------|
| Backend    | 8001      | 8000           |
| Grafana    | 3000      | 3000           |
| Prometheus | 9090      | 9090           |
| PostgreSQL | 5433      | 5432           |
| Redis      | 6379      | 6379           |

## Data Flow

1. Sensor data arrives at `POST /api/data` as JSON.
2. Backend validates fields: temperature −50..100 °C, humidity 0..100 %, gas 0..1000 PPM.
3. Record is written to the `sensor_data` TimescaleDB hypertable.
4. Redis cache for recent/aggregated data is invalidated.
5. Anomaly detection (Z-score sliding window) runs in-process; anomalies are logged.
6. Grafana reads directly from PostgreSQL for dashboard panels.
7. Prometheus scrapes `/metrics` for request counts and latency histograms.

## Database Schema

```sql
CREATE TABLE sensor_data (
    id                 SERIAL PRIMARY KEY,
    temperature        DOUBLE PRECISION NOT NULL,
    humidity           DOUBLE PRECISION NOT NULL,
    gas                DOUBLE PRECISION NOT NULL,  -- stores gas_level from API
    sent_timestamp     TIMESTAMP,
    received_timestamp TIMESTAMP,
    stored_timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
    latency_ms         DOUBLE PRECISION
);

-- Converted to a TimescaleDB hypertable on stored_timestamp
SELECT create_hypertable('sensor_data', 'stored_timestamp');
```

### API–Database field mapping

| API input field | DB column         | Notes                                      |
|-----------------|-------------------|--------------------------------------------|
| `device_id`     | *(not stored)*    | Validated (1–64 chars), echoed in response |
| `timestamp`     | *(not stored)*    | Validated, echoed via `sent_timestamp`     |
| `temperature`   | `temperature`     | −50.0 to 100.0 °C                          |
| `humidity`      | `humidity`        | 0.0 to 100.0 %                             |
| `gas_level`     | `gas`             | 0.0 to 1000.0 PPM (column kept as `gas`)   |
| `sent_timestamp`| `sent_timestamp`  | Optional; used to compute `latency_ms`     |
| *(backend)*     | `received_timestamp` | Set by backend at request arrival       |
| *(backend)*     | `stored_timestamp`| Set by backend after DB insert             |
| *(backend)*     | `latency_ms`      | Computed: `received − sent` in ms          |

> **Known gap (DX-02):** `device_id` and `timestamp` are not persisted. The functional spec
> (`context/spec/001-sensor-monitoring-system/`) requires `device_id` for per-device queries.
> This is tracked in TASKS.md as a schema migration item.

## Key Design Decisions

**TimescaleDB over plain PostgreSQL** — automatic time-partitioning and `time_bucket()`
aggregation without additional code or infrastructure.

**Redis cache** — repeated calls to `/api/data/recent` and `/api/data/aggregated` hit
the cache rather than the database; TTL is configurable via `CACHE_TTL`.

**MQTT and Kafka as opt-in profiles** — disabled by default so the standard stack
requires no broker. Enable selectively with `--profile mqtt` or `--profile kafka`.

**In-process anomaly detection** — Z-score sliding window runs inside the backend
process; no separate service or queue needed for the current data rates.

**Authentication disabled by default** — set `ENABLE_AUTH=true` and supply a
`JWT_SECRET_KEY` to require Bearer tokens. API key auth is also supported via `API_KEYS`.

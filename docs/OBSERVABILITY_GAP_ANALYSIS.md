# Observability Gap Analysis

**Project:** Real-Time Data Collection and Monitoring System (IoT)  
**Date:** 2026-03-03  
**Role:** Principal DevOps / Observability Engineer  

---

## 1. Executive Summary

The system already includes **Grafana**, **Prometheus**, **TimescaleDB**, a **FastAPI** backend with a `/metrics` endpoint, and a single provisioned dashboard. This analysis identifies **gaps** between current state and production-grade observability: missing instrumentation, underused Grafana capabilities, broken or incomplete alerting, and no infrastructure/database visibility.

---

## 2. Current State Summary

### 2.1 Services (docker-compose)

| Service         | Image / Build        | Purpose                          | Healthcheck |
|----------------|----------------------|-----------------------------------|-------------|
| db             | timescale/timescaledb:latest-pg15 | PostgreSQL + TimescaleDB      | pg_isready  |
| redis          | redis:7-alpine       | Cache (recent/aggregated data)    | redis-cli ping |
| backend        | ./backend            | FastAPI API + ingestion           | GET /health |
| prometheus     | ./prometheus         | Scrapes backend /metrics          | /-/healthy  |
| grafana        | ./grafana            | Dashboards + provisioning         | /api/health |
| data_generator | ./data_generator     | Simulated sensor HTTP POST         | none        |
| mosquitto      | ./mosquitto (profile mqtt) | MQTT broker                  | mosquitto_sub |
| kafka          | apache/kafka (profile kafka) | Event stream                 | kafka-topics |
| test           | ./tests (profile test) | E2E/integration tests          | none        |

**Findings:**
- Prometheus is present and scrapes only `backend:8000`. No **postgres_exporter**, **redis_exporter**, or **node_exporter**.
- Grafana depends only on `db`; it does not depend on Prometheus. **Prometheus is not provisioned as a Grafana datasource**, so Prometheus metrics are not visible in Grafana.
- Data generator has no healthcheck; no way to detect "simulator stopped" from the stack.

### 2.2 Backend (FastAPI)

**Endpoints relevant to observability:**
- `GET /health` — DB connectivity only (no Redis/cache check).
- `GET /metrics` — Prometheus text format (see §2.4).
- `POST /api/data` — Ingestion; computes **sensor→backend latency** from `sent_timestamp` vs `received_at` and stores `latency_ms` in DB.
- `GET /api/latency/stats` — Returns avg/min/max/median/p95/p99 from recent rows with `latency_ms`.
- `GET /api/anomaly/stats` — In-memory anomaly detector window stats (not persisted).
- `GET /api/devices` — Device list with record counts and first/last seen.
- `GET /api/mqtt/status`, `GET /api/kafka/status` — Optional brokers status.

**Latency handling:**
- **Sensor → Backend:** `latency_ms = (received_at - sent_dt).total_seconds() * 1000` in `main.py`; stored in `sensor_data.latency_ms`.
- **Backend → DB:** Not measured. `insert_sensor_data()` is not instrumented; no `received_timestamp` → `stored_timestamp` delta exposed as a metric.
- **End-to-end:** Only the client-side portion (sent → received) is stored; "received → stored" is not exposed.

**Findings:**
- Health is DB-only; Redis failure is invisible to `/health`.
- No backend→DB latency metric; no async queue (Kafka/MQTT) latency metrics.

### 2.3 Database Schema (PostgreSQL / TimescaleDB)

**Table: `sensor_data`**
- Columns: `id`, `device_id`, `temperature`, `humidity`, `gas`, `sent_timestamp`, `received_timestamp`, `stored_timestamp`, `latency_ms`.
- Hypertable on `stored_timestamp` (time-partitioning).

**What is stored:**
- Sensor values and client→backend latency per row.
- No continuous aggregates, no retention policies, no compression configured in code (database_optimizer has analysis/vacuum helpers only).
- No materialized views or downsampling views for 1m/5m/1h buckets.

**Findings:**
- Schema supports per-device and latency analysis; **device_id** is persisted.
- Missing: continuous aggregates, compression, retention, and dedicated views for "last N minutes" insert rate / slow queries.

### 2.4 Metrics (Prometheus)

**Defined in `backend/metrics.py`:**
- `http_requests_total` (method, endpoint, status) — **used** via MetricsMiddleware.
- `http_request_duration_seconds` (method, endpoint) — **used** via MetricsMiddleware.
- `db_operations_total`, `db_operation_duration_seconds` — **defined but never incremented** (database.py and main.py do not call `record_db_operation()`).
- `db_connection_pool_size` (state: active, idle, total) — **defined but never set** (no `update_connection_pool_metrics()` calls).
- `sensor_data_ingested_total`, `sensor_data_latency_ms` — **defined but never used** (main.py does not call `record_sensor_data_ingestion()`).
- `cache_operations_total`, `cache_operation_duration_seconds` — **defined but never used** (cache.py does not call `record_cache_operation()`).
- `active_connections`, `data_generator_status` — **defined but never updated**.

**Actually exposed on `/metrics`:**
- Only HTTP request counts and request duration histograms (from middleware).
- No DB, cache, ingestion, or pool metrics.

**Findings:**
- Large gap: rich metrics exist in code but are **not wired**; Prometheus only sees HTTP metrics.

### 2.5 Grafana Current Setup

**Datasources (provisioning):**
- **PostgreSQL** only: `db:5432`, database `sensor_db`, user `postgres`, password from env.  
- **Issue:** Provisioning uses `secureJsonData.password: ${POSTGRES_PASSWORD}`; docker-compose passes `DB_PASSWORD` (and other `DB_*`) to Grafana. So **POSTGRES_PASSWORD** may be unset in the Grafana container unless set explicitly or aligned with `.env`.
- **UID:** Datasource has no explicit `uid`; dashboards reference `"uid": "PostgreSQL"`. Grafana may assign an internal UID; alert rules use `datasourceUid: postgres` (lowercase), which can **mismatch**.

**Dashboards:**
- Single dashboard: **"Real-Time Sensor Data Dashboard"** (uid: `sensor-monitor-v2`).
- Panels: Current Temperature/Humidity/Gas (stat), Avg Latency, Total Records, Active Devices; time series for Temperature, Humidity, Gas, All Sensors, End-to-End Latency; Max Latency, P95 Latency (stat); 5-minute aggregated averages.
- Uses `$__timeFilter(stored_timestamp)` and device variable `$device` (from `SELECT DISTINCT device_id`).
- **Gaps:** No heatmaps, no moving averages, no anomaly annotations, no drill-downs, no folder structure, no system/DB/API dashboards, no Prometheus-sourced panels.

**Alerting (provisioning):**
- File: `grafana/provisioning/alerting/alert_rules.yml`.
- Rules reference **datasourceUid: postgres** and use **model.expr** with Prometheus-like expressions (e.g. `avg(temperature) > 30`). Grafana’s PostgreSQL datasource expects **SQL**, not PromQL. So these rules are **invalid** for the current datasource type and will not evaluate correctly.
- No contact points (email, webhook, Telegram) provisioned; no notification policies.

**Findings:**
- Dashboard is sensor-centric and reasonably complete for one view; lacks system/infra, latency breakdown, and Prometheus metrics.
- Alert rules are **broken** (wrong query type for PostgreSQL); alerting channel configuration is missing.

### 2.6 Prometheus Configuration

- **Scrape:** `prometheus`, `backend` (metrics_path `/metrics`).
- **Commented:** postgres exporter, redis exporter.
- **Rule file:** `alerts.yml` — BackendDown, HighRequestLatency, HighErrorRate; DatabaseConnectionHigh, DatabaseSlowQueries (depend on unconfigured postgres exporter); RedisDown, HighCacheMissRate (depend on unconfigured redis exporter).
- **Alertmanager:** Section present but target commented out; alerts never sent anywhere.

**Findings:**
- Only backend HTTP metrics are collected. DB and Redis alerts reference metrics that do not exist; Alertmanager is not connected.

### 2.7 Data Generator

- Sends POST to `BACKEND_URL` with `device_id`, `timestamp`, `sent_timestamp`, temperature, humidity, gas_level.
- No metrics exported; no health endpoint; no way for Prometheus/Grafana to know if the generator is running or failing.

### 2.8 Logs

- Structured JSON logging with request_id (RequestIDMiddleware); ingestion and errors logged with extra_fields.
- Logs go to stdout; no centralized log pipeline (e.g. Loki) or log-based metrics in Grafana.

---

## 3. Gap Matrix

| Area | What Exists | What’s Missing / Broken |
|------|-------------|--------------------------|
| **Metrics – Backend** | HTTP request count + duration | DB operation count/duration, connection pool size, sensor ingestion count/latency, cache hit/miss/duration, backend→DB latency |
| **Metrics – Database** | None | Query duration, connection count, insert rate, slow queries, storage size, write amplification (no postgres_exporter) |
| **Metrics – Cache** | None | Hit/miss rate, latency, keys (no redis_exporter) |
| **Metrics – Docker/Node** | None | Container CPU/memory, restarts, network/disk (no cAdvisor/node_exporter) |
| **Grafana – Datasources** | PostgreSQL only | Prometheus datasource not provisioned; PostgreSQL uid/password env mismatch risk |
| **Grafana – Dashboards** | One sensor dashboard | Sensor heatmaps, moving averages, anomaly annotations; system/API/DB/ops dashboards; folder structure; time-range presets |
| **Grafana – Alerting** | Provisioned rules | Rules use PromQL on PostgreSQL datasource (invalid); no SQL-based rules; no contact points; no severity matrix |
| **Prometheus – Scrape** | Backend only | postgres_exporter, redis_exporter (and optionally node/cAdvisor) not in stack |
| **Prometheus – Alerts** | Rules defined | DB/Redis rules reference non-existent metrics; Alertmanager not configured |
| **TimescaleDB** | Hypertable only | No continuous aggregates, compression, or retention policies |
| **Latency** | Sensor→backend in DB | Backend→DB and end-to-end pipeline not in metrics; no latency histogram in Prometheus |
| **Health** | /health (DB only) | Redis, optional MQTT/Kafka not in health; no readiness vs liveness split |
| **Anomaly** | In-memory detector, /api/anomaly/stats | Anomalies not persisted; no Grafana annotations or alerts from anomaly events |

---

## 4. What Can Be Measured but Is Not

- **Backend:** Per-endpoint error rate, throughput (req/s), DB operation duration and count, cache hit/miss and duration, connection pool utilization, ingestion count and sensor latency histogram.
- **Database:** Connections, transactions, insert rate, query duration (if pg_stat_statements enabled), table size, replication lag (N/A single node).
- **Redis:** Connected clients, memory, hit/miss, latency.
- **Containers:** CPU, memory, network I/O, restart count (cAdvisor / Docker metrics).
- **IoT-specific:** Sensor offline (no data from device_id for N seconds), data loss (gaps in stored_timestamp), threshold breaches (temperature/gas) over time, latency percentiles over time.

---

## 5. IoT Production-Grade Monitoring Checklist

| Requirement | Status |
|-------------|--------|
| Real-time sensor values (T/H/G) with per-device filter | ✅ Dashboard |
| Historical comparison and time-range zoom | ✅ Time picker |
| Latency (sensor→backend) in DB and on dashboard | ✅ Stored + panels |
| Backend and DB latency in metrics | ❌ Not measured |
| Request rate and error rate | ✅ Prometheus (HTTP only) |
| DB and cache health and metrics | ❌ No exporters / no wiring |
| Temperature/humidity/gas thresholds with alerts | ⚠️ Alerts defined but broken (wrong query type) |
| Sensor offline / no data for N seconds | ⚠️ Rule exists but broken |
| Backend/database down alerts | ✅ Prometheus (backend); ❌ DB (no exporter) |
| Dashboards for system and API performance | ❌ Missing |
| Alert channels (email/webhook/Telegram) | ❌ Not configured |
| Downsampling / aggregates for long-term trends | ❌ No continuous aggregates |
| Anomaly visibility (annotations / events) | ❌ Not in Grafana |

---

## 6. Conclusion

The stack has a solid base (TimescaleDB, Prometheus scrape of backend, one Grafana dashboard with device variable and latency panels) but **observability is underused and partially broken**:

1. **Instrumentation:** Most of `metrics.py` is unused; DB, cache, and ingestion are invisible to Prometheus.
2. **Data sources:** Grafana does not use Prometheus; DB/Redis are not scraped.
3. **Alerting:** Grafana rules are invalid (PromQL on PostgreSQL); Prometheus DB/Redis rules reference missing metrics; no notification channels.
4. **Dashboards:** Only sensor view; no system, API, latency breakdown, or operational dashboards.
5. **TimescaleDB:** No continuous aggregates, compression, or retention.
6. **Latency:** Backend→DB and full pipeline not exposed as metrics.

The next phase is to **design** a full Grafana + Prometheus + instrumentation strategy, then **implement** wiring of metrics, addition of exporters, provisioning of Prometheus in Grafana, new dashboards, SQL-based Grafana alerts, and TimescaleDB optimizations, without breaking existing functionality.

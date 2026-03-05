# Grafana Observability Strategy

**Project:** Real-Time Data Collection and Monitoring System  
**Phase:** 2 — Design  
**Date:** 2026-03-03  

---

## 1. Architecture Overview

```
                    ┌─────────────────────────────────────────────────────────────┐
                    │                     OBSERVABILITY STACK                        │
                    └─────────────────────────────────────────────────────────────┘
┌──────────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────────────┐
│ Data Gen     │────▶│ Backend      │────▶│ TimescaleDB  │◀────│ PostgreSQL Exporter  │
│ (simulator)  │     │ (FastAPI)     │     │ (sensor_data)│     │ :9187                 │
└──────────────┘     │ /metrics     │     └──────────────┘     └──────────┬───────────┘
                     └──────┬───────┘                │                      │
                            │                        │                      │
                            ▼                        │     ┌────────────────┴────────┐
                     ┌──────────────┐                │     │ Redis Exporter :9121    │
                     │ Prometheus   │◀────────────────┴─────┤ (optional)               │
                     │ :9090        │  scrape               └─────────────────────────┘
                     └──────┬───────┘
                            │
                            ▼
                     ┌──────────────┐     ┌──────────────────────┐
                     │ Grafana      │────▶│ PostgreSQL (sensor    │
                     │ :3000        │     │ data + aggregates)   │
                     │              │     └──────────────────────┘
                     │ Datasources: │     ┌──────────────────────┐
                     │ - PostgreSQL │────▶│ Prometheus (metrics   │
                     │ - Prometheus │     │ + infra)             │
                     └──────────────┘     └──────────────────────┘
```

---

## 2. Dashboard Strategy

### 2.1 Folder Structure

| Folder | Purpose |
|--------|---------|
| **Sensors** | Per-sensor and multi-sensor dashboards (raw + aggregated) |
| **System** | Backend, API, infrastructure health |
| **Database** | PostgreSQL/TimescaleDB performance and growth |
| **Latency** | End-to-end and component latency |
| **Operations** | Alerts, errors, device status, data loss |

### 2.2 Sensor-Level Dashboards

- **Real-Time Sensor Data** (existing, enhanced): Current T/H/G, latency, records; time series with threshold bands; device variable; time presets (5m, 1h, 6h, 24h); 5m aggregated panel.
- **Sensor Deep Dive**: Per-sensor selection; moving averages (5m, 15m); heatmaps (temperature/humidity/gas over time); historical comparison (e.g. last 7 days overlay); anomaly threshold coloring; link to Operations for alerts.
- **Aggregates & Trends**: Panels from continuous aggregates (1m, 5m, 1h buckets); daily averages; trend detection (slope); raw vs downsampled toggle via variable.

### 2.3 System Performance

- **Backend**: Request count (by endpoint, status), request duration (p50, p95, p99), error rate, throughput (req/s), uptime (up probe).
- **API Performance**: Per-route latency histogram, 5xx rate, cache hit/miss from Prometheus.
- **Infrastructure**: Container CPU/memory (cAdvisor if added), restart count; optional node_exporter for host.

### 2.4 Database

- Query duration (from backend DB metrics + optional pg_stat_statements), connection pool usage (active/idle/total), insert rate, slow query count, table/chunk size growth, compression ratio (TimescaleDB).

### 2.5 Latency Monitoring

- **Sensor → Backend**: From PostgreSQL `latency_ms` and from Prometheus `sensor_data_latency_ms` (after instrumentation).
- **Backend → DB**: From new metric `db_operation_duration_seconds` (insert).
- **End-to-end**: Sum/overlay sensor→backend + backend→DB where applicable.
- Panels: Latency over time, histogram, p50/p95/p99; alert if p95 > threshold.

### 2.6 Operational Dashboards

- **System Health Overview**: Single pane – backend up, DB up, Redis up, last data received, active devices, critical alerts.
- **IoT Device Status**: Table/cards – device_id, last_seen, record count, status (online/offline by threshold).
- **Errors**: Error rate by endpoint, DB errors, cache errors; links to logs if Loki added later.
- **Data Loss / Sensor Offline**: No data from device for N minutes; gap detection (optional, from time buckets).

### 2.7 Advanced Grafana Features

- **Variables**: Device, time range presets, threshold (e.g. temp max), bucket interval (1m/5m/1h).
- **Templating**: Reusable queries for “last value”, “aggregate”, “count in range”.
- **Annotations**: Anomaly events (if we persist anomaly flags to DB or expose via API and query in Grafana).
- **Panel links**: From sensor panel → Latency dashboard; from System Health → API Performance.
- **Theme**: Support dark/light via default preference.
- **Auto-refresh**: 5s for real-time sensor; 30s–1m for system/DB.
- **Versioning**: Dashboards in git (provisioned JSON); no version field in UI required for initial rollout.

---

## 3. Alerting Strategy

### 3.1 Severity Levels

| Level | Use |
|-------|-----|
| **Critical** | Service down, DB unreachable, no data for extended period, gas danger |
| **Warning** | High latency, high error rate, threshold breach (temp/humidity), sensor offline |
| **Info** | Optional: anomaly detected, cache miss rate high |

### 3.2 Grafana Alerts (SQL-Based, PostgreSQL)

- **Temperature High**: `SELECT 1 WHERE (SELECT AVG(temperature) FROM sensor_data WHERE stored_timestamp > NOW() - INTERVAL '5 minutes') > 35` → Warning/Critical.
- **Temperature Low**: Same pattern for &lt; 10.
- **Gas Danger**: `AVG(gas) > 400` over 5m → Critical.
- **Humidity High**: `AVG(humidity) > 85` over 5m → Warning.
- **No Data Received**: `SELECT 1 WHERE (SELECT COUNT(*) FROM sensor_data WHERE stored_timestamp > NOW() - INTERVAL '10 minutes') = 0` → Critical.
- **Sensor Offline**: Per device: no row for device_id in last N minutes (e.g. 5m) → Warning.
- **High Latency**: `SELECT 1 WHERE (SELECT PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY latency_ms) FROM sensor_data WHERE stored_timestamp > NOW() - INTERVAL '5 minutes') > 500` → Warning.

All use PostgreSQL datasource with `refId`, `relativeTimeRange`, and `model` containing **raw SQL** (not PromQL).

### 3.3 Prometheus Alerts

- **BackendDown**: `up{job="backend"} == 0` → Critical.
- **HighRequestLatency**: p95 > 1s for 5m → Warning.
- **HighErrorRate**: 5xx rate > 5% for 5m → Warning.
- **RedisDown**: `up{job="redis"} == 0` (after redis_exporter) → Critical.
- **DatabaseDown**: `up{job="postgres"} == 0` (after postgres_exporter) → Critical.
- **HighDBLatency**: `db_operation_duration_seconds` p95 > threshold (after instrumentation) → Warning.

### 3.4 Alert Channels

- **Contact points**: Email (SMTP), Webhook (generic), Telegram (bot token).
- **Notification policies**: Route by severity (Critical → all channels; Warning → email + webhook; Info → optional).
- Provision via Grafana (provisioning YAML or API) or env-based config.

---

## 4. Time-Series Optimization (TimescaleDB)

- **Continuous aggregates**: e.g. `sensor_data_1m`, `sensor_data_5m`, `sensor_data_1h` (avg, min, max, count per bucket).
- **Retention**: e.g. raw data 30 days; optionally keep 1h aggregates 1 year (policy on materialized hypertable).
- **Compression**: Enable on `sensor_data` after N days (e.g. 7) to reduce storage.
- **Views**: Optional materialized view for “last 24h 5m buckets” for fast dashboard load.
- Dashboards: Panels for raw (short range) and aggregated (long range) with variable-driven queries.

---

## 5. Prometheus Integration

- **Add Prometheus datasource** in Grafana (provisioned), same network as Prometheus.
- **Backend**: Keep and extend `/metrics`; wire `record_db_operation`, `record_sensor_data_ingestion`, `record_cache_operation`, `update_connection_pool_metrics` in backend code.
- **postgres_exporter**: Add container; scrape DB metrics (connections, transactions, size, optional pg_stat_statements).
- **redis_exporter**: Add container; scrape Redis (memory, keys, hits/misses, latency).
- **Optional**: cAdvisor for container metrics; node_exporter for host (if not Docker-only).
- **Alertmanager**: Optional; connect in prometheus.yml and configure routes for Critical/Warning.

---

## 6. Implementation Order

1. **Backend instrumentation**: Call metrics helpers from database.py, cache.py, main.py (ingestion + pool).
2. **Grafana datasources**: Add Prometheus; fix PostgreSQL uid and password env (POSTGRES_PASSWORD or DB_PASSWORD).
3. **TimescaleDB**: Create continuous aggregates (1m, 5m, 1h); add compression and retention in migrations or init_db.
4. **Exporters**: Add postgres_exporter and redis_exporter to docker-compose; add scrape configs in Prometheus.
5. **Grafana dashboards**: New JSON files – System Health, API Performance, Database, Latency, Operations; place in folders via provisioning.
6. **Grafana alerts**: Replace alert_rules.yml with SQL-based queries; fix datasource UID; add contact points (email, webhook, Telegram if configured).
7. **Prometheus alerts**: Remove or fix rules that depend on missing metrics; enable Alertmanager if desired.
8. **Verification**: Run stack; validate metrics, dashboards, and alert evaluation.

---

## 7. Deliverables (Phase 4)

- Observability architecture diagram (this document + diagram above).
- List of added dashboards and panels.
- List of added/used metrics.
- Alert matrix (rule name, condition, severity, channel).
- Performance impact analysis (scrape load, query load, storage).
- Suggestions for future scaling (Loki, distributed tracing, more devices).

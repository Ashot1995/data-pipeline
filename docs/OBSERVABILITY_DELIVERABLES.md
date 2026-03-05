# Observability Implementation — Final Deliverables

**Project:** Real-Time Data Collection and Monitoring System  
**Date:** 2026-03-03  

---

## 1. Observability Architecture Diagram

```
                    ┌─────────────────────────────────────────────────────────────────┐
                    │                     OBSERVABILITY STACK                            │
                    └─────────────────────────────────────────────────────────────────┘

  Data Generator ──POST /api/data──▶ [ Backend :8000 ] ──▶ [ TimescaleDB :5432 ]
         │                                    │                        │
         │                                    │ /metrics                │
         │                                    ▼                         │
         │                           [ Prometheus :9090 ] ◀─────────────┘
         │                                    │              postgres-exporter :9187
         │                                    │              redis-exporter :9121
         │                                    │
         │                                    ▼
         │                           [ Grafana :3000 ]
         │                                    │
         │                    Datasources: PostgreSQL (postgres) + Prometheus (prometheus)
         │                    Dashboards: Sensors | System | API | Database | Operations
         │                    Alerts: Sensor Alerts (PostgreSQL time-series rules)
         └────────────────────────────────────────────────────────────────────────────
```

---

## 2. List of Added Dashboards

| Dashboard | UID | Folder | Purpose |
|-----------|-----|--------|---------|
| Real-Time Sensor Data Dashboard | sensor-monitor-v2 | (root) | Existing; device variable, T/H/G, latency, 5m aggregates. Datasource UID fixed to `postgres`. |
| System Health Overview | system-health | System | Backend/Postgres/Redis up, DB pool size, records (1h), request rate, error rate. |
| API Performance | api-performance | API | Request duration p50/p95/p99, DB operation duration, sensor latency histogram, cache hit/miss. |
| Database Health | database-health | Database | DB connections (pg_stat_database_numbackends), backend pool active/idle/total, insert rate, ingestion rate. |
| IoT Device Status | operations-devices | Operations | Table of devices with record count, first/last seen; stats for last 10m and 1h. |

---

## 3. List of Added / Wired Metrics

### Backend (Prometheus `/metrics`)

| Metric | Type | Labels | Status |
|--------|------|--------|--------|
| http_requests_total | Counter | method, endpoint, status | Already present |
| http_request_duration_seconds | Histogram | method, endpoint | Already present |
| db_operations_total | Counter | operation, status | **Wired** (database.py) |
| db_operation_duration_seconds | Histogram | operation | **Wired** (database.py) |
| db_connection_pool_size | Gauge | state (active, idle, total) | **Wired** (update_pool_metrics + lifespan task) |
| sensor_data_ingested_total | Counter | sensor_type | **Wired** (main.py) |
| sensor_data_latency_ms | Histogram | — | **Wired** (main.py) |
| cache_operations_total | Counter | operation, status | **Wired** (cache.py) |
| cache_operation_duration_seconds | Histogram | operation | **Wired** (cache.py) |

### Scrape Targets (Prometheus)

| Job | Target | Purpose |
|-----|--------|---------|
| prometheus | localhost:9090 | Self |
| backend | backend:8000 | FastAPI metrics |
| postgres | postgres-exporter:9187 | PostgreSQL (pg_stat_*, etc.) |
| redis | redis-exporter:9121 | Redis (memory, keys, hits/misses) |

---

## 4. Alert Matrix

| Rule | Source | Condition | Severity | Channel (optional) |
|------|--------|-----------|----------|---------------------|
| High Temperature | Grafana (PostgreSQL) | Avg temperature > 35°C for 5m | Warning | default-webhook / default-email |
| Low Temperature | Grafana (PostgreSQL) | Avg temperature < 10°C for 5m | Warning | same |
| High Humidity | Grafana (PostgreSQL) | Avg humidity > 85% for 5m | Warning | same |
| High Gas Concentration | Grafana (PostgreSQL) | Avg gas > 400 PPM for 5m | Critical | same |
| High Latency | Grafana (PostgreSQL) | P95 latency > 500 ms for 5m | Warning | same |
| No Data Received | Grafana (PostgreSQL) | No rows in last 10m for 2m | Critical | same |
| BackendDown | Prometheus | up{job="backend"} == 0 for 1m | Critical | (Alertmanager if configured) |
| HighRequestLatency | Prometheus | p95 request duration > 1s for 5m | Warning | same |
| HighErrorRate | Prometheus | 5xx rate / total rate > 5% for 5m | Warning | same |
| DatabaseConnectionHigh | Prometheus | pg_stat_database_numbackends > 50 for 5m | Warning | same |
| RedisDown | Prometheus | up{job="redis"} == 0 for 1m | Critical | same |
| HighCacheMissRate | Prometheus | Cache miss rate > 50% for 5m | Warning | same |

---

## 5. Performance Impact Analysis

- **Backend:** Per-request overhead from MetricsMiddleware (timer + counter) is negligible. DB/cache metric calls add ~microseconds per operation. Pool metrics run every 15s in a background task (one `pg_stat_activity` query + pool.get_size()).
- **Prometheus:** Scrape interval 15s for backend, postgres, redis. Typical scrape size for backend is small (a few KB). No high-cardinality labels added.
- **Grafana:** PostgreSQL panels use existing indexes and time filters. New dashboards use Prometheus for infra metrics; no heavy ad-hoc SQL.
- **Database:** Continuous aggregate, compression, and retention were added in init_db; they only apply when the table is already a hypertable (see §6). If applied, refresh runs every 5m for the 5m aggregate; compression and retention run on a schedule (minimal CPU).

---

## 6. Known Limitations and Suggestions for Future Scaling

- **Hypertable:** If `sensor_data` was created earlier with a primary key that does not include `stored_timestamp`, TimescaleDB will not convert it to a hypertable. Then continuous aggregate, compression, and retention will not be created (init_db logs warnings). For new deployments, consider creating the table with a composite primary key (e.g. `(stored_timestamp, id)`) or no primary key before `create_hypertable`.
- **Grafana alert thresholds:** Temperature/humidity/gas/latency thresholds are in the alert rule titles/annotations; the actual condition (e.g. “Is above 35”) must be configured in the Grafana UI for each rule (condition expression) or via a full export of the condition block. The provisioned rules supply the data query; threshold is typically set in the UI or in the condition ref.
- **Contact points:** `contact-points.yml` references `GF_ALERTING_WEBHOOK_URL` and `GF_ALERTING_EMAIL`. Set these in the Grafana container env to enable notifications.
- **Scaling:** For more devices, consider: (1) Loki for log aggregation and log-based metrics; (2) distributed tracing (e.g. Tempo) for request flows; (3) Alertmanager for routing Prometheus alerts to PagerDuty/Slack; (4) per-device dashboards or variables to reduce query load.

---

## 7. Verification Steps

1. **Stack up:**  
   `cd src && docker compose up -d db redis backend prometheus postgres-exporter redis-exporter grafana data_generator`

2. **Backend health and metrics:**  
   `curl -s http://localhost:8001/health` → `{"status":"healthy","database":"connected"}`  
   `curl -s http://localhost:8001/metrics | grep -E "db_|sensor_data_|cache_operations"` → metrics present after a few ingestions.

3. **Prometheus targets:**  
   Open http://localhost:9090/targets — backend, postgres, redis should be UP.

4. **Grafana:**  
   Open http://localhost:3000 (admin/admin).  
   - **Datasources:** PostgreSQL (uid postgres) and Prometheus (uid prometheus) should be green.  
   - **Dashboards:** “Real-Time Sensor Data Dashboard”, “System Health Overview”, “API Performance”, “Database Health”, “IoT Device Status” should load; panels may show “No data” until time range and queries match (e.g. Prometheus panels need backend and exporters scraped).

5. **Alerts:**  
   In Grafana, Alerting → Alert rules; “Sensor Alerts” group should list the 6 rules. Fix any condition (e.g. threshold) in the UI if the rule uses “last value” and you want “above X”.

6. **Simulate sensor failure:**  
   Stop data_generator: `docker stop sensor_generator`. After 10+ minutes, “No Data Received” (and optionally “Sensor Offline”) should fire if configured.

7. **Simulate high latency / DB load:**  
   Use a load tool against `POST /api/data` or run heavy queries; check “API Performance” and “Database Health” for latency and pool usage.

8. **Recovery:**  
   Start data_generator again; ensure new data appears in the Sensor dashboard and that “No Data Received” resolves.

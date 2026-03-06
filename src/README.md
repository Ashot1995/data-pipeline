# Real-Time Data Collection and Monitoring System

A comprehensive IoT data pipeline system that collects sensor data (temperature, humidity, gas concentration) from Arduino hardware or Python simulator, stores it in PostgreSQL with TimescaleDB optimization, and visualizes it in real-time using Grafana dashboards.

## 🏗️ Architecture

```
┌─────────────┐      ┌──────────────┐      ┌─────────────┐      ┌─────────────┐
│   Arduino   │      │   Python     │      │   FastAPI   │      │ PostgreSQL  │
│   / ESP8266 │─────▶│   Generator  │─────▶│   Backend   │─────▶│ TimescaleDB │
└─────────────┘      └──────────────┘      └─────────────┘      └─────────────┘
                                                                        │
                                                                        ▼
                                                               ┌─────────────┐
                                                               │   Grafana   │
                                                               │  Dashboards │
                                                               └─────────────┘
```

### Components

1. **Backend (FastAPI)**: REST API for data ingestion and retrieval
2. **Database (PostgreSQL/TimescaleDB)**: Time-series optimized data storage
3. **Data Generator (Python)**: Simulates sensor data for testing
4. **Grafana**: Real-time data visualization dashboards
5. **Arduino Node**: Hardware sensor data collection (optional)

## 🚀 Quick Start

### Prerequisites

- Docker 20.10+ and Docker Compose 2.0+
- Git
- Python 3.9+ (optional, for local development)

### Installation

1. **Clone the repository and enter the src directory:**
   ```bash
   git clone <repository-url>
   cd <repo>/src
   ```

2. **Set up environment variables:**
   ```bash
   cp .env.example .env
   # Edit .env with your configuration (optional)
   ```

3. **Start all services:**
   ```bash
   docker compose up --build
   ```

4. **Verify services are running:**
   ```bash
   docker compose ps
   ```

### Access Points

- **FastAPI API**: http://localhost:8001
- **FastAPI Docs**: http://localhost:8001/docs
- **Grafana Dashboard**: http://localhost:3000 (admin/admin)
- **Database**: localhost:5433 (postgres/postgres)

## 📋 Project Structure

```
src/
├── backend/
│   ├── main.py              # FastAPI application
│   ├── database.py           # Database operations
│   ├── requirements.txt      # Python dependencies
│   └── Dockerfile            # Backend container
│
├── data_generator/
│   ├── generator.py          # Sensor data simulator
│   └── Dockerfile            # Generator container
│
├── arduino/
│   └── sketch.ino            # Arduino code
│
├── grafana/
│   └── provisioning/
│       ├── datasources/      # PostgreSQL datasource config
│       └── dashboards/       # Dashboard definitions
│
├── tests/
│   ├── conftest.py           # Pytest fixtures
│   ├── test_backend_api.py   # API tests
│   ├── test_database_*.py    # Database tests
│   ├── test_e2e.py           # End-to-end tests
│   └── test_docker_compose.py # Docker config tests
│
├── docker-compose.yml        # Service orchestration
├── pytest.ini               # Test configuration
├── requirements-dev.txt      # Development dependencies
├── Makefile                  # Development commands
└── README.md                 # This file
```

## 🔧 Development

### Using Makefile

```bash
# Show all available commands
make help

# Initial setup
make setup

# Start services
make up

# Stop services
make down

# Run tests
make test

# Run specific test types
make test-unit
make test-integration
make test-api

# Code quality
make lint
make format

# View logs
make logs
make logs-backend
make logs-db

# Database shell
make db-shell

# Health check
make health
```

### Manual Commands

```bash
# Start services
docker compose up -d

# View logs
docker compose logs -f [service_name]

# Stop services
docker compose down

# Rebuild services
docker compose build --no-cache

# Run tests (inside container — stack must be running)
docker compose --profile test run --rm test
```

## 📡 API Endpoints

### GET /
API information and available endpoints.

### GET /health
Health check endpoint. Returns service status and database connection status.

**Response:**
```json
{
  "status": "healthy",
  "database": "connected"
}
```

### POST /api/data
Ingest sensor data.

**Request:**
```json
{
  "device_id": "sensor-001",
  "timestamp": "2024-01-15T12:00:00Z",
  "temperature": 23.5,
  "humidity": 45.0,
  "gas_level": 175.0,
  "sent_timestamp": "2024-01-15T12:00:00Z"
}
```

All fields except `sent_timestamp` are required. Field constraints:
- `device_id`: 1–64 characters
- `temperature`: −50.0 to 100.0 °C
- `humidity`: 0.0 to 100.0 %
- `gas_level`: 0.0 to 1000.0 PPM

**Response:**
```json
{
  "status": "success",
  "id": 123,
  "device_id": "sensor-001",
  "data": {
    "temperature": 23.5,
    "humidity": 45.0,
    "gas_level": 175.0
  },
  "timestamps": {
    "client": "2024-01-15T12:00:00Z",
    "received": "2024-01-15T12:00:00.045Z",
    "stored": "2024-01-15T12:00:00.048Z",
    "latency_ms": 45.23
  },
  "anomaly_detection": {
    "anomalies": {"temperature": false, "humidity": false, "gas": false},
    "scores": {"temperature": 0.1, "humidity": 0.3, "gas": 0.05}
  }
}
```

### GET /api/data/recent
Get recent sensor data records.

**Query Parameters:**
- `limit` (optional): Maximum number of records (default: 100)

**Example:**
```bash
curl http://localhost:8001/api/data/recent?limit=10
```

### GET /api/data/aggregated
Get aggregated sensor data using time buckets.

**Query Parameters:**
- `interval_minutes` (optional): Time bucket interval in minutes (default: 5)
- `limit` (optional): Maximum number of buckets (default: 100)

**Example:**
```bash
curl http://localhost:8001/api/data/aggregated?interval_minutes=5&limit=20
```

### GET /api/latency/stats
Get latency statistics from recent records.

**Query Parameters:**
- `limit` (optional): Number of recent records to analyze (default: 1000)

**Response:**
```json
{
  "total_records": 1000,
  "records_with_latency": 950,
  "avg_latency_ms": 45.23,
  "min_latency_ms": 12.5,
  "max_latency_ms": 156.8,
  "median_latency_ms": 42.1,
  "p95_latency_ms": 89.5,
  "p99_latency_ms": 125.3
}
```

## 🗄️ Database Schema

### sensor_data Table

```sql
CREATE TABLE sensor_data (
    id                 SERIAL PRIMARY KEY,
    temperature        DOUBLE PRECISION NOT NULL,
    humidity           DOUBLE PRECISION NOT NULL,
    gas                DOUBLE PRECISION NOT NULL,  -- stores gas_level from API
    sent_timestamp     TIMESTAMP,
    received_timestamp TIMESTAMP,
    stored_timestamp   TIMESTAMP NOT NULL DEFAULT NOW(),
    latency_ms         DOUBLE PRECISION,
    device_id          VARCHAR(64)
);

-- Converted to a TimescaleDB hypertable on stored_timestamp
SELECT create_hypertable('sensor_data', 'stored_timestamp');
```

> **Note:** The API accepts `gas_level` (input) and returns `gas_level` (response), but the
> database column is named `gas`. `device_id` is stored and used for per-device queries.
> `timestamp` is validated at the API layer but not persisted — it is echoed back as
> `sent_timestamp` in the response.

## 🧪 Testing

### Test Structure

- **Unit Tests**: Fast, isolated tests for individual functions
- **Integration Tests**: Test component interactions
- **End-to-End Tests**: Test full system flow
- **Docker Tests**: Test Docker Compose configuration

### Running Tests

All tests run inside Docker containers — do not run pytest directly on the host.

```bash
# All tests (stack must be running: make up)
make test

# Specific test subsets
make test-unit          # fast tests, no services needed
make test-integration   # requires running DB
make test-api           # API endpoint tests

# Lint and format checks
make lint
make format-check
```

### Test Files

- `test_backend_api.py` - API endpoint tests
- `test_database_schema.py` - Database schema tests
- `test_database_persistence.py` - Data persistence tests
- `test_e2e.py` - End-to-end integration tests
- `test_docker_compose.py` - Docker configuration tests

## 🔐 Environment Variables

See `.env.example` for all available environment variables:

### Database
- `DB_HOST` - Database hostname (default: `db`)
- `DB_PORT` - Database port (default: `5432`)
- `DB_NAME` - Database name (default: `sensor_db`)
- `DB_USER` - Database user (default: `postgres`)
- `DB_PASSWORD` - Database password (default: `postgres`)

### Backend
- `BACKEND_PORT` - External port for backend (default: `8001`)

### Grafana
- `GRAFANA_PORT` - External port for Grafana (default: `3000`)
- `GRAFANA_USER` - Grafana admin username (default: `admin`)
- `GRAFANA_PASSWORD` - Grafana admin password (default: `admin`)

### Data Generator
- `BACKEND_URL` - Backend API URL (default: `http://backend:8000/api/data`)
- `INTERVAL_SECONDS` - Data generation interval (default: `5`)
- `BASE_TEMPERATURE` - Base temperature value (default: `23.0`)
- `BASE_HUMIDITY` - Base humidity value (default: `45.0`)
- `BASE_GAS` - Base gas value (default: `150.0`)

## 📊 Grafana Dashboards

The system includes a pre-configured Grafana dashboard with:

- **Temperature Over Time**: Real-time temperature visualization with thresholds
- **Humidity Over Time**: Humidity percentage tracking
- **Gas Concentration**: Gas levels in PPM with warning thresholds
- **Combined Sensor Overview**: All sensors on one panel
- **Latency Tracking**: System latency over time
- **Latency Statistics**: Average, min, max latency metrics
- **Aggregated Views**: 5-minute and 1-hour aggregated data

### Accessing Grafana

1. Open http://localhost:3000
2. Login with admin/admin (or your configured credentials)
3. Navigate to "Dashboards" → "Real-Time Sensor Data Dashboard"

## 🔌 Arduino Integration

### Hardware Requirements

- Arduino Uno (or compatible)
- ESP8266 Wi-Fi Module
- DHT11 Temperature & Humidity Sensor
- MQ-2 Gas Sensor

### Setup

1. **Install Libraries:**
   - ESP8266WiFi
   - DHT sensor library

2. **Configure Wi-Fi:**
   ```cpp
   const char* ssid = "YOUR_WIFI_SSID";
   const char* password = "YOUR_WIFI_PASSWORD";
   ```

3. **Configure Backend URL:**
   ```cpp
   const char* backendUrl = "http://YOUR_BACKEND_IP:8000/api/data";
   ```

4. **Upload Sketch:**
   - Open `arduino/sketch.ino` in Arduino IDE
   - Upload to Arduino board

See [TASKS.md](../TASKS.md) item D-01 — a hardware wiring guide is planned but not yet written.

## 🐛 Troubleshooting

### Backend Cannot Connect to Database

**Symptoms**: Backend logs show connection errors

**Solutions**:
1. Check database is running: `docker compose ps db`
2. Verify database health: `docker compose logs db`
3. Check environment variables: `docker compose config`
4. Restart services: `docker compose restart`

### Grafana Shows No Data

**Symptoms**: Dashboard panels show "No data"

**Solutions**:
1. Verify datasource connection: Grafana → Configuration → Data Sources → Test
2. Check time range: Use "Last 15 minutes" or appropriate range
3. Verify data exists: `curl http://localhost:8001/api/data/recent?limit=5`
4. Check SQL queries in dashboard panels

### Port Conflicts

**Symptoms**: Services fail to start with port binding errors

**Solutions**:
1. Check port usage: `netstat -tulpn | grep <port>` or `lsof -i :<port>`
2. Change ports in `.env` file
3. Stop conflicting services

### Data Generator Not Sending Data

**Symptoms**: No data appearing in database

**Solutions**:
1. Check generator logs: `docker compose logs data_generator`
2. Verify backend is healthy: `curl http://localhost:8001/health`
3. Check BACKEND_URL environment variable
4. Restart generator: `docker compose restart data_generator`

Check `docker compose logs <service>` for detailed error output from any service.

## 📈 Performance

### Expected Performance

- **Latency**: < 100ms average (local Docker network)
- **Throughput**: Handles 100+ requests/second
- **Database**: Optimized for time-series queries with TimescaleDB
- **Storage**: Efficient compression with TimescaleDB

### Monitoring

- Use `/api/latency/stats` endpoint for latency metrics
- Monitor Grafana dashboards for real-time performance
- Check Docker stats: `docker stats`

## 🔒 Security Considerations

### Current State

- Default passwords in docker-compose.yml (change for production)
- No authentication on API endpoints
- No encryption for database connections (local development)

### Production Recommendations

1. **Change Default Passwords**: Update all default credentials
2. **Use Environment Variables**: Store secrets in `.env` (not committed)
3. **Add Authentication**: Implement JWT or API key authentication
4. **Enable SSL/TLS**: Use HTTPS for API and database connections
5. **Network Security**: Use Docker networks and firewall rules
6. **Secrets Management**: Use Docker secrets or external secret managers

## 🚀 Deployment

### Docker Compose Deployment

```bash
# Production deployment
docker compose -f docker-compose.yml up -d

# With custom environment file
docker compose --env-file .env.production up -d
```

### Production Checklist

- [ ] Change all default passwords
- [ ] Configure environment variables
- [ ] Set up SSL/TLS certificates
- [ ] Configure firewall rules
- [ ] Set up monitoring and alerts
- [ ] Configure backup strategy
- [ ] Set up log aggregation
- [ ] Review security settings

## 📚 Documentation

- **API Documentation**: http://localhost:8001/docs (Swagger UI)
- **ReDoc**: http://localhost:8001/redoc
- **Architecture**: [docs/architecture.md](../docs/architecture.md)
- **Development Guide**: [docs/development.md](../docs/development.md)
- **Improvement Tasks**: [TASKS.md](../TASKS.md)

## 🔮 Future Enhancements

See [TASKS.md](../TASKS.md) for a prioritized list of planned improvements.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Run tests: `make test`
6. Run linting: `make lint`
7. Format code: `make format`
8. Submit a pull request

## 📄 License

This project is part of a diploma work and is intended for educational purposes.

## 👤 Author

Created as part of a Real-Time Data Collection and Monitoring System project.

## 🙏 Acknowledgments

- FastAPI for the excellent web framework
- TimescaleDB for time-series database optimization
- Grafana for powerful visualization capabilities
- Docker for containerization

---

**Version**: 1.0.0
**Last Updated**: 2026-03

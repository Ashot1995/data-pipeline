# Development Guide

## Prerequisites

- Docker 20.10+
- Docker Compose v2

No Python, Node, or other tools are needed on the host.
Everything — tests, linting, formatting — runs inside containers.

## First-Time Setup

```bash
cd src/
cp .env.example .env

# Generate a JWT signing key and paste it into .env as JWT_SECRET_KEY:
openssl rand -hex 32

docker compose up --build -d
```

Verify the stack is healthy:

```bash
make health
# or: curl http://localhost:8001/health
```

## Start / Stop

```bash
make up        # start all services (detached)
make down      # stop and remove containers (volumes are preserved)
make rebuild   # stop, rebuild all images from scratch, start
make restart   # restart all running containers
```

## Running Tests

Tests run in an isolated container (`--profile test`) against the live stack:

```bash
# All tests
make test

# Specific subsets
make test-unit          # non-integration tests only
make test-integration   # integration tests only
make test-api           # API tests only (test_backend_api.py)
make test-docker        # Docker Compose config tests

# A specific file, with verbose output
docker compose --profile test run --rm test \
  python -m pytest tests/test_backend_api.py -v

# With coverage report
docker compose --profile test run --rm test \
  python -m pytest tests/ --cov=backend --cov-report=term-missing
```

The `test` service connects to `sensor_network`, so integration tests reach
the live database and backend — the stack must be running before executing tests.

## Linting and Formatting

```bash
make lint          # flake8 — report issues without modifying files
make format        # black — reformat all source files in container
make format-check  # black --check — verify formatting without modifying
make quality       # runs format-check then lint
```

## Logs and Debugging

```bash
make logs               # tail logs from all services
make logs-backend       # backend only
make logs-db            # database only
make logs-grafana       # grafana only
make logs-generator     # data generator only

# Direct docker commands
docker compose logs -f backend --tail=100
docker compose ps                          # check service status
docker stats                               # container resource usage
```

## Database Access

```bash
make db-shell

# Inside psql:
# \dt                     — list tables
# \d sensor_data          — describe the sensor table
# SELECT count(*) FROM sensor_data;
# SELECT * FROM sensor_data ORDER BY stored_timestamp DESC LIMIT 5;
```

## Environment Variables

All settings live in `src/.env`. See `src/.env.example` for the full list with comments.

Key settings for development:

| Variable              | Purpose                                     |
|-----------------------|---------------------------------------------|
| `JWT_SECRET_KEY`      | Required signing key for JWT tokens         |
| `LOG_LEVEL`           | `DEBUG` for verbose output, default `INFO`  |
| `ENABLE_AUTH`         | Set to `true` to require Bearer tokens      |
| `ENABLE_RATE_LIMITING`| Set to `true` to activate rate limiting     |
| `INTERVAL_SECONDS`    | Data generator frequency in seconds         |
| `ANOMALY_THRESHOLD`   | Z-score threshold for anomaly detection     |

## Optional Services

MQTT and Kafka are disabled by default. Start them with Docker Compose profiles:

```bash
# MQTT broker (Mosquitto)
docker compose --profile mqtt up -d

# Kafka
docker compose --profile kafka up -d

# Enable the backend integration via .env:
MQTT_ENABLED=true
KAFKA_ENABLED=true
```

## Adding a New API Endpoint

1. Add the route handler to `src/backend/main.py`.
2. Add a Pydantic model to `main.py` if the endpoint needs input/output validation.
3. Add a test in `src/tests/test_backend_api.py`.
4. Run `make test` — all tests must pass.
5. Run `make quality` — linting and formatting must pass.

## Makefile Reference

| Target           | Description                                           |
|------------------|-------------------------------------------------------|
| `setup`          | Create `.env` from `.env.example`                     |
| `up`             | Start all services (detached)                         |
| `down`           | Stop and remove containers                            |
| `rebuild`        | Full image rebuild + restart                          |
| `restart`        | Restart all running containers                        |
| `status`         | Show container status                                 |
| `test`           | Run all tests in container                            |
| `test-unit`      | Run non-integration tests                             |
| `test-integration` | Run integration tests                               |
| `test-api`       | Run API tests only                                    |
| `test-docker`    | Run Docker Compose config tests                       |
| `lint`           | Run flake8 in container                               |
| `format`         | Run black in container                                |
| `format-check`   | Run black --check without modifying files             |
| `quality`        | format-check + lint                                   |
| `logs`           | Tail all logs                                         |
| `logs-backend`   | Tail backend logs                                     |
| `logs-db`        | Tail database logs                                    |
| `logs-grafana`   | Tail Grafana logs                                     |
| `logs-generator` | Tail data generator logs                              |
| `health`         | Print service status + backend health response        |
| `db-shell`       | Open psql inside the db container                     |
| `clean`          | Remove `__pycache__`, `.pytest_cache` locally         |
| `clean-docker`   | `docker compose down -v` + system prune               |

## Verification After Changes

```bash
# From src/
docker compose up --build -d          # rebuild and start
make health                           # confirm all services are up
make test                             # run full test suite in container
make quality                          # lint + format check
```

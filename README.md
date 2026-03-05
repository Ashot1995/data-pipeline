# Environmental Sensor Monitor

Real-time IoT data pipeline: collects temperature, humidity, and gas readings
from a Python simulator or Arduino hardware, stores them in PostgreSQL with
TimescaleDB, and visualizes them in Grafana.

**For:** students and engineers building or learning containerized IoT monitoring stacks.

---

## Quickstart

Docker and Docker Compose v2 are the only host requirements.
All commands run from the `src/` directory.

```bash
cd src/
cp .env.example .env

# Required — generate a signing key and paste it into .env as JWT_SECRET_KEY:
#   openssl rand -hex 32

docker compose up --build -d
```

| Service        | URL                          | Credentials         |
|----------------|------------------------------|---------------------|
| API            | http://localhost:8001        | —                   |
| API docs       | http://localhost:8001/docs   | —                   |
| Grafana        | http://localhost:3000        | admin / admin       |
| PostgreSQL     | localhost:5433               | postgres / postgres |

## Core Commands

Run from `src/`:

```bash
make setup     # create .env from template
make up        # start all services (detached)
make down      # stop all services
make test      # run all tests inside container
make lint      # run flake8 inside container
make format    # run black inside container
make health    # print service status + backend health check
make logs      # tail all service logs
make db-shell  # open psql inside the db container
make rebuild   # full image rebuild + restart
```

## Configuration

Copy `src/.env.example` to `src/.env` and edit as needed.

| Variable            | Default | Notes                                   |
|---------------------|---------|-----------------------------------------|
| `JWT_SECRET_KEY`    | —       | **Required.** `openssl rand -hex 32`    |
| `BACKEND_PORT`      | 8001    | Host port for the API                   |
| `GRAFANA_PORT`      | 3000    | Host port for Grafana                   |
| `DB_EXTERNAL_PORT`  | 5433    | Host port for direct DB access          |
| `INTERVAL_SECONDS`  | 5       | Sensor data generation interval (s)     |
| `ENABLE_AUTH`       | false   | Require Bearer token on API endpoints   |
| `ENABLE_RATE_LIMITING` | false | Activate token-bucket rate limiter   |

Optional profiles (disabled by default):

```bash
docker compose --profile mqtt  up -d   # add Mosquitto MQTT broker
docker compose --profile kafka up -d   # add Apache Kafka
```

## Documentation

| Document | Audience |
|----------|----------|
| [docs/architecture.md](docs/architecture.md) | Developers — tech stack, service topology, data flow, API–DB field mapping |
| [docs/development.md](docs/development.md) | Developers — full development workflow, adding endpoints, troubleshooting |
| [docs/TEST_STRATEGY.md](docs/TEST_STRATEGY.md) | QA — test matrix, valid payloads, field boundaries, regression checklist |
| [docs/project-status.md](docs/project-status.md) | Managers — feature status, open bugs, spec compliance matrix |
| [TASKS.md](TASKS.md) | All — prioritized improvement backlog |
| [src/README.md](src/README.md) | All — API reference, request/response shapes, environment variables |
| [docs/cloud/AWS_DEPLOYMENT.md](docs/cloud/AWS_DEPLOYMENT.md) | Ops — AWS deployment guide |

## License

Educational / diploma project.

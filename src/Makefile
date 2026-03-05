.PHONY: help setup up down build test lint format clean logs health db-shell

help: ## Show this help message
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-15s %s\n", $$1, $$2}'

setup: ## Initial setup - create .env file from .env.example
	@if [ ! -f .env ]; then \
		cp .env.example .env; \
		echo "Created .env file from .env.example"; \
		echo "Please edit .env with your configuration"; \
	else \
		echo ".env file already exists"; \
	fi

up: ## Start all services
	docker compose up -d

down: ## Stop all services
	docker compose down

build: ## Build all Docker images
	docker compose build

logs: ## View logs from all services
	docker compose logs -f

logs-backend: ## View backend logs
	docker compose logs -f backend

logs-db: ## View database logs
	docker compose logs -f db

logs-grafana: ## View Grafana logs
	docker compose logs -f grafana

logs-generator: ## View data generator logs
	docker compose logs -f data_generator

test: ## Run tests inside container (stack must be running)
	docker compose --profile test run --rm test

test-unit: ## Run unit tests inside container
	docker compose --profile test run --rm test \
		python -m pytest . -v --tb=short -m "not integration"

test-integration: ## Run integration tests inside container
	docker compose --profile test run --rm test \
		python -m pytest . -v --tb=short -m integration

test-api: ## Run API tests inside container
	docker compose --profile test run --rm test \
		python -m pytest test_backend_api.py -v --tb=short

test-docker: ## Run Docker Compose tests inside container
	docker compose --profile test run --rm test \
		python -m pytest test_docker_compose.py -v

lint: ## Run linting inside container (flake8)
	docker compose --profile test run --rm \
		-v $(PWD)/backend:/lint/backend \
		test \
		python -m flake8 /lint/backend/ /tests/ --max-line-length=120 || true

format: ## Format code inside container (black)
	docker compose --profile test run --rm \
		-v $(PWD)/backend:/lint/backend \
		test \
		python -m black /lint/backend/ /tests/ --line-length=100

format-check: ## Check formatting inside container without modifying files
	docker compose --profile test run --rm \
		-v $(PWD)/backend:/lint/backend \
		test \
		python -m black /lint/backend/ /tests/ --line-length=100 --check

quality: format-check lint ## Run all code quality checks in container
	@echo "Code quality checks complete"

clean: ## Clean up generated files and caches
	find . -type d -name __pycache__ -exec rm -r {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -r {} + 2>/dev/null || true
	find . -type d -name ".coverage" -exec rm -r {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -r {} + 2>/dev/null || true

clean-docker: ## Clean up Docker containers and volumes
	docker compose down -v
	docker system prune -f

health: ## Check health of all services
	@echo "Checking service health..."
	@docker compose ps
	@echo ""
	@echo "Backend health:"
	@curl -s http://localhost:8001/health | python3 -m json.tool || echo "Backend not responding"

db-shell: ## Open PostgreSQL shell
	docker exec -it sensor_db psql -U postgres -d sensor_db

rebuild: ## Rebuild and restart all services
	docker compose down
	docker compose build --no-cache
	docker compose up -d

restart: ## Restart all services
	docker compose restart

status: ## Show status of all services
	docker compose ps

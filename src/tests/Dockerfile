FROM python:3.11-slim
WORKDIR /tests
COPY tests/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy backend code so tests can import it via conftest.py sys.path manipulation
COPY backend/ /backend/
# Copy docker-compose.yml to the path expected by test_docker_compose.py
COPY docker-compose.yml /docker-compose.yml
COPY tests/ .
CMD ["pytest", "--tb=short", "-v"]

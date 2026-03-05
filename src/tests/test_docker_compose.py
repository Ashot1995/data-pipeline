"""
Docker Compose Configuration Tests - TEST-INFRA-4

Tests for Docker Compose configuration, service definitions, and dependencies.
"""

import pytest
import yaml
from pathlib import Path

pytestmark = pytest.mark.docker


@pytest.fixture
def docker_compose_file():
    """Path to docker-compose.yml file."""
    compose_path = Path(__file__).parent.parent / "docker-compose.yml"
    if not compose_path.exists():
        pytest.skip("docker-compose.yml not found")
    return compose_path


@pytest.fixture
def docker_compose_config(docker_compose_file):
    """Load docker-compose.yml configuration."""
    with open(docker_compose_file, "r") as f:
        return yaml.safe_load(f)


@pytest.mark.integration
class TestDockerComposeConfig:
    """Tests for Docker Compose configuration."""

    def test_docker_compose_exists(self, docker_compose_file):
        """Test that docker-compose.yml exists."""
        assert docker_compose_file.exists()

    def test_docker_compose_valid_yaml(self, docker_compose_file):
        """Test that docker-compose.yml is valid YAML."""
        with open(docker_compose_file, "r") as f:
            config = yaml.safe_load(f)
        assert config is not None
        assert isinstance(config, dict)

    def test_all_services_defined(self, docker_compose_config):
        """Test that all required services are defined."""
        services = docker_compose_config.get("services", {})

        required_services = ["db", "backend", "grafana", "data_generator"]
        for service in required_services:
            assert service in services, f"Service {service} not found in docker-compose.yml"

    def test_service_dependencies(self, docker_compose_config):
        """Test that service dependencies are configured correctly."""
        services = docker_compose_config.get("services", {})

        # Backend should depend on db
        if "backend" in services:
            backend_deps = services["backend"].get("depends_on", {})
            assert "db" in backend_deps or "db" in str(backend_deps)

        # Grafana should depend on db and backend
        if "grafana" in services:
            grafana_deps = services["grafana"].get("depends_on", [])
            if isinstance(grafana_deps, list):
                assert "db" in grafana_deps or "backend" in grafana_deps
            else:
                assert "db" in grafana_deps or "backend" in grafana_deps

        # Data generator should depend on backend
        if "data_generator" in services:
            generator_deps = services["data_generator"].get("depends_on", {})
            assert "backend" in generator_deps or "backend" in str(generator_deps)

    def test_networks_configured(self, docker_compose_config):
        """Test that networks are configured."""
        networks = docker_compose_config.get("networks", {})
        assert "sensor_network" in networks or len(networks) > 0

    def test_volumes_configured(self, docker_compose_config):
        """Test that volumes are configured."""
        volumes = docker_compose_config.get("volumes", {})
        # Should have at least postgres_data and grafana_data
        assert len(volumes) >= 2

    def test_port_mappings(self, docker_compose_config):
        """Test that port mappings are configured."""
        services = docker_compose_config.get("services", {})

        # Backend should map port
        if "backend" in services:
            ports = services["backend"].get("ports", [])
            assert len(ports) > 0

        # Grafana should map port
        if "grafana" in services:
            ports = services["grafana"].get("ports", [])
            assert len(ports) > 0

        # Database should map port
        if "db" in services:
            ports = services["db"].get("ports", [])
            assert len(ports) > 0

    def test_health_checks_configured(self, docker_compose_config):
        """Test that health checks are configured."""
        services = docker_compose_config.get("services", {})

        # Backend should have health check
        if "backend" in services:
            healthcheck = services["backend"].get("healthcheck")
            assert healthcheck is not None

        # Database should have health check
        if "db" in services:
            healthcheck = services["db"].get("healthcheck")
            assert healthcheck is not None

    def test_restart_policies(self, docker_compose_config):
        """Test that restart policies are configured."""
        services = docker_compose_config.get("services", {})

        for service_name, service_config in services.items():
            restart = service_config.get("restart")
            # Should have restart policy (unless-stopped or similar)
            assert restart is not None, f"Service {service_name} missing restart policy"

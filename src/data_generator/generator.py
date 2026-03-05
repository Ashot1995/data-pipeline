"""
Data Generator - Simulates sensor data and sends it to the backend API and/or MQTT broker.

Generates realistic temperature, humidity, and gas concentration values
and sends them via HTTP POST and optionally via MQTT publish.
"""

import json
import logging
import os
import random
import time
from datetime import datetime
from typing import Dict, Optional

import requests

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# HTTP configuration
BACKEND_URL = os.getenv("BACKEND_URL", "http://backend:8000/api/data")
DEVICE_ID = os.getenv("DEVICE_ID", "sim-01")
INTERVAL_SECONDS = int(os.getenv("INTERVAL_SECONDS", "5"))
BASE_TEMPERATURE = float(os.getenv("BASE_TEMPERATURE", "23.0"))
BASE_HUMIDITY = float(os.getenv("BASE_HUMIDITY", "45.0"))
BASE_GAS = float(os.getenv("BASE_GAS", "150.0"))

# MQTT configuration
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "false").lower() == "true"
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "sensors/data")

# Global MQTT client
_mqtt_client = None


def _init_mqtt():
    """Initialize paho MQTT client; returns None if unavailable."""
    global _mqtt_client
    try:
        import paho.mqtt.client as mqtt

        client = mqtt.Client(client_id="sensor_generator")

        def on_connect(c, userdata, flags, rc):
            if rc == 0:
                logger.info("Generator connected to MQTT broker %s:%d", MQTT_BROKER, MQTT_PORT)
            else:
                logger.warning("Generator MQTT connect failed rc=%d", rc)

        client.on_connect = on_connect
        client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
        client.loop_start()
        _mqtt_client = client
        return client
    except Exception as exc:
        logger.warning("MQTT init failed (non-fatal): %s", exc)
        return None


def generate_sensor_data() -> Dict[str, float]:
    """Generate realistic sensor data values."""
    temperature = BASE_TEMPERATURE + random.uniform(-2.0, 2.0)
    humidity = BASE_HUMIDITY + random.uniform(-5.0, 5.0)
    gas = BASE_GAS + random.uniform(-20.0, 20.0)

    temperature = max(-50, min(100, temperature))
    humidity = max(0, min(100, humidity))
    gas = max(0, min(1000, gas))

    return {
        "temperature": round(temperature, 1),
        "humidity": round(humidity, 1),
        "gas_level": round(gas, 1),
    }


def send_data_http(data: Dict[str, float], sent_timestamp: str,
                   max_retries: int = 3, backoff_factor: float = 1.5) -> Optional[Dict]:
    """Send sensor data to backend via HTTP POST with retry logic."""
    payload = {
        "device_id": DEVICE_ID,
        "timestamp": sent_timestamp,
        "sent_timestamp": sent_timestamp,
        **data,
    }

    for attempt in range(max_retries + 1):
        try:
            response = requests.post(
                BACKEND_URL,
                json=payload,
                timeout=10,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            result = response.json()
            latency_ms = result.get("timestamps", {}).get("latency_ms")
            logger.info(
                "✓ HTTP: temp=%.1f°C humidity=%.1f%% gas=%.1fppm%s",
                data["temperature"], data["humidity"], data["gas_level"],
                f" latency={latency_ms:.2f}ms" if latency_ms else "",
            )
            return result
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            if attempt < max_retries:
                wait = backoff_factor ** attempt
                logger.warning("✗ HTTP attempt %d/%d: %s. Retrying in %.1fs...",
                               attempt + 1, max_retries + 1, exc, wait)
                time.sleep(wait)
            else:
                logger.error("✗ HTTP failed after %d attempts: %s", max_retries + 1, exc)
                return None
        except requests.exceptions.RequestException as exc:
            logger.error("✗ HTTP request failed (no retry): %s", exc)
            return None

    return None


def send_data_mqtt(data: Dict[str, float], sent_timestamp: str) -> bool:
    """Publish sensor data to MQTT broker."""
    global _mqtt_client
    if _mqtt_client is None:
        return False
    try:
        mqtt_payload = {
            "device_id": DEVICE_ID,
            "timestamp": sent_timestamp,
            "sent_timestamp": sent_timestamp,
            **data,
        }
        payload = json.dumps(mqtt_payload)
        result = _mqtt_client.publish(MQTT_TOPIC, payload, qos=1)
        if result.rc == 0:
            logger.info(
                "✓ MQTT: temp=%.1f°C humidity=%.1f%% gas=%.1fppm → %s",
                data["temperature"], data["humidity"], data["gas_level"], MQTT_TOPIC,
            )
            return True
        logger.warning("✗ MQTT publish failed rc=%d", result.rc)
        return False
    except Exception as exc:
        logger.error("✗ MQTT publish error: %s", exc)
        return False


def wait_for_backend(url: str, timeout: int = 30) -> bool:
    """Wait for backend to be ready."""
    health_url = url.replace("/api/data", "/health")
    start = time.time()
    logger.info("Waiting for backend at %s...", health_url)
    while time.time() - start < timeout:
        try:
            if requests.get(health_url, timeout=2).status_code == 200:
                logger.info("✓ Backend ready")
                return True
        except Exception:
            pass
        time.sleep(1)
    logger.warning("Backend not ready after %ds, continuing anyway...", timeout)
    return False


def main() -> None:
    """Main function to run data generator."""
    logger.info("=== Data Generator Starting ===")
    logger.info("Backend URL: %s | Interval: %ds", BACKEND_URL, INTERVAL_SECONDS)
    logger.info("Device ID: %s | Base values: temp=%.1f°C humidity=%.1f%% gas=%.1fppm",
                DEVICE_ID, BASE_TEMPERATURE, BASE_HUMIDITY, BASE_GAS)
    logger.info("MQTT enabled: %s", MQTT_ENABLED)

    wait_for_backend(BACKEND_URL)

    if MQTT_ENABLED:
        _init_mqtt()
        time.sleep(2)  # Allow MQTT connection to establish

    logger.info("Starting data generation loop...")
    try:
        while True:
            data = generate_sensor_data()
            sent_timestamp = datetime.now().isoformat()

            # Always send via HTTP
            send_data_http(data, sent_timestamp)

            # Optionally also publish via MQTT
            if MQTT_ENABLED:
                send_data_mqtt(data, sent_timestamp)

            time.sleep(INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Data generator stopped by user")
    except Exception as exc:
        logger.error("Unexpected error: %s", exc, exc_info=True)
        raise
    finally:
        if _mqtt_client:
            _mqtt_client.loop_stop()
            _mqtt_client.disconnect()


if __name__ == "__main__":
    main()

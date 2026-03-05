"""
MQTT client for the Real-Time Data Collection and Monitoring System.

Subscribes to MQTT topics and processes sensor data messages.
"""

import os
import json
import logging
import asyncio
from typing import Optional, Callable, Any
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

# MQTT Configuration
MQTT_BROKER = os.getenv("MQTT_BROKER", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("MQTT_TOPIC", "sensors/data")
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", "sensor_backend")
MQTT_USERNAME = os.getenv("MQTT_USERNAME", None)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", None)


class MQTTClient:
    """MQTT client for subscribing to sensor data."""

    def __init__(self, message_callback: Optional[Callable[[dict], None]] = None):
        """
        Initialize MQTT client.

        Args:
            message_callback: Callback function to process received messages
        """
        self.client = mqtt.Client(client_id=MQTT_CLIENT_ID)
        self.message_callback = message_callback
        self.connected = False

        # Set callbacks
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.on_subscribe = self._on_subscribe

        # Set credentials if provided
        if MQTT_USERNAME and MQTT_PASSWORD:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    def _on_connect(self, client, userdata, flags, rc):
        """Handle connection callback."""
        if rc == 0:
            self.connected = True
            logger.info(f"Connected to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
            # Subscribe to topic
            client.subscribe(MQTT_TOPIC, qos=1)
            logger.info(f"Subscribed to topic: {MQTT_TOPIC}")
        else:
            logger.error(f"Failed to connect to MQTT broker. Return code: {rc}")

    def _on_disconnect(self, client, userdata, rc):
        """Handle disconnection callback."""
        self.connected = False
        if rc != 0:
            logger.warning(f"Unexpected MQTT disconnection. Return code: {rc}")
        else:
            logger.info("Disconnected from MQTT broker")

    def _on_message(self, client, userdata, msg):
        """Handle message callback."""
        try:
            payload = json.loads(msg.payload.decode())
            logger.debug(f"Received MQTT message on topic {msg.topic}: {payload}")

            if self.message_callback:
                self.message_callback(payload)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to decode MQTT message: {e}")
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}", exc_info=True)

    def _on_subscribe(self, client, userdata, mid, granted_qos):
        """Handle subscription callback."""
        logger.info(f"Subscribed to topic with QoS: {granted_qos}")

    def connect(self):
        """Connect to MQTT broker."""
        try:
            self.client.connect(MQTT_BROKER, MQTT_PORT, keepalive=60)
            logger.info(f"Connecting to MQTT broker at {MQTT_BROKER}:{MQTT_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")

    def start(self):
        """Start MQTT client loop."""
        self.client.loop_start()
        logger.info("MQTT client loop started")

    def stop(self):
        """Stop MQTT client loop."""
        self.client.loop_stop()
        self.client.disconnect()
        logger.info("MQTT client stopped")

    def publish(self, topic: str, payload: dict, qos: int = 1):
        """
        Publish message to MQTT topic.

        Args:
            topic: MQTT topic
            payload: Message payload (dict)
            qos: Quality of Service level
        """
        try:
            message = json.dumps(payload)
            result = self.client.publish(topic, message, qos=qos)
            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"Published message to topic {topic}")
            else:
                logger.error(f"Failed to publish message. Return code: {result.rc}")
        except Exception as e:
            logger.error(f"Error publishing MQTT message: {e}", exc_info=True)


# Global MQTT client instance
_mqtt_client: Optional[MQTTClient] = None


def get_mqtt_client() -> Optional[MQTTClient]:
    """Get global MQTT client instance."""
    return _mqtt_client


def initialize_mqtt(message_callback: Optional[Callable[[dict], None]] = None) -> MQTTClient:
    """
    Initialize and start MQTT client.

    Args:
        message_callback: Callback function to process messages

    Returns:
        MQTT client instance
    """
    global _mqtt_client
    _mqtt_client = MQTTClient(message_callback=message_callback)
    _mqtt_client.connect()
    _mqtt_client.start()
    return _mqtt_client


def stop_mqtt():
    """Stop MQTT client."""
    global _mqtt_client
    if _mqtt_client:
        _mqtt_client.stop()
        _mqtt_client = None

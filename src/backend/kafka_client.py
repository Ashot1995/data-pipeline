"""
Kafka client for the Real-Time Data Collection and Monitoring System.

Produces and consumes sensor data messages from Kafka topics.
"""

import os
import json
import logging
from typing import Optional, Callable, Any
from confluent_kafka import Producer, Consumer, KafkaError

logger = logging.getLogger(__name__)

# Kafka Configuration
KAFKA_BROKER = os.getenv("KAFKA_BROKER", "kafka:9092")
KAFKA_TOPIC = os.getenv("KAFKA_TOPIC", "sensor-data")
KAFKA_GROUP_ID = os.getenv("KAFKA_GROUP_ID", "sensor-backend-group")


class KafkaProducer:
    """Kafka producer for publishing sensor data."""

    def __init__(self):
        """Initialize Kafka producer."""
        self.producer = Producer({
            'bootstrap.servers': KAFKA_BROKER,
            'acks': 'all',
            'retries': 3,
            'max.in.flight.requests.per.connection': 1,
        })

    def produce(self, topic: str, key: Optional[str], value: dict):
        """
        Produce message to Kafka topic.

        Args:
            topic: Kafka topic name
            key: Message key (optional)
            value: Message value (dict)
        """
        try:
            message = json.dumps(value).encode('utf-8')
            self.producer.produce(
                topic,
                key=key.encode('utf-8') if key else None,
                value=message,
                callback=self._delivery_callback
            )
            self.producer.poll(0)
            logger.debug(f"Produced message to topic {topic}")
        except Exception as e:
            logger.error(f"Error producing Kafka message: {e}", exc_info=True)

    def flush(self, timeout: float = 10.0):
        """
        Flush pending messages.

        Args:
            timeout: Flush timeout in seconds
        """
        self.producer.flush(timeout)

    @staticmethod
    def _delivery_callback(err, msg):
        """Handle delivery callback."""
        if err:
            logger.error(f"Message delivery failed: {err}")
        else:
            logger.debug(f"Message delivered to {msg.topic()} [{msg.partition()}]")


class KafkaConsumer:
    """Kafka consumer for consuming sensor data."""

    def __init__(self, message_callback: Optional[Callable[[dict], None]] = None):
        """
        Initialize Kafka consumer.

        Args:
            message_callback: Callback function to process messages
        """
        self.consumer = Consumer({
            'bootstrap.servers': KAFKA_BROKER,
            'group.id': KAFKA_GROUP_ID,
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
        })
        self.message_callback = message_callback
        self.running = False

    def subscribe(self, topics: list):
        """
        Subscribe to Kafka topics.

        Args:
            topics: List of topic names
        """
        self.consumer.subscribe(topics)
        logger.info(f"Subscribed to topics: {topics}")

    def start(self):
        """Start consuming messages."""
        self.running = True
        logger.info("Kafka consumer started")

        try:
            while self.running:
                msg = self.consumer.poll(timeout=1.0)

                if msg is None:
                    continue

                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        logger.debug(f"Reached end of partition {msg.partition()}")
                    else:
                        logger.error(f"Consumer error: {msg.error()}")
                    continue

                try:
                    value = json.loads(msg.value().decode('utf-8'))
                    logger.debug(f"Consumed message from topic {msg.topic()}: {value}")

                    if self.message_callback:
                        self.message_callback(value)

                except json.JSONDecodeError as e:
                    logger.error(f"Failed to decode Kafka message: {e}")
                except Exception as e:
                    logger.error(f"Error processing Kafka message: {e}", exc_info=True)

        except KeyboardInterrupt:
            logger.info("Kafka consumer interrupted")
        finally:
            self.stop()

    def stop(self):
        """Stop consuming messages."""
        self.running = False
        self.consumer.close()
        logger.info("Kafka consumer stopped")


# Global instances
_kafka_producer: Optional[KafkaProducer] = None
_kafka_consumer: Optional[KafkaConsumer] = None


def get_kafka_producer() -> Optional[KafkaProducer]:
    """Get global Kafka producer instance."""
    return _kafka_producer


def initialize_kafka_producer() -> KafkaProducer:
    """Initialize and return Kafka producer."""
    global _kafka_producer
    _kafka_producer = KafkaProducer()
    logger.info("Kafka producer initialized")
    return _kafka_producer


def initialize_kafka_consumer(
    topics: list, message_callback: Optional[Callable[[dict], None]] = None
) -> KafkaConsumer:
    """
    Initialize and start Kafka consumer.

    Args:
        topics: List of topics to subscribe to
        message_callback: Callback function to process messages

    Returns:
        Kafka consumer instance
    """
    global _kafka_consumer
    _kafka_consumer = KafkaConsumer(message_callback=message_callback)
    _kafka_consumer.subscribe(topics)
    return _kafka_consumer


def stop_kafka():
    """Stop Kafka consumer."""
    global _kafka_consumer
    if _kafka_consumer:
        _kafka_consumer.stop()
        _kafka_consumer = None

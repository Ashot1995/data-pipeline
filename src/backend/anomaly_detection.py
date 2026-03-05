"""
Anomaly detection module for the Real-Time Data Collection and Monitoring System.

Detects anomalies in sensor data using statistical methods and machine learning.
"""

import os
import logging
import numpy as np
from typing import Any, Dict, List, Optional, Tuple
from collections import deque
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Anomaly detector for sensor data."""

    def __init__(
        self,
        window_size: int = 100,
        threshold_multiplier: float = 3.0,
        min_samples: int = 10,
    ):
        """
        Initialize anomaly detector.

        Args:
            window_size: Size of sliding window for statistics
            threshold_multiplier: Multiplier for standard deviation threshold
            min_samples: Minimum samples required before detection
        """
        self.window_size = window_size
        self.threshold_multiplier = threshold_multiplier
        self.min_samples = min_samples

        # Sliding windows for each sensor
        self.temperature_window: deque = deque(maxlen=window_size)
        self.humidity_window: deque = deque(maxlen=window_size)
        self.gas_window: deque = deque(maxlen=window_size)

    def add_sample(self, temperature: float, humidity: float, gas: float):
        """
        Add a sample to the detector.

        Args:
            temperature: Temperature reading
            humidity: Humidity reading
            gas: Gas concentration reading
        """
        self.temperature_window.append(temperature)
        self.humidity_window.append(humidity)
        self.gas_window.append(gas)

    def detect_anomalies(
        self, temperature: float, humidity: float, gas: float
    ) -> Dict[str, bool]:
        """
        Detect anomalies in sensor readings.

        Args:
            temperature: Temperature reading
            humidity: Humidity reading
            gas: Gas concentration reading

        Returns:
            Dictionary with anomaly flags for each sensor
        """
        anomalies = {
            "temperature": False,
            "humidity": False,
            "gas": False,
        }

        # Check if we have enough samples
        if len(self.temperature_window) < self.min_samples:
            return anomalies

        # Detect temperature anomaly
        if len(self.temperature_window) >= self.min_samples:
            temp_mean = np.mean(self.temperature_window)
            temp_std = np.std(self.temperature_window)
            if temp_std > 0:
                z_score = abs(temperature - temp_mean) / temp_std
                anomalies["temperature"] = z_score > self.threshold_multiplier

        # Detect humidity anomaly
        if len(self.humidity_window) >= self.min_samples:
            hum_mean = np.mean(self.humidity_window)
            hum_std = np.std(self.humidity_window)
            if hum_std > 0:
                z_score = abs(humidity - hum_mean) / hum_std
                anomalies["humidity"] = z_score > self.threshold_multiplier

        # Detect gas anomaly
        if len(self.gas_window) >= self.min_samples:
            gas_mean = np.mean(self.gas_window)
            gas_std = np.std(self.gas_window)
            if gas_std > 0:
                z_score = abs(gas - gas_mean) / gas_std
                anomalies["gas"] = z_score > self.threshold_multiplier

        return anomalies

    def detect_spike(
        self, current_value: float, sensor_type: str, spike_threshold: float = 0.5
    ) -> bool:
        """
        Detect sudden spikes in sensor values.

        Args:
            current_value: Current sensor reading
            sensor_type: Type of sensor ('temperature', 'humidity', 'gas')
            spike_threshold: Percentage change threshold for spike detection

        Returns:
            True if spike detected, False otherwise
        """
        window = {
            "temperature": self.temperature_window,
            "humidity": self.humidity_window,
            "gas": self.gas_window,
        }.get(sensor_type)

        if not window or len(window) < 2:
            return False

        # Get recent average
        recent_avg = np.mean(list(window)[-5:]) if len(window) >= 5 else np.mean(window)

        if recent_avg == 0:
            return False

        # Calculate percentage change
        change = abs(current_value - recent_avg) / abs(recent_avg)
        return change > spike_threshold

    def detect_drift(
        self, sensor_type: str, drift_threshold: float = 0.2
    ) -> Tuple[bool, float]:
        """
        Detect gradual drift in sensor values.

        Args:
            sensor_type: Type of sensor ('temperature', 'humidity', 'gas')
            drift_threshold: Percentage change threshold for drift detection

        Returns:
            Tuple of (is_drift, drift_percentage)
        """
        window = {
            "temperature": self.temperature_window,
            "humidity": self.humidity_window,
            "gas": self.gas_window,
        }.get(sensor_type)

        if not window or len(window) < 10:
            return False, 0.0

        # Split window into halves
        mid = len(window) // 2
        first_half = list(window)[:mid]
        second_half = list(window)[mid:]

        first_mean = np.mean(first_half)
        second_mean = np.mean(second_half)

        if first_mean == 0:
            return False, 0.0

        drift_percentage = abs(second_mean - first_mean) / abs(first_mean)
        is_drift = drift_percentage > drift_threshold

        return is_drift, drift_percentage

    def get_statistics(self) -> Dict[str, Dict[str, float]]:
        """
        Get current statistics for all sensors.

        Returns:
            Dictionary with statistics for each sensor
        """
        stats = {}

        for sensor_type, window in [
            ("temperature", self.temperature_window),
            ("humidity", self.humidity_window),
            ("gas", self.gas_window),
        ]:
            if len(window) > 0:
                stats[sensor_type] = {
                    "mean": float(np.mean(window)),
                    "std": float(np.std(window)),
                    "min": float(np.min(window)),
                    "max": float(np.max(window)),
                    "count": len(window),
                }
            else:
                stats[sensor_type] = {
                    "mean": 0.0,
                    "std": 0.0,
                    "min": 0.0,
                    "max": 0.0,
                    "count": 0,
                }

        return stats


# Global anomaly detector instance
_anomaly_detector: Optional[AnomalyDetector] = None


def get_anomaly_detector() -> AnomalyDetector:
    """Get global anomaly detector instance."""
    global _anomaly_detector
    if _anomaly_detector is None:
        _anomaly_detector = AnomalyDetector(
            window_size=int(os.getenv("ANOMALY_WINDOW_SIZE", "100")),
            threshold_multiplier=float(os.getenv("ANOMALY_THRESHOLD", "3.0")),
        )
    return _anomaly_detector


def detect_anomalies(
    temperature: float, humidity: float, gas: float
) -> Dict[str, Any]:
    """
    Detect anomalies in sensor data.

    Args:
        temperature: Temperature reading
        humidity: Humidity reading
        gas: Gas concentration reading

    Returns:
        Dictionary with anomaly detection results
    """
    detector = get_anomaly_detector()

    # Add sample
    detector.add_sample(temperature, humidity, gas)

    # Detect anomalies
    anomalies = detector.detect_anomalies(temperature, humidity, gas)

    # Detect spikes
    temp_spike = detector.detect_spike(temperature, "temperature")
    hum_spike = detector.detect_spike(humidity, "humidity")
    gas_spike = detector.detect_spike(gas, "gas")

    # Detect drift
    temp_drift, temp_drift_pct = detector.detect_drift("temperature")
    hum_drift, hum_drift_pct = detector.detect_drift("humidity")
    gas_drift, gas_drift_pct = detector.detect_drift("gas")

    # Get statistics
    stats = detector.get_statistics()

    return {
        "anomalies": anomalies,
        "spikes": {
            "temperature": temp_spike,
            "humidity": hum_spike,
            "gas": gas_spike,
        },
        "drift": {
            "temperature": {"detected": temp_drift, "percentage": temp_drift_pct},
            "humidity": {"detected": hum_drift, "percentage": hum_drift_pct},
            "gas": {"detected": gas_drift, "percentage": gas_drift_pct},
        },
        "statistics": stats,
        "timestamp": datetime.utcnow().isoformat(),
    }

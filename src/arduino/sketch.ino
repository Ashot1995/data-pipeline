/*
 * Arduino Sensor Data Collection Sketch
 *
 * Reads data from sensors (DHT11, MQ-2) and sends it to the FastAPI backend
 * via ESP8266 Wi-Fi module using ISO 8601 timestamps from NTP.
 *
 * Hardware Requirements:
 * - Arduino Uno
 * - ESP8266 Wi-Fi Module
 * - DHT11 Temperature & Humidity Sensor
 * - MQ-2 Gas/Smoke Sensor
 *
 * Libraries Required (install via Arduino Library Manager):
 * - ESP8266WiFi
 * - DHT sensor library (Adafruit)
 * - NTPClient (Fabrice Weinberg)
 */

#include <ESP8266WiFi.h>
#include <WiFiUDP.h>
#include <NTPClient.h>
#include <DHT.h>

// Wi-Fi Configuration
const char* ssid     = "YOUR_WIFI_SSID";
const char* password = "YOUR_WIFI_PASSWORD";

// Backend API Configuration
const char* backendHost = "YOUR_BACKEND_IP";
const int   backendPort = 8000;
const char* backendPath = "/api/data";

// Device identifier — unique per physical unit
const char* deviceId = "arduino-01";

// Sensor Pin Definitions
#define DHT_PIN  2   // DHT11 data pin
#define MQ2_PIN  A0  // MQ-2 analog pin

// DHT Sensor Configuration
#define DHT_TYPE DHT11
DHT dht(DHT_PIN, DHT_TYPE);

// NTP (UTC timestamps for sent_timestamp)
WiFiUDP ntpUDP;
NTPClient timeClient(ntpUDP, "pool.ntp.org", 0, 30000); // UTC, sync every 30 s

// Timing
const unsigned long interval = 5000; // Send data every 5 seconds
unsigned long previousMillis = 0;

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("=== Arduino Sensor Node Starting ===");

  // Initialize sensors
  dht.begin();
  pinMode(MQ2_PIN, INPUT);

  // Connect to Wi-Fi
  Serial.print("Connecting to Wi-Fi: ");
  Serial.println(ssid);
  WiFi.begin(ssid, password);

  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    attempts++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi connected!");
    Serial.print("IP Address: ");
    Serial.println(WiFi.localIP());

    // Sync time via NTP
    timeClient.begin();
    timeClient.update();
    Serial.print("NTP time: ");
    Serial.println(timeClient.getFormattedTime());
  } else {
    Serial.println("\nWi-Fi connection failed! Timestamps will be omitted.");
  }

  Serial.println("Setup complete. Starting data collection...");
}

// ---------------------------------------------------------------------------
// Loop
// ---------------------------------------------------------------------------
void loop() {
  unsigned long currentMillis = millis();

  if (currentMillis - previousMillis >= interval) {
    previousMillis = currentMillis;

    // Read sensor values
    float temperature = dht.readTemperature();
    float humidity    = dht.readHumidity();
    int   rawGas      = analogRead(MQ2_PIN);
    float gasLevel    = (float)map(rawGas, 0, 1023, 0, 1000); // Convert to PPM range

    // Validate DHT readings
    if (isnan(temperature) || isnan(humidity)) {
      Serial.println("Error reading DHT sensor!");
      return; // Skip this reading rather than sending bad data
    }

    // Print for debugging
    Serial.println("--- Sensor Readings ---");
    Serial.print("Temperature: "); Serial.print(temperature, 1); Serial.println(" °C");
    Serial.print("Humidity:    "); Serial.print(humidity, 1);    Serial.println(" %");
    Serial.print("Gas level:   "); Serial.print(gasLevel, 1);   Serial.println(" PPM");

    // Build ISO 8601 UTC timestamp from NTP
    char isoTimestamp[25] = "";
    if (WiFi.status() == WL_CONNECTED) {
      timeClient.update();
      time_t epochTime = (time_t)timeClient.getEpochTime();
      struct tm* timeinfo = gmtime(&epochTime);
      strftime(isoTimestamp, sizeof(isoTimestamp), "%Y-%m-%dT%H:%M:%SZ", timeinfo);
    }

    sendDataToBackend(temperature, humidity, gasLevel, isoTimestamp);
  }
}

// ---------------------------------------------------------------------------
// Reconnect to Wi-Fi if dropped
// ---------------------------------------------------------------------------
bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) return true;

  Serial.println("Wi-Fi disconnected. Reconnecting...");
  WiFi.disconnect();
  delay(100);
  WiFi.begin(ssid, password);

  for (int i = 0; i < 20 && WiFi.status() != WL_CONNECTED; i++) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\nWi-Fi reconnected!");
    return true;
  }
  Serial.println("\nWi-Fi reconnection failed. Skipping this reading.");
  return false;
}

// ---------------------------------------------------------------------------
// HTTP POST sensor data to backend
// ---------------------------------------------------------------------------
void sendDataToBackend(float temperature, float humidity, float gasLevel,
                       const char* isoTimestamp) {
  if (!ensureWiFi()) return;

  // Build JSON payload matching POST /api/data schema:
  // { device_id, temperature, humidity, gas_level, timestamp }
  String jsonPayload = "{";
  jsonPayload += "\"device_id\":\"" + String(deviceId) + "\",";
  jsonPayload += "\"temperature\":" + String(temperature, 1) + ",";
  jsonPayload += "\"humidity\":" + String(humidity, 1) + ",";
  jsonPayload += "\"gas_level\":" + String(gasLevel, 1);
  if (strlen(isoTimestamp) > 0) {
    jsonPayload += ",\"timestamp\":\"" + String(isoTimestamp) + "\"";
  }
  jsonPayload += "}";

  WiFiClient client;
  if (!client.connect(backendHost, backendPort)) {
    Serial.println("Connection to backend failed!");
    return;
  }

  Serial.println("Sending data to backend...");
  client.println(String("POST ") + backendPath + " HTTP/1.1");
  client.println(String("Host: ") + backendHost + ":" + backendPort);
  client.println("Content-Type: application/json");
  client.print("Content-Length: ");
  client.println(jsonPayload.length());
  client.println("Connection: close");
  client.println();
  client.print(jsonPayload);

  // Wait for response (5 s timeout)
  unsigned long timeout = millis();
  while (client.available() == 0) {
    if (millis() - timeout > 5000) {
      Serial.println("Request timeout!");
      client.stop();
      return;
    }
  }

  // Print HTTP status line
  if (client.available()) {
    String statusLine = client.readStringUntil('\n');
    Serial.print("Response: ");
    Serial.println(statusLine);
  }

  client.stop();
  Serial.println("Done.");
}

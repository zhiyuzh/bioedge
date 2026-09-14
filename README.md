# BioEdge: Raspberry Pi Edge Telemetry & Environmental Monitoring System

**BioEdge** is a real-time IoT edge telemetry and environmental sensing system engineered for Raspberry Pi. It integrates hardware sensors over the I2C bus with a lightweight Flask backend and a responsive, high-performance web dashboard featuring live canvas charts, differential sensor analysis, thermal protection heuristics, and multi-channel alerting (audio chimes, visual banners, and automated email alerts).

---

## System Architecture

```
                       +-----------------------------+
                       |      Raspberry Pi (SoC)     |
                       |   Broadcom CPU / vcgencmd   |
                       +--------------+--------------+
                                      |
                      I2C Bus 1 (/dev/i2c-1, SDA/SCL)
               +----------------------+----------------------+
               |                                             |
     +---------+---------+                         +---------+---------+
     |   Bosch BMP280    |                         |  Dual BH1750 /    |
     |   Temp & Pressure |                         |  GY-302 Sensors   |
     |   Address: 0x76   |                         |  0x23 (Sensor 1)  |
     +-------------------+                         |  0x5C (Sensor 2)  |
                                                   +-------------------+
                                      |
                       +--------------v--------------+
                       |    Flask Backend (app.py)   |
                       |  - REST Data Polling (/data)|
                       |  - Alert Dispatch API       |
                       |  - Audit Logger (disk log)  |
                       +--------------+--------------+
                                      |
               +----------------------+----------------------+
               |                                             |
  +------------v-------------+                 +-------------v------------+
  |    Web Dashboard UI      |                 |   Alerting Infrastructure|
  |  - Canvas Stream Visualizer|               |  - Web Audio Synthesizer |
  |  - Dual Light Delta Calc |                 |  - Visual Warning Banners|
  |  - Dark / Light / Cyber  |                 |  - SMTP / Local MTA Relay|
  +--------------------------+                 +--------------------------+
```

---

## Features

### 1. Hardware & Environmental Telemetry
- **Ambient Temperature & Barometric Pressure (Bosch BMP280)**: Reads calibrated temperature (°C / °F) and atmospheric pressure (hPa / mmHg) using Bosch's native 64-bit integer compensation formulas.
- **Dual Ambient Light Sensing (Rohm BH1750 / GY-302)**: Reads illuminance in Lux across two distinct I2C addresses (`0x23` and `0x5C`).
- **Differential Lux Delta Analysis**: Computes real-time Lux differences and rate-of-change between dual sensors to detect shadowing, directional occlusion, or sensor failures.
- **SoC Core Thermal Monitoring**: Queries the Raspberry Pi Broadcom SoC temperature in real time using `vcgencmd measure_temp`.

### 2. Intelligent Multi-Tier Alert System
- **Thermal Safety Guard**: Tracks CPU temperatures with configurable thresholds. If core temperatures exceed configured limits for 10 consecutive seconds, an alert triggers.
- **Illuminance Anomaly Detection**: Warns if differential lux shifts exceed the YAML-defined threshold.
- **Web Audio API Chime**: Generates in-browser synthesized acoustic alert tones (dual-frequency harmonic chime: 587.33 Hz D5 & 880 Hz A5) without external sound assets.
- **Automated Email Dispatch**:
  - Outgoing alert messages sent over SMTP relay (with TLS) or local mail transfer agent (MTA).
  - 60-second cooldown throttling to prevent inbox spamming during sustained anomalies.
  - Disk audit trail logged to `alert_emails.log`.

### 3. Interactive Web Dashboard (`templates/index.html`)
- **Real-Time Canvas Visualizer**: High-frequency telemetry stream with live moving-window averaging.
- **Metric Switching**: Seamlessly toggle visualization between Temperature, Barometric Pressure, and Dual Light curves.
- **Timeline Buffer & Scrubbing**: Drag-to-scrub timeline allowing inspection of historical buffer points with a "Jump to Live" action.
- **Configurable Polling**: Switchable refresh rates (1.0s, 2.0s, 5.0s) and instant pause/resume controls.
- **Theme Engine**: Includes three distinct UI themes:
  - **Cyber Dark**: High-contrast OLED dark interface.
  - **Clean Light**: Crisp daylight telemetry theme.
  - **Rainbow Cyber**: Animated RGB border flow theme.

---

## Hardware Pinout & Wiring

Connect the sensors to the Raspberry Pi standard 40-pin GPIO header:

| Sensor Pin | Function | Raspberry Pi Header Pin |
|---|---|---|
| **VCC** | 3.3V Power | Pin 1 (3V3 Power) |
| **GND** | Ground | Pin 6, 9, 14, 20, 25, 30, 34, or 39 (GND) |
| **SDA** | I2C Data | Pin 3 (GPIO 2 / I2C1_SDA) |
| **SCL** | I2C Clock | Pin 5 (GPIO 3 / I2C1_SCL) |

### Dual GY-302 Address Assignment
The BH1750 / GY-302 sensor uses the `ADDR` pin to select its I2C address:
- **Sensor 1 (`0x23`)**: Connect `ADDR` to **GND** (or leave floating).
- **Sensor 2 (`0x5C`)**: Connect `ADDR` to **3.3V (VCC)**.

---

## Prerequisites & Installation

### 1. Enable I2C on the Raspberry Pi
Ensure I2C is enabled in the Raspberry Pi OS configuration:
```bash
sudo raspi-config
# Navigate to: Interface Options -> I2C -> Enable -> Finish
```

Verify that the I2C bus detects your sensors:
```bash
sudo apt-get update && sudo apt-get install -y i2c-tools
i2cdetect -y 1
```
You should see addresses `0x23`, `0x5C`, and `0x76` active on the bus.

### 2. Clone the Repository & Install Dependencies
```bash
git clone git@github.com:zhiyuzh/bioedge.git
cd bioedge
pip3 install -r requirements.txt
```

*(Note: `vcgencmd` is installed by default on Raspberry Pi OS. If running in a minimal environment, install `libraspberrypi-bin` or `raspberrypi-utils`).*

---

## Configuration

### SMTP Email Alerts (Optional)
To enable outbound email delivery via an external SMTP server (e.g., Gmail, SendGrid, Amazon SES), set the following environment variables prior to running the application:

```bash
export SMTP_HOST="smtp.gmail.com"
export SMTP_PORT="587"
export SMTP_USER="your-email@gmail.com"
export SMTP_PASS="your-app-password"
export SMTP_FROM="your-email@gmail.com"
```

If these environment variables are omitted, BioEdge will attempt delivery via a local MTA on `localhost:25` and record all alert payloads to `alert_emails.log`.

---

## Running the Application

### 1. Start the BioEdge Web Service
```bash
python3 app.py
```
By default, the server listens on `0.0.0.0:5000`. Access the dashboard in your web browser at:
```
http://<YOUR_PI_IP>:5000
```

### 2. Standalone Sensor Diagnostic Tool
To verify the dual GY-302 illuminance sensors from the command line without starting the web server:
```bash
python3 sensor_read.py
```
This will print live Lux readings from both sensors at 1-second intervals:
```
Starting GY-302 readings...
Sensor 1: 342.50 Lux, Sensor 2: 340.10 Lux
```

---

## REST API Endpoints

### `GET /data`
Returns current sensor metrics and hardware telemetry.

**Sample Response:**
```json
{
  "pi_temperature": "temp=42.8'C",
  "temperature": 23.45,
  "pressure": 1013.25,
  "pressure_mmhg": 760.0,
  "light_1_lux": 320.5,
  "light_2_lux": 318.0
}
```

### `POST /api/send_email_alert`
Dispatches an alert notification to the specified recipient.

**Payload:**
```json
{
  "email": "recipient@example.com",
  "type": "CPU Temperature Warning",
  "value": "52.4°C",
  "threshold": "> 50.0°C",
  "message": "Raspberry Pi SoC Core Temperature has exceeded 50°C for longer than 10 consecutive seconds."
}
```

**Response:**
```json
{
  "success": true,
  "email_sent": true,
  "recipient": "recipient@example.com",
  "timestamp": "2026-09-12 19:00:00",
  "note": "Delivered via SMTP relay (smtp.gmail.com)"
}
```

---

## Project Structure

```
bioedge/
├── app.py              # Main Flask application and I2C sensor driver engine
├── sensor_read.py      # Standalone dual-sensor diagnostic CLI utility
├── email.list          # Team alert distribution list
├── requirements.txt    # Python package dependencies
├── .gitignore          # Git exclusion rules (caches, logs, sockets)
├── templates/
│   └── index.html      # Comprehensive real-time dashboard UI
└── README.md           # Project documentation and specifications
```

---

## License

This project is open source and available under the [MIT License](LICENSE).

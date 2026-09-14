# BioEdge: Raspberry Pi Edge Telemetry & Environmental Monitoring System

**BioEdge** is a real-time IoT edge telemetry and environmental sensing system engineered for Raspberry Pi. It integrates hardware sensors over the I2C bus with a lightweight Flask backend and a responsive, high-performance web dashboard featuring live canvas charts, differential sensor analysis, thermal protection heuristics, global multi-client stream synchronization, and multi-channel alerting (in-browser synthesized audio chimes, visual warning banners, and automated SMTP team email alerts).

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
                       |  - Global Stream State Sync |
                       |  - Dynamic YAML Hot-Reload  |
                       |  - Alert Dispatch & Cooldown|
                       |  - Disk Audit Log Engine    |
                       +--------------+--------------+
                                      |
               +----------------------+----------------------+
               |                                             |
  +------------v-------------+                 +-------------v------------+
  |    Web Dashboard UI      |                 |   Alerting Infrastructure|
  |  - Canvas Stream Curves  |                 |  - Web Audio Synthesizer |
  |  - Dual Light Delta Calc |                 |  - Visual Warning Banners|
  |  - Global Pause Control  |                 |  - SMTP (TLS) / MTA Relay|
  |  - Dark / Light / Cyber  |                 |  - 5-Min Email Cooldown  |
  +--------------------------+                 +--------------------------+
```

---

## Features

### 1. Hardware & Environmental Telemetry
- **Ambient Temperature & Barometric Pressure (Bosch BMP280)**: Reads calibrated temperature (°C / °F) and atmospheric pressure (dual display: mmHg primary and hPa secondary) using Bosch's native 64-bit integer compensation formulas.
- **Dual Ambient Light Sensing (Rohm BH1750 / GY-302)**: Reads illuminance in Lux simultaneously across two distinct I2C addresses (`0x23` and `0x5C`).
- **Differential Lux Delta Analysis**: Computes real-time Lux differences (`ΔLux = |Sensor 1 - Sensor 2|`) and rate-of-change between dual sensors to detect shadowing, directional occlusion, or sensor failures.
- **SoC Core Thermal Monitoring**: Continuously queries the Raspberry Pi Broadcom SoC temperature via `vcgencmd measure_temp`.

### 2. Intelligent Multi-Tier Alert System
- **Dual-Condition Persistence Engine**: Prevents false alarms caused by transient sensor spikes or brief CPU load spikes by requiring anomalies to continuously persist beyond a configurable time window (default: `10s`).
- **Differential Illuminance Anomaly Detection**: Warns if differential lux shifts exceed the threshold for longer than the persistence limit.
- **Continuous SoC Thermal Protection**: Tracks Raspberry Pi CPU temperatures across three distinct severity tiers (Optimal, Pending Warning, and Critical Overheat). Thermal protection remains active **even when the UI stream is paused**.
- **Global Stream Synchronization & Pause Suppression**: Pausing the telemetry stream synchronizes across all active clients and automatically suppresses illuminance alerts (both client-side and server-side).
- **Web Audio API Chime**: Generates in-browser synthesized acoustic alert tones (dual-frequency harmonic chime: 587.33 Hz D5 & 880.00 Hz A5) without external sound files.
- **Automated Team Email Dispatch**:
  - Automatically emails all team members registered in `email.list`.
  - Supports external SMTP relays with TLS (e.g. Gmail with App Passwords, SendGrid, Amazon SES) or fallback to local MTA (`localhost:25`).
  - Strict 5-minute (`300,000 ms`) cooldown throttling per anomaly channel to prevent inbox flooding during sustained issues.
  - Complete disk audit trail logged to `alert_emails.log` with true delivery verification status.

### 3. Interactive Web Dashboard (`templates/index.html`)
- **Real-Time Canvas Visualizer**: High-frequency telemetry stream with live moving-window averaging.
- **Metric Switching**: Seamlessly toggle visualization between Temperature, Barometric Pressure, and Dual Light curves.
- **Timeline Buffer & Scrubbing**: Drag-to-scrub timeline allowing inspection of historical buffer points with a "Jump to Live" action.
- **Configurable Polling**: Switchable refresh rates (1.0s, 2.0s, 5.0s) and global pause/resume controls.
- **Dynamic Threshold Badges**: Real-time display of active thresholds and persistence durations loaded dynamically from `thresholds.yaml`.
- **Theme Engine**: Includes three distinct UI themes:
  - **Cyber Dark**: High-contrast OLED dark interface.
  - **Clean Light**: Crisp daylight telemetry theme.
  - **Rainbow Cyber**: Animated RGB border flow theme.

---

## Alert Conditions & Trigger Matrix

BioEdge implements a comprehensive dual-parameter alert heuristic: a **magnitude threshold** combined with a **continuous persistence duration**. This prevents noisy, brief spikes from triggering unnecessary notifications while guaranteeing rapid escalation during genuine hardware or environmental failures.

### Alert Matrix Overview

| Alert Channel | Measured Metric | Trigger Condition | Persistence Required | Global Pause Behavior | Email Cooldown | Audio / Visual Actions |
|---|---|---|---|---|---|---|
| **Differential Illuminance** | `ΔLux = abs(Lux1 - Lux2)` | `ΔLux > illuminance_threshold` | `> illuminance_persistence_seconds` (default: `>10s`) | **Strictly Suppressed** (frontend stops timer & server drops email) | 5 minutes (`300,000 ms`) | Amber pending badge ➔ Red pulsing card, top warning banner, 2-tone audio chime |
| **SoC Core Overheat (Critical)** | Broadcom CPU Core Temp (`T_CPU`) | `T_CPU > temperature_threshold` | `> temperature_persistence_seconds` (default: `>10s`) | **Never Suppressed** (runs continuously for hardware safety) | 5 minutes (`300,000 ms`) | Amber pending badge ➔ Red pulsing card, top warning banner, 2-tone audio chime |
| **SoC Core Temp (Pending Warning)** | Broadcom CPU Core Temp (`T_CPU`) | `max(45°C, T_threshold - 10°C) <= T_CPU <= T_threshold` | Immediate state change | **Never Suppressed** (runs continuously for hardware safety) | No email dispatched (pre-alert advisory) | Amber card glow, amber meter, `⚠️ PENDING WARNING` pill |
| **SoC Core Temp (Optimal)** | Broadcom CPU Core Temp (`T_CPU`) | `T_CPU < max(45°C, T_threshold - 10°C)` | Immediate state change | **Never Suppressed** | N/A | Emerald green status, normal meter |

---

### Condition 1: Differential Illuminance Alert (`ΔLux`)

Dual Rohm BH1750 / GY-302 light sensors placed at different vantage points or orientations are compared in real time.

#### 1. Evaluation Formula
```
ΔLux = |Sensor 1 - Sensor 2|
```

#### 2. Configuration Parameters (`thresholds.yaml`)
- `illuminance_threshold`: Float value in Lux (e.g. `5000.0`).
- `illuminance_persistence_seconds`: Integer seconds (e.g. `10`).

#### 3. State Lifecycle & Escalation
```
[ Normal State ]  -->  ΔLux > Threshold  -->  [ ⏳ LUX PENDING ]  -->  Time > 10s  -->  [ 🚨 ABNORMAL ACTIVE ]
(ΔLux <= Thresh)       Timer starts           (Elapsed <= 10s)                          (Chime, Banner, Email)
       ^                                              |                                           |
       |                                      ΔLux drops <= Thresh                                |
       +----------------------------------------------+-------------------------------------------+
                                                      |
                                     (Stream Paused by user: reset & suppress)
```

1. **Normal State (`ΔLux <= Threshold`)**:
   - Status pill is hidden.
   - Sensor card displays standard theme borders.
   - Persistence timer is inactive (`luxOverThresholdStart = null`).

2. **Pending Verification State (`ΔLux > Threshold` for `elapsed <= Persistence`)**:
   - When `ΔLux` first crosses the threshold, a timestamp is recorded.
   - While elapsed duration is less than or equal to `illuminance_persistence_seconds`, the UI enters verification mode:
     - An amber status pill appears: `⏳ LUX PENDING (Xs / 10s)`.
     - Acoustic chimes and email dispatches are **held back** to filter out temporary shadows or brief light flicker.

3. **Active Alert Trigger (`ΔLux > Threshold` sustained for `elapsed > Persistence`)**:
   - If the anomaly persists longer than `illuminance_persistence_seconds` without interruption:
     - **Card Styling**: Illuminance card flashes in high-visibility red (`.is-abnormal`).
     - **Status Badge**: Shifts to red error badge: `🚨 ABNORMAL (Δ XXX.X Lux)`.
     - **Top Banner**: Displays an animated warning banner with exact delta and individual sensor readings.
     - **Harmonic Chime**: In-browser Web Audio API plays a dual-frequency chime (D5 587.33 Hz + A5 880 Hz). Chimes repeat at most once per minute while the condition remains active.
     - **Team Email Dispatch**: An automated email alert is dispatched to all recipients in `email.list`:
       - **Subject**: `Illuminance warning`
       - **Body**: `Warning: Illuminance warning\nIlluminance difference is above <threshold> Lux for <elapsed>s since <startTime>`
       - **Throttling**: 5-minute cooldown (`LUX_EMAIL_COOLDOWN_MS = 300000`).

4. **Stream Pause Guard (Suppression)**:
   - **Frontend**: When the user pauses the stream, illuminance persistence timers are cleared, active alert banners/pills are dismissed, and illuminance processing halts.
   - **Backend Guard**: If a delayed frontend request reaches `/api/send_email_alert` while `_stream_state["paused"]` is true, the backend suppresses the dispatch, logs `Status: SUPPRESSED (Stream is globally paused by user)` in `alert_emails.log`, and returns `email_sent: false`.

5. **Recovery & Reset**:
   - As soon as `ΔLux` drops back below the threshold, the persistence timer resets to zero, all warning banners and pills dismiss, and the card returns to normal styling.

---

### Condition 2: Raspberry Pi SoC Core Temperature Overheat Alert (`CPU Overheat`)

Monitors the Broadcom BCM2835/BCM2711 SoC temperature via `vcgencmd measure_temp` to protect against thermal throttling and hardware damage.

#### 1. Configuration Parameters (`thresholds.yaml`)
- `temperature_threshold`: Float value in °C (e.g. `60.0`).
- `temperature_persistence_seconds`: Integer seconds (e.g. `10`).

#### 2. Multi-Tier Thermal States

1. **Optimal State (`T_CPU < max(45.0°C, Threshold - 10.0°C)`)**:
   - Status text: `Optimal` (emerald green).
   - Meter: Cyan-to-blue gradient.
   - Overheat timers and alert flags are completely cleared.

2. **Approaching Threshold / Pending Warning State (`max(45.0°C, Threshold - 10.0°C) <= T_CPU <= Threshold`)**:
   - Pre-warning tier indicating elevated thermal load.
   - Card glow: Amber border glow (`.is-pending`).
   - Status badge: Amber pill `⚠️ PENDING WARNING`.
   - Status text: `Pending Warning (≥50°C)`.
   - Meter: Amber.
   - Overheat escalation timer is kept reset.

3. **Overheat Verification State (`T_CPU > Threshold` for `elapsed <= Persistence`)**:
   - Temperature exceeds critical threshold.
   - Card glow: Amber border glow (`.is-pending`).
   - Status badge: Amber pill displaying real-time countdown `⏳ OVERHEAT PENDING (Xs / 10s)`.
   - Status text: `High Temp (Xs / 10s)`.
   - Meter: Amber.
   - No audio or email alerts trigger yet, protecting against momentary CPU bursts.

4. **Critical Overheat Escalation (`T_CPU > Threshold` sustained for `elapsed > Persistence`)**:
   - Condition has persisted continuously beyond `temperature_persistence_seconds`.
   - **Card Styling**: Card pulses in warning rose/red (`.is-overheating`).
   - **Status Badge**: Red error badge: `🚨 OVERHEAT (XX.X°C)`.
   - **Status Text & Meter**: Displays `OVERHEATING (>60°C)` with full rose-red progress meter.
   - **Top Warning Banner**: Animated banner warning operator of persistent thermal breach.
   - **Harmonic Chime**: In-browser dual harmonic chime sounds (repeats every 60 seconds if sustained).
   - **Team Email Dispatch**: Automated notification sent to all addresses in `email.list`:
     - **Subject**: `CPU temperature warning`
     - **Body**: `Warning: CPU temperature warning\nOver heat XX.X°C for <elapsed>s since <startTime>`
     - **Throttling**: 5-minute cooldown (`CPU_EMAIL_COOLDOWN_MS = 300000`).

5. **Continuous Thermal Safety Guarantee**:
   - **Thermal monitoring is NEVER disabled when the stream is paused**. Even if an operator pauses the telemetry visualizer, CPU core temperature checks continue on every `/data` poll to prevent catastrophic unattended thermal runaway.

6. **Recovery & Normalization**:
   - When core temperature drops below `temperature_threshold`, the overheat timer resets, `.is-overheating` is cleared, and the UI transitions smoothly down to Pending Warning or Optimal.

---

### Global Stream Synchronization (`/api/stream/control`)

BioEdge synchronizes UI streaming and pause states globally across all connected web clients using a single backend source of truth.

```
                    +--------------------------------+
                    |  Flask Backend (_stream_state) |
                    +---------------+----------------+
                                    |
            +-----------------------+-----------------------+
            |                                               |
+-----------v------------+                      +-----------v------------+
|  Client A (Browser)    |                      |  Client B (Browser)    |
|  - Clicks [Pause]      |                      |  - Polls /data         |
|  - POST /stream/control|                      |  - Reads is_stream_paused|
|  - UI -> PAUSED        |                      |  - UI -> Auto-PAUSED   |
+------------------------+                      +------------------------+
```

1. **Backend State**: Managed via `_stream_state = {"paused": False, "paused_at": None}` in `app.py`.
2. **REST Endpoints**:
   - `GET /api/stream/control`: Queries current global pause state.
   - `POST /api/stream/control`: Toggles or explicitly sets pause state (`{"paused": true|false}`).
3. **Broadcast via Polling**: Every response from `GET /data` includes `"is_stream_paused": true|false`.
4. **Synchronized Actions**:
   - When any user clicks Pause or Resume, all other open browser tabs update on their next poll cycle.
   - UI displays connection status `STREAM PAUSED (GLOBAL)` and highlights the button in amber.
   - Pausing stops telemetry canvas rendering and suppresses illuminance alerts, while continuing background CPU temperature safety monitoring.

---

### Email Dispatch, Credentials & Audit Logging

Alert emails are managed by a dedicated dispatch module in `app.py`:

1. **Distribution List (`email.list`)**:
   - Plaintext file containing one email address per line.
   - Comments (`#`) and blank lines are ignored.
   - Automatically loaded and broadcast to all members on every alert dispatch.

2. **Credential Loading Priority**:
   - **Tier 1 (Recommended)**: Loaded from local `.env` file (gitignored for security):
     ```bash
     SMTP_HOST=smtp.gmail.com
     SMTP_PORT=587
     SMTP_USER=your_email@gmail.com
     SMTP_PASS=your_16_character_app_password
     SMTP_FROM=your_email@gmail.com
     ```
   - **Tier 2**: Fallback to `thresholds.yaml` under the `smtp:` key.
   - **Tier 3 (Local MTA)**: Fallback attempt to `localhost:25` without authentication.

3. **Audit Trail (`alert_emails.log`)**:
   - Every alert attempt is written to `alert_emails.log` with a verified delivery status:
     - `DELIVERED via SMTP (smtp.gmail.com) to N recipients`
     - `DELIVERED via local mail agent to N recipients`
     - `SUPPRESSED (Stream is globally paused by user)`
     - `NOT DELIVERED (No SMTP credentials configured; local port 25 closed - logged to disk only)`
     - `FAILED: SMTP Error (...)`

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

### 1. Alert Thresholds (`thresholds.yaml`)
BioEdge checks `thresholds.yaml` on every request. Edits to this file are **hot-reloaded automatically** without needing to restart the Flask service:

```yaml
# Differential Illuminance alert threshold (|Sensor 1 - Sensor 2|) in Lux
illuminance_threshold: 5000.0

# Differential Illuminance persistence duration in seconds
illuminance_persistence_seconds: 10

# Raspberry Pi SoC Core CPU Temperature threshold in °C
temperature_threshold: 60.0

# Raspberry Pi SoC Core CPU Overheat persistence duration in seconds
temperature_persistence_seconds: 10
```

### 2. Team Notification List (`email.list`)
Add your alert recipients to `email.list` (one per line):
```
alice@example.com
bob@example.com
zhiyuzh@gmail.com
```

### 3. SMTP Credentials Setup (`.env`)
Create a `.env` file in the project root with your SMTP provider credentials (this file is excluded by `.gitignore`):

```bash
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASS=your-google-app-password
SMTP_FROM=your-email@gmail.com
```

> [!NOTE]
> For Gmail, use an **App Password** (generated from Google Account -> Security -> 2-Step Verification -> App passwords). Standard account passwords will be rejected with `535-5.7.8 BadCredentials`.

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
Returns current sensor metrics, active thresholds, and global stream state.

**Sample Response:**
```json
{
  "pi_temperature": "temp=42.8'C",
  "temperature": 23.45,
  "pressure": 1013.25,
  "pressure_mmhg": 760.0,
  "light_1_lux": 320.5,
  "light_2_lux": 318.0,
  "is_stream_paused": false,
  "thresholds": {
    "illuminance_threshold": 5000.0,
    "illuminance_persistence_seconds": 10,
    "temperature_threshold": 60.0,
    "temperature_persistence_seconds": 10
  }
}
```

### `GET /api/thresholds`
Returns currently active threshold configuration parsed from `thresholds.yaml`.

### `GET /api/stream/control`
Returns current global pause state and pause timestamp.

### `POST /api/stream/control`
Sets or toggles global stream pause state.

**Payload:**
```json
{
  "paused": true
}
```

**Response:**
```json
{
  "success": true,
  "paused": true,
  "paused_at": "2026-09-13 19:30:00"
}
```

### `POST /api/send_email_alert`
Dispatches an alert notification to all addresses in `email.list`.

**Payload:**
```json
{
  "type": "Illuminance warning",
  "value": "Δ 5200.0 Lux",
  "threshold": "> 5000.0 Lux (>10s)",
  "message": "Illuminance difference is above 5000.0 Lux for 11s since 19:30:00"
}
```

**Response (Delivered):**
```json
{
  "success": true,
  "email_sent": true,
  "status": "DELIVERED via SMTP (smtp.gmail.com) to 8 recipients",
  "subject": "Illuminance warning",
  "recipients": ["user1@example.com", "user2@example.com"],
  "timestamp": "2026-09-13 19:30:00",
  "note": "DELIVERED via SMTP (smtp.gmail.com) to 8 recipients"
}
```

**Response (Suppressed during Stream Pause):**
```json
{
  "success": true,
  "email_sent": false,
  "status": "SUPPRESSED (Stream is globally paused by user)",
  "subject": "Illuminance warning",
  "recipients": ["user1@example.com", "user2@example.com"],
  "timestamp": "2026-09-13 19:30:00",
  "note": "SUPPRESSED (Stream is globally paused by user)"
}
```

---

## Project Structure

```
bioedge/
├── app.py              # Main Flask application, sensor drivers, and stream control
├── sensor_read.py      # Standalone dual-sensor diagnostic CLI utility
├── thresholds.yaml     # Operating alert thresholds and persistence durations
├── email.list          # Team alert distribution list
├── alert_emails.log    # Audit trail of all alert dispatches with delivery statuses
├── requirements.txt    # Python package dependencies
├── .env                # Private SMTP credentials (gitignored)
├── .gitignore          # Git exclusion rules (caches, logs, secrets)
├── templates/
│   └── index.html      # Comprehensive real-time dashboard UI & visualizer
└── README.md           # Project documentation and specifications
```

---

## License

This project is open source and available under the [MIT License](LICENSE).

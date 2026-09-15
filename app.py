import smbus2
import time
import subprocess

import os
import datetime
import json
import urllib.request
import urllib.error
import yaml

from flask import Flask, render_template, jsonify, request

def load_env_file():
    env_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_file):
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip('"').strip("'")
                        os.environ[k] = v
        except Exception:
            pass

load_env_file()

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.after_request
def add_no_cache_headers(response):
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

# -------------------------------------------------
# I2C
# -------------------------------------------------

bus = smbus2.SMBus(1)

address = 0x76

# -------------------------------------------------
# BMP280
# -------------------------------------------------

chip_id = bus.read_byte_data(address, 0xD0)
print(f"Connected! BMP280 Chip ID: {chip_id}")


def s16(x):
    return x - 65536 if x > 32767 else x


# Pressure calibration
P1 = bus.read_word_data(address, 0x8E)
P2 = s16(bus.read_word_data(address, 0x90))
P3 = s16(bus.read_word_data(address, 0x92))
P4 = s16(bus.read_word_data(address, 0x94))
P5 = s16(bus.read_word_data(address, 0x96))
P6 = s16(bus.read_word_data(address, 0x98))
P7 = s16(bus.read_word_data(address, 0x9A))
P8 = s16(bus.read_word_data(address, 0x9C))
P9 = s16(bus.read_word_data(address, 0x9E))

# Temperature calibration
T1 = bus.read_word_data(address, 0x88)
T2 = s16(bus.read_word_data(address, 0x8A))
T3 = s16(bus.read_word_data(address, 0x8C))


def init_bmp280():
    """
    Configure and start Bosch BMP280 in continuous normal mode:
    - 0xF5 (config): Standby time 0.5ms, IIR filter coefficient 16 (0x10)
    - 0xF4 (ctrl_meas): Temp oversampling x2 (010), Press oversampling x16 (101), Normal mode (11) -> 0x57
    """
    try:
        bus.write_byte_data(address, 0xF5, 0x10)
        bus.write_byte_data(address, 0xF4, 0x57)
        time.sleep(0.05)
    except Exception as e:
        print(f"Error initializing BMP280: {e}")


init_bmp280()


def read_sensor():
    try:
        data = bus.read_i2c_block_data(address, 0xF7, 6)

        raw_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
        raw_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)

        # 0x80000 indicates uninitialized / sleep mode / skipped measurement
        if raw_p == 0x80000 or raw_t == 0x80000:
            init_bmp280()
            return None, None

        # Temperature
        v1 = (((raw_t >> 3) - (T1 << 1)) * T2) >> 11
        v2 = (((((raw_t >> 4) - T1) ** 2) >> 12) * T3) >> 14
        t_fine = v1 + v2

        temperature = (t_fine * 5 + 128) / 25600

        # Pressure
        v1 = t_fine - 128000
        v2 = v1 * v1 * P6 + ((v1 * P5) << 17) + (P4 << 35)

        v1 = ((v1 * v1 * P3) >> 8) + ((v1 * P2) << 12)
        if v1 == 0:
            return temperature, None
        v1 = (((1 << 47) + v1) * P1) >> 33
        if v1 == 0:
            return temperature, None

        p = 1048576 - raw_p
        p = ((p << 31) - v2) * 3125 // v1

        v1 = (P9 * (p >> 13) ** 2) >> 25
        v2 = (P8 * p) >> 19

        p = ((p + v1 + v2) >> 8) + (P7 << 4)

        pressure = p / 25600

        return temperature, pressure
    except Exception as e:
        print(f"Error reading BMP280: {e}")
        return None, None


# -------------------------------------------------
# Raspberry Pi CPU temperature
# -------------------------------------------------

def read_pi_temperature():

    temp = subprocess.check_output(
        ["vcgencmd", "measure_temp"]
    ).decode().strip()

    return temp

def read_light(address):
    try:
        data = bus.read_i2c_block_data(address, 0x10, 2)
        lux = ((data[0] << 8) | data[1]) / 1.2
        return lux
    except Exception as e:
        print(f"Error reading GY-302 {hex(address)}: {e}")
        return None
# -------------------------------------------------
# Thresholds Configuration Loader (YAML)
# -------------------------------------------------

_thresholds_cache = None
_thresholds_mtime = 0

def load_thresholds():
    global _thresholds_cache, _thresholds_mtime
    config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.yaml")
    if not os.path.exists(config_file):
        alt_config = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.yaml")
        if os.path.exists(alt_config):
            config_file = alt_config

    defaults = {
        "illuminance_threshold": 50.0,
        "illuminance_persistence_seconds": 10,
        "temperature_threshold": 55.0,
        "temperature_persistence_seconds": 10
    }

    if not os.path.exists(config_file):
        return defaults

    try:
        mtime = os.path.getmtime(config_file)
        if _thresholds_cache is not None and mtime == _thresholds_mtime:
            return _thresholds_cache

        with open(config_file, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        thresholds = dict(defaults)
        if isinstance(cfg, dict):
            if "illuminance_threshold" in cfg:
                thresholds["illuminance_threshold"] = float(cfg["illuminance_threshold"])
            elif "illuminance_difference_threshold" in cfg:
                thresholds["illuminance_threshold"] = float(cfg["illuminance_difference_threshold"])
            elif "illuminance" in cfg:
                if isinstance(cfg["illuminance"], dict):
                    thresholds["illuminance_threshold"] = float(cfg["illuminance"].get("threshold", cfg["illuminance"].get("difference_threshold", 50.0)))
                else:
                    thresholds["illuminance_threshold"] = float(cfg["illuminance"])

            if "illuminance_persistence_seconds" in cfg:
                thresholds["illuminance_persistence_seconds"] = int(cfg["illuminance_persistence_seconds"])
            elif "illuminance_persistence" in cfg:
                thresholds["illuminance_persistence_seconds"] = int(cfg["illuminance_persistence"])
            elif "lux_persistence_seconds" in cfg:
                thresholds["illuminance_persistence_seconds"] = int(cfg["lux_persistence_seconds"])

            if "temperature_threshold" in cfg:
                thresholds["temperature_threshold"] = float(cfg["temperature_threshold"])
            elif "cpu_temperature_threshold" in cfg:
                thresholds["temperature_threshold"] = float(cfg["cpu_temperature_threshold"])
            elif "temperature" in cfg:
                if isinstance(cfg["temperature"], dict):
                    thresholds["temperature_threshold"] = float(cfg["temperature"].get("threshold", cfg["temperature"].get("cpu_threshold", 55.0)))
                else:
                    thresholds["temperature_threshold"] = float(cfg["temperature"])

            if "temperature_persistence_seconds" in cfg:
                thresholds["temperature_persistence_seconds"] = int(cfg["temperature_persistence_seconds"])
            elif "persistence_seconds" in cfg:
                thresholds["temperature_persistence_seconds"] = int(cfg["persistence_seconds"])
            elif "persistent_seconds" in cfg:
                thresholds["temperature_persistence_seconds"] = int(cfg["persistent_seconds"])
            elif "temperature_persistence" in cfg:
                thresholds["temperature_persistence_seconds"] = int(cfg["temperature_persistence"])
            elif "persistent_time" in cfg:
                thresholds["temperature_persistence_seconds"] = int(cfg["persistent_time"])

        _thresholds_cache = thresholds
        _thresholds_mtime = mtime
        return thresholds
    except Exception as e:
        print(f"[BioEdge YAML Load Error]: {e}")
        return defaults


# -------------------------------------------------
# Global Stream State (Synchronized across all clients)
# -------------------------------------------------

_stream_state = {
    "paused": False,
    "paused_at": None
}


# -------------------------------------------------
# Flask webpage
# -------------------------------------------------

@app.route("/")
def home():
    thresholds = load_thresholds()
    return render_template(
        "index.html",
        thresholds=thresholds,
        is_stream_paused=_stream_state["paused"]
    )


# -------------------------------------------------
# Sensor data for webpage
# -------------------------------------------------

@app.route("/data")
def data():

    # BMP280
    temperature, pressure = read_sensor()

    # Raspberry Pi CPU temperature
    pi_temperature = read_pi_temperature()

    # GY-302 sensors
    lux1 = read_light(0x23)
    lux2 = read_light(0x5C)

    thresholds = load_thresholds()

    return jsonify({
        "pi_temperature": pi_temperature,
        "temperature": round(temperature, 2) if temperature is not None else None,
        "pressure": round(pressure, 2) if pressure is not None else None,
        "pressure_mmhg": round(pressure * 0.750062, 2) if pressure is not None else None,
        "light_1_lux": round(lux1, 2) if lux1 is not None else None,
        "light_2_lux": round(lux2, 2) if lux2 is not None else None,
        "thresholds": thresholds,
        "is_stream_paused": _stream_state["paused"]
    })


@app.route("/api/thresholds")
def get_thresholds():
    return jsonify(load_thresholds())


# -------------------------------------------------
# Global Stream Control API
# -------------------------------------------------

@app.route("/api/stream/control", methods=["GET", "POST"])
def stream_control():
    global _stream_state
    if request.method == "POST":
        payload = request.get_json(force=True, silent=True) or {}
        if "paused" in payload:
            _stream_state["paused"] = bool(payload["paused"])
        else:
            _stream_state["paused"] = not _stream_state["paused"]

        if _stream_state["paused"]:
            _stream_state["paused_at"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            _stream_state["paused_at"] = None

    return jsonify({
        "success": True,
        "paused": _stream_state["paused"],
        "paused_at": _stream_state["paused_at"]
    })


def load_email_list():
    email_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "email.list")
    recipients = []
    if os.path.exists(email_file):
        with open(email_file, "r", encoding="utf-8") as f:
            for line in f:
                addr = line.strip()
                if addr and not addr.startswith("#") and "@" in addr:
                    recipients.append(addr)
    return recipients


def send_brevo_api_email(api_key, sender_email, sender_name, recipients, subject, body):
    """
    Dispatches transactional email via Brevo REST API v3 (POST https://api.brevo.com/v3/smtp/email).
    Returns (success: bool, delivery_status: str).
    """
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": api_key,
        "content-type": "application/json",
        "user-agent": "BioEdge/1.0"
    }
    payload = {
        "sender": {
            "name": sender_name or "BioEdge Telemetry",
            "email": sender_email
        },
        "to": [{"email": r} for r in recipients],
        "subject": subject,
        "textContent": body
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            resp_body = resp.read().decode("utf-8")
            resp_data = json.loads(resp_body) if resp_body else {}
            msg_id = resp_data.get("messageId", "sent")
            return True, f"DELIVERED via Brevo API ({msg_id}) to {len(recipients)} recipients"
    except urllib.error.HTTPError as e:
        err_msg = ""
        try:
            err_json = json.loads(e.read().decode("utf-8"))
            err_msg = err_json.get("message") or str(err_json)
        except Exception:
            err_msg = f"HTTP {e.code}"
        return False, f"FAILED: Brevo API Error ({err_msg})"
    except Exception as e:
        return False, f"FAILED: Brevo API Error ({e})"


# -------------------------------------------------
# Email Alert Dispatcher API
# -------------------------------------------------

@app.route("/api/send_email_alert", methods=["POST"])
def send_email_alert():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        recipients = payload.get("recipients") or []
        if isinstance(recipients, str):
            recipients = [r.strip() for r in recipients.splitlines() if r.strip()]
        if not recipients and payload.get("email"):
            recipients = [payload.get("email").strip()]
        if not recipients:
            recipients = load_email_list()

        alert_type = payload.get("type", "CPU temperature warning")
        detail_msg = payload.get("message", "").strip()

        # Subject: (Error Type)
        # Body: Warning: (Illuminance warning or CPU temperature warning)
        # <detail line>
        subject = alert_type
        if detail_msg:
            body = f"Warning: {alert_type}\n{detail_msg}"
        else:
            body = f"Warning: {alert_type}"

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        send_to_formatted = "\n".join(recipients)

        # Server-side guard: block Illuminance alerts if stream is globally paused
        if _stream_state["paused"] and "Illuminance" in alert_type:
            delivery_status = "SUPPRESSED (Stream is globally paused by user)"
            log_entry = (
                f"[{timestamp}] ALERT EMAIL DISPATCH\n"
                f"Status: {delivery_status}\n"
                f"Subject: {subject}\n"
                f"Send to:\n{send_to_formatted}\n"
                f"Body:\n{body}\n"
                f"{'='*60}\n"
            )
            log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_emails.log")
            try:
                with open(log_file, "a", encoding="utf-8") as f:
                    f.write(log_entry)
            except Exception as log_err:
                print(f"[BioEdge Email Log Error]: {log_err}")
            return jsonify({
                "success": True,
                "email_sent": False,
                "status": delivery_status,
                "subject": subject,
                "recipients": recipients,
                "timestamp": timestamp,
                "note": delivery_status
            })

        # Server-side guard: validate against thresholds.yaml to reject stale client triggers
        active_thresholds = load_thresholds()
        is_test = payload.get("is_test", False) or "Test" in alert_type or "Verification" in alert_type

        if not is_test and "Illuminance" in alert_type:
            req_thresh = float(active_thresholds.get("illuminance_threshold", 5000.0))
            lux1 = read_light(0x23)
            lux2 = read_light(0x5C)
            if lux1 is not None and lux2 is not None:
                current_delta = abs(lux1 - lux2)
                if current_delta < req_thresh:
                    delivery_status = f"SUPPRESSED (Server check: current delta {current_delta:.1f} Lux < threshold {req_thresh:.1f} Lux from thresholds.yaml)"
                    log_entry = (
                        f"[{timestamp}] ALERT EMAIL DISPATCH\n"
                        f"Status: {delivery_status}\n"
                        f"Subject: {subject}\n"
                        f"Send to:\n{send_to_formatted}\n"
                        f"Body:\n{body}\n"
                        f"{'='*60}\n"
                    )
                    log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_emails.log")
                    try:
                        with open(log_file, "a", encoding="utf-8") as f:
                            f.write(log_entry)
                    except Exception as log_err:
                        print(f"[BioEdge Email Log Error]: {log_err}")
                    return jsonify({
                        "success": True,
                        "email_sent": False,
                        "status": delivery_status,
                        "subject": subject,
                        "recipients": recipients,
                        "timestamp": timestamp,
                        "note": delivery_status
                    })

        elif not is_test and ("CPU" in alert_type or "temperature" in alert_type.lower()):
            req_temp = float(active_thresholds.get("temperature_threshold", 60.0))
            raw_pi = read_pi_temperature()
            current_pi_temp = None
            if raw_pi:
                try:
                    current_pi_temp = float(raw_pi.replace("temp=", "").replace("'C", ""))
                except Exception:
                    pass
            if current_pi_temp is not None and current_pi_temp < req_temp:
                delivery_status = f"SUPPRESSED (Server check: current CPU temp {current_pi_temp:.1f}°C < threshold {req_temp:.1f}°C from thresholds.yaml)"
                log_entry = (
                    f"[{timestamp}] ALERT EMAIL DISPATCH\n"
                    f"Status: {delivery_status}\n"
                    f"Subject: {subject}\n"
                    f"Send to:\n{send_to_formatted}\n"
                    f"Body:\n{body}\n"
                    f"{'='*60}\n"
                )
                log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_emails.log")
                try:
                    with open(log_file, "a", encoding="utf-8") as f:
                        f.write(log_entry)
                except Exception as log_err:
                    print(f"[BioEdge Email Log Error]: {log_err}")
                return jsonify({
                    "success": True,
                    "email_sent": False,
                    "status": delivery_status,
                    "subject": subject,
                    "recipients": recipients,
                    "timestamp": timestamp,
                    "note": delivery_status
                })

        # 1. Reload .env and check environment variables
        load_env_file()
        brevo_api_key = os.environ.get("BREVO_API_KEY")
        brevo_sender_email = os.environ.get("BREVO_SENDER_EMAIL")
        brevo_sender_name = os.environ.get("BREVO_SENDER_NAME", "BioEdge Telemetry")

        # 2. Check thresholds.yaml for optional credentials if not in environment
        config_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thresholds.yaml")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r", encoding="utf-8") as f:
                    cfg = yaml.safe_load(f) or {}
                if isinstance(cfg, dict):
                    brevo_cfg = cfg.get("brevo") or {}
                    if isinstance(brevo_cfg, dict):
                        brevo_api_key = brevo_api_key or brevo_cfg.get("api_key")
                        brevo_sender_email = brevo_sender_email or brevo_cfg.get("sender_email") or brevo_cfg.get("from")
                        brevo_sender_name = brevo_sender_name or brevo_cfg.get("sender_name")
            except Exception:
                pass

        email_sent = False
        delivery_status = "NOT DELIVERED (No Brevo API credentials configured - logged to disk only)"

        # Brevo REST API (HTTPS Port 443)
        if brevo_api_key and brevo_sender_email and recipients:
            email_sent, delivery_status = send_brevo_api_email(
                api_key=brevo_api_key,
                sender_email=brevo_sender_email,
                sender_name=brevo_sender_name,
                recipients=recipients,
                subject=subject,
                body=body
            )
            if not email_sent:
                print(f"[BioEdge Brevo API Error]: {delivery_status}")
        elif not recipients:
            delivery_status = "NOT DELIVERED (Recipient roster empty - logged to disk only)"

        # Log to disk with exact Subject, Status, Send to, and Body
        log_entry = (
            f"[{timestamp}] ALERT EMAIL DISPATCH\n"
            f"Status: {delivery_status}\n"
            f"Subject: {subject}\n"
            f"Send to:\n{send_to_formatted}\n"
            f"Body:\n{body}\n"
            f"{'='*60}\n"
        )

        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_emails.log")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as log_err:
            print(f"[BioEdge Email Log Error]: {log_err}")

        return jsonify({
            "success": True,
            "email_sent": email_sent,
            "status": delivery_status,
            "subject": subject,
            "recipients": recipients,
            "timestamp": timestamp,
            "note": delivery_status
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# -------------------------------------------------
# Start Flask
# -------------------------------------------------

if __name__ == "__main__":

    print("Starting Bio Edge web server...")
    print("Open http://YOUR_PI_IP:5000 in your browser")

    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )
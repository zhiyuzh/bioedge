import smbus2
import time
import subprocess

import os
import datetime
import smtplib
import yaml
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from flask import Flask, render_template, jsonify, request

app = Flask(__name__)
app.config['TEMPLATES_AUTO_RELOAD'] = True

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
        "temperature_threshold": 55.0
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

            if "temperature_threshold" in cfg:
                thresholds["temperature_threshold"] = float(cfg["temperature_threshold"])
            elif "cpu_temperature_threshold" in cfg:
                thresholds["temperature_threshold"] = float(cfg["cpu_temperature_threshold"])
            elif "temperature" in cfg:
                if isinstance(cfg["temperature"], dict):
                    thresholds["temperature_threshold"] = float(cfg["temperature"].get("threshold", cfg["temperature"].get("cpu_threshold", 55.0)))
                else:
                    thresholds["temperature_threshold"] = float(cfg["temperature"])

        _thresholds_cache = thresholds
        _thresholds_mtime = mtime
        return thresholds
    except Exception as e:
        print(f"[BioEdge YAML Load Error]: {e}")
        return defaults


# -------------------------------------------------
# Flask webpage
# -------------------------------------------------

@app.route("/")
def home():
    thresholds = load_thresholds()
    return render_template("index.html", thresholds=thresholds)


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
        "thresholds": thresholds
    })


@app.route("/api/thresholds")
def get_thresholds():
    return jsonify(load_thresholds())


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

        # Log to disk with exact Subject, Send to (separated by lines), and Body
        log_entry = (
            f"[{timestamp}] ALERT EMAIL DISPATCH\n"
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

        # Send via Gmail SMTP if credentials configured
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", 587))
        smtp_user = os.environ.get("SMTP_USER") or os.environ.get("GMAIL_USER")
        smtp_pass = os.environ.get("SMTP_PASS") or os.environ.get("GMAIL_APP_PASS")
        smtp_from = os.environ.get("SMTP_FROM", smtp_user or "bioedge-alert@gmail.com")

        email_sent = False
        delivery_note = f"Logged to {os.path.basename(log_file)}"

        if smtp_user and smtp_pass and recipients:
            try:
                msg = MIMEMultipart()
                msg["From"] = smtp_from
                msg["To"] = ", ".join(recipients)
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))

                server = smtplib.SMTP(smtp_host, smtp_port, timeout=5)
                if smtp_port == 587:
                    server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, recipients, msg.as_string())
                server.quit()
                email_sent = True
                delivery_note = f"Delivered via Gmail SMTP ({smtp_host}) to {len(recipients)} recipients"
            except Exception as e:
                delivery_note = f"Gmail SMTP error: {e} (logged to {os.path.basename(log_file)})"
                print(f"[BioEdge SMTP Error]: {e}")
        elif recipients:
            # Attempt local SMTP on port 25 as fallback
            try:
                msg = MIMEMultipart()
                msg["From"] = "bioedge-alert@localhost"
                msg["To"] = ", ".join(recipients)
                msg["Subject"] = subject
                msg.attach(MIMEText(body, "plain"))

                server = smtplib.SMTP("localhost", 25, timeout=2)
                server.sendmail("bioedge-alert@localhost", recipients, msg.as_string())
                server.quit()
                email_sent = True
                delivery_note = f"Delivered via local mail agent to {len(recipients)} recipients"
            except Exception:
                delivery_note = f"Logged to server disk ({os.path.basename(log_file)}) - Gmail credentials not configured"

        return jsonify({
            "success": True,
            "email_sent": email_sent,
            "subject": subject,
            "recipients": recipients,
            "timestamp": timestamp,
            "note": delivery_note
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
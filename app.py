import smbus2
import time
import subprocess

import os
import datetime
import smtplib
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


def read_sensor():

    data = bus.read_i2c_block_data(address, 0xF7, 6)

    raw_p = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
    raw_t = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)

    # Temperature
    v1 = (((raw_t >> 3) - (T1 << 1)) * T2) >> 11
    v2 = (((((raw_t >> 4) - T1) ** 2) >> 12) * T3) >> 14
    t_fine = v1 + v2

    temperature = (t_fine * 5 + 128) / 25600

    # Pressure
    v1 = t_fine - 128000
    v2 = v1 * v1 * P6 + ((v1 * P5) << 17) + (P4 << 35)

    v1 = ((v1 * v1 * P3) >> 8) + ((v1 * P2) << 12)
    v1 = (((1 << 47) + v1) * P1) >> 33

    p = 1048576 - raw_p
    p = ((p << 31) - v2) * 3125 // v1

    v1 = (P9 * (p >> 13) ** 2) >> 25
    v2 = (P8 * p) >> 19

    p = ((p + v1 + v2) >> 8) + (P7 << 4)

    pressure = p / 25600

    return temperature, pressure


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
# Flask webpage
# -------------------------------------------------

@app.route("/")
def home():
    return render_template("index.html")


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

    return jsonify({
        "pi_temperature": pi_temperature,
        "temperature": round(temperature, 2),
        "pressure": round(pressure, 2),
        "pressure_mmhg": round(pressure * 0.750062, 2),
        "light_1_lux": round(lux1, 2) if lux1 is not None else None,
        "light_2_lux": round(lux2, 2) if lux2 is not None else None
    })


# -------------------------------------------------
# Email Alert Dispatcher API
# -------------------------------------------------

@app.route("/api/send_email_alert", methods=["POST"])
def send_email_alert():
    try:
        payload = request.get_json(force=True, silent=True) or {}
        recipient = payload.get("email", "").strip()
        alert_type = payload.get("type", "CPU Temperature Warning")
        value = payload.get("value", "N/A")
        threshold = payload.get("threshold", "> 50.0°C")
        message = payload.get("message", "Raspberry Pi SoC Core Temperature has exceeded 50°C for longer than 10 consecutive seconds.")

        if not recipient:
            return jsonify({"success": False, "error": "No recipient email address provided"}), 400

        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = (
            f"[{timestamp}] ALERT EMAIL TO <{recipient}> | "
            f"Type: {alert_type} | Val: {value} | Thresh: {threshold} | {message}\n"
        )

        # Log to disk so notifications are always auditable
        log_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_emails.log")
        try:
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(log_entry)
        except Exception as log_err:
            print(f"[BioEdge Email Log Error]: {log_err}")

        # Attempt SMTP delivery if configured or available
        smtp_host = os.environ.get("SMTP_HOST")
        email_sent = False
        delivery_note = f"Logged to {os.path.basename(log_file)}"

        if smtp_host:
            try:
                smtp_port = int(os.environ.get("SMTP_PORT", 587))
                smtp_user = os.environ.get("SMTP_USER")
                smtp_pass = os.environ.get("SMTP_PASS")
                smtp_from = os.environ.get("SMTP_FROM", smtp_user or "bioedge-alert@localhost")

                msg = MIMEMultipart()
                msg["From"] = smtp_from
                msg["To"] = recipient
                msg["Subject"] = f"BioEdge Critical Alert: {alert_type} (>10s)"
                body = (
                    f"BioEdge Telemetry Alert\n"
                    f"====================================\n"
                    f"Timestamp: {timestamp}\n"
                    f"Alert Type: {alert_type}\n"
                    f"Measured Value: {value}\n"
                    f"Threshold: {threshold}\n"
                    f"Duration: Sustained for > 10 consecutive seconds\n\n"
                    f"Details:\n{message}\n"
                    f"------------------------------------\n"
                    f"Sent automatically by BioEdge System on Raspberry Pi.\n"
                )
                msg.attach(MIMEText(body, "plain"))

                server = smtplib.SMTP(smtp_host, smtp_port, timeout=3)
                if smtp_port == 587:
                    server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_from, recipient, msg.as_string())
                server.quit()
                email_sent = True
                delivery_note = f"Delivered via SMTP relay ({smtp_host})"
            except Exception as e:
                delivery_note = f"SMTP error: {e} (logged to {os.path.basename(log_file)})"
                print(f"[BioEdge SMTP Error]: {e}")
        else:
            # Check local SMTP on port 25
            try:
                msg = MIMEMultipart()
                msg["From"] = "bioedge-alert@localhost"
                msg["To"] = recipient
                msg["Subject"] = f"BioEdge Critical Alert: {alert_type} (>10s)"
                body = (
                    f"BioEdge Telemetry Alert\n"
                    f"====================================\n"
                    f"Timestamp: {timestamp}\n"
                    f"Alert Type: {alert_type}\n"
                    f"Measured Value: {value}\n"
                    f"Threshold: {threshold}\n"
                    f"Duration: Sustained for > 10 consecutive seconds\n\n"
                    f"Details:\n{message}\n"
                )
                msg.attach(MIMEText(body, "plain"))
                server = smtplib.SMTP("localhost", 25, timeout=2)
                server.sendmail("bioedge-alert@localhost", recipient, msg.as_string())
                server.quit()
                email_sent = True
                delivery_note = "Delivered via local mail agent"
            except Exception:
                delivery_note = "Logged to server disk (alert_emails.log)"

        return jsonify({
            "success": True,
            "email_sent": email_sent,
            "recipient": recipient,
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
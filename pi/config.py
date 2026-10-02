"""
config.py – Central configuration of the Smart Desk.

This file is the "contract" between hardware and software: every pin number,
threshold, timer and MQTT topic is defined here exactly once. All other
programs import their settings from this file, so a change in the wiring only
needs a change here.

Secrets (passwords, API keys) are NOT stored here but in the .env file in the
root of the repository (see .env.example).
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load the .env file from the repository root (one level above pi/)
REPO_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(REPO_ROOT / ".env")

# True = short timers so everything can be shown in the demo video
DEMO_MODE = os.getenv("DEMO_MODE", "1") == "1"


# ---------------------------------------------------------------------------
# Pins (BCM numbering). Use board.D<pin> in Blinka, e.g. board.D12.
# ---------------------------------------------------------------------------
class Pins:
    """GPIO pin assignment of the Raspberry Pi 5."""

    # I2C bus (BH1750 + BMP280): fixed hardware pins
    I2C_SDA = 2
    I2C_SCL = 3

    # SPI bus (MCP3008 + OLED): fixed hardware pins
    SPI_SCLK = 11
    SPI_MOSI = 10
    SPI_MISO = 9
    MCP3008_CS = 24          # software chip select
    OLED_CS = 5
    OLED_DC = 6
    OLED_RST = 4

    # PWM desk lamp (hardware PWM0 via dtoverlay=pwm,pin=12,func=4)
    LAMP_PWM = 12

    # RGB posture LED (common cathode, plain digital outputs)
    RGB_RED = 13
    RGB_GREEN = 19
    RGB_BLUE = 26

    # Stepper motor 28BYJ-48 via ULN2003
    STEPPER = (17, 27, 22, 23)   # IN1, IN2, IN3, IN4

    # Ultrasonic sensor HC-SR04 (voltage divider on ECHO!)
    US_TRIG = 20
    US_ECHO = 21

    # Fan
    FAN_RELAY = 16           # relay input is active LOW
    FAN_BUTTON = 25          # to GND, internal pull-up


# I2C addresses
BH1750_ADDRESS = 0x23
BMP280_ADDRESS = 0x77        # 0x77 = Adafruit board, 0x76 = most Chinese boards

# MCP3008 channels
ADC_THRESHOLD_POT = 0        # potentiometer: light threshold
ADC_WINDOW_LDR = 1           # LDR at the window

# OLED size
OLED_WIDTH = 128
OLED_HEIGHT = 64


# ---------------------------------------------------------------------------
# Thresholds and timers
# ---------------------------------------------------------------------------
class Limits:
    """Thresholds and timers used by the rules in desk_controller.py."""

    # Desk light: the potentiometer maps to this lux range
    LUX_THRESHOLD_MIN = 50
    LUX_THRESHOLD_MAX = 600

    # Window light (0–100 %) with hysteresis so the shade does not flutter
    SHADE_CLOSE_ABOVE = 70
    SHADE_OPEN_BELOW = 50
    SHADE_STEPS = 2048       # steps for a fully closed shade (half a turn)

    # Temperature (°C) with 1 °C hysteresis
    FAN_ON_ABOVE = 25.0
    FAN_OFF_BELOW = 24.0

    # Presence: distance drop (cm) below the baseline that counts as "someone"
    PRESENCE_DROP_CM = 5
    STANDBY_AFTER_S = 30 if DEMO_MODE else 300

    # Seated time before a movement reminder
    SEATED_LIMIT_S = 60 if DEMO_MODE else 50 * 60

    # Posture
    BAD_POSTURE_ANGLE = 25   # degrees forward lean of the neck
    BAD_POSTURE_AFTER_S = 10
    ALERT_COOLDOWN_S = 60 if DEMO_MODE else 300


# ---------------------------------------------------------------------------
# MQTT
# ---------------------------------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))


class Topics:
    """MQTT topics used between the programs (see README)."""

    CHAIR = "desk/chair/occupied"   # Pico → "1" / "0"
    PRESENCE = "desk/presence"      # "1" / "0"
    POSTURE = "desk/posture"        # JSON {"state", "angle"}
    ENV = "desk/env"                # JSON {"lux", "temp", "window", "threshold"}
    ACTUATORS = "desk/actuators"    # JSON {"lamp", "fan", "shade"}
    ALERT = "desk/alert"            # text, forwarded to ntfy
    ALL = "desk/#"


# ---------------------------------------------------------------------------
# Cloud services
# ---------------------------------------------------------------------------
THINGSPEAK_HOST = "mqtt3.thingspeak.com"
THINGSPEAK_PORT = 1883
THINGSPEAK_CHANNEL_ID = os.getenv("THINGSPEAK_CHANNEL_ID", "")
THINGSPEAK_CLIENT_ID = os.getenv("THINGSPEAK_CLIENT_ID", "")
THINGSPEAK_USERNAME = os.getenv("THINGSPEAK_USERNAME", "")
THINGSPEAK_PASSWORD = os.getenv("THINGSPEAK_PASSWORD", "")
THINGSPEAK_INTERVAL_S = 15   # free tier: max. one update every 15 s

NTFY_URL = "https://ntfy.sh"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "smartdesk")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "smartdesk")
DB_LOG_INTERVAL_S = 10


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
CAMERA_INDEX = 0
POSE_MODEL = "yolo11n-pose_ncnn_model"   # created once with model.export(format="ncnn")
AI_FRAME_INTERVAL_S = 1.0

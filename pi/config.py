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

    # SPI0 bus (MCP3008 only): fixed hardware pins
    SPI_SCLK = 11
    SPI_MOSI = 10
    SPI_MISO = 9
    MCP3008_CS = 24          # software chip select

    # SPI1 bus (OLED only, dtoverlay=spi1-1cs). Our OLED module has no CS pin,
    # so it would react to the MCP3008 traffic on SPI0 – it gets its own bus.
    # The overlay also claims GPIO19 (MISO1) and GPIO18 (CE0): keep them free.
    OLED_SCLK = 21           # module pin "SCL" (it is SPI clock, not I2C!)
    OLED_MOSI = 20           # module pin "SDA" (it is SPI data, not I2C!)
    OLED_CS = None           # module has no CS pin
    OLED_DC = 6
    OLED_RST = 4

    # PWM desk lamp (hardware PWM0 channel 0 via dtoverlay=pwm,pin=12,func=4)
    LAMP_PWM = 12

    # RGB posture LED (common cathode, plain digital outputs)
    RGB_RED = 13
    RGB_GREEN = 5
    RGB_BLUE = 26

    # Stepper motor 28BYJ-48 via ULN2003
    STEPPER = (17, 27, 22, 23)   # IN1, IN2, IN3, IN4
    STEPPER_REVERSE = False      # True if the shade moves the wrong way (test_stepper.py --reverse)

    # Shade button: toggles the sunshade open/closed. GPIO7 is SPI0 CE1; the
    # overlay dtoverlay=spi0-1cs (setup_pi.sh) lets SPI0 keep only CE0 (GPIO8),
    # which we do not use either (the MCP3008 has its own CS on GPIO24).
    SHADE_BUTTON = 7         # to GND, internal pull-up (header pin 26, GND on pin 25)

    # Ultrasonic sensor HC-SR04, powered from 3.3 V: ECHO goes straight to the GPIO
    # GPIO14/15 are the UART pins: the serial port must be off (setup_pi.sh,
    # check_setup.py checks it), otherwise the HC-SR04 cannot claim them.
    US_TRIG = 14
    US_ECHO = 15

    # Fan
    FAN_RELAY = 16           # relay input is active LOW
    FAN_BUTTON = 25          # to GND, internal pull-up (toggles the fan)


# I2C addresses
BH1750_ADDRESS = 0x23
BMP280_ADDRESS = 0x76        # 0x77 = Adafruit board, 0x76 = most Chinese boards

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

    # Desk lamp control (closed loop: the lamp itself also lights the BH1750).
    # Every sensor reading the lamp level moves by LAMP_GAIN x the relative
    # shortfall ((threshold - lux) / threshold), at most LAMP_MAX_STEP %.
    # Lamp pumps up and down? Lower LAMP_GAIN.
    LAMP_GAIN = 30           # % per reading at 100 % shortfall
    LAMP_MAX_STEP = 20       # % per reading (0 -> 100 % in about 5 s)
    LAMP_DEADBAND = 0.05     # +/- 5 % around the threshold counts as "right"
    LAMP_FADE_PER_S = 40     # the LEDs follow the new level smoothly at this speed

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

    # Seated time before a movement reminder (repeated every SEATED_LIMIT_S while seated)
    SEATED_LIMIT_S = 60 if DEMO_MODE else 50 * 60
    # Away from the seat at least this long = a real break: the seated timer restarts.
    # Shorter (grabbing a coffee, shifting on the chair) and the timer just goes on.
    BREAK_MIN_S = 10 if DEMO_MODE else 2 * 60

    # desk_controller.py: how often the sensors are read and desk/env is published
    SENSOR_INTERVAL_S = 1.0

    # Posture (posture_ai.py): neck angle = how far the ear is in front of the
    # shoulder, seen from the side. 0° = ear straight above the shoulder.
    BAD_POSTURE_ANGLE = 25   # degrees forward lean of the neck: above = bad
    GOOD_POSTURE_ANGLE = 22  # below = good again (hysteresis: no flicker around 25°)
    BAD_POSTURE_AFTER_S = 10 # bad this long -> posture warning on desk/alert
    ALERT_COOLDOWN_S = 60 if DEMO_MODE else 300   # at most one posture warning per cooldown
    POSTURE_STALE_S = 5      # no desk/posture message for this long = posture unknown (posture_ai stopped?)

    # OLED: how long an alert ("Time to move!", posture warning) fills the screen
    ALERT_SCREEN_S = 5


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
    ENV = "desk/env"                # JSON {"lux", "temp", "window", "threshold", "distance"}
    ACTUATORS = "desk/actuators"    # JSON {"lamp", "fan", "shade"}
    SEATED = "desk/seated"          # seated time in minutes, e.g. "12.5"
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
THINGSPEAK_INTERVAL_S = 16   # free tier: max. one update per 15 s (1 s margin)

NTFY_URL = "https://ntfy.sh"
NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_USER = os.getenv("DB_USER", "smartdesk")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "smartdesk")
DB_LOG_INTERVAL_S = 10       # db_logger.py: one snapshot per interval (durations = rows x interval)


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------
CAMERA_INDEX = 0                     # /dev/video0 (v4l2-ctl --list-devices)
CAMERA_WIDTH = 640                   # Logitech C270: 640x480 is plenty and fast
CAMERA_HEIGHT = 480
MODEL_DIR = REPO_ROOT / "models"     # not in git (.gitignore); filled on the first run
POSE_MODEL = "yolo11n-pose"          # models/yolo11n-pose.pt is downloaded once and
                                     # exported to models/yolo11n-pose_ncnn_model (lesson 8c)
AI_FRAME_INTERVAL_S = 1.0            # one posture check per second
KEYPOINT_MIN_CONF = 0.5              # ignore ear/shoulder points the model is unsure about
POSTURE_SMOOTHING = 3                # median of the last N angles (filters one bad frame)

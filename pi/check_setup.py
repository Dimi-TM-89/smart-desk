"""
check_setup.py – Verifies that the Raspberry Pi is ready for the Smart Desk.

Run after scripts/setup_pi.sh and a reboot:
    source .venv/bin/activate
    python pi/check_setup.py

Each check prints OK or a hint about what to fix. Nothing is changed on the Pi.
"""

import importlib
import os
import socket
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
results = []


def check(name, func):
    """Run one check, remember and print the result."""
    try:
        detail = func()
        results.append(True)
        print(f"  OK    {name}" + (f" – {detail}" if detail else ""))
    except Exception as exc:  # noqa: BLE001 – we want to report every failure
        results.append(False)
        print(f"  FAIL  {name} – {exc}")


def python_packages():
    """All Python packages from requirements.txt can be imported."""
    modules = ["board", "busio", "digitalio", "pwmio", "lgpio",
               "adafruit_bh1750", "adafruit_bmp280", "adafruit_mcp3xxx",
               "adafruit_ssd1306", "paho.mqtt.client", "mariadb",
               "requests", "dotenv", "PIL"]
    missing = []
    for mod in modules:
        try:
            importlib.import_module(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        raise RuntimeError("missing: " + ", ".join(missing))


def ai_packages():
    """Optional: AI packages for posture detection."""
    importlib.import_module("ultralytics")
    importlib.import_module("cv2")


def interfaces():
    """I2C and SPI device files exist (enabled in raspi-config)."""
    missing = [d for d in ("/dev/i2c-1", "/dev/spidev0.0") if not os.path.exists(d)]
    if missing:
        raise RuntimeError("not found: " + ", ".join(missing) + " – enable I2C/SPI and reboot")


def i2c_devices():
    """Scan the I2C bus and list the addresses found (0x23 BH1750, 0x76/0x77 BMP280)."""
    import board
    import busio

    i2c = busio.I2C(board.SCL, board.SDA)
    while not i2c.try_lock():
        pass
    try:
        found = [hex(a) for a in i2c.scan()]
    finally:
        i2c.unlock()
        i2c.deinit()
    return "found: " + (", ".join(found) if found else "nothing (is anything connected yet?)")


def mqtt_broker():
    """Mosquitto listens on port 1883 on the network, not only on localhost."""
    with socket.create_connection(("localhost", 1883), timeout=2):
        pass
    conf = Path("/etc/mosquitto/conf.d/smartdesk.conf")
    if not conf.exists():
        raise RuntimeError("broker runs, but smartdesk.conf is missing – the Pico cannot connect")
    return f"Pico should connect to {_local_ip()}:1883"


def _local_ip():
    """Best-effort local IP address of the Pi (for the Pico's settings.toml)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "unknown"
    finally:
        s.close()


def env_file():
    """.env exists and the important values are filled in."""
    env = REPO_ROOT / ".env"
    if not env.exists():
        raise RuntimeError("no .env – run: cp .env.example .env")
    sys.path.insert(0, str(REPO_ROOT / "pi"))
    import config

    empty = [k for k in ("THINGSPEAK_CHANNEL_ID", "NTFY_TOPIC", "DB_PASSWORD")
             if not getattr(config, k)]
    return "still empty: " + ", ".join(empty) if empty else "complete"


def hardware_pwm():
    """The PWM overlay for GPIO12 is active."""
    cfg = Path("/boot/firmware/config.txt").read_text()
    if "dtoverlay=pwm,pin=12,func=4" not in cfg:
        raise RuntimeError("overlay missing in /boot/firmware/config.txt")


if __name__ == "__main__":
    print("Smart Desk – setup check\n")
    check("Python packages", python_packages)
    check("AI packages (optional)", ai_packages)
    check("I2C / SPI enabled", interfaces)
    check("Hardware PWM GPIO12", hardware_pwm)
    check("I2C scan", i2c_devices)
    check("Mosquitto broker", mqtt_broker)
    check(".env file", env_file)
    print(f"\n{sum(results)}/{len(results)} checks passed")

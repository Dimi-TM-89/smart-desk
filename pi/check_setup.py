"""
check_setup.py – Verifies that the Raspberry Pi is ready for the Smart Desk.

Run after scripts/setup_pi.sh and a reboot:
    source .venv/bin/activate
    python pi/check_setup.py

Each check prints OK or a hint about what to fix. Nothing is changed on the Pi.
"""

import importlib
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_TXT = Path("/boot/firmware/config.txt")
CMDLINE_TXT = Path("/boot/firmware/cmdline.txt")
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
    """I2C, SPI0 (MCP3008) and SPI1 (OLED) device files exist."""
    missing = [d for d in ("/dev/i2c-1", "/dev/spidev0.0", "/dev/spidev1.0")
               if not os.path.exists(d)]
    if missing:
        raise RuntimeError("not found: " + ", ".join(missing)
                           + " – run scripts/setup_pi.sh (I2C, SPI, dtoverlay=spi1-1cs) and reboot")


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


def database():
    """MariaDB runs and the smartdesk database with its tables exists (scripts/setup_db.sh)."""
    sys.path.insert(0, str(REPO_ROOT / "pi"))
    from database import Database

    db = Database()
    try:
        db.connect()
        counts = db.table_counts()
    except Exception as exc:  # noqa: BLE001 – show the connector's message
        raise RuntimeError(f"{exc} – run: bash scripts/setup_db.sh") from exc
    finally:
        db.close()
    return ", ".join(f"{t} {n} rows" for t, n in counts.items())


def serial_port_off():
    """GPIO14/15 are free for the HC-SR04: no UART and no serial console on them."""
    problems = []
    for line in CONFIG_TXT.read_text().splitlines():
        line = line.strip()
        if line in ("dtparam=uart0", "dtparam=uart0=on", "enable_uart=1"):
            problems.append(f"'{line}' in config.txt")
    if re.search(r"console=(serial0|ttyAMA0|ttyS0)\b", CMDLINE_TXT.read_text()):
        problems.append("serial console in cmdline.txt")
    if problems:
        raise RuntimeError(", ".join(problems)
                           + " – run scripts/setup_pi.sh again (or see README) and reboot")

    # The files are fine; after a fix the pins only change at the next reboot
    if shutil.which("pinctrl"):
        out = subprocess.run(["pinctrl", "get", "14,15"], capture_output=True, text=True).stdout
        if "TXD0" in out or "RXD0" in out:
            raise RuntimeError("config is fixed, but GPIO14/15 are still TXD0/RXD0 – reboot the Pi")
    return "GPIO14/15 free for the ultrasonic sensor"


def hardware_pwm():
    """GPIO12 is routed to the PWM block and the sysfs PWM channel is usable."""
    active_lines = [
        line.strip()
        for line in CONFIG_TXT.read_text().splitlines()
        if not line.lstrip().startswith("#")
    ]
    if "dtoverlay=pwm,pin=12,func=4" not in active_lines:
        raise RuntimeError("overlay missing in /boot/firmware/config.txt – "
                           "run scripts/setup_pi.sh again and reboot")

    sys.path.insert(0, str(REPO_ROOT / "pi"))
    from actuators.hw_pwm import find_pwm_chip

    chip = find_pwm_chip()          # raises with a hint when the overlay is not loaded
    if not os.access(chip / "export", os.W_OK):
        raise RuntimeError(f"no write access to {chip}/export – add the user to the gpio group")

    # After a fix in config.txt the pin only changes at the next reboot
    if shutil.which("pinctrl"):
        out = subprocess.run(["pinctrl", "get", "12"], capture_output=True, text=True).stdout
        if "PWM" not in out:
            raise RuntimeError(f"GPIO12 is not in PWM mode ({out.strip()}) – reboot the Pi")
    return f"{chip.name}, channel 0 on GPIO12"


if __name__ == "__main__":
    print("Smart Desk – setup check\n")
    if sys.prefix == sys.base_prefix:
        print("  WARNING: the virtual environment is not active.")
        print("           Run first:  source .venv/bin/activate\n")
    check("Python packages", python_packages)
    check("AI packages (optional)", ai_packages)
    check("I2C / SPI0 / SPI1 enabled", interfaces)
    check("Hardware PWM GPIO12", hardware_pwm)
    check("Serial port off (GPIO14/15)", serial_port_off)
    check("I2C scan", i2c_devices)
    check("Mosquitto broker", mqtt_broker)
    check(".env file", env_file)
    check("MariaDB database", database)
    print(f"\n{sum(results)}/{len(results)} checks passed")

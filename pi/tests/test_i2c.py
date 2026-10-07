"""
test_i2c.py – Test both I2C sensors: BH1750 (light) and BMP280 (temperature).

What it does:
    1. scans the I2C bus and lists every address that answers
    2. prints lux and temperature every second

Expected: addresses 0x23 (BH1750) and 0x76 or 0x77 (BMP280). Covering the
BH1750 lowers the lux; a finger on the BMP280 raises the temperature.

Run from the repository root:   python pi/tests/test_i2c.py
Stop with Ctrl+C.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from hardware import make_i2c  # noqa: E402
from sensors.light import LightSensor  # noqa: E402
from sensors.temperature import TemperatureSensor  # noqa: E402


def scan(i2c):
    """Return the list of I2C addresses that answer."""
    while not i2c.try_lock():
        pass
    try:
        return i2c.scan()
    finally:
        i2c.unlock()


def main():
    """Scan the bus, create both sensors and print their values until Ctrl+C."""
    i2c = make_i2c()
    found = scan(i2c)
    print("I2C scan:", ", ".join(hex(a) for a in found) or "nothing found")
    if not found:
        print("FAIL: check SDA=GPIO2, SCL=GPIO3, 3.3 V and GND, and that I2C is enabled.")
        return

    light = temp = None
    try:
        light = LightSensor(i2c, config.BH1750_ADDRESS)
        print(f"OK   BH1750 at {hex(config.BH1750_ADDRESS)}")
    except (ValueError, RuntimeError, OSError) as exc:
        print(f"FAIL BH1750 at {hex(config.BH1750_ADDRESS)}: {exc}")

    try:
        temp = TemperatureSensor(i2c, config.BMP280_ADDRESS)
        print(f"OK   BMP280 at {hex(temp.address)}")
        if temp.address != config.BMP280_ADDRESS:
            print(f"     -> set BMP280_ADDRESS = {hex(temp.address)} in pi/config.py")
    except RuntimeError as exc:
        print(f"FAIL BMP280: {exc}")

    if light is None and temp is None:
        return

    print("\nReading every second (Ctrl+C to stop):")
    try:
        while True:
            parts = []
            if light:
                parts.append(f"light {light.lux:7.1f} lx")
            if temp:
                parts.append(f"temp {temp.temperature:5.1f} °C  ({temp.pressure:6.1f} hPa)")
            print("  " + "   ".join(parts))
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        i2c.deinit()


if __name__ == "__main__":
    main()

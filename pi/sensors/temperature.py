"""
temperature.py – BMP280 temperature sensor on the I2C bus (room temperature).

The address depends on the board: 0x77 for the Adafruit board, 0x76 for most
other boards. If the address from config.py does not answer, the other one is
tried automatically, and the address that was found is stored in .address so
a test script can tell you to fix config.py.
"""

import adafruit_bmp280

POSSIBLE_ADDRESSES = (0x77, 0x76)


class TemperatureSensor:
    """Room temperature in °C (and air pressure as a bonus)."""

    def __init__(self, i2c, address):
        """Create the sensor, trying the configured address first."""
        candidates = [address] + [a for a in POSSIBLE_ADDRESSES if a != address]
        last_error = None
        for addr in candidates:
            try:
                self.sensor = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr)
                self.address = addr
                break
            except (ValueError, RuntimeError, OSError) as exc:
                last_error = exc
        else:
            raise RuntimeError(
                f"No BMP280 found at {', '.join(hex(a) for a in candidates)}"
            ) from last_error
        self.sensor.sea_level_pressure = 1013.25

    @property
    def temperature(self):
        """Current temperature in °C."""
        return self.sensor.temperature

    @property
    def pressure(self):
        """Current air pressure in hPa."""
        return self.sensor.pressure

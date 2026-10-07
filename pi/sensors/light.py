"""
light.py – BH1750 ambient light sensor on the I2C bus (desk light level).

Uses the Adafruit CircuitPython BH1750 library, which does the same as the
course example (command 0x10, 2 bytes back, divided by 1.2) for us.
Default address 0x23 (ADDR pin LOW or not connected).
"""

import adafruit_bh1750


class LightSensor:
    """Desk light level in lux."""

    def __init__(self, i2c, address):
        """Create the sensor on an existing I2C bus (see hardware.make_i2c)."""
        self.sensor = adafruit_bh1750.BH1750(i2c, address=address)

    @property
    def lux(self):
        """Current light level in lux."""
        return self.sensor.lux

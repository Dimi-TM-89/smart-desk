"""
adc.py – MCP3008 analog-to-digital converter on the SPI bus.

Reads the two analog inputs of the Smart Desk:
    CH0 – potentiometer: light threshold set by the user
    CH1 – LDR at the window (LDR to 3.3 V, 10 kΩ to GND: more light = higher value)

Uses the Adafruit MCP3xxx library. It sends the same 3 bytes as the course
example (start bit, single-ended + channel, don't care) and drives the
chip-select pin (GPIO24) itself. Raw MCP3008 values are 10 bit (0–1023);
the library scales them to 16 bit (0–65535), so we convert to 0–100 %.
"""

import digitalio
from adafruit_mcp3xxx.analog_in import AnalogIn
from adafruit_mcp3xxx.mcp3008 import MCP3008

from hardware import board_pin


class AnalogInputs:
    """Potentiometer and window LDR on the MCP3008."""

    def __init__(self, spi, cs_gpio, pot_channel, ldr_channel):
        """Create the ADC on an existing SPI bus (see hardware.make_spi)."""
        self.cs = digitalio.DigitalInOut(board_pin(cs_gpio))
        self.mcp = MCP3008(spi, self.cs)
        self.pot = AnalogIn(self.mcp, pot_channel)
        self.ldr = AnalogIn(self.mcp, ldr_channel)

    @staticmethod
    def _percent(channel):
        """Value of a channel as 0–100 %."""
        return channel.value * 100 / 65535

    @property
    def pot_percent(self):
        """Potentiometer position, 0–100 %."""
        return self._percent(self.pot)

    @property
    def window_percent(self):
        """Window light level, 0 (dark) – 100 % (bright)."""
        return self._percent(self.ldr)

    @staticmethod
    def raw10(channel):
        """Raw 10-bit value (0–1023) as in the course, handy for debugging."""
        return channel.value >> 6

    def deinit(self):
        """Release the chip-select pin."""
        self.cs.deinit()

"""
hardware.py – Small helpers to create the shared hardware buses.

The I2C bus (BH1750 + BMP280) and the SPI bus (MCP3008 + OLED) are shared by
several devices. Create each bus ONCE in a program and pass it to every class
that needs it, instead of letting every class open its own bus.

Pin numbers come from config.py (BCM numbering); board_pin() turns such a
number into the Blinka pin object, e.g. board_pin(12) -> board.D12.
"""

import board
import busio


def board_pin(gpio):
    """Return the Blinka pin object for a BCM GPIO number (12 -> board.D12)."""
    try:
        return getattr(board, f"D{gpio}")
    except AttributeError as exc:
        raise ValueError(f"GPIO{gpio} does not exist on this board") from exc


def make_i2c():
    """Create the I2C bus on GPIO2 (SDA) / GPIO3 (SCL)."""
    return busio.I2C(board.SCL, board.SDA)


def make_spi():
    """Create the SPI0 bus on GPIO11 (SCLK) / GPIO10 (MOSI) / GPIO9 (MISO).

    The chip-select lines are plain GPIOs (MCP3008 on GPIO24, OLED on GPIO5),
    driven by the device classes themselves, as in the course (lesson 6).
    """
    return busio.SPI(board.SCLK, MOSI=board.MOSI, MISO=board.MISO)

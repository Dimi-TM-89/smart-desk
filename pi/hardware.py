"""
hardware.py – Small helpers to create the shared hardware buses.

Buses of the Smart Desk:
    I2C   – BH1750 + BMP280 (shared)
    SPI0  – MCP3008
    SPI1  – OLED (the module has no CS pin, so it gets a bus of its own)
Create each bus ONCE in a program and pass it to every class that needs it,
instead of letting every class open its own bus.

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
    """Create the SPI0 bus on GPIO11 (SCLK) / GPIO10 (MOSI) / GPIO9 (MISO) – MCP3008.

    The chip-select line is a plain GPIO (GPIO24), driven by the device class
    itself, as in the course (lesson 6).
    """
    return busio.SPI(board.SCLK, MOSI=board.MOSI, MISO=board.MISO)


def make_spi1():
    """Create the SPI1 bus on GPIO21 (SCLK) / GPIO20 (MOSI) – OLED only.

    Needs dtoverlay=spi1-1cs in /boot/firmware/config.txt (setup_pi.sh adds it).
    Our OLED has no CS pin, so it cannot share SPI0 with the MCP3008
    (course lesson 6, "OLED SPI SSD1306 without CS"). Only clock and data are
    used; the display never sends anything back.
    """
    return busio.SPI(board_pin(21), MOSI=board_pin(20))   # SCLK1, MOSI1

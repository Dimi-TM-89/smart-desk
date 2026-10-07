"""
oled.py – SSD1306 128×64 OLED on the SPI bus (local dashboard).

Drawing is done on a PIL image in memory, which is then sent to the display
in one go (as in the course, lesson 6). The OLED shares the SPI bus with the
MCP3008; each device has its own chip-select pin (OLED: GPIO5).

If your OLED module has NO CS pin, it reacts to every SPI transfer, including
the ones meant for the MCP3008, and shows garbage. The fix from the course is
to put the OLED on the separate SPI1 bus (GPIO 19/20/21) – but those pins are
used by the RGB LED and the ultrasonic sensor in our pin plan. Check this with
test_oled.py --with-adc before the wiring is final.
"""

import adafruit_ssd1306
import digitalio
from PIL import Image, ImageDraw, ImageFont

from hardware import board_pin


class Oled:
    """Text display: show up to ~5 lines of text."""

    def __init__(self, spi, cs_gpio, dc_gpio, rst_gpio, width=128, height=64):
        """Create the display on an existing SPI bus and clear it."""
        self.cs = digitalio.DigitalInOut(board_pin(cs_gpio))
        self.dc = digitalio.DigitalInOut(board_pin(dc_gpio))
        self.rst = digitalio.DigitalInOut(board_pin(rst_gpio))
        self.display = adafruit_ssd1306.SSD1306_SPI(width, height, spi, self.dc, self.rst, self.cs)
        self.width = width
        self.height = height
        self.font = ImageFont.load_default()
        bbox = self.font.getbbox("Ag")
        self.line_height = bbox[3] - bbox[1] + 3
        self.clear()

    def new_canvas(self):
        """Return (image, draw) for custom drawing; show it with show_image()."""
        image = Image.new("1", (self.width, self.height))
        return image, ImageDraw.Draw(image)

    def show_image(self, image):
        """Send a PIL image (mode "1", display size) to the display."""
        self.display.image(image)
        self.display.show()

    def show_lines(self, lines):
        """Show a list of text lines, top to bottom. Lines that do not fit are dropped."""
        image, draw = self.new_canvas()
        y = 0
        for line in lines:
            if y + self.line_height > self.height + 2:
                break
            draw.text((0, y), str(line), font=self.font, fill=255)
            y += self.line_height
        self.show_image(image)

    def clear(self):
        """Make the display black."""
        self.display.fill(0)
        self.display.show()

    def deinit(self):
        """Clear the display and release the pins."""
        self.clear()
        for pin in (self.cs, self.dc, self.rst):
            pin.deinit()

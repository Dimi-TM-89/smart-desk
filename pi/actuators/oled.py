"""
oled.py – SSD1306 128×64 OLED on SPI1 (local dashboard).

Drawing is done on a PIL image in memory, which is then sent to the display
in one go (as in the course, lesson 6).

Our module has 6 pins: GND VCC SCL SDA RES DC – and NO CS pin. Despite the
names, SCL/SDA are SPI clock/data, not I2C. Without CS the display listens to
every transfer on its bus, so it cannot share SPI0 with the MCP3008. It gets
the SPI1 bus (GPIO21 clock, GPIO20 data) on its own, as in the course
("OLED SPI SSD1306 without CS"). Pass cs_gpio=None for such a module.
"""

import adafruit_ssd1306
import digitalio
from PIL import Image, ImageDraw, ImageFont

from hardware import board_pin


class Oled:
    """Text display: show up to ~5 lines of text."""

    def __init__(self, spi, cs_gpio, dc_gpio, rst_gpio, width=128, height=64):
        """Create the display on an existing SPI bus and clear it.

        cs_gpio is None for a module without a CS pin (ours).
        """
        self.cs = digitalio.DigitalInOut(board_pin(cs_gpio)) if cs_gpio is not None else None
        self.dc = digitalio.DigitalInOut(board_pin(dc_gpio))
        self.rst = digitalio.DigitalInOut(board_pin(rst_gpio))
        # cs may be None: the library's SPIDevice supports that, its type hint does not
        self.display = adafruit_ssd1306.SSD1306_SPI(
            width, height, spi, self.dc, self.rst, self.cs  # pyright: ignore[reportArgumentType]
        )
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
            if pin is not None:
                pin.deinit()

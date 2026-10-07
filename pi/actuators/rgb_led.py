"""
rgb_led.py – RGB posture LED (common cathode) on three digital outputs.

Common cathode: the long leg goes to GND, each colour pin gets a 220 Ω
resistor to its GPIO. A GPIO HIGH switches that colour on.

Colours used by the Smart Desk: green = good posture, red = bad posture,
blue = no person in view, off = standby.
"""

import digitalio

from hardware import board_pin

COLOURS = {
    "off": (False, False, False),
    "red": (True, False, False),
    "green": (False, True, False),
    "blue": (False, False, True),
    "yellow": (True, True, False),
    "cyan": (False, True, True),
    "magenta": (True, False, True),
    "white": (True, True, True),
}


class RgbLed:
    """Three-colour LED that shows one named colour at a time."""

    def __init__(self, red_gpio, green_gpio, blue_gpio):
        """Set up the three pins as outputs, LED off."""
        self.pins = []
        for gpio in (red_gpio, green_gpio, blue_gpio):
            pin = digitalio.DigitalInOut(board_pin(gpio))
            pin.switch_to_output(value=False)
            self.pins.append(pin)
        self.colour = "off"

    def set(self, colour):
        """Show a colour by name, e.g. "green" (see COLOURS)."""
        if colour not in COLOURS:
            raise ValueError(f"unknown colour {colour!r}, use one of {', '.join(COLOURS)}")
        for pin, on in zip(self.pins, COLOURS[colour]):
            pin.value = on
        self.colour = colour

    def off(self):
        """Switch all colours off."""
        self.set("off")

    def deinit(self):
        """Switch off and release the pins."""
        self.off()
        for pin in self.pins:
            pin.deinit()

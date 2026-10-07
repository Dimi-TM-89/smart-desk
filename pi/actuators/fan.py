"""
fan.py – Fan switched by a relay board (digital output, active LOW).

The relay board from the kit is active LOW (course lesson 3):
    GPIO LOW  (0 V)   -> relay ON  -> fan runs
    GPIO HIGH (3.3 V) -> relay OFF -> fan stops
The pin is therefore set HIGH at startup, so the fan does not switch on for a
moment while the program starts.

Only the relay input is connected to the Pi. The fan gets its own supply
through the relay contact (COM -> NO).
"""

import digitalio

from hardware import board_pin


class Fan:
    """Fan on/off via an active-low relay."""

    def __init__(self, gpio):
        """Set up the relay pin, fan off."""
        self.pin = digitalio.DigitalInOut(board_pin(gpio))
        self.pin.switch_to_output(value=True)   # HIGH = relay off
        self.is_on = False

    def set(self, on):
        """Switch the fan on (True) or off (False)."""
        self.pin.value = not on                 # active LOW
        self.is_on = bool(on)

    def on(self):
        """Switch the fan on."""
        self.set(True)

    def off(self):
        """Switch the fan off."""
        self.set(False)

    def toggle(self):
        """Switch the fan to the other state (used by the fan button)."""
        self.set(not self.is_on)

    def deinit(self):
        """Switch off and release the pin."""
        self.off()
        self.pin.deinit()

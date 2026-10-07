"""
button.py – Push button to GND with the internal pull-up (digital input).

Not pressed: input HIGH (pull-up). Pressed: input LOW (connected to GND).
was_pressed() reports each press only once and ignores contact bounce, so the
main loop can simply poll it.
"""

import time

import digitalio

from hardware import board_pin

DEBOUNCE_S = 0.05


class Button:
    """Debounced push button with press detection."""

    def __init__(self, gpio):
        """Set up the pin as input with the internal pull-up."""
        self.pin = digitalio.DigitalInOut(board_pin(gpio))
        self.pin.switch_to_input(pull=digitalio.Pull.UP)
        self._candidate = self.is_pressed
        self._last_change = time.monotonic()
        self._reported = self._candidate

    @property
    def is_pressed(self):
        """Raw state: True while the button is held down."""
        return not self.pin.value

    def was_pressed(self):
        """True once for every new press (debounced). Call it often."""
        now = time.monotonic()
        raw = self.is_pressed
        if raw != self._candidate:
            self._candidate = raw
            self._last_change = now
        if now - self._last_change >= DEBOUNCE_S and self._candidate != self._reported:
            self._reported = self._candidate
            return self._candidate  # only the press counts, not the release
        return False

    def deinit(self):
        """Release the GPIO pin."""
        self.pin.deinit()

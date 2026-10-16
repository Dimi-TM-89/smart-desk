"""
lamp.py – Dimmable LED desk lamp on hardware PWM (GPIO12).

The pin must not be claimed by the kernel PWM overlay. Blinka's pwmio uses
the Pi's hardware PWM through lgpio and claims the GPIO itself.

Our eyes do not see brightness linearly: 50 % duty cycle looks almost as
bright as 100 %. A gamma correction makes 50 % *look* like half brightness.
"""

import pwmio

from hardware import board_pin

PWM_FREQUENCY = 1000   # Hz, high enough to avoid visible flicker
GAMMA = 2.2


class Lamp:
    """Desk lamp with brightness in percent."""

    def __init__(self, gpio):
        """Start hardware PWM through Blinka with the lamp off."""
        self.pwm = pwmio.PWMOut(board_pin(gpio), frequency=PWM_FREQUENCY, duty_cycle=0)
        self.percent = 0.0

    def set(self, percent):
        """Set the brightness, 0 (off) – 100 % (full)."""
        percent = max(0.0, min(100.0, float(percent)))
        self.pwm.duty_cycle = int(((percent / 100) ** GAMMA) * 65535)
        self.percent = percent

    def off(self):
        """Switch the lamp off."""
        self.set(0)

    def deinit(self):
        """Switch off and release the PWM channel."""
        self.off()
        self.pwm.deinit()

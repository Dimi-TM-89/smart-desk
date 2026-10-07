"""
lamp.py – Dimmable LED desk lamp on hardware PWM (GPIO12).

Hardware PWM must be enabled with the overlay dtoverlay=pwm,pin=12,func=4 in
/boot/firmware/config.txt (scripts/setup_pi.sh does this). As in the course,
pwmio uses a 16-bit duty cycle (0–65535).

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
        """Start the hardware PWM output with the lamp off."""
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

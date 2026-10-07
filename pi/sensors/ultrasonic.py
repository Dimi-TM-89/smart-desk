"""
ultrasonic.py – HC-SR04 ultrasonic distance sensor (digital in/out).

Works as in the course (lesson 3): a 10 µs pulse on TRIG starts a measurement,
the length of the HIGH pulse on ECHO is the time the sound needs to travel to
the object and back. distance (cm) = time (s) × 34300 / 2 = time × 17150.

Wiring: the 5 V HC-SR04 returns a 5 V ECHO signal. Use a voltage divider
(1 kΩ / 2 kΩ) between ECHO and the GPIO, otherwise the Pi can be damaged.
"""

import statistics
import time

import digitalio

from hardware import board_pin

SPEED_OF_SOUND_HALF = 17150   # cm/s, (343 m/s) / 2 for the way back and forth
ECHO_TIMEOUT_S = 0.03         # ~5 m range; longer = no echo (nothing in range)


class Ultrasonic:
    """HC-SR04 on two GPIO pins, with a baseline for presence detection."""

    def __init__(self, trig_gpio, echo_gpio):
        """Set up TRIG as output (LOW) and ECHO as input."""
        self.trig = digitalio.DigitalInOut(board_pin(trig_gpio))
        self.trig.switch_to_output(value=False)
        self.echo = digitalio.DigitalInOut(board_pin(echo_gpio))
        self.echo.switch_to_input()
        self.baseline_cm = None
        time.sleep(0.05)  # let the sensor settle after TRIG goes LOW

    def measure_once(self):
        """Do one measurement. Returns the distance in cm, or None on timeout."""
        # 10 µs trigger pulse
        self.trig.value = True
        time.sleep(0.00001)
        self.trig.value = False

        # Wait for the echo pulse to start ...
        deadline = time.perf_counter() + ECHO_TIMEOUT_S
        while not self.echo.value:
            if time.perf_counter() > deadline:
                return None
        start = time.perf_counter()

        # ... and to end
        deadline = start + ECHO_TIMEOUT_S
        while self.echo.value:
            if time.perf_counter() > deadline:
                return None
        stop = time.perf_counter()

        return (stop - start) * SPEED_OF_SOUND_HALF

    def distance_cm(self, samples=5):
        """Median of a few measurements (filters single bad echoes). None if all failed."""
        values = []
        for _ in range(samples):
            d = self.measure_once()
            if d is not None:
                values.append(d)
            time.sleep(0.06)  # HC-SR04 needs ~60 ms between measurements
        return statistics.median(values) if values else None

    def calibrate(self, samples=15):
        """Measure the empty scene (e.g. the wall of the scale model) as baseline."""
        self.baseline_cm = self.distance_cm(samples)
        return self.baseline_cm

    def someone_present(self, drop_cm):
        """True when the distance is clearly shorter than the baseline.

        drop_cm is Limits.PRESENCE_DROP_CM from config.py. Call calibrate()
        first; without a baseline this always returns False.
        """
        if self.baseline_cm is None:
            return False
        d = self.distance_cm()
        return d is not None and d < self.baseline_cm - drop_cm

    def deinit(self):
        """Release the GPIO pins."""
        self.trig.deinit()
        self.echo.deinit()

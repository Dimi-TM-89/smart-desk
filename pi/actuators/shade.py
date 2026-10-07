"""
shade.py – Sunshade driven by a 28BYJ-48 stepper motor via a ULN2003 driver.

The motor is driven in half-step mode: 8 coil patterns per cycle, 4096 half
steps for one full turn of the output shaft. Limits.SHADE_STEPS (2048) is the
number of half steps from fully open to fully closed (half a turn).

The ULN2003 board needs its own 5 V supply (Pi 5 V pin is fine with the 27 W
power supply); IN1–IN4 go to the GPIOs from config.py.

Position: the class remembers where the shade is. At startup it assumes the
shade is fully OPEN, so put it in that position before starting a program
(test_stepper.py has a jog option for that).

move_to() blocks until the movement is finished (about 3 s for a full
open/close). In desk_controller.py run it in a separate thread.
"""

import time

import digitalio

from hardware import board_pin

# Half-step sequence IN1..IN4 (one or two coils on at a time)
HALF_STEP_SEQUENCE = (
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (0, 1, 0, 0),
    (0, 1, 1, 0),
    (0, 0, 1, 0),
    (0, 0, 1, 1),
    (0, 0, 0, 1),
    (1, 0, 0, 1),
)
STEP_DELAY_S = 0.0012   # shorter = faster, but below ~1 ms the motor starts to skip


class Shade:
    """Sunshade position 0 % (open) – 100 % (closed)."""

    def __init__(self, gpios, full_steps, reverse=False):
        """Set up the 4 coil pins (all off).

        gpios      -- tuple (IN1, IN2, IN3, IN4) from config.Pins.STEPPER
        full_steps -- half steps from open to closed (config.Limits.SHADE_STEPS)
        reverse    -- True if the shade moves the wrong way
        """
        self.coils = []
        for gpio in gpios:
            pin = digitalio.DigitalInOut(board_pin(gpio))
            pin.switch_to_output(value=False)
            self.coils.append(pin)
        self.full_steps = full_steps
        self.direction = -1 if reverse else 1
        self.position = 0          # in half steps, 0 = open
        self._phase = 0            # index in HALF_STEP_SEQUENCE

    @property
    def percent(self):
        """Current position, 0 % (open) – 100 % (closed)."""
        return self.position * 100 / self.full_steps

    def step(self, count):
        """Move a number of half steps: positive = closing, negative = opening.

        Does not check the limits – used by move_to() and to jog the shade
        into its start position.
        """
        sign = 1 if count > 0 else -1
        for _ in range(abs(count)):
            self._phase = (self._phase + sign * self.direction) % len(HALF_STEP_SEQUENCE)
            for pin, on in zip(self.coils, HALF_STEP_SEQUENCE[self._phase]):
                pin.value = bool(on)
            self.position += sign
            time.sleep(STEP_DELAY_S)
        self.release()

    def move_to(self, percent):
        """Move to a position 0 % (open) – 100 % (closed). Blocks until done."""
        percent = max(0.0, min(100.0, float(percent)))
        target = round(percent * self.full_steps / 100)
        if target != self.position:
            self.step(target - self.position)

    def open(self):
        """Fully open the shade."""
        self.move_to(0)

    def close(self):
        """Fully close the shade."""
        self.move_to(100)

    def release(self):
        """Switch all coils off (the motor would get hot when it holds its position)."""
        for pin in self.coils:
            pin.value = False

    def deinit(self):
        """Release the coils and the pins."""
        self.release()
        for pin in self.coils:
            pin.deinit()

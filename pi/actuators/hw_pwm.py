"""
hw_pwm.py – Real hardware PWM on the Raspberry Pi 5 through the kernel (sysfs).

Why not pwmio?
    On the Pi 5, Blinka's pwmio.PWMOut uses lgpio.tx_pwm(): that is PWM timed
    by software (a thread toggles the pin). For true hardware PWM the PWM
    block of the RP1 chip has to generate the signal itself. Linux exposes that
    block in /sys/class/pwm once the overlay is enabled (course lesson 5,
    "Hardware PWM on Pi"):

        dtoverlay=pwm,pin=12,func=4      (in /boot/firmware/config.txt)

    The overlay hands GPIO12 to the PWM block, so lgpio/Blinka can no longer
    claim that pin – that is expected: from now on the hardware drives it.

How sysfs PWM works (everything is a file):
    /sys/class/pwm/pwmchipN/export          write the channel number to create pwmX/
    /sys/class/pwm/pwmchipN/pwmX/period      period in nanoseconds (1 kHz = 1 000 000)
    /sys/class/pwm/pwmchipN/pwmX/duty_cycle  high time in nanoseconds (<= period)
    /sys/class/pwm/pwmchipN/pwmX/enable      1 = output on, 0 = off

Pi 5 channel per pin (RP1 PWM0): GPIO12 -> 0, GPIO13 -> 1, GPIO18 -> 2,
GPIO19 -> 3. The chip number differs between kernel versions (pwmchip2 on
early Bookworm kernels, pwmchip0 on newer ones), so it is detected
automatically: the RP1 PWM block is the chip with 4 channels.

To stay close to the course code, duty_cycle is a 16-bit value (0–65535),
exactly like pwmio.PWMOut.
"""

import errno
import time
from pathlib import Path

SYSFS_PWM = Path("/sys/class/pwm")
RP1_PWM_ADDRESS = "1f00098000"      # RP1 PWM0 block, part of the chip's device path
CHANNEL_FOR_GPIO = {12: 0, 13: 1, 18: 2, 19: 3}


def find_pwm_chip(root=SYSFS_PWM):
    """Return the pwmchip directory of the RP1 PWM block.

    Preference: the chip whose device path contains the RP1 PWM0 address,
    otherwise the first chip with 4 channels.
    """
    chips = sorted(root.glob("pwmchip*"))
    if not chips:
        raise RuntimeError(
            f"no pwmchip in {root} – add dtoverlay=pwm,pin=12,func=4 to "
            "/boot/firmware/config.txt and reboot"
        )
    for chip in chips:
        device = chip / "device"
        if device.exists() and RP1_PWM_ADDRESS in str(device.resolve()):
            return chip
    for chip in chips:
        if (chip / "npwm").read_text().strip() == "4":
            return chip
    raise RuntimeError(f"no 4-channel PWM chip found among {[c.name for c in chips]}")


class HardwarePWM:
    """One hardware PWM channel, with the same duty_cycle scale as pwmio (0–65535)."""

    def __init__(self, gpio, frequency=1000, duty_cycle=0, chip=None, root=SYSFS_PWM):
        """Export the channel for this GPIO and start it with the given duty cycle."""
        if gpio not in CHANNEL_FOR_GPIO:
            raise ValueError(f"GPIO{gpio} has no hardware PWM channel "
                             f"(use one of {sorted(CHANNEL_FOR_GPIO)})")
        self.gpio = gpio
        self.channel = CHANNEL_FOR_GPIO[gpio]
        self.chip = Path(chip) if chip else find_pwm_chip(Path(root))
        self.path = self.chip / f"pwm{self.channel}"
        self._period_ns = 0
        self._duty = 0

        self._export()
        self._write("enable", 0)          # start from a known state
        self._write("duty_cycle", 0)      # duty must never be larger than the period
        self.frequency = frequency
        self.duty_cycle = duty_cycle
        self._write("enable", 1)

    # --- sysfs helpers -----------------------------------------------------

    def _export(self):
        """Create pwmX/. If it already exists (e.g. after a crash), reuse it."""
        if not self.path.exists():
            try:
                (self.chip / "export").write_text(str(self.channel))
            except OSError as exc:
                if exc.errno != errno.EBUSY:      # EBUSY = already exported
                    raise
        # udev needs a moment to create pwmX/ and give the gpio group access
        for _ in range(50):
            try:
                (self.path / "period").read_text()
                return
            except (FileNotFoundError, PermissionError):
                time.sleep(0.02)
        raise RuntimeError(f"{self.path} did not appear or is not accessible "
                           "(is the user in the gpio group?)")

    def _write(self, name, value):
        """Write one sysfs attribute; retry briefly while udev fixes permissions."""
        for attempt in range(50):
            try:
                (self.path / name).write_text(str(int(value)))
                return
            except PermissionError:
                if attempt == 49:
                    raise
                time.sleep(0.02)

    # --- pwmio-compatible properties --------------------------------------

    @property
    def frequency(self):
        """PWM frequency in Hz."""
        return 1_000_000_000 / self._period_ns

    @frequency.setter
    def frequency(self, hz):
        period_ns = int(1_000_000_000 / hz)
        new_duty_ns = self._duty * period_ns // 65535
        if period_ns < self._period_ns:
            # shrinking: lower the duty first so that duty <= period stays true
            self._write("duty_cycle", new_duty_ns)
            self._write("period", period_ns)
        else:
            self._write("period", period_ns)
            self._write("duty_cycle", new_duty_ns)
        self._period_ns = period_ns

    @property
    def duty_cycle(self):
        """Duty cycle as a 16-bit value: 0 = always low, 65535 = always high."""
        return self._duty

    @duty_cycle.setter
    def duty_cycle(self, value):
        value = max(0, min(65535, int(value)))
        self._write("duty_cycle", value * self._period_ns // 65535)
        self._duty = value

    def deinit(self):
        """Switch the output off and hand the channel back to the kernel."""
        try:
            self._write("enable", 0)
            (self.chip / "unexport").write_text(str(self.channel))
        except OSError:
            pass   # already released

    def __str__(self):
        return (f"hardware PWM {self.chip.name}/pwm{self.channel} on GPIO{self.gpio}, "
                f"{self.frequency:.0f} Hz")

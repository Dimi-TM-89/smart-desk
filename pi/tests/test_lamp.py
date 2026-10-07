"""
test_lamp.py – Test the PWM desk lamp on GPIO12 (hardware PWM).

What it does: fades the lamp up and down a few times, then lets you type a
brightness (0–100) to set it yourself.

Expected: smooth fading without flicker.
If creating the PWM output fails: check that /boot/firmware/config.txt
contains  dtoverlay=pwm,pin=12,func=4  and that you rebooted
(python pi/check_setup.py checks this too). `ls /sys/class/pwm/` should
show a pwmchip.

Run from the repository root:   python pi/tests/test_lamp.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from actuators.lamp import Lamp  # noqa: E402


def main():
    """Fade the lamp, then accept brightness values from the keyboard."""
    print(f"Desk lamp on GPIO{config.Pins.LAMP_PWM} (hardware PWM)")
    try:
        lamp = Lamp(config.Pins.LAMP_PWM)
    except Exception as exc:  # noqa: BLE001 – show the hint for every failure
        print(f"FAIL: could not start PWM: {exc}")
        print("  -> is dtoverlay=pwm,pin=12,func=4 in /boot/firmware/config.txt? Reboot after adding.")
        return

    try:
        print("Fading 3 times ...")
        for _ in range(3):
            for p in range(0, 101, 2):
                lamp.set(p)
                time.sleep(0.02)
            for p in range(100, -1, -2):
                lamp.set(p)
                time.sleep(0.02)

        print("Type a brightness 0–100 and Enter (q to quit):")
        while True:
            answer = input("  brightness> ").strip()
            if answer.lower() in ("q", "quit", ""):
                break
            try:
                lamp.set(float(answer))
                print(f"  lamp at {lamp.percent:.0f} %")
            except ValueError:
                print("  type a number")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        lamp.deinit()


if __name__ == "__main__":
    main()

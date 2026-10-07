"""
test_rgb.py – Test the RGB posture LED (R=GPIO13, G=GPIO19, B=GPIO26).

What it does: shows red, green and blue for 1 s each (twice), then lets
you type a colour name.

Expected: the colours appear in the order red -> green -> blue.
    Wrong colour  -> two colour wires are swapped.
    Nothing at all -> the LED is common ANODE, or the long leg is not on GND.

Run from the repository root:   python pi/tests/test_rgb.py
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from actuators.rgb_led import COLOURS, RgbLed  # noqa: E402


def main():
    """Cycle the colours, then accept colour names from the keyboard."""
    p = config.Pins
    print(f"RGB LED on R=GPIO{p.RGB_RED}, G=GPIO{p.RGB_GREEN}, B=GPIO{p.RGB_BLUE}")
    led = RgbLed(p.RGB_RED, p.RGB_GREEN, p.RGB_BLUE)
    try:
        for _ in range(2):
            for colour in ("red", "green", "blue"):
                print(f"  {colour}")
                led.set(colour)
                time.sleep(1)
        led.off()

        print(f"Type a colour ({', '.join(COLOURS)}), q to quit:")
        while True:
            answer = input("  colour> ").strip().lower()
            if answer in ("q", "quit", ""):
                break
            try:
                led.set(answer)
            except ValueError as exc:
                print(f"  {exc}")
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        led.deinit()


if __name__ == "__main__":
    main()

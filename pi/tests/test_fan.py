"""
test_fan.py – Test the fan relay (GPIO16, active LOW) and the fan button (GPIO25).

What it does:
    1. switches the relay on and off 3 times (you hear it click)
    2. then every press on the fan button toggles the fan

Expected: the relay LED and click follow the messages on screen.

Problem: the relay stays ON (LED on) even when the program says OFF.
    Some 5 V relay boards do not switch off at 3.3 V logic. Fix: remove the
    JD-VCC jumper, feed JD-VCC with 5 V and VCC with 3.3 V (VCC is the input
    side of the opto-coupler). Ask the hardware lead.

Run from the repository root:   python pi/tests/test_fan.py
Stop with Ctrl+C.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from actuators.fan import Fan  # noqa: E402
from sensors.button import Button  # noqa: E402


def main():
    """Click the relay a few times, then toggle it with the button until Ctrl+C."""
    p = config.Pins
    print(f"Fan relay on GPIO{p.FAN_RELAY} (active LOW), button on GPIO{p.FAN_BUTTON}\n")
    fan = Fan(p.FAN_RELAY)
    button = Button(p.FAN_BUTTON)
    try:
        for _ in range(3):
            fan.on()
            print("  relay ON  (fan should run)")
            time.sleep(1.5)
            fan.off()
            print("  relay OFF (fan should stop)")
            time.sleep(1.5)

        print("\nNow press the fan button to toggle the fan (Ctrl+C to stop).")
        while True:
            if button.was_pressed():
                fan.toggle()
                print(f"  button pressed -> fan {'ON' if fan.is_on else 'OFF'}")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        fan.deinit()
        button.deinit()


if __name__ == "__main__":
    main()

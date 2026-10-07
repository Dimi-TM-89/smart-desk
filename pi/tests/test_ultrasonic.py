"""
test_ultrasonic.py – Test the HC-SR04 ultrasonic sensor (TRIG GPIO20, ECHO GPIO21).

What it does:
    1. measures the empty scene for a baseline (keep your hand away!)
    2. prints the distance twice per second and "PRESENT" when something is
       clearly closer than the baseline (Limits.PRESENCE_DROP_CM)

Expected: a stable distance to the wall; moving your hand in front of the
sensor lowers the distance and shows PRESENT.

Run from the repository root:   python pi/tests/test_ultrasonic.py
Stop with Ctrl+C.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from sensors.ultrasonic import Ultrasonic  # noqa: E402


def main():
    """Calibrate, then show distance and presence until Ctrl+C."""
    print(f"HC-SR04 on TRIG=GPIO{config.Pins.US_TRIG}, ECHO=GPIO{config.Pins.US_ECHO}")
    print("Reminder: 5 V sensor -> voltage divider (1k/2k) on ECHO!\n")
    sensor = Ultrasonic(config.Pins.US_TRIG, config.Pins.US_ECHO)
    try:
        print("Calibrating baseline, keep the area in front of the sensor empty ...")
        baseline = sensor.calibrate()
        if baseline is None:
            print("FAIL: no echo at all.")
            print("  - check TRIG/ECHO are not swapped and the sensor has 5 V and GND")
            print("  - check the voltage divider on ECHO (GND side of the divider!)")
            return
        print(f"Baseline: {baseline:.1f} cm (presence below "
              f"{baseline - config.Limits.PRESENCE_DROP_CM:.1f} cm)\n")

        while True:
            d = sensor.distance_cm()
            if d is None:
                print("  no echo (out of range or wiring problem)")
            else:
                present = d < baseline - config.Limits.PRESENCE_DROP_CM
                print(f"  {d:6.1f} cm   {'PRESENT' if present else '-'}")
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        sensor.deinit()


if __name__ == "__main__":
    main()

"""
test_stepper.py – Test the sunshade stepper (28BYJ-48 + ULN2003 on GPIO 17/27/22/23).

    python pi/tests/test_stepper.py            close, wait, open (full movement)
    python pi/tests/test_stepper.py --jog 200  move 200 half steps (negative = other way)
    python pi/tests/test_stepper.py --reverse  same test with the direction reversed
    python pi/tests/test_stepper.py --button   shade buttons (up GPIO8, down GPIO7) +
                                               shade thread: up opens, down closes,
                                               also while the shade is still moving

Use --jog to put the shade in its OPEN start position: every program assumes
the shade is open when it starts.

Expected: the 4 LEDs on the ULN2003 board blink in sequence and the motor turns
half a turn (Limits.SHADE_STEPS half steps) one way, then back.
    Motor only buzzes / shakes -> IN1–IN4 wires are in the wrong order.
    Shade moves the wrong way  -> try --reverse; if that is right, the
                                  controller must create Shade(..., reverse=True).
    Nothing at all             -> the ULN2003 board needs 5 V and GND.
    --button: "GPIO busy"      -> dtoverlay=spi0-0cs is missing, or no reboot yet
                                  (scripts/setup_pi.sh, python pi/check_setup.py).
    --button: up closes        -> the buttons are swapped: swap SHADE_UP_BUTTON
                                  and SHADE_DOWN_BUTTON in config.py.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from actuators.shade import Shade  # noqa: E402
from actuators.shade_mover import ShadeMover  # noqa: E402
from sensors.button import Button  # noqa: E402


def button_test(shade):
    """Open/close the shade with the two buttons; the main thread keeps printing the position.

    The printing goes on WHILE the motor turns: that is the shade thread at work.
    """
    up_gpio, down_gpio = config.Pins.SHADE_UP_BUTTON, config.Pins.SHADE_DOWN_BUTTON
    print(f"Shade buttons: up on GPIO{up_gpio} opens, down on GPIO{down_gpio} closes (Ctrl+C to stop).")
    up = Button(up_gpio)
    down = Button(down_gpio)
    mover = ShadeMover(shade)
    last_print = 0
    try:
        while True:
            for button, target, name in ((up, 0, "up"), (down, 100, "down")):
                if button.was_pressed():
                    if mover.target == target:
                        print(f"  {name} button -> already {'closed' if target else 'open'} (or on its way)")
                    else:
                        mover.move_to(target)
                        print(f"  {name} button -> {'closing' if target else 'opening'}")
            now = time.monotonic()
            if mover.moving and now - last_print >= 0.25:
                last_print = now
                print(f"    main thread still running: shade at {mover.percent:3.0f} %")
            time.sleep(0.01)
    except KeyboardInterrupt:
        print("\nOpening the shade ...")
    finally:
        mover.stop(park=True)
        up.deinit()
        down.deinit()


def main():
    """Do a full close/open, or jog a given number of half steps."""
    reverse = "--reverse" in sys.argv
    print(f"Stepper on GPIO {config.Pins.STEPPER}, {config.Limits.SHADE_STEPS} half steps "
          f"open -> closed{', REVERSED' if reverse else ''}")
    shade = Shade(config.Pins.STEPPER, config.Limits.SHADE_STEPS,
                  reverse=reverse or config.Pins.STEPPER_REVERSE)
    try:
        if "--button" in sys.argv:
            button_test(shade)
            return
        if "--jog" in sys.argv:
            steps = int(sys.argv[sys.argv.index("--jog") + 1])
            print(f"Jogging {steps} half steps ...")
            shade.step(steps)
            return

        start = time.monotonic()
        print("Closing ...")
        shade.close()
        print(f"  closed ({shade.percent:.0f} %) in {time.monotonic() - start:.1f} s")
        time.sleep(1)
        print("Opening ...")
        shade.open()
        print(f"  open ({shade.percent:.0f} %)")
        print("Half way ...")
        shade.move_to(50)
        print(f"  at {shade.percent:.0f} %")
        time.sleep(1)
        shade.open()
        print("Done, shade is open again.")
    except (IndexError, ValueError):
        print("Usage: --jog <number of half steps>, e.g. --jog -300")
    except KeyboardInterrupt:
        print("\nStopped (position is now unknown – jog it back to open).")
    finally:
        shade.deinit()


if __name__ == "__main__":
    main()

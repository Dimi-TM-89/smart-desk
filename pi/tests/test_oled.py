"""
test_oled.py – Test the SSD1306 OLED, and whether it can share SPI0 with the MCP3008.

    python pi/tests/test_oled.py             OLED alone: text + a counter
    python pi/tests/test_oled.py --with-adc  OLED and MCP3008 together

The --with-adc test is important: it reads the ADC between screen updates
and shows the potentiometer value on the OLED.

    Picture stays clean while you turn the potentiometer
        -> the OLED has a working CS pin, the pin plan is fine.
    Garbage / random pixels appear on the OLED
        -> the module has no CS pin (it listens to the ADC traffic too).
           Then the OLED must move to SPI1 (GPIO 19/20/21), and the RGB LED
           and ultrasonic sensor need other pins. Tell the software lead!

Stop with Ctrl+C.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from actuators.oled import Oled  # noqa: E402
from hardware import make_spi  # noqa: E402


def main():
    """Show test screens on the OLED until Ctrl+C."""
    with_adc = "--with-adc" in sys.argv
    p = config.Pins
    print(f"OLED on SPI0, CS=GPIO{p.OLED_CS}, DC=GPIO{p.OLED_DC}, RST=GPIO{p.OLED_RST}")

    spi = make_spi()
    oled = Oled(spi, p.OLED_CS, p.OLED_DC, p.OLED_RST, config.OLED_WIDTH, config.OLED_HEIGHT)
    adc = None
    if with_adc:
        from sensors.adc import AnalogInputs
        adc = AnalogInputs(spi, p.MCP3008_CS, config.ADC_THRESHOLD_POT, config.ADC_WINDOW_LDR)
        print("Shared-bus test: turn the potentiometer and watch for garbage on the OLED.")

    # Frame around the screen, to check the size (128x64) is right
    image, draw = oled.new_canvas()
    draw.rectangle((0, 0, oled.width - 1, oled.height - 1), outline=255)
    draw.text((6, 6), "Smart Desk", font=oled.font, fill=255)
    draw.text((6, 20), "OLED test", font=oled.font, fill=255)
    oled.show_image(image)
    print("You should see a frame around the whole screen. Half a frame -> wrong height.")
    time.sleep(3)

    count = 0
    try:
        while True:
            lines = ["Smart Desk OLED", f"counter: {count}"]
            if adc:
                pot = 0.0
                for _ in range(20):         # lots of ADC traffic between updates
                    pot = adc.pot_percent
                lines += [f"pot: {pot:5.1f} %", f"window: {adc.window_percent:5.1f} %"]
            lines.append(time.strftime("%H:%M:%S"))
            oled.show_lines(lines)
            count += 1
            time.sleep(0.3)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        oled.deinit()
        if adc:
            adc.deinit()
        spi.deinit()


if __name__ == "__main__":
    main()

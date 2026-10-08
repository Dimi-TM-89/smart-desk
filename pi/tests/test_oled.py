"""
test_oled.py – Test the SSD1306 OLED on SPI1 (no CS pin), alone and together with the MCP3008.

    python pi/tests/test_oled.py             OLED alone: frame, text and a counter
    python pi/tests/test_oled.py --with-adc  OLED (SPI1) and MCP3008 (SPI0) together

Our OLED has 6 pins (GND VCC SCL SDA RES DC) and no CS pin, so it runs on its
own SPI1 bus: SCL -> GPIO21 (pin 40), SDA -> GPIO20 (pin 38), RES -> GPIO4,
DC -> GPIO6. SCL/SDA are SPI here, NOT the I2C pins 3/5.

SPI1 needs dtoverlay=spi1-1cs in /boot/firmware/config.txt (setup_pi.sh adds
it) and a reboot; /dev/spidev1.0 must exist.

--with-adc reads the potentiometer on SPI0 between screen updates and shows it
on the OLED: the picture must stay clean while you turn the potentiometer.

Stop with Ctrl+C.
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from actuators.oled import Oled  # noqa: E402
from hardware import make_spi, make_spi1  # noqa: E402


def main():
    """Show test screens on the OLED until Ctrl+C."""
    with_adc = "--with-adc" in sys.argv
    p = config.Pins
    print(f"OLED on SPI1: SCL(clock)=GPIO{p.OLED_SCLK}, SDA(data)=GPIO{p.OLED_MOSI}, "
          f"DC=GPIO{p.OLED_DC}, RES=GPIO{p.OLED_RST}, no CS")
    if not os.path.exists("/dev/spidev1.0"):
        print("FAIL: /dev/spidev1.0 not found – add dtoverlay=spi1-1cs to "
              "/boot/firmware/config.txt (or run scripts/setup_pi.sh) and reboot.")
        return

    spi1 = make_spi1()
    oled = Oled(spi1, p.OLED_CS, p.OLED_DC, p.OLED_RST, config.OLED_WIDTH, config.OLED_HEIGHT)
    spi0 = adc = None
    if with_adc:
        from sensors.adc import AnalogInputs
        spi0 = make_spi()
        adc = AnalogInputs(spi0, p.MCP3008_CS, config.ADC_THRESHOLD_POT, config.ADC_WINDOW_LDR)
        print("Both buses: turn the potentiometer, the value on the OLED must follow cleanly.")

    # Frame around the screen, to check the size (128x64) is right
    image, draw = oled.new_canvas()
    draw.rectangle((0, 0, oled.width - 1, oled.height - 1), outline=255)
    draw.text((6, 6), "Smart Desk", font=oled.font, fill=255)
    draw.text((6, 20), "OLED test", font=oled.font, fill=255)
    oled.show_image(image)
    print("You should see a frame around the whole screen. Half a frame -> wrong height.")
    print("Nothing at all -> check VCC=3.3 V, GND, and SCL/SDA on pins 40/38 (not 3/5).")
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
        spi1.deinit()
        if adc:
            adc.deinit()
        if spi0:
            spi0.deinit()


if __name__ == "__main__":
    main()

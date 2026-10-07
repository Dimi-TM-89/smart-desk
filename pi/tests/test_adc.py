"""
test_adc.py – Test the MCP3008 with the potentiometer (CH0) and the window LDR (CH1).

What it does: prints both channels every 0.5 s, as a raw 10-bit value
(0–1023, as in the course) and as a percentage. For the potentiometer it also
shows the lux threshold it will set in the Smart Desk.

Expected: turning the potentiometer goes smoothly from ~0 to ~1023;
covering the LDR lowers the window value, a lamp/torch raises it.
If the LDR works the other way round, swap the LDR and the 10 kΩ resistor.

Run from the repository root:   python pi/tests/test_adc.py
Stop with Ctrl+C.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from hardware import make_spi  # noqa: E402
from sensors.adc import AnalogInputs  # noqa: E402

L = config.Limits


def main():
    """Print both analog inputs until Ctrl+C."""
    print(f"MCP3008 on SPI0, CS=GPIO{config.Pins.MCP3008_CS}; "
          f"pot=CH{config.ADC_THRESHOLD_POT}, LDR=CH{config.ADC_WINDOW_LDR}\n")
    spi = make_spi()
    adc = AnalogInputs(spi, config.Pins.MCP3008_CS,
                       config.ADC_THRESHOLD_POT, config.ADC_WINDOW_LDR)
    try:
        while True:
            pot = adc.pot_percent
            threshold = L.LUX_THRESHOLD_MIN + pot / 100 * (L.LUX_THRESHOLD_MAX - L.LUX_THRESHOLD_MIN)
            print(f"  pot {adc.raw10(adc.pot):4d} ({pot:5.1f} %) -> threshold {threshold:5.0f} lx"
                  f"   |   window {adc.raw10(adc.ldr):4d} ({adc.window_percent:5.1f} %)")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        adc.deinit()
        spi.deinit()


if __name__ == "__main__":
    main()

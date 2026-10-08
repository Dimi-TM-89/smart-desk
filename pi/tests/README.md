# Component tests

One stand-alone script per component. Each script uses the pins from
`../config.py` and the same classes as the real program (`pi/sensors/`,
`pi/actuators/`), so a component that passes its test also works in
`desk_controller.py`.

Run from the repository root with the virtual environment active:

```bash
source .venv/bin/activate
python pi/tests/test_ultrasonic.py
```

Stop a test with **Ctrl+C**. Each script prints what you should see and
the most likely fix when something is wrong.

## Suggested order

Wire and test one part at a time. Commit when a test passes.

| # | Script | Component | Pins (BCM) | Passes when |
|---|---|---|---|---|
| 1 | `test_i2c.py` | BH1750 + BMP280 | SDA 2, SCL 3 | Scan shows 0x23 and 0x76/0x77, values change |
| 2 | `test_adc.py` | MCP3008, pot, LDR | SPI0, CS 24 | Pot goes 0 → 1023 smoothly, LDR reacts to light |
| 3 | `test_oled.py` | SSD1306 OLED (no CS) | SPI1: SCL→21, SDA→20, DC 6, RES 4 | Frame fills the screen, counter runs |
| 3b | `test_oled.py --with-adc` | OLED + MCP3008 together | SPI1 + SPI0 | Pot value follows cleanly on the OLED |
| 4 | `test_lamp.py` | Desk lamp LEDs | 12 (hardware PWM) | Smooth fade, no flicker |
| 5 | `test_rgb.py` | RGB LED | 13 / 5 / 26 | Red → green → blue in that order |
| 6 | `test_fan.py` | Relay + fan button | 16 / 25 | Relay clicks; button toggles the fan |
| 7 | `test_stepper.py` | Stepper sunshade | 17 / 27 / 22 / 23 | Half a turn one way and back |
| 8 | `test_ultrasonic.py` | HC-SR04 | TRIG 14, ECHO 15 | Stable distance, PRESENT when a hand is in front |
| 9 | `test_mqtt.py` | Mosquitto + Pico | – | `desk/chair/occupied 1/0` when the seat button is pressed |

Our OLED has no CS pin, so it runs on its own SPI1 bus (GPIO 21/20). Its pins
are labelled SCL/SDA, but they are SPI: connect them to pins 40/38, **not** to
the I²C pins 3/5. GPIO18 and GPIO19 belong to SPI1 too and stay free.

## Before wiring

- HC-SR04 (5 V): voltage divider on ECHO (1 kΩ / 2 kΩ).
- ULN2003 stepper board: its own 5 V and GND.
- Relay board: only the IN pin goes to the GPIO; the fan has its own supply
  through COM → NO.

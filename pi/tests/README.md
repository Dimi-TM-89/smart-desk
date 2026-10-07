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
| 3 | `test_oled.py` | SSD1306 OLED | SPI0, CS 5, DC 6, RST 4 | Frame fills the screen, counter runs |
| 3b | `test_oled.py --with-adc` | OLED + MCP3008 together | – | **No garbage** on the OLED while turning the pot |
| 4 | `test_lamp.py` | Desk lamp LEDs | 12 (hardware PWM) | Smooth fade, no flicker |
| 5 | `test_rgb.py` | RGB LED | 13 / 19 / 26 | Red → green → blue in that order |
| 6 | `test_fan.py` | Relay + fan button | 16 / 25 | Relay clicks; button toggles the fan |
| 7 | `test_stepper.py` | Stepper sunshade | 17 / 27 / 22 / 23 | Half a turn one way and back |
| 8 | `test_ultrasonic.py` | HC-SR04 | TRIG 20, ECHO 21 | Stable distance, PRESENT when a hand is in front |
| 9 | `test_mqtt.py` | Mosquitto + Pico | – | `desk/chair/occupied 1/0` when the seat button is pressed |

Test 3b decides whether the OLED can stay on SPI0. If it shows garbage, the
module has no CS pin and the pin plan must change **before** the RGB LED and
ultrasonic sensor are wired (they use GPIO 19/20/21, the SPI1 pins).

## Before wiring

- HC-SR04 (5 V): voltage divider on ECHO (1 kΩ / 2 kΩ).
- ULN2003 stepper board: its own 5 V and GND.
- Relay board: only the IN pin goes to the GPIO; the fan has its own supply
  through COM → NO.

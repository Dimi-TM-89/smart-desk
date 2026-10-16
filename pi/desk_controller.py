"""
desk_controller.py – Main program of the Smart Desk (runs on the Raspberry Pi 5).

Responsibilities (built in layers, see README "Running the Smart Desk"):
    1. read all sensors and publish desk/env                       <- done
    2. climate rules: PWM lamp, sunshade, fan (+ button override)  <- this layer
    3. presence (ultrasonic), seat (Pico over MQTT), seated timer, movement alert
    4. posture input (RGB LED) and the OLED status screen
db_logger.py stores what this program publishes in MariaDB, cloud_bridge.py
sends it to ThingSpeak.

Layer 1 – sensors:
    BH1750   (I2C)              desk light in lux
    BMP280   (I2C)              room temperature in °C
    MCP3008  (SPI0) CH0 pot     lamp threshold, mapped to LUX_THRESHOLD_MIN..MAX
             (SPI0) CH1 LDR     window light 0–100 %
    HC-SR04  (GPIO)             distance in cm; the empty scene is measured
                                at startup as the baseline for presence
Every SENSOR_INTERVAL_S seconds the values are published on desk/env as JSON:
    {"lux": 312.5, "temp": 22.8, "window": 41, "threshold": 300, "distance": 38.2}
A value that cannot be read is sent as null, so the dashboards stay empty
instead of showing a wrong 0.

Layer 2 – climate rules (every SENSOR_INTERVAL_S, after the sensor reading):
    Desk lamp  (PWM GPIO12)     closed loop: the lamp adds light until the
                                BH1750 reaches the threshold from the pot, and
                                dims down when daylight comes back
    Fan        (relay GPIO16)   on above FAN_ON_ABOVE, off below FAN_OFF_BELOW
    Sunshade   (stepper)        closes above SHADE_CLOSE_ABOVE % window light,
                                opens below SHADE_OPEN_BELOW %
    Fan button (GPIO25) and shade button (GPIO7) toggle their part by hand.
    The manual state holds until the automatic rule itself changes its mind
    (the sun goes away, the room cools down), or until the button is pressed
    again: then the rule is in charge again.
The states are published on desk/actuators: {"lamp": 40, "fan": true, "shade": 100}

Multithreading: the stepper needs ~3 s for a full movement. It runs in its
own thread (actuators/shade_mover.py), so the main loop keeps reading the
buttons and sensors while the shade moves. A button press during a movement
turns the shade around at once. (paho-mqtt adds its own network thread with
loop_start().)

Parts that are not connected (yet) are reported at startup and skipped: the
program keeps running with the rest. That way every part can be added and
checked one at a time.

Run from the repository root:   python pi/desk_controller.py
Keep the scale model EMPTY for the first seconds (ultrasonic baseline), and
put the shade in its OPEN position first (python pi/tests/test_stepper.py --jog).
At Ctrl+C the shade is driven back to open.
Stop with Ctrl+C. Do not run tests/simulate_desk.py at the same time.
"""

import json
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import config
import hardware
from actuators.fan import Fan
from actuators.lamp import Lamp
from actuators.shade import Shade
from actuators.shade_mover import ShadeMover
from sensors.adc import AnalogInputs
from sensors.button import Button
from sensors.light import LightSensor
from sensors.temperature import TemperatureSensor
from sensors.ultrasonic import Ultrasonic

T = config.Topics
L = config.Limits
P = config.Pins

LOOP_S = 0.05               # main loop pause: the buttons are polled 20x per second
WARN_EVERY_S = 30           # repeat a "cannot read X" warning at most this often


# ---------------------------------------------------------------------------
# Small helpers (no hardware, easy to test)
# ---------------------------------------------------------------------------
def threshold_from_pot(pot_percent):
    """Map the potentiometer (0–100 %) to a lux threshold (LUX_THRESHOLD_MIN..MAX)."""
    pot_percent = max(0.0, min(100.0, pot_percent))
    span = L.LUX_THRESHOLD_MAX - L.LUX_THRESHOLD_MIN
    return L.LUX_THRESHOLD_MIN + span * pot_percent / 100


def rounded(value, digits=1):
    """Round a number for publishing (digits=0 gives an int); None stays None."""
    if value is None:
        return None
    return int(round(value)) if digits == 0 else round(value, digits)


def next_lamp_level(current, lux, threshold):
    """New lamp level (0–100 %) after one reading: closed-loop light control.

    The lamp also shines on the BH1750, so "lamp = shortfall" would flicker
    (more lamp -> more lux -> less lamp -> ...). Instead the level moves a
    little each reading, in proportion to how far the desk is from the
    threshold, and settles where lux = threshold. Without a reading it stays.
    """
    if lux is None or threshold is None or threshold <= 0:
        return current
    shortfall = (threshold - lux) / threshold      # +1 = pitch dark, < 0 = too bright
    if abs(shortfall) <= L.LAMP_DEADBAND:
        return current
    change = max(-L.LAMP_MAX_STEP, min(L.LAMP_MAX_STEP, L.LAMP_GAIN * shortfall))
    return max(0.0, min(100.0, current + change))


class Hysteresis:
    """On/off rule with two limits, so the output does not flutter around one value.

    Above on_above -> on, below off_below -> off, in between -> unchanged.
    A missing reading (None) changes nothing.
    """

    def __init__(self, on_above, off_below):
        """Start in the off state."""
        self.on_above = on_above
        self.off_below = off_below
        self.state = False

    def update(self, value):
        """Feed a new reading; returns the (possibly new) state."""
        if value is not None:
            if value > self.on_above:
                self.state = True
            elif value < self.off_below:
                self.state = False
        return self.state


class ManualOverride:
    """Button override on top of an automatic on/off rule.

    A press flips the output and holds it, until either
      - the automatic rule changes its mind (e.g. the sun goes away), or
      - the button flips it back to what the rule wants anyway.
    After that the rule decides again.
    """

    def __init__(self):
        """No override at the start."""
        self.active = False
        self.state = False
        self._auto_at_press = None

    def press(self, auto, current):
        """The button was pressed: return the new output (the opposite of current)."""
        new = not current
        if new == auto:
            self.active = False                 # back to what the rule wants: automatic again
        else:
            self.active = True
            self.state = new
            self._auto_at_press = auto
        return new

    def output(self, auto):
        """Output for the current automatic decision (manual state while active)."""
        if self.active and auto != self._auto_at_press:
            self.active = False                 # the rule changed its mind: it takes over
        return self.state if self.active else auto


# ---------------------------------------------------------------------------
# The controller
# ---------------------------------------------------------------------------
class DeskController:
    """Reads the sensors (layer 1) and runs the climate rules (layer 2)."""

    def __init__(self):
        """Prepare the rules and the MQTT client; the hardware is opened in setup_hardware()."""
        self.light = None           # LightSensor or None when not connected
        self.temp = None            # TemperatureSensor
        self.adc = None             # AnalogInputs (pot + window LDR)
        self.ultrasonic = None      # Ultrasonic
        self.lamp = None            # Lamp (hardware PWM)
        self.fan = None             # Fan (relay)
        self.fan_button = None      # Button
        self.shade = None           # ShadeMover (the Shade runs in its own thread)
        self._stepper = None        # the Shade itself, released at the end
        self.shade_button = None    # Button

        # Layer 2 rules
        self.lamp_target = 0.0      # level the lamp fades towards (%)
        self.fan_rule = Hysteresis(L.FAN_ON_ABOVE, L.FAN_OFF_BELOW)
        self.shade_rule = Hysteresis(L.SHADE_CLOSE_ABOVE, L.SHADE_OPEN_BELOW)
        self.fan_override = ManualOverride()
        self.shade_override = ManualOverride()

        self._buses = []            # I2C / SPI buses, released at the end
        self._last_warning = {}     # sensor name -> time of the last warning

        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-controller")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_connect_fail = self._on_connect_fail

    # --- startup -----------------------------------------------------------
    @staticmethod
    def _try(name, factory):
        """Create one part; print OK or the reason it is skipped. Returns the object or None."""
        try:
            part = factory()
        except Exception as exc:  # noqa: BLE001 – any wiring problem: report it and go on
            print(f"  SKIP  {name}: {exc}")
            return None
        print(f"  OK    {name}")
        return part

    def setup_hardware(self):
        """Open the buses and create every sensor that answers."""
        print("Hardware:")
        i2c = self._try("I2C bus (GPIO2/3)", hardware.make_i2c)
        if i2c is not None:
            self._buses.append(i2c)
            self.light = self._try(f"BH1750 light sensor ({hex(config.BH1750_ADDRESS)})",
                                   lambda: LightSensor(i2c, config.BH1750_ADDRESS))
            self.temp = self._try("BMP280 temperature sensor",
                                  lambda: TemperatureSensor(i2c, config.BMP280_ADDRESS))
            if self.temp is not None and self.temp.address != config.BMP280_ADDRESS:
                print(f"        found at {hex(self.temp.address)}: set BMP280_ADDRESS in config.py")

        spi = self._try("SPI0 bus (GPIO11/10/9)", hardware.make_spi)
        if spi is not None:
            self._buses.append(spi)
            self.adc = self._try(f"MCP3008 ADC (CS GPIO{P.MCP3008_CS})",
                                 lambda: AnalogInputs(spi, P.MCP3008_CS,
                                                      config.ADC_THRESHOLD_POT, config.ADC_WINDOW_LDR))

        self.ultrasonic = self._try(f"HC-SR04 ultrasonic (TRIG {P.US_TRIG}, ECHO {P.US_ECHO})",
                                    lambda: Ultrasonic(P.US_TRIG, P.US_ECHO))
        if self.ultrasonic is not None:
            print("        measuring the empty scene (keep the entrance clear) ...")
            baseline = self.ultrasonic.calibrate()
            if baseline is None:
                print("        no echo: check the wiring (VCC on 3.3 V, TRIG/ECHO not swapped)")
            else:
                print(f"        baseline {baseline:.1f} cm, presence below "
                      f"{baseline - L.PRESENCE_DROP_CM:.1f} cm")

        self.lamp = self._try(f"Desk lamp (hardware PWM GPIO{P.LAMP_PWM})", lambda: Lamp(P.LAMP_PWM))
        if self.lamp is None:
            print("        needs dtoverlay=pwm,pin=12,func=4 + reboot (scripts/setup_pi.sh)")
        self.fan = self._try(f"Fan relay (GPIO{P.FAN_RELAY})", lambda: Fan(P.FAN_RELAY))
        self.fan_button = self._try(f"Fan button (GPIO{P.FAN_BUTTON})", lambda: Button(P.FAN_BUTTON))

        shade = self._try(f"Sunshade stepper (GPIO {P.STEPPER})",
                          lambda: Shade(P.STEPPER, L.SHADE_STEPS, reverse=P.STEPPER_REVERSE))
        if shade is not None:
            self._stepper = shade
            self.shade = ShadeMover(shade)       # starts the shade thread
            print("        runs in its own thread; assumes the shade is OPEN now")
        self.shade_button = self._try(f"Shade button (GPIO{P.SHADE_BUTTON})",
                                      lambda: Button(P.SHADE_BUTTON))
        if self.shade_button is None:
            print("        GPIO7 is freed by dtoverlay=spi0-1cs + reboot (scripts/setup_pi.sh)")

    # --- MQTT --------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Report the connection to the local broker."""
        if reason_code.is_failure:
            print(f"[mqtt] connection refused: {reason_code}")
        else:
            print(f"[mqtt] connected to {config.MQTT_HOST}:{config.MQTT_PORT}")

    def _on_connect_fail(self, client, userdata):
        """The broker cannot be reached; the desk keeps working and paho keeps retrying."""
        print(f"[mqtt] cannot reach the broker at {config.MQTT_HOST}:{config.MQTT_PORT}, retrying ... "
              "(sudo systemctl status mosquitto)")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        """Report it; paho reconnects by itself."""
        if reason_code.is_failure:
            print(f"[mqtt] disconnected ({reason_code}), reconnecting ...")

    def publish(self, topic, payload, retain=False):
        """Publish a str, or a dict as JSON. Silently skipped while the broker is away."""
        if isinstance(payload, dict):
            payload = json.dumps(payload)
        self.client.publish(topic, payload, retain=retain)

    # --- layer 1: sensors --------------------------------------------------
    def _read(self, name, func):
        """Call func() and return its value; None (plus a rate-limited warning) on a read error."""
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 – a glitch on the bus must not stop the desk
            now = time.monotonic()
            if now - self._last_warning.get(name, -WARN_EVERY_S) >= WARN_EVERY_S:
                self._last_warning[name] = now
                print(f"[sensor] cannot read {name}: {exc}")
            return None

    def read_sensors(self):
        """Read every connected sensor once. Missing or failing sensors give None."""
        light, temp, adc, us = self.light, self.temp, self.adc, self.ultrasonic
        pot = self._read("potentiometer", lambda: adc.pot_percent) if adc else None
        return {
            "lux": self._read("BH1750", lambda: light.lux) if light else None,
            "temp": self._read("BMP280", lambda: temp.temperature) if temp else None,
            "window": self._read("window LDR", lambda: adc.window_percent) if adc else None,
            "threshold": threshold_from_pot(pot) if pot is not None else None,
            "distance": self._read("HC-SR04", us.distance_cm) if us else None,
        }

    def publish_env(self, values):
        """Publish the sensor values on desk/env; returns what was sent."""
        env = {
            "lux": rounded(values["lux"]),
            "temp": rounded(values["temp"]),
            "window": rounded(values["window"], 0),
            "threshold": rounded(values["threshold"], 0),
            "distance": rounded(values["distance"]),
        }
        self.publish(T.ENV, env)
        return env

    # --- layer 2: climate rules --------------------------------------------
    @property
    def shade_closed(self):
        """True when the shade is closed or closing (its target is past half way)."""
        return self.shade is not None and self.shade.target >= 50

    def _set_fan(self, on, why):
        """Switch the fan if it is not in that state yet, and say why."""
        if self.fan is not None and on != self.fan.is_on:
            self.fan.set(on)
            print(f"[fan]   {'ON' if on else 'OFF'} ({why})")

    def _set_shade(self, closed, why):
        """Send the shade thread a new target if it changes, and say why."""
        if self.shade is not None and closed != self.shade_closed:
            self.shade.move_to(100 if closed else 0)
            print(f"[shade] {'closing' if closed else 'opening'} ({why})")

    def apply_rules(self, values):
        """Decide lamp, fan and shade from one sensor reading."""
        if self.lamp is not None:
            self.lamp_target = next_lamp_level(self.lamp_target, values["lux"], values["threshold"])

        auto = self.fan_rule.update(values["temp"])
        want = self.fan_override.output(auto)
        self._set_fan(want, "manual" if self.fan_override.active else f"temperature {values['temp']} °C")

        auto = self.shade_rule.update(values["window"])
        want = self.shade_override.output(auto)
        window = "?" if values["window"] is None else f"{values['window']:.0f}"
        self._set_shade(want, "manual" if self.shade_override.active else f"window light {window} %")

    def poll_buttons(self):
        """Handle a press on the fan or shade button (called 20x per second)."""
        if self.fan_button is not None and self.fan is not None and self.fan_button.was_pressed():
            on = self.fan_override.press(self.fan_rule.state, self.fan.is_on)
            self._set_fan(on, "button, " + ("manual" if self.fan_override.active else "automatic again"))

        if self.shade_button is not None and self.shade is not None and self.shade_button.was_pressed():
            closed = self.shade_override.press(self.shade_rule.state, self.shade_closed)
            self._set_shade(closed, "button, " + ("manual" if self.shade_override.active else "automatic again"))

    def fade_lamp(self, dt):
        """Move the lamp towards lamp_target at LAMP_FADE_PER_S, so it never jumps."""
        if self.lamp is None or self.lamp.percent == self.lamp_target:
            return
        step = L.LAMP_FADE_PER_S * dt
        diff = self.lamp_target - self.lamp.percent
        self.lamp.set(self.lamp_target if abs(diff) <= step else self.lamp.percent + step * (1 if diff > 0 else -1))

    def check_shade_thread(self):
        """Report once if the shade thread died on an error; the desk keeps running without it."""
        if self.shade is not None and not self.shade.alive:
            print(f"[shade] thread stopped: {self.shade.error} – sunshade disabled")
            self.shade = None

    def publish_actuators(self):
        """Publish lamp %, fan on/off and shade % on desk/actuators; returns what was sent."""
        act = {
            "lamp": rounded(self.lamp.percent, 0) if self.lamp else None,
            "fan": self.fan.is_on if self.fan else None,
            "shade": rounded(self.shade.percent, 0) if self.shade else None,
        }
        self.publish(T.ACTUATORS, act)
        return act

    # --- main loop ---------------------------------------------------------
    def run(self):
        """Set up, then read and publish every SENSOR_INTERVAL_S until Ctrl+C."""
        print(f"Smart Desk controller (demo mode: {config.DEMO_MODE})")
        self.setup_hardware()

        # connect_async: the controller also works while the broker is down,
        # and paho keeps trying to connect in the background
        self.client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
        self.client.loop_start()

        print(f"Publishing {T.ENV} and {T.ACTUATORS} every {L.SENSOR_INTERVAL_S} s (Ctrl+C to stop)")
        next_read = last = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                self.poll_buttons()
                if now >= next_read:
                    # never "catch up" with a burst when a read took long
                    next_read = max(next_read + L.SENSOR_INTERVAL_S, now)
                    values = self.read_sensors()
                    self.apply_rules(values)
                    self.check_shade_thread()
                    env = self.publish_env(values)
                    act = self.publish_actuators()
                    print("  " + "  ".join(f"{k}={'–' if v is None else v}"
                                           for k, v in {**env, **act}.items()))
                self.fade_lamp(now - last)
                last = now
                time.sleep(LOOP_S)
        except KeyboardInterrupt:
            print("\nStopping ...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Release every part and disconnect, even after an error."""
        if self.shade is not None:
            print("Opening the shade (start position for the next run) ...")
            self.shade.stop(park=True)           # waits for the shade thread to finish
            if self.shade.alive:
                print("  the shade thread did not finish in time – jog the shade back to open")
        for part in (self.lamp, self.fan, self._stepper, self.fan_button, self.shade_button,
                     self.adc, self.ultrasonic):
            if part is not None:
                try:
                    part.deinit()
                except Exception:  # noqa: BLE001 – best effort while shutting down
                    pass
        for bus in self._buses:
            try:
                bus.deinit()
            except Exception:  # noqa: BLE001
                pass
        self.client.loop_stop()
        self.client.disconnect()


def main():
    """Entry point."""
    DeskController().run()


if __name__ == "__main__":
    main()

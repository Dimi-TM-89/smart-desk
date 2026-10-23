"""
desk_controller.py – Main program of the Smart Desk (runs on the Raspberry Pi 5).

Responsibilities (built in layers, see README "Running the Smart Desk"):
    1. read all sensors and publish desk/env                       <- done
    2. climate rules: PWM lamp, sunshade, fan (+ button override)  <- done
    3. presence (ultrasonic), seat (Pico over MQTT), seated timer, movement alert  <- done
    4. posture input (RGB LED, posture warning) and the OLED status screen     <- this layer
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
    Fan button (GPIO25) toggles the fan by hand. The shade has two buttons:
    up (GPIO8) opens it, down (GPIO7) closes it.
    The manual state holds until the automatic rule itself changes its mind
    (the sun goes away, the room cools down), or until a button puts the part
    back where the rule wants it anyway: then the rule is in charge again.
The states are published on desk/actuators: {"lamp": 40, "fan": true, "shade": 100}

Layer 3 – presence and seat:
    Presence   Someone is "there" after the HC-SR04 sees them at the entrance,
               while the seat is occupied, or after a button press. With no
               such activity for STANDBY_AFTER_S the desk goes to STANDBY:
               lamp and fan off (the sunshade keeps protecting the room).
    Seat       The Pico publishes desk/chair/occupied (1/0). The seated timer
               starts when someone sits down; a short stand-up does not reset
               it, a real break (BREAK_MIN_S) does.
    Movement   After SEATED_LIMIT_S in the chair a reminder goes to desk/alert
               (cloud_bridge.py forwards it to ntfy), and again every
               SEATED_LIMIT_S while the person keeps sitting.
Published every SENSOR_INTERVAL_S: desk/presence "1"/"0", desk/seated "12.5" (minutes).

Layer 4 – posture and OLED:
    Posture    posture_ai.py publishes desk/posture {"state": "good|bad|none", "angle"}.
               RGB LED: green = good, red = bad, blue = nobody in view or no
               posture data (posture_ai.py not running), off = standby.
               Bad posture for BAD_POSTURE_AFTER_S -> warning on desk/alert,
               at most once per ALERT_COOLDOWN_S.
    OLED       Status screen, refreshed every second:
                   SMART DESK      14:32
                   Desk  312lx (>300)
                   23.5C  Fan ON   man
                   Shade 100%     auto
                   Seat 12m  Posture OK
               "man" = set by a button, "auto" = set by the rule.
               In standby: "Standby" and the time. When an alert is sent, it
               fills the screen (inverted) for ALERT_SCREEN_S.

Multithreading – this program runs four threads:
    main thread    buttons (20x per second), sensors and rules (every second)
    shade          actuators/shade_mover.py: the stepper needs ~3 s for a full
                   movement; the main thread only sets a target. Pressing the
                   other shade button during a movement turns it around at once.
    ultrasonic     sensors/ultrasonic_watcher.py: one distance takes ~0.2 s, so
                   it is measured non-stop in the background (~5x per second)
                   and the main thread only reads the newest value.
    MQTT network   paho-mqtt's loop_start(). Seat and posture messages arrive
                   on that thread; they go through a queue.Queue to the main
                   thread, which owns all the seat and posture state.

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
import queue
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import config
import hardware
from actuators.fan import Fan
from actuators.lamp import Lamp
from actuators.oled import Oled
from actuators.rgb_led import RgbLed
from actuators.shade import Shade
from actuators.shade_mover import ShadeMover
from sensors.adc import AnalogInputs
from sensors.button import Button
from sensors.light import LightSensor
from sensors.temperature import TemperatureSensor
from sensors.ultrasonic import Ultrasonic
from sensors.ultrasonic_watcher import UltrasonicWatcher

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

    A button sets the output and holds it, until either
      - the automatic rule changes its mind (e.g. the sun goes away), or
      - a button sets it back to what the rule wants anyway.
    After that the rule decides again.
    Fan: one toggle button (press). Shade: an up and a down button (set).
    """

    def __init__(self):
        """No override at the start."""
        self.active = False
        self.state = False
        self._auto_at_press = None

    def press(self, auto, current):
        """A toggle button was pressed: return the new output (the opposite of current)."""
        return self.set(auto, not current)

    def set(self, auto, new):
        """A button asks for output `new` (e.g. shade up/down): return it."""
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


def posture_colour(present, posture):
    """RGB LED colour: off in standby, else green/red for good/bad, blue for none or unknown."""
    if not present:
        return "off"
    return {"good": "green", "bad": "red"}.get(posture, "blue")


def status_lines(clock, env, fan_on, fan_manual, shade_pct, shade_manual,
                 seated, seated_min, posture):
    """The 5 lines of the OLED status screen (max. 21 characters = 126 px in the 6 px font).

    env is the dict published on desk/env; missing values are shown as "--".
    """
    def num(value, fmt, width):
        return "--".rjust(width) if value is None else format(value, fmt).rjust(width)

    mode = {True: "man", False: "auto"}
    fan = "--" if fan_on is None else ("ON" if fan_on else "off")
    shade = num(shade_pct, ".0f", 3)
    minutes = int(seated_min)
    seat = ("-" if not seated else f"{minutes}m" if minutes < 100 else f"{minutes // 60}h{minutes % 60:02d}")
    posture_text = {"good": "OK", "bad": "BAD"}.get(posture or "", "-")   # none or unknown: "-"
    lines = [
        f"SMART DESK{clock:>10}",
        f"Desk {num(env['lux'], '.0f', 4)}lx (>{num(env['threshold'], '.0f', 3).strip()})",
        f"{num(env['temp'], '.1f', 4)}C  Fan {fan:<4}{mode[fan_manual] if fan_on is not None else ''}",
        f"Shade {shade}%  {mode[shade_manual] if shade_pct is not None else ''}",
        f"Seat {seat:<4} Posture {posture_text}",
    ]
    return [line[:21] for line in lines]


# ---------------------------------------------------------------------------
# The controller
# ---------------------------------------------------------------------------
class DeskController:
    """Sensors (layer 1), climate rules (layer 2), presence and seat (layer 3), posture and OLED (layer 4)."""

    def __init__(self):
        """Prepare the rules and the MQTT client; the hardware is opened in setup_hardware()."""
        self.light = None           # LightSensor or None when not connected
        self.temp = None            # TemperatureSensor
        self.adc = None             # AnalogInputs (pot + window LDR)
        self.ultrasonic = None      # UltrasonicWatcher (the Ultrasonic runs in its own thread)
        self._sonar = None          # the Ultrasonic itself, released at the end
        self.lamp = None            # Lamp (hardware PWM)
        self.fan = None             # Fan (relay)
        self.fan_button = None      # Button
        self.shade = None           # ShadeMover (the Shade runs in its own thread)
        self._stepper = None        # the Shade itself, released at the end
        self.shade_up_button = None     # Button (opens the shade)
        self.shade_down_button = None   # Button (closes the shade)
        self.rgb = None            # RgbLed (posture feedback)
        self.oled = None            # Oled (local dashboard)

        # Layer 2 rules
        self.lamp_target = 0.0      # level the lamp fades towards (%)
        self.fan_rule = Hysteresis(L.FAN_ON_ABOVE, L.FAN_OFF_BELOW)
        self.shade_rule = Hysteresis(L.SHADE_CLOSE_ABOVE, L.SHADE_OPEN_BELOW)
        self.fan_override = ManualOverride()
        self.shade_override = ManualOverride()

        # Layer 3: presence and seat (only used by the main thread)
        self.inbox = queue.Queue()  # messages from the MQTT thread: (topic, payload)
        self.present = False        # False = standby
        self.last_activity = None   # time.monotonic() of the last sign of life
        self.seated = False         # newest state from the Pico
        self.seated_since = None    # start of the current sitting session
        self.left_seat_at = None    # when the person last stood up
        self.next_move_alert = None # when the next movement reminder is due

        # Layer 4: posture and OLED (only used by the main thread)
        self.posture = None         # "good" / "bad" / "none", None = no (recent) data
        self.posture_angle = None
        self.posture_at = None      # time.monotonic() of the last desk/posture message
        self.bad_since = None       # start of the current bad-posture period
        self.last_posture_alert = None
        self.alert_screen = None    # lines shown full-screen after an alert
        self.alert_screen_until = 0.0
        self._env = None            # newest desk/env values, for the OLED

        self._buses = []            # I2C / SPI buses, released at the end
        self._last_warning = {}     # sensor name -> time of the last warning

        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-controller")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_connect_fail = self._on_connect_fail
        self.client.on_message = self._on_message

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

        sonar = self._try(f"HC-SR04 ultrasonic (TRIG {P.US_TRIG}, ECHO {P.US_ECHO})",
                          lambda: Ultrasonic(P.US_TRIG, P.US_ECHO))
        if sonar is not None:
            print("        measuring the empty scene (keep the entrance clear) ...")
            baseline = sonar.calibrate()
            if baseline is None:
                print("        no echo: check the wiring (VCC on 3.3 V, TRIG/ECHO not swapped)")
            else:
                print(f"        baseline {baseline:.1f} cm, presence below "
                      f"{baseline - L.PRESENCE_DROP_CM:.1f} cm")
            self._sonar = sonar
            self.ultrasonic = UltrasonicWatcher(sonar, L.PRESENCE_DROP_CM)   # starts its thread
            print("        measures in its own thread")

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
        self.shade_up_button = self._try(f"Shade up button (GPIO{P.SHADE_UP_BUTTON})",
                                         lambda: Button(P.SHADE_UP_BUTTON))
        self.shade_down_button = self._try(f"Shade down button (GPIO{P.SHADE_DOWN_BUTTON})",
                                           lambda: Button(P.SHADE_DOWN_BUTTON))
        if self.shade_up_button is None or self.shade_down_button is None:
            print("        GPIO7/8 are freed by dtoverlay=spi0-0cs + reboot (scripts/setup_pi.sh)")

        self.rgb = self._try(f"RGB posture LED (GPIO {P.RGB_RED}/{P.RGB_GREEN}/{P.RGB_BLUE})",
                             lambda: RgbLed(P.RGB_RED, P.RGB_GREEN, P.RGB_BLUE))
        spi1 = self._try("SPI1 bus (GPIO21/20)", hardware.make_spi1)
        if spi1 is None:
            print("        needs dtoverlay=spi1-1cs + reboot (scripts/setup_pi.sh)")
        else:
            self._buses.append(spi1)
            self.oled = self._try(f"OLED display (DC {P.OLED_DC}, RES {P.OLED_RST})",
                                  lambda: Oled(spi1, P.OLED_CS, P.OLED_DC, P.OLED_RST,
                                               config.OLED_WIDTH, config.OLED_HEIGHT))

    # --- MQTT --------------------------------------------------------------
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Report the connection to the local broker."""
        if reason_code.is_failure:
            print(f"[mqtt] connection refused: {reason_code}")
        else:
            print(f"[mqtt] connected to {config.MQTT_HOST}:{config.MQTT_PORT}")
            # (Re)subscribe on every connect; the Pico's retained message
            # arrives at once, so the seat state is known right away
            client.subscribe([(T.CHAIR, 0), (T.POSTURE, 0)])

    def _on_message(self, client, userdata, msg):
        """Runs on the MQTT thread: only hand the message to the main thread."""
        self.inbox.put((msg.topic, msg.payload.decode(errors="replace").strip()))

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
            "distance": us.distance if us else None,    # newest value from the ultrasonic thread
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
        """Decide lamp, fan and shade from one sensor reading.

        In standby (nobody there) the lamp and the fan stay off; the sunshade
        keeps working, it protects the room from the sun also when it is empty.
        """
        auto = self.fan_rule.update(values["temp"])     # keep following the temperature
        if not self.present:
            self.lamp_target = 0.0
            self.fan_override.active = False
            self._set_fan(False, "standby")
        else:
            if self.lamp is not None:
                self.lamp_target = next_lamp_level(self.lamp_target, values["lux"], values["threshold"])
            want = self.fan_override.output(auto)
            self._set_fan(want, "manual" if self.fan_override.active else f"temperature {values['temp']} °C")

        auto = self.shade_rule.update(values["window"])
        want = self.shade_override.output(auto)
        window = "?" if values["window"] is None else f"{values['window']:.0f}"
        self._set_shade(want, "manual" if self.shade_override.active else f"window light {window} %")

    def poll_buttons(self):
        """Handle a press on the fan button or a shade button (called 20x per second)."""
        if self.fan_button is not None and self.fan is not None and self.fan_button.was_pressed():
            self.activity("fan button")
            on = self.fan_override.press(self.fan_rule.state, self.fan.is_on)
            self._set_fan(on, "button, " + ("manual" if self.fan_override.active else "automatic again"))

        # Up opens, down closes. Pressing the button for the way the shade is
        # already going (or already is) changes nothing; the other button turns
        # it around at once, also halfway a movement.
        for button, closed, name in ((self.shade_up_button, False, "up"),
                                     (self.shade_down_button, True, "down")):
            if button is not None and button.was_pressed() and self.shade is not None:
                self.activity(f"shade {name} button")
                self.shade_override.set(self.shade_rule.state, closed)
                mode = "manual" if self.shade_override.active else "automatic again"
                self._set_shade(closed, f"{name} button, {mode}")

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

    # --- layer 3: presence, seat, movement reminder -------------------------
    def activity(self, why):
        """A sign of life: wake up from standby (or stay awake)."""
        self.last_activity = time.monotonic()
        if not self.present:
            self.present = True
            print(f"[presence] awake ({why})")

    def handle_messages(self):
        """Process what the MQTT thread received (runs on the main thread)."""
        while True:
            try:
                topic, payload = self.inbox.get_nowait()
            except queue.Empty:
                return
            if topic == T.CHAIR:
                if payload in ("1", "0"):
                    self.seat_changed(payload == "1")
                else:
                    print(f"[seat] ignored unknown payload {payload!r}")
            elif topic == T.POSTURE:
                self.posture_received(payload)

    def posture_received(self, payload):
        """posture_ai.py sends {"state": "good|bad|none", "angle": 12.3}."""
        try:
            data = json.loads(payload)
            state = data["state"]
        except (ValueError, KeyError, TypeError):
            print(f"[posture] ignored unreadable payload {payload!r}")
            return
        if state not in ("good", "bad", "none"):
            print(f"[posture] ignored unknown state {state!r}")
            return
        if state != self.posture:
            print(f"[posture] {state}" + (f" ({data.get('angle')}°)" if data.get("angle") is not None else ""))
        self.posture = state
        self.posture_angle = data.get("angle")
        self.posture_at = time.monotonic()

    def seat_changed(self, seated):
        """The Pico reports a new seat state."""
        if seated == self.seated:
            return                                  # e.g. the retained message after a reconnect
        now = time.monotonic()
        self.seated = seated
        if seated:
            self.activity("seat")
            if self.seated_since is None:           # new session (first time, or after a real break)
                self.seated_since = now
                self.next_move_alert = now + L.SEATED_LIMIT_S
                print("[seat] sat down – timer started")
            elif self.left_seat_at is not None:
                print(f"[seat] back after {now - self.left_seat_at:.0f} s – timer goes on")
            self.left_seat_at = None
        else:
            self.left_seat_at = now
            print("[seat] stood up")

    @property
    def seated_minutes(self):
        """Length of the current sitting session in minutes (0 without one)."""
        if self.seated_since is None:
            return 0.0
        return (time.monotonic() - self.seated_since) / 60

    def update_presence_and_seat(self):
        """Once per reading: seat timer, movement reminder, standby."""
        now = time.monotonic()

        # A real break ends the sitting session
        if not self.seated and self.left_seat_at is not None and now - self.left_seat_at >= L.BREAK_MIN_S:
            if self.seated_since is not None:
                print(f"[seat] break of {L.BREAK_MIN_S} s – timer reset")
            self.seated_since = self.next_move_alert = self.left_seat_at = None

        # Movement reminder, repeated every SEATED_LIMIT_S while sitting
        if self.seated and self.next_move_alert is not None and now >= self.next_move_alert:
            self.next_move_alert += L.SEATED_LIMIT_S
            text = f"Seated for {self.seated_minutes:.0f} min: time to move – 10 squats or a short walk"
            self.publish(T.ALERT, text)
            print(f"[alert] {text}")
            self.show_alert(["TIME TO MOVE!", "", "10 squats or", "a short walk"])

        # Presence: the entrance sensor and the seat count as activity
        if self.ultrasonic is not None:
            seen = self.ultrasonic.last_seen
            if seen is not None and (self.last_activity is None or seen > self.last_activity):
                self.activity("entrance")
        if self.seated:
            self.activity("seat")
        if (self.present and self.last_activity is not None
                and now - self.last_activity >= L.STANDBY_AFTER_S):
            self.present = False
            print(f"[presence] nobody for {L.STANDBY_AFTER_S} s – standby")

    def check_ultrasonic_thread(self):
        """Report once if the ultrasonic thread died on an error; presence then relies on the seat."""
        if self.ultrasonic is not None and not self.ultrasonic.alive:
            print(f"[sensor] ultrasonic thread stopped: {self.ultrasonic.error} – entrance detection off")
            self.ultrasonic = None

    # --- layer 4: posture and OLED --------------------------------------------
    def update_posture(self):
        """Once per reading: forget stale posture data and send a warning after long bad posture."""
        now = time.monotonic()
        if self.posture is not None and self.posture_at is not None and now - self.posture_at > L.POSTURE_STALE_S:
            print(f"[posture] no data for {L.POSTURE_STALE_S} s (is posture_ai.py running?)")
            self.posture = None

        if not (self.present and self.posture == "bad"):
            self.bad_since = None
            return
        if self.bad_since is None:
            self.bad_since = now
        cooled_down = self.last_posture_alert is None or now - self.last_posture_alert >= L.ALERT_COOLDOWN_S
        if now - self.bad_since >= L.BAD_POSTURE_AFTER_S and cooled_down:
            self.last_posture_alert = now
            text = f"Bad posture for {now - self.bad_since:.0f} s: sit up straight, shoulders back"
            self.publish(T.ALERT, text)
            print(f"[alert] {text}")
            self.show_alert(["SIT UP STRAIGHT", "", "shoulders back"])

    def update_rgb(self):
        """Show the posture on the RGB LED (only switches pins when the colour changes)."""
        rgb = self.rgb
        if rgb is None:
            return
        colour = posture_colour(self.present, self.posture)
        if colour != rgb.colour:
            self._display("RGB LED", lambda: rgb.set(colour))

    def show_alert(self, lines):
        """Fill the OLED with an alert for ALERT_SCREEN_S."""
        self.alert_screen = lines
        self.alert_screen_until = time.monotonic() + L.ALERT_SCREEN_S
        self.update_oled()

    def update_oled(self):
        """Draw the right screen: alert, standby or the status lines."""
        oled = self.oled
        if oled is None or self._env is None:
            return
        clock = time.strftime("%H:%M")
        if self.alert_screen is not None and time.monotonic() < self.alert_screen_until:
            lines = self.alert_screen
            self._display("OLED", lambda: oled.show_centered(lines, inverted=True))
        elif not self.present:
            self._display("OLED", lambda: oled.show_centered(["Standby", "", clock]))
        else:
            lines = status_lines(
                clock, self._env,
                fan_on=self.fan.is_on if self.fan else None, fan_manual=self.fan_override.active,
                shade_pct=self.shade.percent if self.shade else None,
                shade_manual=self.shade_override.active,
                seated=self.seated, seated_min=self.seated_minutes, posture=self.posture)
            self._display("OLED", lambda: oled.show_lines(lines))

    def _display(self, name, func):
        """Drive an output; a glitch gives a rate-limited warning instead of stopping the desk."""
        try:
            func()
        except Exception as exc:  # noqa: BLE001
            now = time.monotonic()
            if now - self._last_warning.get(name, -WARN_EVERY_S) >= WARN_EVERY_S:
                self._last_warning[name] = now
                print(f"[output] cannot update {name}: {exc}")

    def publish_status(self):
        """Publish desk/presence and desk/seated; returns what was sent (for the console line)."""
        presence = "1" if self.present else "0"
        seated = f"{self.seated_minutes:.1f}"
        self.publish(T.PRESENCE, presence)
        self.publish(T.SEATED, seated)
        return {"present": presence, "seat": "1" if self.seated else "0", "seated_min": seated,
                "posture": self.posture}

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

        print(f"Publishing {T.ENV}, {T.ACTUATORS}, {T.PRESENCE} and {T.SEATED} "
              f"every {L.SENSOR_INTERVAL_S} s (Ctrl+C to stop)")
        print("[presence] standby until someone enters, sits down or presses a button")
        next_read = last = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                self.poll_buttons()
                self.handle_messages()
                self.update_rgb()
                if now >= next_read:
                    # never "catch up" with a burst when a read took long
                    next_read = max(next_read + L.SENSOR_INTERVAL_S, now)
                    self.check_ultrasonic_thread()
                    self.update_presence_and_seat()
                    values = self.read_sensors()
                    self.apply_rules(values)
                    self.check_shade_thread()
                    env = self.publish_env(values)
                    act = self.publish_actuators()
                    self.update_posture()
                    self._env = env
                    self.update_oled()
                    status = self.publish_status()
                    print("  " + "  ".join(f"{k}={'–' if v is None else v}"
                                           for k, v in {**env, **act, **status}.items()))
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
        if self.ultrasonic is not None:
            self.ultrasonic.stop()                   # ends the ultrasonic thread
        for part in (self.lamp, self.fan, self._stepper, self.fan_button,
                     self.shade_up_button, self.shade_down_button, self.rgb, self.oled, self.adc, self._sonar):
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

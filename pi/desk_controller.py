"""
desk_controller.py – Main program of the Smart Desk (runs on the Raspberry Pi 5).

Responsibilities (built in layers, see README "Running the Smart Desk"):
    1. read all sensors and publish desk/env                       <- this layer
    2. climate rules: PWM lamp, sunshade, fan (+ button override)
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

Parts that are not connected (yet) are reported at startup and skipped: the
program keeps running with the rest. That way every part can be added and
checked one at a time.

Run from the repository root:   python pi/desk_controller.py
Keep the scale model EMPTY for the first seconds (ultrasonic baseline).
Stop with Ctrl+C. Do not run tests/simulate_desk.py at the same time.
"""

import json
import time

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import config
import hardware
from sensors.adc import AnalogInputs
from sensors.light import LightSensor
from sensors.temperature import TemperatureSensor
from sensors.ultrasonic import Ultrasonic

T = config.Topics
L = config.Limits
P = config.Pins

LOOP_S = 0.05               # main loop pause; later layers poll the fan button here
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


# ---------------------------------------------------------------------------
# The controller
# ---------------------------------------------------------------------------
class DeskController:
    """Reads the sensors and publishes them (layer 1)."""

    def __init__(self):
        """Prepare the MQTT client; the hardware is opened in setup_hardware()."""
        self.light = None           # LightSensor or None when not connected
        self.temp = None            # TemperatureSensor
        self.adc = None             # AnalogInputs (pot + window LDR)
        self.ultrasonic = None      # Ultrasonic
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
                print("        no echo: check the wiring / voltage divider on ECHO")
            else:
                print(f"        baseline {baseline:.1f} cm, presence below "
                      f"{baseline - L.PRESENCE_DROP_CM:.1f} cm")

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
        """Publish the sensor values on desk/env and print them."""
        env = {
            "lux": rounded(values["lux"]),
            "temp": rounded(values["temp"]),
            "window": rounded(values["window"], 0),
            "threshold": rounded(values["threshold"], 0),
            "distance": rounded(values["distance"]),
        }
        self.publish(T.ENV, env)
        print("  " + "  ".join(f"{k}={'–' if v is None else v}" for k, v in env.items()))

    # --- main loop ---------------------------------------------------------
    def run(self):
        """Set up, then read and publish every SENSOR_INTERVAL_S until Ctrl+C."""
        print(f"Smart Desk controller (demo mode: {config.DEMO_MODE})")
        self.setup_hardware()

        # connect_async: the controller also works while the broker is down,
        # and paho keeps trying to connect in the background
        self.client.connect_async(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
        self.client.loop_start()

        print(f"Publishing {T.ENV} every {L.SENSOR_INTERVAL_S} s (Ctrl+C to stop)")
        next_read = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if now >= next_read:
                    # never "catch up" with a burst when a read took long
                    next_read = max(next_read + L.SENSOR_INTERVAL_S, now)
                    self.publish_env(self.read_sensors())
                time.sleep(LOOP_S)
        except KeyboardInterrupt:
            print("\nStopping ...")
        finally:
            self.shutdown()

    def shutdown(self):
        """Release every part and disconnect, even after an error."""
        for part in (self.adc, self.ultrasonic):
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

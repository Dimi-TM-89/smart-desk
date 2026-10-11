"""
cloud_bridge.py – Connects the Smart Desk to the cloud (runs on the Raspberry Pi 5).

Subscribes to desk/# on the local Mosquitto broker, remembers the latest value
of every topic and
    - sends the 8 dashboard fields to ThingSpeak every THINGSPEAK_INTERVAL_S
      seconds over MQTT (mqtt3.thingspeak.com, as in course lesson 4)
    - forwards every message on desk/alert to ntfy (push notification on the
      phone, course lesson 8b)

ThingSpeak fields (channel "Smart Desk", see report section 7.2):
    field1 desk light (lux)       field5 posture (1 = good, 0 = bad)
    field2 temperature (°C)       field6 presence (1/0)
    field3 window light (%)       field7 fan (1/0)
    field4 seated time (min)      field8 sunshade position (%)

Settings and secrets come from config.py / .env. Missing ThingSpeak or ntfy
settings switch that part off with a warning, so the bridge can be tested
one part at a time.

Run from the repository root:   python pi/cloud_bridge.py
Stop with Ctrl+C.
"""

import json
import queue
import threading
import time

import paho.mqtt.client as mqtt
import requests
from paho.mqtt.enums import CallbackAPIVersion

import config

T = config.Topics


# ---------------------------------------------------------------------------
# Turning the latest MQTT values into ThingSpeak fields
# ---------------------------------------------------------------------------
def parse_payload(payload):
    """Decode an MQTT payload: JSON object/number if possible, otherwise text."""
    text = payload.decode("utf-8", errors="replace").strip()
    try:
        return json.loads(text)
    except ValueError:
        return text


def _num(value, digits=1):
    """Round a number for the dashboard (digits=0 gives a whole number); None if not a number."""
    try:
        number = round(float(value), digits)
    except (TypeError, ValueError):
        return None
    return int(number) if digits == 0 else number


def _flag(value):
    """Turn 1/0, true/false, "1"/"0" into 1 or 0; None if unknown."""
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("1", "true", "on"):
            return 1
        if value in ("0", "false", "off"):
            return 0
        return None
    if value is None:
        return None
    return 1 if value else 0


def build_fields(latest):
    """Map the latest topic values to ThingSpeak fields.

    latest -- dict topic -> decoded payload (see parse_payload)
    Returns a dict like {"field1": 312.5, ...}; fields without a value are left
    out, so ThingSpeak keeps them empty instead of logging a wrong 0.
    """
    env = latest.get(T.ENV) if isinstance(latest.get(T.ENV), dict) else {}
    act = latest.get(T.ACTUATORS) if isinstance(latest.get(T.ACTUATORS), dict) else {}
    posture = latest.get(T.POSTURE) if isinstance(latest.get(T.POSTURE), dict) else {}

    posture_value = {"good": 1, "bad": 0}.get(str(posture.get("state", "")))  # "none" -> empty

    fields = {
        "field1": _num(env.get("lux")),
        "field2": _num(env.get("temp")),
        "field3": _num(env.get("window"), 0),
        "field4": _num(latest.get(T.SEATED)),
        "field5": posture_value,
        "field6": _flag(latest.get(T.PRESENCE)),
        "field7": _flag(act.get("fan")),
        "field8": _num(act.get("shade"), 0),
    }
    return {k: v for k, v in fields.items() if v is not None}


def thingspeak_payload(fields):
    """Payload in the format of the course example: field1=..&field2=..&status=MQTTPUBLISH."""
    parts = [f"{k}={v}" for k, v in sorted(fields.items())]
    parts.append("status=MQTTPUBLISH")
    return "&".join(parts)


# ---------------------------------------------------------------------------
# The bridge
# ---------------------------------------------------------------------------
class CloudBridge:
    """Local broker -> ThingSpeak (every interval) and desk/alert -> ntfy."""

    def __init__(self):
        """Prepare both MQTT clients; nothing is connected yet."""
        self.latest = {}                 # topic -> decoded payload
        self.lock = threading.Lock()     # latest is written by the MQTT thread
        self.alerts = queue.Queue()      # desk/alert texts waiting for ntfy

        self.ts_enabled = all((config.THINGSPEAK_CHANNEL_ID, config.THINGSPEAK_CLIENT_ID,
                               config.THINGSPEAK_USERNAME, config.THINGSPEAK_PASSWORD))
        self.ntfy_enabled = bool(config.NTFY_TOPIC)
        self.ts_topic = f"channels/{config.THINGSPEAK_CHANNEL_ID}/publish"

        # Local broker (Mosquitto on the Pi)
        self.local = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-cloud-bridge")
        self.local.on_connect = self._on_local_connect
        self.local.on_message = self._on_local_message

        # ThingSpeak broker (client ID / username / password from the MQTT device)
        self.ts = None
        if self.ts_enabled:
            self.ts = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=config.THINGSPEAK_CLIENT_ID)
            self.ts.username_pw_set(config.THINGSPEAK_USERNAME, config.THINGSPEAK_PASSWORD)
            self.ts.on_connect = self._on_ts_connect
            self.ts.on_disconnect = self._on_ts_disconnect
            self.ts.on_connect_fail = self._on_ts_connect_fail
            self.ts.reconnect_delay_set(min_delay=2, max_delay=60)

    # --- local broker callbacks (run in paho's network thread) -------------
    def _on_local_connect(self, client, userdata, flags, reason_code, properties):
        """Subscribe to all desk topics after every (re)connect."""
        if reason_code.is_failure:
            print(f"[local] connection refused: {reason_code}")
            return
        print(f"[local] connected to {config.MQTT_HOST}:{config.MQTT_PORT}, subscribing to {T.ALL}")
        client.subscribe(T.ALL)

    def _on_local_message(self, client, userdata, msg):
        """Remember the newest value of each topic; queue alerts for ntfy."""
        value = parse_payload(msg.payload)
        if msg.topic == T.ALERT:
            self.alerts.put(str(value))
            return
        with self.lock:
            self.latest[msg.topic] = value

    # --- ThingSpeak callbacks ----------------------------------------------
    def _on_ts_connect(self, client, userdata, flags, reason_code, properties):
        """Report the result of connecting to ThingSpeak."""
        if reason_code.is_failure:
            print(f"[thingspeak] connection refused: {reason_code} "
                  "(check THINGSPEAK_CLIENT_ID / USERNAME / PASSWORD in .env)")
        else:
            print(f"[thingspeak] connected, publishing to {self.ts_topic}")

    def _on_ts_connect_fail(self, client, userdata):
        """Called when ThingSpeak cannot be reached at all (no internet, DNS ...)."""
        print(f"[thingspeak] cannot reach {config.THINGSPEAK_HOST}:{config.THINGSPEAK_PORT}, retrying ...")

    def _on_ts_disconnect(self, client, userdata, flags, reason_code, properties):
        """Report it; after an unexpected disconnect paho reconnects by itself."""
        if reason_code.is_failure:
            print(f"[thingspeak] disconnected ({reason_code}), reconnecting ...")
        else:
            print("[thingspeak] disconnected")

    # --- work done in the main loop ----------------------------------------
    def publish_to_thingspeak(self):
        """Send the current values as one ThingSpeak update."""
        if self.ts is None:
            return
        with self.lock:
            fields = build_fields(self.latest)
        if not fields:
            print("[thingspeak] nothing to send yet (no desk/* values received)")
            return
        payload = thingspeak_payload(fields)
        info = self.ts.publish(self.ts_topic, payload, qos=0)
        if info.rc == mqtt.MQTT_ERR_SUCCESS:
            print(f"[thingspeak] {payload}")
        else:
            print(f"[thingspeak] not sent (not connected): {payload}")

    def send_alerts(self):
        """Forward queued desk/alert messages to ntfy (HTTP POST, as in lesson 8b)."""
        while not self.alerts.empty():
            text = self.alerts.get()
            if not self.ntfy_enabled:
                print(f"[ntfy] off (NTFY_TOPIC empty), alert not sent: {text}")
                continue
            try:
                r = requests.post(f"{config.NTFY_URL}/{config.NTFY_TOPIC}", data=text.encode("utf-8"),
                                  headers={"Title": "Smart Desk", "Tags": "chair"}, timeout=10)
                print(f"[ntfy] sent ({r.status_code}): {text}")
            except requests.RequestException as exc:
                print(f"[ntfy] failed: {exc}")

    def run(self):
        """Connect, then publish every interval and forward alerts until Ctrl+C."""
        if not self.ts_enabled:
            print("[thingspeak] OFF – fill in THINGSPEAK_* in .env to enable it")
        if not self.ntfy_enabled:
            print("[ntfy] OFF – fill in NTFY_TOPIC in .env to enable it")

        try:
            self.local.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
        except OSError as exc:
            print(f"[local] cannot reach the broker at {config.MQTT_HOST}:{config.MQTT_PORT}: {exc}")
            print("        -> sudo systemctl status mosquitto")
            return
        self.local.loop_start()
        if self.ts:
            # connect_async: the network thread keeps retrying until it works
            self.ts.connect_async(config.THINGSPEAK_HOST, config.THINGSPEAK_PORT, keepalive=60)
            self.ts.loop_start()

        next_update = time.monotonic() + config.THINGSPEAK_INTERVAL_S
        try:
            while True:
                self.send_alerts()
                if self.ts and time.monotonic() >= next_update:
                    next_update += config.THINGSPEAK_INTERVAL_S
                    self.publish_to_thingspeak()
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopping ...")
        finally:
            self.local.loop_stop()
            self.local.disconnect()
            if self.ts:
                self.ts.loop_stop()
                self.ts.disconnect()


def main():
    """Entry point."""
    print(f"Smart Desk cloud bridge – ThingSpeak every {config.THINGSPEAK_INTERVAL_S} s")
    CloudBridge().run()


if __name__ == "__main__":
    main()

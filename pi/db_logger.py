"""
db_logger.py – Stores the Smart Desk data in MariaDB (runs on the Raspberry Pi 5).

Subscribes to desk/# on the local Mosquitto broker, just like cloud_bridge.py,
and writes to the smartdesk database (see db/schema.sql):

    readings – every DB_LOG_INTERVAL_S seconds one snapshot of the latest
               values: light, temperature, window light, threshold, presence,
               seat, seated time, posture, lamp, fan and sunshade
    posture  – one row each time the posture state changes (good/bad/none)
    alerts   – every message on desk/alert (movement reminders, posture warnings)

Because it only listens to MQTT, it works the same with the real desk
(desk_controller.py, posture_ai.py, the Pico) and with tests/simulate_desk.py.
When no desk/* messages arrive for STALE_AFTER_S seconds (desk program
stopped), it pauses instead of logging old values over and over.

Privacy: only values and the posture result are stored, never camera images.

Run from the repository root:   python pi/db_logger.py
Stop with Ctrl+C.
"""

import queue
import threading
import time

import mariadb
import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

import config
from cloud_bridge import parse_payload
from database import Database

T = config.Topics
STALE_AFTER_S = 3 * config.DB_LOG_INTERVAL_S   # no desk/* message this long -> pause snapshots


# ---------------------------------------------------------------------------
# Turning MQTT values into database values
# ---------------------------------------------------------------------------
def to_float(value):
    """Number as float, or None (-> NULL in the database) if it is not a number."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_bool(value):
    """1/0, true/false, "1"/"0", "on"/"off" -> True/False; None if unknown."""
    if isinstance(value, str):
        value = value.strip().lower()
        if value in ("1", "true", "on"):
            return True
        if value in ("0", "false", "off"):
            return False
        return None
    if value is None:
        return None
    return bool(value)


def posture_state(value):
    """'good' / 'bad' / 'none' from a desk/posture payload, or None if invalid."""
    if isinstance(value, dict):
        state = str(value.get("state", "")).lower()
        if state in ("good", "bad", "none"):
            return state
    return None


def build_reading(latest):
    """Map the latest topic values to one row for the readings table.

    latest -- dict topic -> decoded payload (see cloud_bridge.parse_payload)
    Returns a dict with the keys of database.READING_COLUMNS; unknown values are None.
    """
    env = latest.get(T.ENV) if isinstance(latest.get(T.ENV), dict) else {}
    act = latest.get(T.ACTUATORS) if isinstance(latest.get(T.ACTUATORS), dict) else {}

    return {
        "lux": to_float(env.get("lux")),
        "temperature": to_float(env.get("temp")),
        "window_pct": to_float(env.get("window")),
        "threshold": to_float(env.get("threshold")),
        "presence": to_bool(latest.get(T.PRESENCE)),
        "seated": to_bool(latest.get(T.CHAIR)),
        "seated_min": to_float(latest.get(T.SEATED)),
        "posture": posture_state(latest.get(T.POSTURE)),
        "lamp_pct": to_float(act.get("lamp")),
        "fan_on": to_bool(act.get("fan")),
        "shade_pct": to_float(act.get("shade")),
    }


def alert_kind(text):
    """Classify an alert text for the alerts table: 'movement', 'posture' or 'other'."""
    lower = text.lower()
    if "posture" in lower:
        return "posture"
    if "move" in lower or "seated" in lower or "walk" in lower:
        return "movement"
    return "other"


# ---------------------------------------------------------------------------
# The logger
# ---------------------------------------------------------------------------
class DbLogger:
    """Local broker (desk/#) -> MariaDB."""

    def __init__(self):
        """Prepare the MQTT client and the database object; nothing is connected yet."""
        self.db = Database()
        self.latest = {}                    # topic -> decoded payload
        self.lock = threading.Lock()        # latest is written by the MQTT thread
        self.events = queue.Queue()         # ("posture", state, angle) / ("alert", kind, text)
        self.last_message = None            # time.monotonic() of the last desk/* message
        self.last_posture = None            # last posture state, to detect changes
        self.paused = False                 # True while no fresh desk/* data arrives

        self.client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-db-logger")
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # --- MQTT callbacks (run in paho's network thread: no database work here)
    def _on_connect(self, client, userdata, flags, reason_code, properties):
        """Subscribe to all desk topics after every (re)connect."""
        if reason_code.is_failure:
            print(f"[mqtt] connection refused: {reason_code}")
            return
        print(f"[mqtt] connected to {config.MQTT_HOST}:{config.MQTT_PORT}, subscribing to {T.ALL}")
        client.subscribe(T.ALL)

    def _on_message(self, client, userdata, msg):
        """Remember the newest values; queue posture changes and alerts for the database."""
        value = parse_payload(msg.payload)
        if msg.topic == T.ALERT:
            text = str(value)
            self.events.put(("alert", alert_kind(text), text))
            return

        with self.lock:
            self.latest[msg.topic] = value
            if not msg.retain:          # a retained message is old news, not a sign of life
                self.last_message = time.monotonic()

        if msg.topic == T.POSTURE:
            state = posture_state(value)
            if state is not None and state != self.last_posture:
                self.last_posture = state
                angle = to_float(value.get("angle")) if isinstance(value, dict) else None
                self.events.put(("posture", state, angle))

    # --- work done in the main loop ----------------------------------------
    def write_events(self):
        """Write queued posture changes and alerts."""
        while not self.events.empty():
            kind, a, b = self.events.get()
            try:
                if kind == "posture":
                    self.db.insert_posture(a, b)
                    print(f"[db] posture -> {a}" + (f" ({b:.1f}°)" if b is not None else ""))
                else:
                    self.db.insert_alert(a, b)
                    print(f"[db] alert ({a}): {b}")
            except mariadb.Error as exc:
                print(f"[db] write failed, {kind} lost: {exc}")

    def write_reading(self):
        """Write one snapshot, unless no fresh data has arrived recently."""
        with self.lock:
            fresh = self.last_message is not None and time.monotonic() - self.last_message < STALE_AFTER_S
            row = build_reading(self.latest)
        if not fresh:
            if not self.paused:         # say it once, not every interval
                self.paused = True
                print("[db] paused: no desk/* data (is desk_controller.py or the simulator running?)")
            return
        if self.paused:
            self.paused = False
            print("[db] desk data is back, logging again")
        try:
            self.db.insert_reading(row)
            print(f"[db] reading: lux={row['lux']} temp={row['temperature']} seated={row['seated']} "
                  f"posture={row['posture']} lamp={row['lamp_pct']} fan={row['fan_on']} shade={row['shade_pct']}")
        except mariadb.Error as exc:
            print(f"[db] write failed, reading lost: {exc}")

    def run(self):
        """Connect to MariaDB and the broker, then log until Ctrl+C."""
        try:
            # At boot MariaDB can start after us: keep trying for about a minute
            self.db.connect(retries=12, delay_s=5)
        except mariadb.Error as exc:
            print(f"[db] cannot connect to {config.DB_USER}@{config.DB_HOST}/{config.DB_NAME}: {exc}")
            print("     -> run scripts/setup_db.sh and check DB_PASSWORD in .env")
            return
        print(f"[db] connected to {config.DB_NAME} on {config.DB_HOST}")

        try:
            self.client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
        except OSError as exc:
            print(f"[mqtt] cannot reach the broker at {config.MQTT_HOST}:{config.MQTT_PORT}: {exc}")
            print("       -> sudo systemctl status mosquitto")
            self.db.close()
            return
        self.client.loop_start()

        next_reading = time.monotonic() + config.DB_LOG_INTERVAL_S
        try:
            while True:
                self.write_events()
                if time.monotonic() >= next_reading:
                    next_reading += config.DB_LOG_INTERVAL_S
                    self.write_reading()
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("\nStopping ...")
        finally:
            self.client.loop_stop()
            self.client.disconnect()
            self.write_events()          # do not lose the last alerts
            self.db.close()


def main():
    """Entry point."""
    print(f"Smart Desk database logger – one snapshot every {config.DB_LOG_INTERVAL_S} s")
    DbLogger().run()


if __name__ == "__main__":
    main()

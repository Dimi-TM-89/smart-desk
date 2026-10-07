"""
test_mqtt.py – Test the local Mosquitto broker and watch all Smart Desk messages.

What it does:
    1. connects to the broker from .env (default localhost:1883)
    2. publishes one test message on desk/test
    3. prints every message on desk/# with a timestamp

Use it to check the Pico: press the seat button and you should see
desk/chair/occupied 1 / 0 appear. (Same as: mosquitto_sub -h localhost -t 'desk/#' -v)

Run from the repository root:   python pi/tests/test_mqtt.py
Stop with Ctrl+C.
"""

import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402


def on_connect(client, userdata, flags, reason_code, properties):
    """Subscribe to everything under desk/ once connected."""
    if reason_code == 0:
        print(f"Connected to {config.MQTT_HOST}:{config.MQTT_PORT}")
        client.subscribe(config.Topics.ALL)
        client.publish("desk/test", "hello from test_mqtt.py")
    else:
        print(f"Connection refused: {reason_code}")


def on_message(client, userdata, msg):
    """Print each received message with the time and the retained flag."""
    retained = " (retained)" if msg.retain else ""
    print(f"  {time.strftime('%H:%M:%S')}  {msg.topic:24s} {msg.payload.decode(errors='replace')}{retained}")


def main():
    """Connect, subscribe and print messages until Ctrl+C."""
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-test")
    client.on_connect = on_connect
    client.on_message = on_message
    try:
        client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    except OSError as exc:
        print(f"FAIL: cannot reach the broker: {exc}")
        print("  -> sudo systemctl status mosquitto")
        return
    try:
        client.loop_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.disconnect()


if __name__ == "__main__":
    main()

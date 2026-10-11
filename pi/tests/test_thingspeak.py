"""
test_thingspeak.py – Check the ThingSpeak MQTT device and channel (no hardware needed).

What it does:
    1. connects to mqtt3.thingspeak.com with the MQTT device credentials from .env
    2. publishes ONE update with test values in all 8 fields
       (same format as the course example: field1=..&field2=..&status=MQTTPUBLISH)

Expected: "connected" and "published". Within a few seconds the channel's
Private View shows one new point in every chart (field1 = 123, field2 = 21.5, ...).

    "Not authorized"         -> client ID / username / password in .env are wrong
    connected, but no point  -> the MQTT device is not authorized to PUBLISH to
                                this channel, or THINGSPEAK_CHANNEL_ID is wrong
                                (ThingSpeak uses QoS 0: wrong data is silently dropped)

Run from the repository root:   python pi/tests/test_thingspeak.py
Wait at least 15 s between two runs (free-account limit).
"""

import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402

TEST_PAYLOAD = ("field1=123&field2=21.5&field3=40&field4=5&field5=1&field6=1&field7=0&field8=50"
                "&status=MQTTPUBLISH")
result: dict = {"connected": None, "reason": ""}


def on_connect(client, userdata, flags, reason_code, properties):
    """Remember whether ThingSpeak accepted the credentials."""
    result["connected"] = not reason_code.is_failure
    result["reason"] = str(reason_code)


def main():
    """Connect, publish one test update and report."""
    missing = [k for k in ("THINGSPEAK_CHANNEL_ID", "THINGSPEAK_CLIENT_ID",
                           "THINGSPEAK_USERNAME", "THINGSPEAK_PASSWORD") if not getattr(config, k)]
    if missing:
        print("FAIL: still empty in .env: " + ", ".join(missing))
        return

    topic = f"channels/{config.THINGSPEAK_CHANNEL_ID}/publish"
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id=config.THINGSPEAK_CLIENT_ID)
    client.username_pw_set(config.THINGSPEAK_USERNAME, config.THINGSPEAK_PASSWORD)
    client.on_connect = on_connect

    print(f"Connecting to {config.THINGSPEAK_HOST}:{config.THINGSPEAK_PORT} ...")
    try:
        client.connect(config.THINGSPEAK_HOST, config.THINGSPEAK_PORT, keepalive=60)
    except OSError as exc:
        print(f"FAIL: cannot reach ThingSpeak: {exc} (internet connection?)")
        return
    client.loop_start()
    deadline = time.monotonic() + 10
    while result["connected"] is None and time.monotonic() < deadline:
        time.sleep(0.1)

    if result["connected"] is None:
        print("FAIL: no answer from ThingSpeak within 10 s")
    elif not result["connected"]:
        print(f"FAIL: connection refused: {result['reason']}")
        print("  -> copy client ID, username and password again from Devices > MQTT")
    else:
        print("OK   connected")
        info = client.publish(topic, TEST_PAYLOAD, qos=0)
        info.wait_for_publish(timeout=5)
        print(f"OK   published to {topic}:\n     {TEST_PAYLOAD}")
        print("Now open the channel (Private View): every chart should get a new point.")
        time.sleep(1)

    client.loop_stop()
    client.disconnect()


if __name__ == "__main__":
    main()

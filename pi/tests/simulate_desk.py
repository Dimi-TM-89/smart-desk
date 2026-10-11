"""
simulate_desk.py – Publish realistic FAKE desk/* values on the local broker.

Lets you build and test the cloud side (cloud_bridge.py, ThingSpeak charts,
ntfy) before desk_controller.py and the hardware are finished. It publishes
the same topics and payloads as the real programs (see README, "MQTT topics"):

    desk/env, desk/actuators, desk/presence, desk/seated, desk/posture,
    desk/chair/occupied – every 3 s
    desk/alert          – with --alert, by the same rules as the real desk
                          (demo timers from config.Limits):
                            * movement reminder after SEATED_LIMIT_S of sitting
                              (once per sitting period)
                            * posture warning when the posture stays bad for
                              BAD_POSTURE_AFTER_S, at most once per ALERT_COOLDOWN_S

The values drift slowly (light, temperature, window light), someone sits down
and gets up every ~2 minutes, and the posture switches between good and bad.

Run from the repository root:   python pi/tests/simulate_desk.py [--alert]
(With DEMO_MODE=0 in .env the real timers apply: 50 min seated, 5 min cooldown.)
Do NOT run it at the same time as desk_controller.py. Stop with Ctrl+C.
"""

import json
import math
import random
import sys
import time
from pathlib import Path

import paho.mqtt.client as mqtt
from paho.mqtt.enums import CallbackAPIVersion

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402

T = config.Topics
L = config.Limits
STEP_S = 3


def publish_alert(client, text):
    """Publish one alert on desk/alert (cloud_bridge.py forwards it to ntfy)."""
    client.publish(T.ALERT, text)
    print(f"  >>> ALERT: {text}")


def main():
    """Publish a new set of simulated values every STEP_S seconds until Ctrl+C."""
    client = mqtt.Client(CallbackAPIVersion.VERSION2, client_id="smartdesk-simulator")
    try:
        client.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
    except OSError as exc:
        print(f"FAIL: cannot reach the broker: {exc}")
        return
    client.loop_start()
    print(f"Simulating the desk on {config.MQTT_HOST}:{config.MQTT_PORT} (Ctrl+C to stop)")

    send_alerts = "--alert" in sys.argv
    if send_alerts:
        print(f"  alerts ON: movement after {L.SEATED_LIMIT_S} s seated, posture after "
              f"{L.BAD_POSTURE_AFTER_S} s bad (cooldown {L.ALERT_COOLDOWN_S} s)")

    start = time.monotonic()
    lux = 320.0
    seated_since = None
    shade_closed = False
    fan_on = False
    move_alert_sent = False        # movement reminder already sent this sitting period
    bad_since = None               # when the posture became bad
    last_posture_alert = -1e9      # time of the last posture warning
    try:
        while True:
            t = time.monotonic() - start

            # Environment: slow drift plus a little noise
            lux = min(800.0, max(40.0, lux + random.uniform(-25, 25)))
            temp = 23.5 + 2.5 * math.sin(t / 240) + random.uniform(-0.1, 0.1)
            window = 55 + 35 * math.sin(t / 150) + random.uniform(-2, 2)
            threshold = 300

            # Same rules as the real desk (with hysteresis)
            lamp = max(0.0, min(100.0, (threshold - lux) / threshold * 100))
            if window > L.SHADE_CLOSE_ABOVE:
                shade_closed = True
            elif window < L.SHADE_OPEN_BELOW:
                shade_closed = False
            if temp > L.FAN_ON_ABOVE:
                fan_on = True
            elif temp < L.FAN_OFF_BELOW:
                fan_on = False

            # Someone sits for ~90 s, then is away for ~30 s
            seated = (t % 120) < 90
            if seated and seated_since is None:
                seated_since = t
            if not seated:
                seated_since = None
            seated_min = (t - seated_since) / 60 if seated_since is not None else 0.0

            posture = ("good" if (t // 30) % 2 == 0 else "bad") if seated else "none"
            angle = None if posture == "none" else (12.0 if posture == "good" else 31.0) + random.uniform(-3, 3)

            # Alerts, by the same rules as desk_controller.py
            if not seated:
                move_alert_sent = False
            bad_since = (bad_since if bad_since is not None else t) if posture == "bad" else None
            if send_alerts and seated_since is not None and not move_alert_sent and t - seated_since >= L.SEATED_LIMIT_S:
                move_alert_sent = True
                publish_alert(client, f"Seated for {seated_min:.0f} min: time to move – 10 squats or a short walk")
            if (send_alerts and bad_since is not None and t - bad_since >= L.BAD_POSTURE_AFTER_S
                    and t - last_posture_alert >= L.ALERT_COOLDOWN_S):
                last_posture_alert = t
                publish_alert(client, "Bad posture: sit up straight, shoulders back")

            client.publish(T.CHAIR, "1" if seated else "0", retain=True)
            client.publish(T.PRESENCE, "1")
            client.publish(T.SEATED, f"{seated_min:.1f}")
            client.publish(T.ENV, json.dumps({"lux": round(lux, 1), "temp": round(temp, 1),
                                              "window": round(window), "threshold": threshold}))
            client.publish(T.ACTUATORS, json.dumps({"lamp": round(lamp), "fan": fan_on,
                                                    "shade": 100 if shade_closed else 0}))
            client.publish(T.POSTURE, json.dumps({"state": posture,
                                                  "angle": None if angle is None else round(angle, 1)}))
            print(f"  t={t:5.0f}s  lux={lux:5.0f}  temp={temp:4.1f}  window={window:3.0f}%  "
                  f"seated={'yes' if seated else 'no '} {seated_min:4.1f} min  posture={posture}")
            time.sleep(STEP_S)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
"""
cloud_bridge.py – Connects the Smart Desk to the cloud (runs on the Raspberry Pi 5).

Subscribes to desk/# on the local broker and
    - sends 8 fields to ThingSpeak every 15 seconds (MQTT)
    - forwards every message on desk/alert to ntfy (HTTPS push notification)

Status: skeleton.
"""

import config


def main():
    """Entry point: will connect to both brokers and start forwarding."""
    print(f"cloud_bridge – not implemented yet (ThingSpeak every {config.THINGSPEAK_INTERVAL_S} s)")


if __name__ == "__main__":
    main()

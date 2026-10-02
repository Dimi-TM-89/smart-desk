"""
desk_controller.py – Main program of the Smart Desk (runs on the Raspberry Pi 5).

Responsibilities:
    - read all sensors (ultrasonic, BH1750, BMP280, MCP3008, fan button)
    - receive the seat state from the Pico and the posture from posture_ai.py (MQTT)
    - apply the rules (see section 5.3 of the report)
    - drive the actuators (PWM lamp, RGB LED, fan relay, stepper sunshade)
    - show the status on the OLED
    - publish desk/* topics and log to MariaDB

Status: skeleton – implemented step by step (see README, "Way of working").
"""

import config


def main():
    """Entry point: will set up hardware and MQTT, then run the main loop."""
    print(f"desk_controller – not implemented yet (demo mode: {config.DEMO_MODE})")


if __name__ == "__main__":
    main()

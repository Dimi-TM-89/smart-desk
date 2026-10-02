"""
code.py – Seat sensor on the Raspberry Pi Pico 2 W (CircuitPython).

Reads the push button under the seat (GP15 to GND, internal pull-up),
debounces it and publishes "1" (seated) or "0" (empty) on
desk/chair/occupied to the Mosquitto broker on the Pi, only when the state
changes. The onboard LED shows that Wi-Fi and MQTT are connected.

Settings (Wi-Fi, broker IP) come from settings.toml on the CIRCUITPY drive.

Status: skeleton.
"""

print("Smart Desk seat sensor – not implemented yet")

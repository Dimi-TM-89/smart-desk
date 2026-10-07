"""
code.py – Seat sensor on the Raspberry Pi Pico 2 W (CircuitPython).

Reads the push button under the seat (GP15 to GND, internal pull-up),
debounces it and publishes "1" (seated) or "0" (empty) on
desk/chair/occupied to the Mosquitto broker on the Pi, only when the state
changes. The onboard LED shows that Wi-Fi and MQTT are connected.

Details:
    - Messages are sent with retain=True: the broker remembers the last state,
      so desk_controller.py gets it immediately when it (re)starts.
    - Last will "0": if the Pico loses power or Wi-Fi, the broker publishes
      "0" for it, so the desk never keeps counting seated time for nobody.
    - Lost connections are retried forever (Wi-Fi first, then MQTT); the LED
      is off while the Pico is not connected.

Settings (Wi-Fi, broker IP) come from settings.toml on the CIRCUITPY drive.
Libraries in CIRCUITPY/lib: adafruit_minimqtt, adafruit_connection_manager.
"""

import os
import time

import adafruit_connection_manager
import adafruit_minimqtt.adafruit_minimqtt as MQTT
import board
import digitalio
import wifi

# --- Settings ---------------------------------------------------------------
SSID = os.getenv("CIRCUITPY_WIFI_SSID")
PASSWORD = os.getenv("CIRCUITPY_WIFI_PASSWORD")
BROKER = os.getenv("MQTT_BROKER")
PORT = int(os.getenv("MQTT_PORT", 1883))
TOPIC = os.getenv("MQTT_TOPIC", "desk/chair/occupied")

SEAT_DEBOUNCE_S = 0.5      # state must be stable this long (shifting on the chair)
POLL_INTERVAL_S = 0.02     # how often the button is read
MQTT_LOOP_EVERY_S = 5      # how often keep-alive pings are handled
RETRY_DELAY_S = 5          # wait between reconnect attempts

# --- Hardware ---------------------------------------------------------------
seat = digitalio.DigitalInOut(board.GP15)
seat.switch_to_input(pull=digitalio.Pull.UP)   # pressed = LOW = seated

led = digitalio.DigitalInOut(board.LED)
led.switch_to_output(value=False)


def seat_occupied():
    """Raw button state: True while someone sits (button pressed)."""
    return not seat.value


# --- Network ----------------------------------------------------------------
def connect_wifi():
    """Connect to Wi-Fi if not connected yet."""
    if wifi.radio.connected:
        return
    print(f"Connecting to Wi-Fi {SSID} ...")
    wifi.radio.connect(SSID, PASSWORD)
    print(f"Wi-Fi OK, IP address {wifi.radio.ipv4_address}")


def make_mqtt_client():
    """Create the MQTT client with a unique client ID and the last will."""
    pool = adafruit_connection_manager.get_radio_socketpool(wifi.radio)
    client_id = "smartdesk-pico-" + "".join(f"{b:02x}" for b in wifi.radio.mac_address[-3:])
    client = MQTT.MQTT(
        broker=BROKER,
        port=PORT,
        client_id=client_id,
        socket_pool=pool,
        is_ssl=False,
        keep_alive=60,
        socket_timeout=0.25,
    )
    client.will_set(TOPIC, "0", retain=True)
    return client


def publish_state(client, occupied):
    """Publish the seat state ("1" / "0") as a retained message."""
    payload = "1" if occupied else "0"
    client.publish(TOPIC, payload, retain=True)
    print(f"Published {TOPIC} = {payload}")


def connect_all(client, occupied):
    """(Re)connect Wi-Fi and MQTT until it works, then publish the current state."""
    while True:
        led.value = False
        try:
            connect_wifi()
            print(f"Connecting to MQTT broker {BROKER}:{PORT} ...")
            if client.is_connected():
                client.disconnect()
            client.connect()
            publish_state(client, occupied)
            led.value = True
            print("MQTT OK")
            return
        except Exception as exc:  # noqa: BLE001 – keep trying whatever went wrong
            print(f"Connection failed: {exc} – retry in {RETRY_DELAY_S} s")
            time.sleep(RETRY_DELAY_S)


# --- Main loop --------------------------------------------------------------
def main():
    """Watch the seat button and publish every (debounced) change."""
    print("Smart Desk seat sensor")
    if not BROKER:
        print("MQTT_BROKER missing in settings.toml – stopping.")
        return

    reported = seat_occupied()      # state the broker knows
    candidate = reported            # state we are debouncing
    candidate_since = time.monotonic()
    last_loop = time.monotonic()

    client = None
    while client is None:
        try:
            connect_wifi()
            client = make_mqtt_client()
        except Exception as exc:  # noqa: BLE001
            print(f"Wi-Fi failed: {exc} – retry in {RETRY_DELAY_S} s")
            time.sleep(RETRY_DELAY_S)
    connect_all(client, reported)

    while True:
        now = time.monotonic()

        # Debounce: a new state must stay the same for SEAT_DEBOUNCE_S
        raw = seat_occupied()
        if raw != candidate:
            candidate = raw
            candidate_since = now
        elif candidate != reported and now - candidate_since >= SEAT_DEBOUNCE_S:
            try:
                publish_state(client, candidate)
                reported = candidate
            except Exception as exc:  # noqa: BLE001
                print(f"Publish failed: {exc}")
                connect_all(client, candidate)   # publishes the state itself
                reported = candidate

        # Keep the connection alive (sends a ping when needed)
        if now - last_loop >= MQTT_LOOP_EVERY_S:
            last_loop = now
            try:
                client.loop(timeout=0.25)
            except Exception as exc:  # noqa: BLE001
                print(f"Connection lost: {exc}")
                connect_all(client, reported)

        time.sleep(POLL_INTERVAL_S)


main()

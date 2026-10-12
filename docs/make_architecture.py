"""
make_architecture.py – Draws docs/architecture.png (Figure 2 of the report).

Change the boxes or arrows below and run it again whenever the design changes:
    python docs/make_architecture.py
Needs matplotlib (sudo apt install python3-matplotlib). Uses the Inter font
when it is installed, otherwise the matplotlib default.
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch  # noqa: E402

OUT = Path(__file__).resolve().parent / "architecture.png"

# Colour per kind of box: (border, fill)
GREEN = ("#2e7d57", "#eaf3ee")     # our programs and the Pi's own hardware
ORANGE = ("#b7791f", "#fef6e6")    # services on the Pi (broker, database)
BLUE = ("#2b6cb0", "#e8f0fb")      # things reached over the network
DARK = "#1f2937"

if any("Inter" in f.name for f in font_manager.fontManager.ttflist):
    plt.rcParams["font.family"] = "Inter"

# Layout in pixels (1750 x 940), y grows downwards
W, H = 1750, 940
LEFT = (25, 385)                   # x range of the outside column on the left
COLS = [(455, 690), (795, 1035), (1120, 1355)]   # the three columns inside the Pi
RIGHT = (1445, 1730)               # outside column on the right
ROWS = [(160, 330), (410, 580), (660, 830)]

fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
ax = fig.add_axes((0, 0, 1, 1))
ax.set_xlim(0, W)
ax.set_ylim(H, 0)
ax.axis("off")


def box(x_range, row, title, lines, colours):
    """Draw a rounded box with a bold title and up to two lines of text."""
    (x0, x1), (y0, y1) = x_range, ROWS[row]
    border, fill = colours
    ax.add_patch(FancyBboxPatch((x0, y0), x1 - x0, y1 - y0, boxstyle="round,pad=0,rounding_size=14",
                                linewidth=3, edgecolor=border, facecolor=fill))
    cx = (x0 + x1) / 2
    top = y0 + (45 if lines else (y1 - y0) / 2)
    ax.text(cx, top, title, ha="center", va="center", fontsize=16.5, fontweight="bold", color=border)
    for i, line in enumerate(lines):
        ax.text(cx, y0 + 95 + i * 38, line, ha="center", va="center", fontsize=13, color=DARK)
    return {"l": x0, "r": x1, "t": y0, "b": y1, "cx": cx, "cy": (y0 + y1) / 2}


def arrow(start, end, colour, both=False, label=None, label_at=None, label_colour=None):
    """Draw an arrow from start to end (pixel points), with an optional italic label."""
    ax.add_patch(FancyArrowPatch(start, end, arrowstyle="<|-|>" if both else "-|>",
                                 mutation_scale=22, linewidth=3, color=colour,
                                 shrinkA=0, shrinkB=0))
    if label:
        ax.text(*label_at, label, ha="center", va="center", fontsize=11, style="italic",
                color=label_colour or colour)


# Title and the Raspberry Pi frame
ax.text(W / 2, 48, "Smart Desk – System architecture", ha="center", va="center",
        fontsize=24, fontweight="bold", color=DARK)
ax.add_patch(FancyBboxPatch((430, 85), 950, 785, boxstyle="round,pad=0,rounding_size=16",
                            linewidth=3.5, edgecolor=DARK, facecolor="#f5f7f9"))
ax.text(905, 125, "Raspberry Pi 5", ha="center", va="center", fontsize=19, fontweight="bold", color=DARK)

# Outside the Pi
gpio = box(LEFT, 0, "Pi GPIO hardware", ["I²C · SPI · digital · PWM", "sensors + actuators"], GREEN)
cam = box(LEFT, 1, "USB webcam", ["side view of user"], GREEN)
pico = box(LEFT, 2, "Pico 2 W (chair)", ["seat push button"], BLUE)
thingspeak = box(RIGHT, 1, "ThingSpeak", ["online dashboard"], BLUE)
ntfy = box(RIGHT, 2, "ntfy.sh", ["phone / PC alerts"], BLUE)

# Inside the Pi
ctrl = box(COLS[0], 0, "desk_controller.py", ["sensors, actuators,", "OLED, rules"], GREEN)
ai = box(COLS[0], 1, "posture_ai.py", ["YOLO pose model"], GREEN)
logger = box(COLS[1], 0, "db_logger.py", ["snapshot every 10 s,", "posture, alerts"], GREEN)
broker = box(COLS[1], 1, "Mosquitto", ["local MQTT broker"], ORANGE)
db = box(COLS[2], 0, "MariaDB", ["history for the", "report / insights"], ORANGE)
bridge = box(COLS[2], 2, "cloud_bridge.py", ["ThingSpeak + ntfy"], GREEN)

G, B = GREEN[0], BLUE[0]
arrow((gpio["r"] + 4, gpio["cy"]), (ctrl["l"] - 4, ctrl["cy"]), G, both=True)
arrow((cam["r"] + 4, cam["cy"]), (ai["l"] - 4, ai["cy"]), G, label="USB", label_at=(408, cam["cy"] - 26))
arrow((ctrl["r"] - 20, ctrl["b"] + 4), (broker["l"] + 20, broker["t"] - 4), G, both=True,
      label="desk/*", label_at=(700, 372))
arrow((ai["r"] + 4, ai["cy"]), (broker["l"] - 4, broker["cy"]), G,
      label="desk/posture", label_at=(742, ai["cy"] - 26))
arrow((broker["cx"], broker["t"] - 4), (logger["cx"], logger["b"] + 4), G,
      label="desk/#", label_at=(broker["cx"] + 48, 370))
arrow((logger["r"] + 4, logger["cy"]), (db["l"] - 4, db["cy"]), G, label="SQL", label_at=(1077, logger["cy"] - 26))
arrow((broker["r"] - 20, broker["b"] + 4), (bridge["l"] + 20, bridge["t"] - 4), G,
      label="desk/#", label_at=(1118, 610))
arrow((pico["r"] + 4, pico["cy"] + 10), (broker["l"] + 30, broker["b"] + 4), B)
ax.text(590, 790, "Wi-Fi · MQTT\ndesk/chair/occupied", ha="center", va="center", fontsize=12,
        style="italic", color=B, linespacing=1.4)
arrow((bridge["r"] + 4, bridge["t"] + 30), (thingspeak["l"] - 4, thingspeak["b"] - 30), B,
      label="MQTT", label_at=(1452, 628))
arrow((bridge["r"] + 4, bridge["cy"] + 20), (ntfy["l"] - 4, ntfy["cy"] + 20), B,
      label="HTTPS", label_at=(1413, bridge["cy"] + 48))

fig.savefig(OUT, dpi=100, facecolor="white")
print(f"saved {OUT}")

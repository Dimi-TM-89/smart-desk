"""
db_report.py – Show what the Smart Desk stored in MariaDB (runs on the Pi 5).

The "data-driven insights" part of the project: turns the logged snapshots
into work-habit figures per day and, optionally, a chart (course lesson 8a:
read the database and display the content with matplotlib).

    python pi/db_report.py                # summary per day + latest values
    python pi/db_report.py --days 30      # longer period
    python pi/db_report.py --plot         # also save a chart of the last 24 h
    python pi/db_report.py --plot --hours 2

The chart is saved as db_report.png in the repository root (works over SSH,
no screen needed). Open it in VS Code or copy it into the report.
"""

import argparse
from datetime import timedelta
from typing import Any, Callable

import mariadb

import config
from database import Database


def print_summary(db, days):
    """Print one line per day with seated time, posture, climate and alerts."""
    rows = db.daily_summary(days)
    print(f"\nWork habits – last {days} day(s)")
    if not rows:
        print("  (no readings yet – is db_logger.py running?)")
        return
    print(f"  {'day':10}  {'seated':>8}  {'good posture':>12}  {'avg °C':>6}  {'avg lux':>7}  "
          f"{'lamp':>5}  {'fan on':>7}  {'alerts':>6}")
    for r in rows:
        good = f"{r['good_pct']:.0f} %" if r["good_pct"] is not None else "–"
        temp = f"{r['avg_temp']:.1f}" if r["avg_temp"] is not None else "–"
        lux = f"{r['avg_lux']:.0f}" if r["avg_lux"] is not None else "–"
        lamp = f"{r['avg_lamp']:.0f} %" if r["avg_lamp"] is not None else "–"
        print(f"  {str(r['day']):10}  {float(r['seated_min'] or 0):6.1f} m  {good:>12}  {temp:>6}  "
              f"{lux:>7}  {lamp:>5}  {float(r['fan_min'] or 0):5.1f} m  {r['alerts']:>6}")


def print_latest(db):
    """Print the newest snapshots and alerts."""
    print("\nLatest readings")
    for r in reversed(db.latest_readings(5)):
        print(f"  {r['ts']}  lux={r['lux']}  temp={r['temperature']}  window={r['window_pct']}  "
              f"seated={r['seated']}  posture={r['posture']}  lamp={r['lamp_pct']}  "
              f"fan={r['fan_on']}  shade={r['shade_pct']}")
    alerts = db.latest_alerts(5)
    print("\nLatest alerts")
    if not alerts:
        print("  (none)")
    for a in reversed(alerts):
        print(f"  {a['ts']}  [{a['kind']}] {a['message']}")


def with_gaps(rows):
    """Insert an empty point wherever the logger was not running, so the chart
    shows a gap there instead of a straight line across the night."""
    max_gap = timedelta(seconds=3 * config.DB_LOG_INTERVAL_S)
    result = []
    for row in rows:
        if result and row["ts"] - result[-1]["ts"] > max_gap:
            result.append({"ts": result[-1]["ts"] + max_gap / 3})   # all other values missing
        result.append(row)
    return result


def series(rows, key, convert: Callable[[Any], float] = float):
    """Values of one column for matplotlib; missing values become NaN (= no line there)."""
    nan = float("nan")
    return [nan if row.get(key) is None else convert(row[key]) for row in rows]


def save_plot(db, hours):
    """Save a chart of light, temperature, seat and posture of the last `hours` hours."""
    try:
        import matplotlib
        matplotlib.use("Agg")           # draw to a file, no screen needed
        import matplotlib.dates as mdates
        import matplotlib.pyplot as plt
    except ImportError:
        print("\nmatplotlib is not installed:  sudo apt install python3-matplotlib")
        return

    rows = db.readings_since(hours)
    if not rows:
        print(f"\nNo readings in the last {hours} h – nothing to plot.")
        return

    rows = with_gaps(rows)
    ts = [r["ts"] for r in rows]
    fig, (ax_light, ax_temp, ax_desk) = plt.subplots(3, 1, sharex=True, figsize=(10, 7))
    fig.suptitle(f"Smart Desk – last {hours} h")

    ax_light.plot(ts, series(rows, "lux"), label="desk light (lux)")
    ax_light.plot(ts, series(rows, "threshold"), "--", label="threshold (lux)")
    ax_light.set_ylabel("lux")
    ax_light.legend(loc="best", fontsize="small")

    ax_temp.plot(ts, series(rows, "temperature"), color="tab:red", label="temperature (°C)")
    ax_temp.fill_between(ts, 0, 1, where=[bool(r.get("fan_on")) for r in rows],
                         transform=ax_temp.get_xaxis_transform(), alpha=0.15, label="fan on")
    ax_temp.set_ylabel("°C")
    ax_temp.legend(loc="best", fontsize="small")

    seated = series(rows, "seated", lambda v: 1 if v else 0)
    nan = float("nan")                  # nan = no dot at that moment
    good = [1.15 if r.get("posture") == "good" else nan for r in rows]
    bad = [1.15 if r.get("posture") == "bad" else nan for r in rows]
    ax_desk.step(ts, seated, where="post", label="seated")
    ax_desk.scatter(ts, good, s=8, color="tab:green", label="good posture")
    ax_desk.scatter(ts, bad, s=8, color="tab:red", label="bad posture")
    ax_desk.set_yticks([0, 1])
    ax_desk.set_yticklabels(["empty", "seated"])
    ax_desk.set_ylim(-0.2, 1.4)
    ax_desk.legend(loc="best", ncol=3, fontsize="small")
    ax_desk.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))

    fig.tight_layout()
    out = config.REPO_ROOT / "db_report.png"
    fig.savefig(out, dpi=110)
    print(f"\nChart saved: {out}")


def main():
    """Parse the options and print the report."""
    parser = argparse.ArgumentParser(description="Smart Desk database report")
    parser.add_argument("--days", type=int, default=7, help="days in the summary (default 7)")
    parser.add_argument("--plot", action="store_true", help="also save a chart as db_report.png")
    parser.add_argument("--hours", type=int, default=24, help="hours in the chart (default 24)")
    args = parser.parse_args()

    db = Database()
    try:
        db.connect()
    except mariadb.Error as exc:
        print(f"Cannot connect to the database: {exc}  -> run python pi/tests/test_db.py")
        return
    try:
        counts = db.table_counts()
        print("Rows stored: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
        print_summary(db, args.days)
        print_latest(db)
        if args.plot:
            save_plot(db, args.hours)
    finally:
        db.close()


if __name__ == "__main__":
    main()

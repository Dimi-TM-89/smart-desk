"""
test_db.py – Check the MariaDB database of the Smart Desk (no hardware needed).

What it does:
    1. connects with DB_USER / DB_PASSWORD / DB_NAME from .env
    2. checks that the tables readings, posture and alerts exist
    3. writes one test row in every table, reads it back and deletes it again
    4. shows how many rows each table holds

Expected: four "OK" lines. Typical failures:
    "Access denied"         -> DB_PASSWORD in .env differs from the database user:
                               run scripts/setup_db.sh again (it updates the password)
    "Unknown database"      -> the database does not exist yet: run scripts/setup_db.sh
    "Can't connect"         -> MariaDB is not running: sudo systemctl start mariadb
    table missing           -> run scripts/setup_db.sh (creates the tables)

Run from the repository root:   python pi/tests/test_db.py
"""

import sys
from pathlib import Path

import mariadb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # make pi/ importable

import config  # noqa: E402
from database import Database  # noqa: E402

TABLES = ("readings", "posture", "alerts")
TEST_TEXT = "test_db.py test row"


def main():
    """Run the checks and report."""
    if not config.DB_PASSWORD:
        print("FAIL: DB_PASSWORD is empty in .env")
        return

    db = Database()
    try:
        db.connect()
    except mariadb.Error as exc:
        print(f"FAIL: cannot connect as {config.DB_USER}@{config.DB_HOST} to {config.DB_NAME}: {exc}")
        return
    print(f"OK   connected as {config.DB_USER}@{config.DB_HOST} to database {config.DB_NAME}")

    try:
        cursor = db.connection().cursor()
        cursor.execute("SHOW TABLES")
        found = {row[0] for row in cursor.fetchall()}
        missing = [t for t in TABLES if t not in found]
        if missing:
            print(f"FAIL: missing tables: {', '.join(missing)}  -> run scripts/setup_db.sh")
            return
        print(f"OK   tables present: {', '.join(TABLES)}")

        # Write one test row in every table ...
        reading_id = db.insert_reading({"lux": 123.4, "temperature": 21.5, "window_pct": 40,
                                        "threshold": 300, "presence": True, "seated": True,
                                        "seated_min": 1.5, "posture": "good", "lamp_pct": 60,
                                        "fan_on": False, "shade_pct": 0})
        posture_id = db.insert_posture("bad", 31.2)
        alert_id = db.insert_alert("other", TEST_TEXT)

        # ... read them back ...
        cursor.execute("SELECT lux, posture FROM readings WHERE id = %s", (reading_id,))
        lux, posture = cursor.fetchone()
        cursor.execute("SELECT state FROM posture WHERE id = %s", (posture_id,))
        (state,) = cursor.fetchone()
        cursor.execute("SELECT message FROM alerts WHERE id = %s", (alert_id,))
        (message,) = cursor.fetchone()
        if abs(lux - 123.4) > 0.01 or posture != "good" or state != "bad" or message != TEST_TEXT:
            print(f"FAIL: read back other values: lux={lux} posture={posture} state={state} message={message}")
        else:
            print("OK   wrote and read back a test row in every table")

        # ... and remove them again so they do not end up in the statistics
        cursor.execute("DELETE FROM readings WHERE id = %s", (reading_id,))
        cursor.execute("DELETE FROM posture WHERE id = %s", (posture_id,))
        cursor.execute("DELETE FROM alerts WHERE id = %s", (alert_id,))
        cursor.close()

        counts = db.table_counts()
        print("OK   rows stored: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    except mariadb.Error as exc:
        print(f"FAIL: {exc}")
    finally:
        db.close()


if __name__ == "__main__":
    main()

"""
database.py – Small wrapper around the Smart Desk MariaDB database.

Used by db_logger.py (writing) and db_report.py / tests/test_db.py (reading).
Uses the official MariaDB connector, as in course lesson 8a
(pip install mariadb). Connection settings come from config.py / .env.

The tables are created by scripts/setup_db.sh from db/schema.sql:
    readings – snapshot of the whole desk every DB_LOG_INTERVAL_S seconds
    posture  – one row per posture change (good / bad / none)
    alerts   – every alert that was sent

If the connection is lost (MariaDB restarted, Pi busy ...), the next write
reconnects once and tries again, so a hiccup does not stop the logger.
"""

import time

import mariadb

import config

# Columns of the readings table that db_logger.py fills, in insert order
READING_COLUMNS = ("lux", "temperature", "window_pct", "threshold", "presence", "seated",
                   "seated_min", "posture", "lamp_pct", "fan_on", "shade_pct")


class Database:
    """Connection to the smartdesk database with simple insert and query methods."""

    def __init__(self):
        """Remember the settings; call connect() before using the database."""
        self.conn = None

    # --- connection --------------------------------------------------------
    def connect(self, retries=1, delay_s=5):
        """Open the connection; try `retries` times (MariaDB may still be starting at boot).

        Raises mariadb.Error when the last attempt fails.
        """
        for attempt in range(1, retries + 1):
            try:
                self.conn = mariadb.connect(host=config.DB_HOST, user=config.DB_USER,
                                            password=config.DB_PASSWORD, database=config.DB_NAME,
                                            connect_timeout=5, autocommit=True)
                return
            except mariadb.Error as exc:
                if attempt == retries:
                    raise
                print(f"[db] cannot connect ({exc}), retry {attempt}/{retries - 1} in {delay_s} s ...")
                time.sleep(delay_s)

    def close(self):
        """Close the connection (safe to call twice)."""
        if self.conn is not None:
            try:
                self.conn.close()
            except mariadb.Error:
                pass
            self.conn = None

    def _execute(self, sql, params=()):
        """Run one write statement and return the new row id; reconnect once if the connection was lost."""
        for attempt in (1, 2):
            try:
                if self.conn is None:
                    self.connect()
                cursor = self.conn.cursor()
                cursor.execute(sql, params)
                row_id = cursor.lastrowid
                cursor.close()
                return row_id
            except mariadb.Error:
                self.close()          # forget the broken connection
                if attempt == 2:
                    raise

    def _query(self, sql, params=()):
        """Run one SELECT and return the rows as a list of dicts."""
        if self.conn is None:
            self.connect()
        cursor = self.conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        return rows

    # --- writing (db_logger.py) --------------------------------------------
    def insert_reading(self, values):
        """Insert one snapshot and return its id.

        values: dict with (some of) READING_COLUMNS; missing ones become NULL.
        """
        columns = ", ".join(READING_COLUMNS)
        placeholders = ", ".join("%s" for _ in READING_COLUMNS)
        return self._execute(f"INSERT INTO readings ({columns}) VALUES ({placeholders})",
                      tuple(values.get(c) for c in READING_COLUMNS))

    def insert_posture(self, state, angle):
        """Insert one posture change and return its id: state 'good' / 'bad' / 'none', angle in degrees or None."""
        return self._execute("INSERT INTO posture (state, angle) VALUES (%s, %s)", (state, angle))

    def insert_alert(self, kind, message):
        """Insert one sent alert and return its id: kind 'movement' / 'posture' / 'other'."""
        return self._execute("INSERT INTO alerts (kind, message) VALUES (%s, %s)", (kind, message[:255]))

    # --- reading (db_report.py, tests) -------------------------------------
    def table_counts(self):
        """Number of rows in each table, e.g. {'readings': 120, 'posture': 8, 'alerts': 2}."""
        return {t: self._query(f"SELECT COUNT(*) AS n FROM {t}")[0]["n"]
                for t in ("readings", "posture", "alerts")}

    def latest_readings(self, limit=10):
        """The newest `limit` snapshots, newest first."""
        return self._query("SELECT * FROM readings ORDER BY ts DESC, id DESC LIMIT %s", (limit,))

    def readings_since(self, hours=24):
        """All snapshots of the last `hours` hours, oldest first (for charts)."""
        return self._query("SELECT * FROM readings WHERE ts >= NOW() - INTERVAL %s HOUR "
                           "ORDER BY ts, id", (hours,))

    def latest_alerts(self, limit=10):
        """The newest `limit` alerts, newest first."""
        return self._query("SELECT * FROM alerts ORDER BY ts DESC, id DESC LIMIT %s", (limit,))

    def daily_summary(self, days=7):
        """One row per day with the work-habit figures for the report.

        Durations are counted as (number of snapshots) x DB_LOG_INTERVAL_S,
        because db_logger.py writes exactly one snapshot per interval.
            seated_min  minutes on the chair
            good_pct    share of the time with a person in view that the posture was good
            fan_min     minutes the fan was on
            alerts      alerts sent that day
        """
        step_min = config.DB_LOG_INTERVAL_S / 60
        return self._query(
            """
            SELECT r.day,
                   r.samples,
                   ROUND(r.seated_samples * %s, 1)                          AS seated_min,
                   ROUND(100 * r.good / NULLIF(r.good + r.bad, 0))         AS good_pct,
                   r.avg_temp, r.avg_lux, r.avg_lamp,
                   ROUND(r.fan_samples * %s, 1)                             AS fan_min,
                   COALESCE(a.n, 0)                                        AS alerts
            FROM (SELECT DATE(ts)                          AS day,
                         COUNT(*)                          AS samples,
                         SUM(seated = 1)                   AS seated_samples,
                         SUM(posture = 'good')             AS good,
                         SUM(posture = 'bad')              AS bad,
                         ROUND(AVG(temperature), 1)        AS avg_temp,
                         ROUND(AVG(lux))                   AS avg_lux,
                         ROUND(AVG(lamp_pct))              AS avg_lamp,
                         SUM(fan_on = 1)                   AS fan_samples
                  FROM readings
                  WHERE ts >= CURDATE() - INTERVAL %s DAY
                  GROUP BY DATE(ts)) AS r
            LEFT JOIN (SELECT DATE(ts) AS day, COUNT(*) AS n
                       FROM alerts GROUP BY DATE(ts)) AS a ON a.day = r.day
            ORDER BY r.day
            """,
            (step_min, step_min, days - 1))

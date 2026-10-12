-- ---------------------------------------------------------------------------
-- Smart Desk – MariaDB schema
--
-- Easiest: let the setup script create the database, the user and these
-- tables in one go (it takes the password from .env):
--     bash scripts/setup_db.sh
--
-- By hand (same result):
--     sudo mariadb
--     CREATE DATABASE smartdesk;
--     CREATE USER 'smartdesk'@'localhost' IDENTIFIED BY '<DB_PASSWORD from .env>';
--     GRANT ALL PRIVILEGES ON smartdesk.* TO 'smartdesk'@'localhost';
--     exit
--     mariadb -u smartdesk -p smartdesk < db/schema.sql
--
-- Written by pi/db_logger.py. No camera images are ever stored (GDPR):
-- only the posture result (good / bad / none) and the neck angle.
-- ---------------------------------------------------------------------------

-- Snapshot of the whole desk, one row every DB_LOG_INTERVAL_S seconds (10 s).
-- Because the interval is fixed, "number of rows x 10 s" gives durations,
-- e.g. seated time per day or the share of time with good posture.
CREATE TABLE IF NOT EXISTS readings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lux         FLOAT,                          -- desk light, BH1750 (lux)
    temperature FLOAT,                          -- BMP280 (°C)
    window_pct  FLOAT,                          -- window LDR via MCP3008 (0–100 %)
    threshold   FLOAT,                          -- lamp threshold set with the potentiometer (lux)
    presence    BOOLEAN,                        -- someone in the room (ultrasonic)
    seated      BOOLEAN,                        -- seat button on the Pico
    seated_min  FLOAT,                          -- minutes in the current sitting period
    posture     ENUM('good', 'bad', 'none'),    -- latest AI result
    lamp_pct    FLOAT,                          -- PWM duty of the desk lamp (0–100 %)
    fan_on      BOOLEAN,                        -- relay state
    shade_pct   FLOAT,                          -- sunshade position (0 = open, 100 = closed)
    INDEX idx_readings_ts (ts)
);

-- Posture changes from posture_ai.py: one row each time the state changes
-- (good -> bad, bad -> none, ...), so the table shows every slouch moment.
CREATE TABLE IF NOT EXISTS posture (
    id    INT AUTO_INCREMENT PRIMARY KEY,
    ts    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state ENUM('good', 'bad', 'none') NOT NULL,
    angle FLOAT,                                -- forward lean of the neck (degrees), NULL if nobody
    INDEX idx_posture_ts (ts)
);

-- Every alert that was sent to ntfy (movement reminders, posture warnings)
CREATE TABLE IF NOT EXISTS alerts (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    ts      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind    VARCHAR(20) NOT NULL,               -- 'movement', 'posture' or 'other'
    message VARCHAR(255) NOT NULL,
    INDEX idx_alerts_ts (ts)
);

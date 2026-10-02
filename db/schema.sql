-- Smart Desk – MariaDB schema
-- Create the database and user once (replace the password, use the same in .env):
--   sudo mysql -u root
--   CREATE DATABASE smartdesk;
--   CREATE USER 'smartdesk'@'localhost' IDENTIFIED BY 'change-me';
--   GRANT ALL PRIVILEGES ON smartdesk.* TO 'smartdesk'@'localhost';
-- Then load this file:
--   mysql -u smartdesk -p smartdesk < db/schema.sql

-- Environment and status, one row every DB_LOG_INTERVAL_S seconds
CREATE TABLE IF NOT EXISTS readings (
    id          INT AUTO_INCREMENT PRIMARY KEY,
    ts          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lux         FLOAT,
    temperature FLOAT,
    window_pct  FLOAT,
    presence    BOOLEAN,
    seated      BOOLEAN,
    seated_min  FLOAT,
    lamp_pct    FLOAT,
    fan_on      BOOLEAN,
    shade_pct   FLOAT
);

-- Posture results from posture_ai.py (no images are stored)
CREATE TABLE IF NOT EXISTS posture (
    id    INT AUTO_INCREMENT PRIMARY KEY,
    ts    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    state ENUM('good', 'bad', 'none') NOT NULL,
    angle FLOAT
);

-- Alerts that were sent (movement reminders, posture warnings)
CREATE TABLE IF NOT EXISTS alerts (
    id      INT AUTO_INCREMENT PRIMARY KEY,
    ts      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    kind    VARCHAR(20) NOT NULL,
    message VARCHAR(255) NOT NULL
);

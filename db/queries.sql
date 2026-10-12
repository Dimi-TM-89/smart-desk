-- ---------------------------------------------------------------------------
-- Smart Desk – handy queries for the mariadb prompt or phpMyAdmin
--     mariadb -u smartdesk -p smartdesk
-- Durations use the fixed snapshot interval: rows x 10 s (DB_LOG_INTERVAL_S).
-- ---------------------------------------------------------------------------

-- Latest 10 snapshots
SELECT * FROM readings ORDER BY ts DESC LIMIT 10;

-- Seated time and posture per day
SELECT DATE(ts)                                              AS day,
       ROUND(SUM(seated = 1) * 10 / 60, 1)                   AS seated_min,
       ROUND(100 * SUM(posture = 'good')
             / NULLIF(SUM(posture IN ('good', 'bad')), 0))   AS good_posture_pct
FROM readings
GROUP BY DATE(ts)
ORDER BY day;

-- Average climate per hour of today
SELECT HOUR(ts)                          AS hour,
       ROUND(AVG(temperature), 1)        AS avg_temp,
       ROUND(AVG(lux))                   AS avg_lux,
       ROUND(AVG(window_pct))            AS avg_window_pct,
       ROUND(SUM(fan_on = 1) * 10 / 60)  AS fan_min
FROM readings
WHERE ts >= CURDATE()
GROUP BY HOUR(ts)
ORDER BY hour;

-- How often the posture went bad, per day
SELECT DATE(ts) AS day, COUNT(*) AS times_bad, ROUND(AVG(angle), 1) AS avg_angle
FROM posture
WHERE state = 'bad'
GROUP BY DATE(ts)
ORDER BY day;

-- Alerts per day and kind
SELECT DATE(ts) AS day, kind, COUNT(*) AS n
FROM alerts
GROUP BY DATE(ts), kind
ORDER BY day, kind;

-- Clean up: delete everything older than 30 days
-- DELETE FROM readings WHERE ts < NOW() - INTERVAL 30 DAY;
-- DELETE FROM posture  WHERE ts < NOW() - INTERVAL 30 DAY;
-- DELETE FROM alerts   WHERE ts < NOW() - INTERVAL 30 DAY;

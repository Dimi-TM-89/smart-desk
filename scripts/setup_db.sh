#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# setup_db.sh – Create the Smart Desk database in MariaDB (one time).
#
# Reads DB_NAME, DB_USER and DB_PASSWORD from .env and then
#   1. creates the database and the user (or updates the user's password)
#   2. creates the tables from db/schema.sql
#
# Safe to run again: existing tables and data are kept.
#
# Usage (from the repository root, MariaDB installed by setup_pi.sh):
#   bash scripts/setup_db.sh           # create / update
#   bash scripts/setup_db.sh --reset   # DELETE all tables and data, then recreate
# ---------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO"

if [[ ! -f .env ]]; then
    echo "No .env file – run first:  cp .env.example .env  and fill in DB_PASSWORD"
    exit 1
fi

# Read one value from .env (KEY=value, surrounding quotes removed)
env_value() {
    local line
    line="$(grep -E "^$1=" .env | tail -n 1 || true)"
    line="${line#*=}"
    line="${line%\"}"; line="${line#\"}"
    line="${line%\'}"; line="${line#\'}"
    echo "$line"
}

DB_NAME="$(env_value DB_NAME)";         DB_NAME="${DB_NAME:-smartdesk}"
DB_USER="$(env_value DB_USER)";         DB_USER="${DB_USER:-smartdesk}"
DB_PASSWORD="$(env_value DB_PASSWORD)"

if [[ -z "$DB_PASSWORD" ]]; then
    echo "DB_PASSWORD is empty in .env – choose a password there first."
    exit 1
fi
if [[ ! "$DB_NAME" =~ ^[A-Za-z0-9_]+$ || ! "$DB_USER" =~ ^[A-Za-z0-9_]+$ ]]; then
    echo "DB_NAME and DB_USER may only contain letters, digits and _"
    exit 1
fi

# Escape \ and ' so any password can be used inside the SQL string
SQL_PASSWORD="${DB_PASSWORD//\\/\\\\}"
SQL_PASSWORD="${SQL_PASSWORD//\'/\\\'}"

echo "==> Checking that MariaDB runs"
if ! sudo mariadb -e "SELECT 1" > /dev/null 2>&1; then
    echo "Cannot reach MariaDB. Start it with:  sudo systemctl start mariadb"
    exit 1
fi

echo "==> Creating database '$DB_NAME' and user '$DB_USER'@'localhost'"
sudo mariadb <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$SQL_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$SQL_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL

if [[ "${1:-}" == "--reset" ]]; then
    read -r -p "Delete ALL Smart Desk data in '$DB_NAME'? Type yes: " answer
    if [[ "$answer" == "yes" ]]; then
        echo "==> Dropping the tables"
        sudo mariadb "$DB_NAME" -e "DROP TABLE IF EXISTS readings, posture, alerts;"
    else
        echo "Not reset."
    fi
fi

echo "==> Creating the tables from db/schema.sql (as $DB_USER)"
MYSQL_PWD="$DB_PASSWORD" mariadb -u "$DB_USER" "$DB_NAME" < db/schema.sql

echo "==> Tables in $DB_NAME:"
MYSQL_PWD="$DB_PASSWORD" mariadb -u "$DB_USER" "$DB_NAME" -e "SHOW TABLES;"

echo
echo "Database ready. Check it with:  python pi/tests/test_db.py"

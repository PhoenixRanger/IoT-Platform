#!/usr/bin/env bash

# Create a timestamped backup of the IoT Dashboard SQLite database.
#
# Usage:
#   scripts/backup_db.sh
#   scripts/backup_db.sh /path/to/sensor.db
#
# By default, this script backs up ./sensor.db into ./backups/.
# Run it from the project root on the Raspberry Pi.

set -u

DB_PATH="${1:-sensor.db}"
BACKUP_DIR="backups"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
DB_NAME="$(basename "$DB_PATH")"
BACKUP_PATH="$BACKUP_DIR/${DB_NAME%.db}_$TIMESTAMP.db"

fail() {
    echo "Backup failed: $1" >&2
    exit 1
}

if [ ! -f "$DB_PATH" ]; then
    fail "database file not found at $DB_PATH"
fi

mkdir -p "$BACKUP_DIR" || fail "could not create $BACKUP_DIR"

if [ -e "$BACKUP_PATH" ]; then
    fail "backup already exists at $BACKUP_PATH"
fi

cp -p "$DB_PATH" "$BACKUP_PATH" || fail "could not copy $DB_PATH to $BACKUP_PATH"

echo "Database backup created: $BACKUP_PATH"

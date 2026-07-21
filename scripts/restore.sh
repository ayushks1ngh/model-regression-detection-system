#!/bin/bash
set -euo pipefail

# PostgreSQL restore script for MRDS
# Usage: scripts/restore.sh <backup-file>

if [ $# -lt 1 ]; then
  echo "Usage: $0 <backup-file>"
  exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "${BACKUP_FILE}" ]; then
  echo "restore: backup file not found: ${BACKUP_FILE}"
  exit 1
fi

# Load connection parameters from environment or compose defaults
PGUSER="${POSTGRES_USER:-mrds}"
PGPASSWORD="${POSTGRES_PASSWORD:-mrds}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${POSTGRES_DB:-mrds}"

export PGPASSWORD PGUSER PGHOST PGPORT PGDATABASE

echo "restore: starting restore from ${BACKUP_FILE}"

# Drop existing connections and recreate
psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" -d postgres -c "
  SELECT pg_terminate_backend(pg_stat_activity.pid)
  FROM pg_stat_activity
  WHERE pg_stat_activity.datname = '${PGDATABASE}'
    AND pid <> pg_backend_pid();
"

dropdb --if-exists -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" "${PGDATABASE}"
createdb -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" "${PGDATABASE}"

if [[ "${BACKUP_FILE}" == *.gz ]]; then
  gunzip -c "${BACKUP_FILE}" | psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" "${PGDATABASE}"
else
  psql -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" "${PGDATABASE}" < "${BACKUP_FILE}"
fi

echo "restore: complete"

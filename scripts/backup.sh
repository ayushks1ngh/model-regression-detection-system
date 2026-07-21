#!/bin/bash
set -euo pipefail

# PostgreSQL backup script for MRDS
# Usage: scripts/backup.sh [output-dir]

OUTPUT_DIR="${1:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "${OUTPUT_DIR}"

# Load connection parameters from environment or compose defaults
PGUSER="${POSTGRES_USER:-mrds}"
PGPASSWORD="${POSTGRES_PASSWORD:-mrds}"
PGHOST="${PGHOST:-localhost}"
PGPORT="${PGPORT:-5432}"
PGDATABASE="${POSTGRES_DB:-mrds}"

export PGPASSWORD PGUSER PGHOST PGPORT PGDATABASE

BACKUP_FILE="${OUTPUT_DIR}/mrds_${TIMESTAMP}.sql.gz"

echo "backup: starting backup to ${BACKUP_FILE}"
pg_dump --no-owner --no-acl --compress=9 -h "${PGHOST}" -p "${PGPORT}" -U "${PGUSER}" "${PGDATABASE}" > "${BACKUP_FILE}"
echo "backup: complete (${BACKUP_FILE})"

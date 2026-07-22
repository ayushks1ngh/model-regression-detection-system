#!/bin/bash
set -e

# Wait for PostgreSQL to be ready
if [ -n "$MRDS_DATABASE_URL" ]; then
  echo "entrypoint: waiting for database..."
  until python -c "
import os, urllib.parse, socket, sys
url = urllib.parse.urlparse(os.environ['MRDS_DATABASE_URL'])
host = url.hostname or 'localhost'
port = url.port or 5432
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    s.connect((host, port))
    s.close()
    sys.exit(0)
except Exception:
    sys.exit(1)
" 2>/dev/null; do
    sleep 1
  done
  echo "entrypoint: database is ready"

  # Run migrations
  echo "entrypoint: running alembic migrations..."
  alembic upgrade head
  echo "entrypoint: migrations complete"
fi

exec "$@"

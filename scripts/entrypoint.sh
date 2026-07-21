#!/bin/bash
set -e

# Wait for PostgreSQL to be ready
if [ -n "$MRDS_DATABASE_URL" ]; then
  echo "entrypoint: waiting for database..."
  until python -c "
import urllib.parse, time
url = urllib.parse.urlparse('${MRDS_DATABASE_URL}')
host, port = url.hostname or 'localhost', url.port or 5432
import socket
s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    s.connect((host, port))
    s.close()
    exit(0)
except:
    exit(1)
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

#!/usr/bin/env python3
"""Worker health check — verifies the worker subprocess is alive via PID file or process name."""

import logging
import os
import sys

PID_FILE = "/tmp/mrds-worker.pid"

if os.path.isfile(PID_FILE):
    with open(PID_FILE) as f:
        pid = f.read().strip()
    if pid.isdigit() and os.path.isdir(f"/proc/{pid}"):
        sys.exit(0)

# Fallback: check if any process is running mrds worker
try:
    import subprocess

    result = subprocess.run(
        ["pgrep", "-f", "^mrds worker"],
        capture_output=True,
        timeout=5,
    )
    if result.returncode == 0:
        sys.exit(0)
except Exception:
    logging.getLogger(__name__).debug("pgrep fallback failed", exc_info=True)

sys.exit(1)

#!/bin/sh

set -eu

CRON_DIR="/home/node/.openclaw/cron"
DEFAULT_JOBS="/home/node/cron-jobs-default.json"
JOBS_FILE="${CRON_DIR}/jobs.json"

# Ensure cron directory exists.
mkdir -p "$CRON_DIR"

# Seed default cron jobs (scan every minute) if missing, otherwise upsert the scan job.
if [ ! -f "$JOBS_FILE" ]; then
  cp "$DEFAULT_JOBS" "$JOBS_FILE"
else
  # Upsert scan-every-minute into existing jobs.json so restarts always keep the scan job.
  python3 - "$DEFAULT_JOBS" "$JOBS_FILE" <<'PY'
import json
import sys
from pathlib import Path

default_path = Path(sys.argv[1])
jobs_path = Path(sys.argv[2])

try:
    default_data = json.loads(default_path.read_text(encoding="utf-8"))
except Exception:
    sys.exit(0)

default_job = None
for j in default_data.get("jobs", []) or []:
    if isinstance(j, dict) and j.get("id") == "scan-every-minute":
        default_job = j
        break

if not default_job:
    sys.exit(0)

try:
    existing = json.loads(jobs_path.read_text(encoding="utf-8"))
except Exception:
    existing = {}

version = existing.get("version", default_data.get("version", 1))
jobs = existing.get("jobs")
if not isinstance(jobs, list):
    jobs = []

upserted = False
for i, j in enumerate(jobs):
    if isinstance(j, dict) and j.get("id") == "scan-every-minute":
        # Preserve enabled flag if user explicitly changed it.
        enabled = j.get("enabled", default_job.get("enabled", True))
        merged = dict(default_job)
        merged["enabled"] = enabled
        jobs[i] = merged
        upserted = True
        break

if not upserted:
    jobs.append(default_job)

out = {"version": version, "jobs": jobs}
jobs_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
PY
fi

exec "$@"

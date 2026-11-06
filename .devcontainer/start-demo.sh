#!/usr/bin/env bash
set -euo pipefail

# Codespaces may attach more than once to the same running workspace.
exec 9>/tmp/real-estate-broker-demo.lock
flock -n 9 || exit 0
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
    > /tmp/real-estate-broker-demo.log 2>&1 </dev/null &

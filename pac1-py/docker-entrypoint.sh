#!/bin/bash
set -eo pipefail

mkdir -p runs
TS=$(date +%Y%m%d_%H%M%S)
LOG="runs/docker_${TS}.txt"

echo "[entrypoint] logging to ${LOG}" >&2
uv run --frozen python main.py "$@" 2>&1 | tee "${LOG}"

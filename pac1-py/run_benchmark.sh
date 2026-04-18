#!/bin/bash
# Run the full PAC1 benchmark and save the log durably so tmp cleanup
# can't destroy the results.  Usage:
#   ./run_benchmark.sh                           # use default MODEL_ID from .env
#   MODEL_ID=openai/qwen3.6:35b-a3b-q4_K_M ./run_benchmark.sh
#   ./run_benchmark.sh qwen3.5:27b-q4_K_M        # override model as arg
set -euo pipefail

cd "$(dirname "$0")"

# Allow overriding MODEL_ID via positional arg: run_benchmark.sh <model>
if [[ $# -gt 0 ]]; then
    export MODEL_ID="openai/$1"
fi

# Read MODEL_ID from .env if not set
if [[ -z "${MODEL_ID:-}" && -f .env ]]; then
    export MODEL_ID="$(grep '^MODEL_ID=' .env | cut -d= -f2-)"
fi

if [[ -z "${MODEL_ID:-}" ]]; then
    echo "ERROR: MODEL_ID not set (neither env nor .env)" >&2
    exit 1
fi

# Normalize model name for filename (strip openai/ prefix, replace : and /)
MODEL_SLUG=$(echo "$MODEL_ID" | sed 's|^openai/||; s|[:/]|_|g')
TIMESTAMP=$(date +%Y%m%d_%H%M)
OUT="runs/bench_${MODEL_SLUG}_${TIMESTAMP}.txt"

mkdir -p runs
echo "Running benchmark: $MODEL_ID"
echo "Log file: $OUT"
echo "Start time: $(date)"
echo

uv run python main.py 2>&1 | tee "$OUT"

# Save FINAL summary into a summary index file
if grep -q "FINAL:" "$OUT"; then
    FINAL=$(grep "FINAL:" "$OUT" | tail -1)
    echo "$(date +%Y-%m-%d\ %H:%M)  |  $MODEL_ID  |  $FINAL  |  log=${OUT}" \
        >> runs/summary.txt
    echo
    echo "Appended summary to runs/summary.txt:"
    tail -5 runs/summary.txt
fi

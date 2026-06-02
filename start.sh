#!/usr/bin/env bash
set -e

for dep in wf-recorder python3; do
  if ! command -v "$dep" &>/dev/null; then
    echo "Error: '$dep' is not installed."
    exit 1
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pkill -f "$SCRIPT_DIR/stream.py" 2>/dev/null || true
pkill -f "wf-recorder -c mjpeg -m mpjpeg" 2>/dev/null || true

python3 "$SCRIPT_DIR/stream.py" "$@"

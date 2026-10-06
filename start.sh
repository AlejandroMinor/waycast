#!/usr/bin/env bash
set -e

REQ=wf-recorder
for ((i = 1; i <= $#; i++)); do
  if [[ "${!i}" == "--backend" ]]; then
    j=$((i + 1))
    if [[ "${!j}" == "x11" ]]; then
      REQ=ffmpeg
    fi
  elif [[ "${!i}" == "--backend=x11" ]]; then
    REQ=ffmpeg
  fi
done

for dep in "$REQ" python3; do
  if ! command -v "$dep" &>/dev/null; then
    echo "Error: '$dep' is not installed."
    exit 1
  fi
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pkill -f "$SCRIPT_DIR/stream.py" 2>/dev/null || true
pkill -f "wf-recorder -c mjpeg -m mpjpeg" 2>/dev/null || true

python3 "$SCRIPT_DIR/stream.py" "$@"

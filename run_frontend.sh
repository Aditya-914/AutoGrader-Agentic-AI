#!/usr/bin/env bash
# Quick launcher for AutoGrader Frontend Web Interface
set -e

PORT=${1:-8000}
echo "Starting AutoGrader Web Interface on port $PORT..."
python3 server.py --port "$PORT" --open

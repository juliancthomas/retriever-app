#!/usr/bin/env bash

# Function to clean up background processes on Ctrl+C
cleanup() {
  echo ""
  echo "Stopping FastAPI and Vite..."
  kill $(jobs -p) 2>/dev/null
  wait
  echo "All processes stopped."
}

# Trap SIGINT (Ctrl+C) and SIGTERM
trap cleanup SIGINT SIGTERM

echo "Starting FastAPI backend..."
(cd app && python -m fastapi dev main.py) &

echo "Starting Vite frontend..."
(cd frontend && npm run dev) &

# Wait for background jobs to finish
wait
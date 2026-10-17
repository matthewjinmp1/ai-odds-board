#!/bin/sh
# Serve the AI Odds Board at http://localhost:3003
cd "$(dirname "$0")" && exec python3 server.py

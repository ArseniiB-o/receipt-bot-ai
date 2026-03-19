#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "========================================"
echo "  Receipt Bot"
echo "========================================"

# Activate virtual environment if present
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
elif [ -f "venv/bin/activate" ]; then
    source venv/bin/activate
fi

# Check .env
if [ ! -f ".env" ]; then
    echo "[ERROR] .env file not found!"
    echo "Copy .env.example to .env and fill in your tokens."
    exit 1
fi

# Install dependencies
pip install -r requirements.txt -q

echo "[OK] Starting bot..."
echo "Press Ctrl+C to stop"
echo
python main.py

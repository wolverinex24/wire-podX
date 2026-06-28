#!/bin/bash
# Start script for Wire-Pod External Agent Proxy Orchestrator

# Determine the script directory
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"
cd "$DIR"

# Check if venv exists and activate it
if [ -d "venv" ]; then
    echo "Activating virtual environment..."
    source venv/bin/activate
fi

# Run the python app
echo "Launching Wire-Pod External Agent Proxy Orchestrator on port 8099..."
python3 main.py

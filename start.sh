#!/bin/bash

# Startup script for Restricted Content Download Bot
# This script ensures clean session handling

echo "========================================"
echo "Starting Restricted Content Download Bot"
echo "Made by: Surya (@tataa_sumo)"
echo "========================================"

# Check if session file exists and is valid
if [ -f "idfinderpro.session" ]; then
    echo "Found existing session file..."
else
    echo "No session file found - will create new one..."
fi

# Start the bot
python3 bot.py


#!/bin/bash

# Kill all python3 processes related to bot.py
pkill -9 -f "python3.*bot.py"

# Wait a bit
sleep 2

# Clear Telegram webhook
python3 reset_webhook.py

# Wait for Telegram to release the connection
sleep 3

# Start the bot
python3 bot.py

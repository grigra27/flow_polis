#!/bin/bash

# Telegram Configuration for Backup Notifications
# This file loads Telegram bot credentials from environment variables or .env files

# Load Telegram credentials from environment variables or .env files
# Priority: Environment variables > .env.prod > .env

# Try to load from .env.prod first (production environment)
if [ -f "$(dirname "$0")/../.env.prod" ]; then
    source "$(dirname "$0")/../.env.prod"
fi

# Try to load from .env (development/local environment)
if [ -f "$(dirname "$0")/../.env" ]; then
    source "$(dirname "$0")/../.env"
fi

# Telegram Bot Token (from @BotFather)
# Set via environment variable: TELEGRAM_BOT_TOKEN
TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN:-}"

# Telegram Chat ID (channel or chat where to send notifications)
# Set via environment variable: TELEGRAM_CHAT_ID
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"

# Enable/Disable Telegram notifications (true/false)
TELEGRAM_ENABLED="${TELEGRAM_ENABLED:-false}"

# Enable/Disable file uploads to Telegram (true/false)
TELEGRAM_UPLOAD_FILES="${TELEGRAM_UPLOAD_FILES:-true}"

# Maximum file size for Telegram upload (in MB)
# Telegram Bot API limit is 50MB
TELEGRAM_MAX_FILE_SIZE="${TELEGRAM_MAX_FILE_SIZE:-45}"

# Telegram API URL (constructed from bot token)
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    TELEGRAM_API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
else
    TELEGRAM_API_URL=""
fi

# Export variables for use in other scripts
export TELEGRAM_BOT_TOKEN
export TELEGRAM_CHAT_ID
export TELEGRAM_ENABLED
export TELEGRAM_UPLOAD_FILES
export TELEGRAM_MAX_FILE_SIZE
export TELEGRAM_API_URL

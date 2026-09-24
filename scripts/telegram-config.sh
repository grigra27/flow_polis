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

# SOCKS5 proxy for reaching api.telegram.org (2026-09-24): the production
# server is in Russia, where api.telegram.org is blocked at the network
# level (DPI/SNI) — direct curl calls time out. Set to "host:port" (e.g.
# "127.0.0.1:1080") to route Telegram calls through a local SOCKS5 proxy,
# e.g. an SSH -D tunnel to a server with clean connectivity. Empty (the
# default) means "connect directly" — unaffected everywhere else (VK has
# no such block, and dev/CI environments outside Russia don't need this).
TELEGRAM_SOCKS5_PROXY="${TELEGRAM_SOCKS5_PROXY:-}"

# Telegram API URL (constructed from bot token)
if [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    TELEGRAM_API_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}"
else
    TELEGRAM_API_URL=""
fi

# VK mirror configuration (optional, for Telegram -> VK mirroring)
VK_ENABLED="${VK_ENABLED:-false}"
VK_COMMUNITY_TOKEN="${VK_COMMUNITY_TOKEN:-}"
VK_USER_ID="${VK_USER_ID:-}"

# Export variables for use in other scripts
export TELEGRAM_BOT_TOKEN
export TELEGRAM_CHAT_ID
export TELEGRAM_ENABLED
export TELEGRAM_UPLOAD_FILES
export TELEGRAM_MAX_FILE_SIZE
export TELEGRAM_API_URL
export TELEGRAM_SOCKS5_PROXY
export VK_ENABLED
export VK_COMMUNITY_TOKEN
export VK_USER_ID

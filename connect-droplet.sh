#!/bin/bash

# Quick connect script to Droplet
# Быстрое подключение к Droplet

DROPLET_IP="64.227.75.233"
DROPLET_USER="root"
APP_DIR="/opt/insurance_broker"

echo "Connecting to Droplet: $DROPLET_IP"
echo "User: $DROPLET_USER"
echo "App directory: $APP_DIR"
echo ""

ssh -t "$DROPLET_USER@$DROPLET_IP" "cd $APP_DIR && exec bash"

#!/bin/bash

# Script to monitor Docker container health
# Can be run manually or via cron for automated monitoring
# Usage: ./scripts/monitor-health.sh [--alert-email email@example.com]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
COMPOSE_FILE="docker-compose.prod.yml"
ALERT_EMAIL=""
SEND_ALERTS=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --alert-email)
            ALERT_EMAIL="$2"
            SEND_ALERTS=true
            shift 2
            ;;
        --dev)
            COMPOSE_FILE="docker-compose.dev.yml"
            shift
            ;;
        -h|--help)
            echo "Usage: $0 [--alert-email email@example.com] [--dev]"
            echo ""
            echo "Options:"
            echo "  --alert-email EMAIL  Send alerts to this email address"
            echo "  --dev                Use development compose file"
            echo "  -h, --help           Show this help message"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Check if docker-compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}Error: $COMPOSE_FILE not found${NC}"
    exit 1
fi

# Function to send alert
send_alert() {
    local subject="$1"
    local message="$2"
    
    if [ "$SEND_ALERTS" = true ] && [ -n "$ALERT_EMAIL" ]; then
        echo "$message" | mail -s "$subject" "$ALERT_EMAIL" 2>/dev/null || true
    fi
}

# Display header
echo -e "${BLUE}=== Docker Health Monitor ===${NC}"
echo -e "${BLUE}Time:${NC} $(date)"
echo -e "${BLUE}Compose file:${NC} $COMPOSE_FILE"
echo ""

# Initialize counters
TOTAL_SERVICES=0
HEALTHY_SERVICES=0
UNHEALTHY_SERVICES=0
DOWN_SERVICES=0

# Get list of services
SERVICES=$(docker compose -f "$COMPOSE_FILE" config --services 2>/dev/null)

if [ -z "$SERVICES" ]; then
    echo -e "${RED}Error: Could not get list of services${NC}"
    exit 1
fi

# Check each service
echo -e "${YELLOW}Checking service health...${NC}"
echo ""

for SERVICE in $SERVICES; do
    TOTAL_SERVICES=$((TOTAL_SERVICES + 1))
    
    # Get container name
    CONTAINER=$(docker compose -f "$COMPOSE_FILE" ps -q "$SERVICE" 2>/dev/null)
    
    if [ -z "$CONTAINER" ]; then
        echo -e "${RED}✗ $SERVICE: DOWN (container not found)${NC}"
        DOWN_SERVICES=$((DOWN_SERVICES + 1))
        send_alert "Docker Alert: $SERVICE is DOWN" "Service $SERVICE is not running"
        continue
    fi
    
    # Get container status
    STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER" 2>/dev/null)
    
    if [ "$STATUS" != "running" ]; then
        echo -e "${RED}✗ $SERVICE: $STATUS${NC}"
        DOWN_SERVICES=$((DOWN_SERVICES + 1))
        send_alert "Docker Alert: $SERVICE is $STATUS" "Service $SERVICE status: $STATUS"
        continue
    fi
    
    # Check health status if available
    HEALTH=$(docker inspect --format='{{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' "$CONTAINER" 2>/dev/null)
    
    case "$HEALTH" in
        healthy)
            echo -e "${GREEN}✓ $SERVICE: healthy${NC}"
            HEALTHY_SERVICES=$((HEALTHY_SERVICES + 1))
            ;;
        unhealthy)
            echo -e "${RED}✗ $SERVICE: unhealthy${NC}"
            UNHEALTHY_SERVICES=$((UNHEALTHY_SERVICES + 1))
            send_alert "Docker Alert: $SERVICE is UNHEALTHY" "Service $SERVICE failed health check"
            ;;
        starting)
            echo -e "${YELLOW}⟳ $SERVICE: starting${NC}"
            ;;
        no-healthcheck)
            echo -e "${GREEN}✓ $SERVICE: running (no health check)${NC}"
            HEALTHY_SERVICES=$((HEALTHY_SERVICES + 1))
            ;;
        *)
            echo -e "${YELLOW}? $SERVICE: $HEALTH${NC}"
            ;;
    esac
done

# Display summary
echo ""
echo -e "${BLUE}=== Summary ===${NC}"
echo -e "Total services: $TOTAL_SERVICES"
echo -e "${GREEN}Healthy: $HEALTHY_SERVICES${NC}"
if [ $UNHEALTHY_SERVICES -gt 0 ]; then
    echo -e "${RED}Unhealthy: $UNHEALTHY_SERVICES${NC}"
fi
if [ $DOWN_SERVICES -gt 0 ]; then
    echo -e "${RED}Down: $DOWN_SERVICES${NC}"
fi

# Check disk usage
echo ""
echo -e "${BLUE}=== Disk Usage ===${NC}"
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 80 ]; then
    echo -e "${RED}⚠ Disk usage: ${DISK_USAGE}% (WARNING: High disk usage)${NC}"
    send_alert "Docker Alert: High Disk Usage" "Disk usage is at ${DISK_USAGE}%"
else
    echo -e "${GREEN}✓ Disk usage: ${DISK_USAGE}%${NC}"
fi

# Check Docker disk usage
DOCKER_DISK=$(docker system df --format "{{.Type}}\t{{.Size}}" 2>/dev/null || echo "")
if [ -n "$DOCKER_DISK" ]; then
    echo ""
    echo -e "${BLUE}Docker disk usage:${NC}"
    echo "$DOCKER_DISK"
fi

# Exit with error if any services are unhealthy or down
if [ $UNHEALTHY_SERVICES -gt 0 ] || [ $DOWN_SERVICES -gt 0 ]; then
    echo ""
    echo -e "${RED}⚠ Some services are not healthy!${NC}"
    exit 1
else
    echo ""
    echo -e "${GREEN}✓ All services are healthy${NC}"
    exit 0
fi

#!/bin/bash

# Script to view logs from Docker containers
# Usage: ./scripts/view-logs.sh [service_name] [options]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Default compose file
COMPOSE_FILE="docker-compose.prod.yml"

# Function to display usage
usage() {
    echo -e "${BLUE}Docker Logs Viewer${NC}"
    echo ""
    echo "Usage: $0 [service_name] [options]"
    echo ""
    echo "Services:"
    echo "  web           - Django application logs"
    echo "  db            - PostgreSQL database logs"
    echo "  redis         - Redis cache logs"
    echo "  celery_worker - Celery worker logs"
    echo "  celery_beat   - Celery beat scheduler logs"
    echo "  nginx         - Nginx reverse proxy logs"
    echo "  certbot       - SSL certificate management logs"
    echo "  all           - All services logs (default)"
    echo ""
    echo "Options:"
    echo "  -f, --follow      Follow log output (like tail -f)"
    echo "  -n, --lines NUM   Number of lines to show (default: 100)"
    echo "  -t, --timestamps  Show timestamps"
    echo "  --dev             Use development compose file"
    echo "  -h, --help        Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                          # Show last 100 lines from all services"
    echo "  $0 web -f                   # Follow web service logs"
    echo "  $0 celery_worker -n 50      # Show last 50 lines from celery worker"
    echo "  $0 all -f -t                # Follow all logs with timestamps"
    echo "  $0 nginx --dev              # Show nginx logs from dev environment"
}

# Parse arguments
SERVICE="all"
FOLLOW=""
LINES="100"
TIMESTAMPS=""

while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -f|--follow)
            FOLLOW="--follow"
            shift
            ;;
        -n|--lines)
            LINES="$2"
            shift 2
            ;;
        -t|--timestamps)
            TIMESTAMPS="--timestamps"
            shift
            ;;
        --dev)
            COMPOSE_FILE="docker-compose.dev.yml"
            shift
            ;;
        web|db|redis|celery_worker|celery_beat|nginx|certbot|all)
            SERVICE="$1"
            shift
            ;;
        *)
            echo -e "${RED}Error: Unknown option $1${NC}"
            usage
            exit 1
            ;;
    esac
done

# Check if docker-compose file exists
if [ ! -f "$COMPOSE_FILE" ]; then
    echo -e "${RED}Error: $COMPOSE_FILE not found${NC}"
    exit 1
fi

# Display header
echo -e "${GREEN}=== Docker Logs Viewer ===${NC}"
echo -e "${BLUE}Compose file:${NC} $COMPOSE_FILE"
echo -e "${BLUE}Service:${NC} $SERVICE"
echo -e "${BLUE}Lines:${NC} $LINES"
echo ""

# View logs
if [ "$SERVICE" = "all" ]; then
    echo -e "${YELLOW}Showing logs from all services...${NC}"
    docker compose -f "$COMPOSE_FILE" logs --tail="$LINES" $FOLLOW $TIMESTAMPS
else
    echo -e "${YELLOW}Showing logs from $SERVICE...${NC}"
    docker compose -f "$COMPOSE_FILE" logs "$SERVICE" --tail="$LINES" $FOLLOW $TIMESTAMPS
fi

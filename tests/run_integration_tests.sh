#!/bin/bash

# Integration Test Runner for Docker Deployment
# This script sets up the environment and runs integration tests

set -e  # Exit on error

echo "=========================================="
echo "Docker Integration Test Runner"
echo "=========================================="
echo ""

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Check if Docker is running
if ! docker info > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker is not running${NC}"
    echo "Please start Docker and try again"
    exit 1
fi

echo -e "${GREEN}✓ Docker is running${NC}"

# Check if Docker Compose is available
if ! docker compose version > /dev/null 2>&1; then
    echo -e "${RED}Error: Docker Compose is not available${NC}"
    echo "Please install Docker Compose and try again"
    exit 1
fi

echo -e "${GREEN}✓ Docker Compose is available${NC}"

# Check if environment files exist
if [ ! -f ".env.prod" ]; then
    echo -e "${YELLOW}Warning: .env.prod not found${NC}"
    echo "Creating test environment file from example..."
    if [ -f ".env.prod.example" ]; then
        cp .env.prod.example .env.prod
        echo -e "${YELLOW}Please edit .env.prod with appropriate test values${NC}"
    else
        echo -e "${RED}Error: .env.prod.example not found${NC}"
        exit 1
    fi
fi

if [ ! -f ".env.prod.db" ]; then
    echo -e "${YELLOW}Warning: .env.prod.db not found${NC}"
    echo "Creating test database environment file from example..."
    if [ -f ".env.prod.db.example" ]; then
        cp .env.prod.db.example .env.prod.db
        echo -e "${YELLOW}Please edit .env.prod.db with appropriate test values${NC}"
    else
        echo -e "${RED}Error: .env.prod.db.example not found${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}✓ Environment files exist${NC}"
echo ""

# Clean up any existing test containers
echo "Cleaning up any existing test containers..."
docker compose -f docker-compose.prod.yml -p insurance_broker_test down -v > /dev/null 2>&1 || true
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""

# Run the tests
echo "=========================================="
echo "Running Integration Tests"
echo "=========================================="
echo ""

# Run tests with Python
if command -v pytest > /dev/null 2>&1; then
    echo "Running tests with pytest..."
    python -m pytest tests/test_docker_integration.py -v --tb=short
else
    echo "Running tests with unittest..."
    python tests/test_docker_integration.py
fi

TEST_EXIT_CODE=$?

echo ""
echo "=========================================="
if [ $TEST_EXIT_CODE -eq 0 ]; then
    echo -e "${GREEN}All tests passed!${NC}"
else
    echo -e "${RED}Some tests failed${NC}"
fi
echo "=========================================="

exit $TEST_EXIT_CODE

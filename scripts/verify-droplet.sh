#!/bin/bash

# Droplet Verification Script
# This script verifies that the Digital Ocean Droplet is properly configured
# Run on the Droplet: bash verify-droplet.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

PASSED=0
FAILED=0

# Check function
check() {
    local description="$1"
    local command="$2"

    echo -n "Checking $description... "

    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ PASS${NC}"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}"
        ((FAILED++))
        return 1
    fi
}

# Check with output
check_with_output() {
    local description="$1"
    local command="$2"

    echo -n "Checking $description... "

    output=$(eval "$command" 2>&1)
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ PASS${NC} ($output)"
        ((PASSED++))
        return 0
    else
        echo -e "${RED}✗ FAIL${NC}"
        ((FAILED++))
        return 1
    fi
}

echo "=========================================="
echo "Digital Ocean Droplet Verification"
echo "=========================================="
echo ""

# System checks
echo "System Checks:"
check_with_output "Ubuntu version" "lsb_release -d | grep -o 'Ubuntu 22.04'"
check "System is up to date" "apt-get update > /dev/null 2>&1"
echo ""

# Docker checks
echo "Docker Checks:"
check "Docker installed" "command -v docker"
check_with_output "Docker version" "docker --version | cut -d' ' -f3"
check "Docker service running" "systemctl is-active docker"
check "Docker service enabled" "systemctl is-enabled docker"
check "Docker can run containers" "docker run --rm hello-world"
echo ""

# Docker Compose checks
echo "Docker Compose Checks:"
check "Docker Compose installed" "command -v docker-compose"
check_with_output "Docker Compose version" "docker-compose --version | grep -oP 'version v?\K[0-9.]+'"
echo ""

# Firewall checks
echo "Firewall Checks:"
check "UFW installed" "command -v ufw"
check "UFW enabled" "ufw status | grep -q 'Status: active'"
check "Port 22 (SSH) open" "ufw status | grep -q '22/tcp.*ALLOW'"
check "Port 80 (HTTP) open" "ufw status | grep -q '80/tcp.*ALLOW'"
check "Port 443 (HTTPS) open" "ufw status | grep -q '443/tcp.*ALLOW'"
echo ""

# Directory checks
echo "Directory Checks:"
check "Application directory exists" "[ -d /opt/insurance-broker ]"
check "PostgreSQL data directory exists" "[ -d /opt/insurance-broker/postgres_data ]"
check "Redis data directory exists" "[ -d /opt/insurance-broker/redis_data ]"
check "Media directory exists" "[ -d /opt/insurance-broker/media ]"
check "Static files directory exists" "[ -d /opt/insurance-broker/staticfiles ]"
check "Certbot conf directory exists" "[ -d /opt/insurance-broker/certbot/conf ]"
check "Certbot www directory exists" "[ -d /opt/insurance-broker/certbot/www ]"
echo ""

# SSH checks
echo "SSH Checks:"
check "SSH service running" "systemctl is-active sshd"
check "SSH authorized_keys exists" "[ -f ~/.ssh/authorized_keys ]"
if [ -f ~/.ssh/github_deploy_key ]; then
    echo -e "${GREEN}✓${NC} GitHub deploy key found"
    ((PASSED++))
else
    echo -e "${YELLOW}⚠${NC} GitHub deploy key not found (run ssh-keygen to create)"
fi
echo ""

# System limits checks
echo "System Limits Checks:"
check "File descriptor limits configured" "grep -q 'nofile 65536' /etc/security/limits.conf"
check "Process limits configured" "grep -q 'nproc 65536' /etc/security/limits.conf"
check "Kernel parameters configured" "grep -q 'vm.max_map_count' /etc/sysctl.conf"
echo ""

# Network checks
echo "Network Checks:"
check "Internet connectivity" "ping -c 1 google.com"
check "DNS resolution" "nslookup google.com"
check "Can reach Docker Hub" "curl -s https://hub.docker.com > /dev/null"
echo ""

# Summary
echo "=========================================="
echo "Verification Summary"
echo "=========================================="
echo -e "Passed: ${GREEN}$PASSED${NC}"
echo -e "Failed: ${RED}$FAILED${NC}"
echo ""

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! Droplet is ready for deployment.${NC}"
    echo ""
    echo "Next steps:"
    echo "  1. Configure DNS to point onbr.site to this server"
    echo "  2. Set up GitHub Secrets for automated deployment"
    echo "  3. Deploy the application"
    exit 0
else
    echo -e "${RED}✗ Some checks failed. Please review and fix the issues.${NC}"
    echo ""
    echo "Common fixes:"
    echo "  - Run the setup script: curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/setup-droplet.sh | bash"
    echo "  - Check firewall: sudo ufw status verbose"
    echo "  - Check Docker: sudo systemctl status docker"
    exit 1
fi

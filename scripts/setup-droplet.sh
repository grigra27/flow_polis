#!/bin/bash

# Digital Ocean Droplet Setup Script
# This script automates the setup of a Ubuntu 22.04 Droplet for the Insurance Broker application
# Run as root: curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/setup-droplet.sh | bash

set -e  # Exit on any error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    log_error "Please run as root (use sudo)"
    exit 1
fi

log_info "Starting Digital Ocean Droplet setup for Insurance Broker application..."

# Step 1: Update system packages
log_info "Step 1/7: Updating system packages..."
apt-get update
apt-get upgrade -y
log_info "System packages updated successfully"

# Step 2: Install Docker
log_info "Step 2/7: Installing Docker..."

# Check if Docker is already installed
if command -v docker &> /dev/null; then
    log_warn "Docker is already installed ($(docker --version))"
else
    # Install prerequisites
    apt-get install -y \
        apt-transport-https \
        ca-certificates \
        curl \
        gnupg \
        lsb-release

    # Add Docker's official GPG key
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg

    # Set up Docker repository
    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu \
      $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null

    # Install Docker Engine
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io

    log_info "Docker installed successfully ($(docker --version))"
fi

# Step 3: Install Docker Compose
log_info "Step 3/7: Installing Docker Compose..."

# Check if Docker Compose is already installed
if command -v docker-compose &> /dev/null; then
    log_warn "Docker Compose is already installed ($(docker-compose --version))"
else
    DOCKER_COMPOSE_VERSION="2.24.0"
    curl -L "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose
    chmod +x /usr/local/bin/docker-compose

    log_info "Docker Compose installed successfully ($(docker-compose --version))"
fi

# Step 4: Configure firewall (UFW)
log_info "Step 4/7: Configuring firewall (UFW)..."

# Install UFW if not present
if ! command -v ufw &> /dev/null; then
    apt-get install -y ufw
fi

# Configure UFW rules
ufw --force enable
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'HTTP'
ufw allow 443/tcp comment 'HTTPS'

log_info "Firewall configured successfully"
ufw status verbose

# Step 5: Enable Docker auto-start
log_info "Step 5/7: Enabling Docker auto-start..."
systemctl enable docker
systemctl enable containerd

log_info "Docker services enabled for auto-start"

# Step 6: Create application directories
log_info "Step 6/7: Creating application directories..."

mkdir -p /opt/insurance-broker
mkdir -p /opt/insurance-broker/postgres_data
mkdir -p /opt/insurance-broker/redis_data
mkdir -p /opt/insurance-broker/media
mkdir -p /opt/insurance-broker/staticfiles
mkdir -p /opt/insurance-broker/certbot/conf
mkdir -p /opt/insurance-broker/certbot/www
mkdir -p /opt/insurance-broker/logs
mkdir -p /opt/insurance-broker/backups

log_info "Application directories created at /opt/insurance-broker"

# Step 7: Configure system limits for production
log_info "Step 7/7: Configuring system limits..."

# Increase file descriptor limits
if ! grep -q "insurance-broker limits" /etc/security/limits.conf; then
    cat >> /etc/security/limits.conf << EOF

# Insurance Broker application limits
* soft nofile 65536
* hard nofile 65536
* soft nproc 65536
* hard nproc 65536
EOF
    log_info "System limits configured"
else
    log_warn "System limits already configured"
fi

# Configure kernel parameters
if ! grep -q "insurance-broker sysctl" /etc/sysctl.conf; then
    cat >> /etc/sysctl.conf << EOF

# Insurance Broker application sysctl
vm.max_map_count=262144
fs.file-max=65536
EOF
    sysctl -p
    log_info "Kernel parameters configured"
else
    log_warn "Kernel parameters already configured"
fi

# Test Docker installation
log_info "Testing Docker installation..."
if docker run --rm hello-world > /dev/null 2>&1; then
    log_info "Docker test successful"
else
    log_error "Docker test failed"
    exit 1
fi

# Summary
echo ""
echo "=========================================="
log_info "Droplet setup completed successfully!"
echo "=========================================="
echo ""
echo "Installed versions:"
echo "  - Docker: $(docker --version)"
echo "  - Docker Compose: $(docker-compose --version)"
echo ""
echo "Firewall status:"
ufw status numbered
echo ""
echo "Docker service status:"
systemctl is-enabled docker
echo ""
echo "Application directory: /opt/insurance-broker"
echo ""
echo "Next steps:"
echo "  1. Configure DNS to point onbr.site to this server's IP"
echo "  2. Set up SSH keys for GitHub Actions deployment"
echo "  3. Deploy the application using the deployment script"
echo ""
echo "For SSH key setup, run:"
echo "  ssh-keygen -t ed25519 -C 'github-actions-deploy' -f ~/.ssh/github_deploy_key -N ''"
echo "  cat ~/.ssh/github_deploy_key.pub >> ~/.ssh/authorized_keys"
echo "  cat ~/.ssh/github_deploy_key  # Add this to GitHub Secrets as SSH_PRIVATE_KEY"
echo ""

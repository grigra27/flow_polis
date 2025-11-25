# Digital Ocean Droplet Setup Guide

This guide walks you through setting up a Digital Ocean Droplet for the Insurance Broker application.

## Prerequisites

- Digital Ocean account
- SSH key pair generated on your local machine
- Domain `onbr.site` registered and ready for DNS configuration

## Step 1: Create Droplet

1. Log in to [Digital Ocean](https://cloud.digitalocean.com/)
2. Click "Create" → "Droplets"
3. Choose the following configuration:
   - **Image**: Ubuntu 22.04 (LTS) x64
   - **Plan**: Basic
   - **CPU options**: Regular (2 GB RAM / 1 CPU recommended minimum)
   - **Datacenter region**: Choose closest to your users
   - **Authentication**: SSH keys (add your public key)
   - **Hostname**: `insurance-broker-prod` (or your preference)
   - **Tags**: `production`, `insurance-broker`

4. Click "Create Droplet"
5. Note the IP address once the Droplet is created

## Step 2: Initial Server Setup

Once your Droplet is created, SSH into it:

```bash
ssh root@YOUR_DROPLET_IP
```

### Update System Packages

```bash
apt-get update
apt-get upgrade -y
```

### Create Non-Root User (Optional but Recommended)

```bash
adduser deploy
usermod -aG sudo deploy
```

Copy SSH keys to new user:
```bash
rsync --archive --chown=deploy:deploy ~/.ssh /home/deploy
```

## Step 3: Install Docker

Run the automated setup script from this repository:

```bash
# Download and run the setup script
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/setup-droplet.sh | bash
```

Or follow manual installation steps below.

### Manual Docker Installation

```bash
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

# Verify Docker installation
docker --version
```

## Step 4: Install Docker Compose

```bash
# Download Docker Compose
DOCKER_COMPOSE_VERSION="2.24.0"
curl -L "https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose

# Make it executable
chmod +x /usr/local/bin/docker-compose

# Verify installation
docker-compose --version
```

## Step 5: Configure Firewall (UFW)

```bash
# Enable UFW
ufw --force enable

# Allow SSH (IMPORTANT: Do this first!)
ufw allow 22/tcp

# Allow HTTP
ufw allow 80/tcp

# Allow HTTPS
ufw allow 443/tcp

# Check status
ufw status verbose
```

Expected output:
```
Status: active

To                         Action      From
--                         ------      ----
22/tcp                     ALLOW       Anywhere
80/tcp                     ALLOW       Anywhere
443/tcp                    ALLOW       Anywhere
22/tcp (v6)                ALLOW       Anywhere (v6)
80/tcp (v6)                ALLOW       Anywhere (v6)
443/tcp (v6)                ALLOW       Anywhere (v6)
```

## Step 6: Configure Docker Auto-start

```bash
# Enable Docker service to start on boot
systemctl enable docker

# Enable containerd service
systemctl enable containerd

# Verify services are enabled
systemctl is-enabled docker
systemctl is-enabled containerd
```

Both should return `enabled`.

## Step 7: Add User to Docker Group (Optional)

If you created a non-root user:

```bash
usermod -aG docker deploy
```

Log out and back in for changes to take effect.

## Step 8: Create Application Directory

```bash
# Create directory for the application
mkdir -p /opt/insurance-broker
chown -R deploy:deploy /opt/insurance-broker  # If using non-root user

# Create directories for persistent data
mkdir -p /opt/insurance-broker/postgres_data
mkdir -p /opt/insurance-broker/redis_data
mkdir -p /opt/insurance-broker/media
mkdir -p /opt/insurance-broker/staticfiles
mkdir -p /opt/insurance-broker/certbot/conf
mkdir -p /opt/insurance-broker/certbot/www
```

## Step 9: Configure SSH for GitHub Actions

### Generate Deploy Key on Droplet

```bash
# Generate SSH key for deployments
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy_key -N ""

# Display the public key (add this to authorized_keys)
cat ~/.ssh/github_deploy_key.pub >> ~/.ssh/authorized_keys

# Display the private key (add this to GitHub Secrets)
cat ~/.ssh/github_deploy_key
```

Copy the **private key** output and add it to GitHub Secrets as `SSH_PRIVATE_KEY`.

## Step 10: Test Docker Installation

```bash
# Run a test container
docker run hello-world

# Check Docker info
docker info

# Check Docker Compose
docker-compose version
```

## Step 11: Configure System Limits (Optional but Recommended)

For production workloads, increase system limits:

```bash
# Edit limits.conf
cat >> /etc/security/limits.conf << EOF
* soft nofile 65536
* hard nofile 65536
* soft nproc 65536
* hard nproc 65536
EOF

# Edit sysctl.conf
cat >> /etc/sysctl.conf << EOF
vm.max_map_count=262144
fs.file-max=65536
EOF

# Apply changes
sysctl -p
```

## Verification Checklist

Run through this checklist to ensure everything is set up correctly:

- [ ] Droplet created with Ubuntu 22.04
- [ ] Can SSH into Droplet
- [ ] Docker installed and running (`docker --version`)
- [ ] Docker Compose installed (`docker-compose --version`)
- [ ] UFW firewall enabled with ports 22, 80, 443 open
- [ ] Docker service enabled for auto-start (`systemctl is-enabled docker`)
- [ ] Application directory created at `/opt/insurance-broker`
- [ ] SSH keys configured for GitHub Actions
- [ ] Test container runs successfully (`docker run hello-world`)

## Next Steps

After completing this setup:

1. Configure DNS (Task 18) - Point `onbr.site` to your Droplet IP
2. Deploy the application (Task 19)
3. Set up SSL certificates with Let's Encrypt

## Troubleshooting

### Cannot SSH into Droplet

- Verify the IP address is correct
- Ensure your SSH key was added during Droplet creation
- Check that port 22 is not blocked by your local firewall

### Docker commands require sudo

- Add your user to the docker group: `usermod -aG docker $USER`
- Log out and back in

### UFW blocks SSH connection

If you accidentally lock yourself out:
- Use Digital Ocean's web console (Droplet → Access → Launch Console)
- Run: `ufw allow 22/tcp && ufw reload`

### Docker service won't start

```bash
# Check Docker service status
systemctl status docker

# View Docker logs
journalctl -u docker.service

# Restart Docker
systemctl restart docker
```

## Security Recommendations

1. **Disable root login via SSH** (after setting up non-root user):
   ```bash
   # Edit SSH config
   nano /etc/ssh/sshd_config
   # Set: PermitRootLogin no
   systemctl restart sshd
   ```

2. **Install fail2ban** to prevent brute force attacks:
   ```bash
   apt-get install -y fail2ban
   systemctl enable fail2ban
   systemctl start fail2ban
   ```

3. **Enable automatic security updates**:
   ```bash
   apt-get install -y unattended-upgrades
   dpkg-reconfigure -plow unattended-upgrades
   ```

4. **Set up monitoring** (optional):
   - Digital Ocean Monitoring (free)
   - Install monitoring agents as needed

## Resources

- [Digital Ocean Documentation](https://docs.digitalocean.com/)
- [Docker Documentation](https://docs.docker.com/)
- [UFW Documentation](https://help.ubuntu.com/community/UFW)

# Digital Ocean Droplet Quick Start

This is a quick reference guide for setting up your Digital Ocean Droplet. For detailed instructions, see [DROPLET_SETUP.md](./DROPLET_SETUP.md).

## Quick Setup (5 minutes)

### 1. Create Droplet on Digital Ocean

- Go to https://cloud.digitalocean.com/
- Click **Create** → **Droplets**
- Select **Ubuntu 22.04 LTS**
- Choose plan (minimum 2GB RAM recommended)
- Add your SSH key
- Click **Create Droplet**
- Note the IP address

### 2. SSH into Droplet

```bash
ssh root@YOUR_DROPLET_IP
```

### 3. Run Automated Setup Script

```bash
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/setup-droplet.sh | bash
```

This script will:
- ✓ Update system packages
- ✓ Install Docker
- ✓ Install Docker Compose
- ✓ Configure firewall (UFW)
- ✓ Enable Docker auto-start
- ✓ Create application directories
- ✓ Configure system limits

### 4. Set Up SSH Keys for GitHub Actions

```bash
# Generate deploy key
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy_key -N ""

# Add public key to authorized_keys
cat ~/.ssh/github_deploy_key.pub >> ~/.ssh/authorized_keys

# Display private key (copy this to GitHub Secrets)
cat ~/.ssh/github_deploy_key
```

**Important:** Copy the private key output and add it to GitHub repository:
- Go to your GitHub repository
- Settings → Secrets and variables → Actions
- New repository secret
- Name: `SSH_PRIVATE_KEY`
- Value: (paste the private key)

### 5. Verify Setup

```bash
# Download and run verification script
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/verify-droplet.sh | bash
```

All checks should pass ✓

## GitHub Secrets Required

Add these secrets to your GitHub repository (Settings → Secrets and variables → Actions):

| Secret Name | Description | Example |
|------------|-------------|---------|
| `SSH_PRIVATE_KEY` | Private key from step 4 | `-----BEGIN OPENSSH PRIVATE KEY-----...` |
| `DROPLET_HOST` | Droplet IP address | `164.92.123.45` |
| `DROPLET_USER` | SSH user (usually `root`) | `root` |

## Firewall Ports

The following ports are configured:

| Port | Protocol | Purpose |
|------|----------|---------|
| 22 | TCP | SSH access |
| 80 | TCP | HTTP (redirects to HTTPS) |
| 443 | TCP | HTTPS |

## Application Directory Structure

```
/opt/insurance-broker/
├── postgres_data/      # PostgreSQL data
├── redis_data/         # Redis data
├── media/              # User uploaded files
├── staticfiles/        # Static assets
├── certbot/
│   ├── conf/          # SSL certificates
│   └── www/           # ACME challenge
├── logs/              # Application logs
└── backups/           # Database backups
```

## Verification Checklist

- [ ] Droplet created with Ubuntu 22.04
- [ ] Can SSH into Droplet
- [ ] Docker installed (`docker --version`)
- [ ] Docker Compose installed (`docker-compose --version`)
- [ ] Firewall configured (`ufw status`)
- [ ] Docker auto-start enabled (`systemctl is-enabled docker`)
- [ ] Application directories created
- [ ] SSH keys configured for GitHub Actions
- [ ] GitHub Secrets added
- [ ] Verification script passes

## Next Steps

1. **Configure DNS** (Task 18)
   - Add A record: `onbr.site` → `YOUR_DROPLET_IP`
   - Add A record: `www.onbr.site` → `YOUR_DROPLET_IP`

2. **Deploy Application** (Task 19)
   - Push code to `main` branch
   - GitHub Actions will automatically deploy

3. **Set Up SSL**
   - SSL certificates will be obtained automatically during first deployment

## Troubleshooting

### Can't SSH into Droplet
```bash
# Check if SSH key is correct
ssh -v root@YOUR_DROPLET_IP

# Use Digital Ocean web console if locked out
# Droplet → Access → Launch Console
```

### Docker not working
```bash
# Check Docker status
systemctl status docker

# Restart Docker
systemctl restart docker

# View Docker logs
journalctl -u docker.service -n 50
```

### Firewall issues
```bash
# Check firewall status
ufw status verbose

# Reset firewall (careful!)
ufw --force reset
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable
```

### Verification script fails
```bash
# Re-run setup script
curl -fsSL https://raw.githubusercontent.com/YOUR_USERNAME/YOUR_REPO/main/scripts/setup-droplet.sh | bash

# Check specific component
docker --version
docker-compose --version
ufw status
```

## Useful Commands

```bash
# Check Docker status
systemctl status docker

# View running containers
docker ps

# View Docker logs
docker logs CONTAINER_NAME

# Check disk space
df -h

# Check memory usage
free -h

# Check system resources
htop

# View firewall rules
ufw status numbered

# Check open ports
netstat -tulpn
```

## Security Recommendations

After basic setup, consider:

1. **Disable root login** (after creating non-root user)
2. **Install fail2ban** for brute force protection
3. **Enable automatic security updates**
4. **Set up monitoring** (Digital Ocean Monitoring is free)
5. **Configure regular backups**

See [DROPLET_SETUP.md](./DROPLET_SETUP.md) for detailed security instructions.

## Support

- [Digital Ocean Documentation](https://docs.digitalocean.com/)
- [Docker Documentation](https://docs.docker.com/)
- [Project Documentation](../README.md)

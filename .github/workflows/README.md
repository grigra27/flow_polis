# GitHub Actions CI/CD Workflow

## Overview

This workflow automatically deploys the Insurance Broker application to Digital Ocean when code is pushed to the `main` branch.

## Workflow Steps

1. **Validate** - Validates docker-compose syntax and checks for required files
2. **Build** - Builds the Docker image and tests it
3. **Deploy** - Deploys to Digital Ocean Droplet via SSH
4. **Run Migrations** - Executes database migrations and collects static files
5. **Health Check** - Verifies all containers are running properly
6. **Notify** - Reports deployment status
7. **Rollback** - Automatically rolls back on failure

## Required GitHub Secrets

Before the workflow can run, you need to configure the following secrets in your GitHub repository:

### Setting up GitHub Secrets

1. Go to your GitHub repository
2. Click on **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** for each of the following:

### Required Secrets

#### `SSH_PRIVATE_KEY`
Your SSH private key for connecting to the Digital Ocean Droplet.

**How to generate:**
```bash
# On your local machine
ssh-keygen -t ed25519 -C "github-actions-deploy" -f ~/.ssh/github_deploy_key

# Copy the private key (this goes into GitHub Secrets)
cat ~/.ssh/github_deploy_key

# Copy the public key to your Droplet
ssh-copy-id -i ~/.ssh/github_deploy_key.pub user@your-droplet-ip
```

**Value:** The entire contents of the private key file, including:
```
-----BEGIN OPENSSH PRIVATE KEY-----
...
-----END OPENSSH PRIVATE KEY-----
```

#### `DROPLET_HOST`
The IP address or domain name of your Digital Ocean Droplet.

**Example:** `123.45.67.89` or `onbr.site`

#### `DROPLET_USER`
The SSH user for connecting to the Droplet.

**Example:** `root` or `ubuntu` or your custom user

### Optional Secrets

You may want to add additional secrets for:
- Database passwords
- Django SECRET_KEY
- Email credentials
- API keys

These can be passed to the deployment process as needed.

## Manual Deployment

You can also trigger the deployment manually:

1. Go to **Actions** tab in your GitHub repository
2. Select **Deploy to Production** workflow
3. Click **Run workflow**
4. Select the `main` branch
5. Click **Run workflow**

## Monitoring Deployments

### View Deployment Status

1. Go to the **Actions** tab in your repository
2. Click on the latest workflow run
3. View the logs for each step

### Common Issues

#### SSH Connection Failed
- Verify `SSH_PRIVATE_KEY` is correctly set
- Verify `DROPLET_HOST` and `DROPLET_USER` are correct
- Check that the public key is in `~/.ssh/authorized_keys` on the Droplet

#### Docker Build Failed
- Check the Dockerfile syntax
- Verify all dependencies in requirements.prod.txt are valid
- Check the build logs in the Actions tab

#### Migration Failed
- Check database connectivity
- Verify database credentials in .env.prod on the server
- Review migration files for errors

#### Container Health Check Failed
- Check container logs: `docker-compose -f docker-compose.prod.yml logs`
- Verify all environment variables are set correctly
- Check if ports are available

## Rollback

If a deployment fails, the workflow automatically attempts to rollback to the previous version. You can also manually rollback:

```bash
# SSH into your Droplet
ssh user@your-droplet-ip

# Navigate to the project directory
cd ~/insurance_broker

# Restart with previous images
docker-compose -f docker-compose.prod.yml down
docker-compose -f docker-compose.prod.yml up -d
```

## Testing Locally

Before pushing to `main`, test the deployment process locally:

```bash
# Validate docker-compose syntax
docker-compose -f docker-compose.prod.yml config

# Build the image
docker build -t insurance-broker:test .

# Test the image
docker run --rm insurance-broker:test python --version
```

## Workflow Customization

### Change Deployment Branch

To deploy from a different branch, edit `.github/workflows/deploy.yml`:

```yaml
on:
  push:
    branches:
      - production  # Change from 'main' to your branch
```

### Add Staging Environment

Create a separate workflow file `.github/workflows/deploy-staging.yml` with:
- Different branch trigger (e.g., `develop`)
- Different server secrets (e.g., `STAGING_DROPLET_HOST`)
- Same deployment steps

### Add Slack/Discord Notifications

Add a notification step at the end:

```yaml
- name: Notify Slack
  if: always()
  uses: 8398a7/action-slack@v3
  with:
    status: ${{ job.status }}
    webhook_url: ${{ secrets.SLACK_WEBHOOK }}
```

## Security Best Practices

1. **Never commit secrets** - Always use GitHub Secrets
2. **Rotate SSH keys regularly** - Update keys every 90 days
3. **Use least privilege** - Create a dedicated deploy user on the Droplet
4. **Enable 2FA** - Enable two-factor authentication on GitHub
5. **Review logs** - Regularly check deployment logs for suspicious activity

## Support

If you encounter issues with the deployment workflow:

1. Check the Actions logs for detailed error messages
2. Verify all secrets are correctly configured
3. Test SSH connection manually: `ssh -i ~/.ssh/deploy_key user@droplet-ip`
4. Review the deployment documentation in `docs/DEPLOYMENT.md`

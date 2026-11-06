# GitHub Actions CI/CD Workflow

## Overview

This workflow automatically deploys the Insurance Broker application to Timeweb Cloud when code is pushed to the `main` branch.

## Workflow Steps

1. **Validate and test** - Validates Compose syntax and required files, then runs the full pytest suite before building.
2. **Build once in CI** - Builds one `linux/amd64` application image tagged `insurance-broker:<commit SHA>-<run_id>-<run_attempt>` and labelled with the source revision. The image passes the Python smoke check and a Kombu JSON publish/consume round trip against a disposable Redis in an isolated network. CI exports this tested image as `image.tar.gz`, its SHA-256 checksum and `manifest.json`, then uploads the bundle as a short-lived workflow artifact.
3. **Preflight** - Requires the Docker Compose plugin >= 2.20 (newer major versions are accepted; production has v5.6.0), confirms project `insurance_broker` and existing volumes, then saves the running application image IDs, immutable per-run rollback tags, Compose file and nginx configuration before rsync.
4. **Deliver the release** - Downloads the artifact by the ID returned by this build job and transfers the bundle over SSH to the per-run state directory, outside the rsynced checkout. Rsync preserves production credentials, certificates, logs and user data. The state directory is `~/.local/state/onlinepolis-deploy/<run_id>-<run_attempt>/`.
5. **Verify and load on the server** - Verifies the bundle checksum, commit revision and image content identity, then loads the CI image with `docker load`. Only after verification is the image assigned to the three existing application image tags. The production Compose file has no application build blocks; no server build or dependency download is performed.
6. **Prepare the release** - Runs migrations and `collectstatic` once through noninteractive one-off containers using the loaded image, then validates nginx configuration. Docker and Compose stdin is disconnected so clients cannot consume the remaining SSH script.
7. **Activate** - Recreates the three application services, waits for readiness, then recreates nginx to refresh its bind-mounted configuration and web DNS resolution. The workflow does not stop or recreate database, Redis or certbot containers.
8. **Health check** - Requires completed activation markers and matches all three running application image IDs to the verified image loaded for this release, then inspects all seven services and verifies the HTTPS login page. Healthy old containers cannot satisfy this check; beat and certbot may have no Docker healthcheck but must be running.
9. **Recover on failure** - Restores saved configuration before activation; after activation it also restores the saved application image IDs and verifies HTTPS. Database migrations are never automatically reversed.

Runs are serialized by the `onlinepolis-production` concurrency group; a new push does not cancel an active deployment. A shared host `flock` also serializes preflight, activation, verification and recovery if a remote shell survives a lost SSH connection. Production commands use `docker compose --compatibility -p insurance_broker --env-file .env.prod -f docker-compose.prod.yml`. The explicit project and application image names preserve the existing infrastructure namespace. Legacy `docker-compose` v1 is retained for older read/exec scripts; it is not the deployment CLI.

## CI Image Artifact

The deploy job downloads the exact artifact ID exported by the build job, rather than searching by a reusable name or fetching a mutable registry tag. The bundle contains `image.tar.gz`, `image.tar.gz.sha256` and `manifest.json`; the manifest binds the archive to the source commit, immutable image reference, target platform and image content identity. Deployment checks these values before retagging or switching application services.

The exported archive config is compared with the smoke-tested local image's filesystem layer digests and runtime settings. A Buildx config digest is also checked when the driver provides it. The SHA-256 of the saved image config is the portable identity: native Docker image IDs can differ between classic and containerd image stores. Production records its own loaded image ID and requires all three running application services to use that ID.

The artifact is retained for two days and uploaded without an additional compression layer because the Docker archive is already gzip-compressed. A retry of a failed deploy can reuse the successful build job's artifact. After artifact expiry, rerun the full workflow to build and validate a fresh bundle for that commit. Production still keeps its separately tagged rollback images and per-run recovery files.

## Required GitHub Secrets

Before the workflow can run, you need to configure the following secrets in your GitHub repository:

### Setting up GitHub Secrets

1. Go to your GitHub repository
2. Click on **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** for each of the following:

### Required Secrets

#### `SSH_PRIVATE_KEY`
Your SSH private key for connecting to the Timeweb Cloud Droplet.

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
The IP address or domain name of your Timeweb Cloud Droplet.

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
- Check container logs from the prepared production shell: `docker compose --compatibility -p insurance_broker --env-file .env.prod -f docker-compose.prod.yml logs --tail=50`
- Verify all environment variables are set correctly
- Check if ports are available

## Recovery

Before copying files, preflight saves Compose/nginx configuration and the IDs of the three running application images under `~/.local/state/onlinepolis-deploy/<run_id>-<run_attempt>/`. Each running application image receives an immutable `onlinepolis-rollback:<run_id>-<run_attempt>-<service>` tag so the current release remains available after loading a new CI artifact.

If preflight fails, release files and containers have not changed. If a later failure happens before activation, recovery restores the saved configuration and legacy image tags and leaves the old containers running. If activation has started, recovery restores the saved Compose/nginx configuration, recreates only the three application services with the saved images, recreates nginx, compares actual image IDs with the snapshot and checks the HTTPS login page. A release that already passed final health checks is not rolled back because a later notification failed.

Recovery does not downgrade the database or restore media/static content. An incompatible migration may require manual database recovery. Keep the per-run artifacts until the release is accepted; the workflow does not automatically delete tagged rollback images. The failed deployment remains a failed workflow run even when recovery succeeds.

For read-only inspection on the production server:

```bash
cd /root/insurance_broker
set +x
set -a
source .env.prod
set +a
docker compose version
docker compose --compatibility -p insurance_broker --env-file .env.prod -f docker-compose.prod.yml ps
```

## Testing Locally

Before pushing to `main`, run the project tests and image smoke check:

```bash
pytest --tb=short
docker build -t insurance-broker:test .
docker run --rm --entrypoint python insurance-broker:test --version
```

When a local `.env.prod` has been prepared separately, validate Compose without printing expanded secrets:

```bash
set +x
set -a
source .env.prod
set +a
docker compose --compatibility -p insurance_broker --env-file .env.prod -f docker-compose.prod.yml config --quiet
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
4. Review the deployment documentation in `docs/DEPLOYMENT_QUICK_REFERENCE.md`

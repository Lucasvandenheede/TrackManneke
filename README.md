# TrackManneke

Discord bot with two runtime modes:

- Development: local run with `.env`
- Production: Docker image run with `.env.production`

## Local Development (dev branch)

1. Install dependencies:
   `pip install -r requirements.txt`
2. Ensure `.env` exists at repository root.
3. Run locally:
   `python src/main.py`

By default, the bot loads `.env` because `APP_ENV` defaults to `development`.

## Production Build (master + release tag)

The GitHub Actions workflow builds and pushes a production image only when you push a tag matching `v*` and that tag points to a commit on `master`.

Workflow file:

- `.github/workflows/deploy.yml`

It builds with:

- `--build-arg ENV_FILE=.env.production`

Before the image build, the workflow writes `.env.production` from the `ENV_PRODUCTION` GitHub secret.

And tags/pushes to Google Artifact Registry as:

- `<region>-docker.pkg.dev/<project>/<repo>/trackmanneke:<tag>`
- `<region>-docker.pkg.dev/<project>/<repo>/trackmanneke:latest`

## Required GitHub Variables and Secrets

Repository variables:

- `GCP_REGION`
- `GCP_PROJECT_ID`
- `GAR_REPOSITORY`

Repository secrets:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_SERVICE_ACCOUNT`
- `ENV_PRODUCTION` (full multi-line `.env.production` contents)

## Environment Selection Logic

`src/config.py` loads dotenv in this order:

1. `ENV_FILE` if explicitly set
2. `.env.production` when `APP_ENV=production`
3. `.env` otherwise

This gives you local dev with test-server credentials and production releases with production credentials.

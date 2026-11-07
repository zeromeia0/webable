# Webable deployment and updates

Advanced setup for people self-hosting or maintaining Webable. For a normal install, see the [README](README.md).

## Compose files

| File | Use |
|------|-----|
| `docker-compose.yml` | Builds from source. This is the default (`make run`). |
| `docker-compose.ai.yml` | Optional Ollama overlay (`make ai`, `make ai-run`). |
| `docker-compose.image.yml` | Pulls the prebuilt image from GHCR, no local build (`make up-image`). |
| `docker-compose.watchtower.yml` | Optional Watchtower sidecar for automatic image updates (`make up-watchtower`). |

## Prebuilt images (GHCR)

The `VERSION` file at the repo root sets the default image tag. `make up-image` passes it as `WEBABLE_VERSION`, or you can set it yourself:

```bash
WEBABLE_VERSION=1.0.0 docker compose -f docker-compose.image.yml up -d
```

- **Automatic updates:** add the Watchtower file. Watchtower only recreates containers labelled `com.centurylinklabs.watchtower.enable=true`, and the `webable` service already has that label.
  ```bash
  WEBABLE_VERSION=1.0.0 docker compose -f docker-compose.image.yml -f docker-compose.watchtower.yml up -d
  ```
- **Rollback:** set `WEBABLE_VERSION` to an older tag (or pin a digest in `docker-compose.image.yml`) and run `docker compose up -d`.

Your data stays in `./data` on the host either way.

## In-app updates

Webable checks whether GitHub `main` is ahead of the running build. It does this once shortly after startup and caches the result for `WEBABLE_UPDATE_CACHE_TTL` seconds (default 300). If it finds a newer build, it shows a dialog with release notes from `update.md`. When the machine is offline, the check is skipped.

How an update gets applied depends on how Webable was installed:

| Install type | How updates apply |
|--------------|-------------------|
| **Git clone** (has `.git`) | With `WEBABLE_AUTO_UPDATE=1`, the in-app button runs `git pull --ff-only origin main`. It never runs `git clean` or touches `data/`. To restart the container afterwards, also set `WEBABLE_GIT_UPDATE_USE_COMPOSE_RESTART=1` and `WEBABLE_DOCKER_COMPOSE_PATH`. Otherwise, restart the process yourself. |
| **Image** (no `.git`) | Updated from outside the app (Watchtower, Kubernetes, `docker compose pull`). Alternatively, set `WEBABLE_ALLOW_IMAGE_SELF_UPDATE=1` plus `WEBABLE_DOCKER_COMPOSE_PATH` on a host with the Docker CLI and socket. |

Set `WEBABLE_EXPECT_EXTERNAL_UPDATER=1` when Watchtower or something similar handles updates. The UI will then explain that one-click updates may not apply immediately.

The standard Docker image has no `.git`, so it can't detect its own commit. Pass the commit at build time so update detection works:

```bash
WEBABLE_GIT_COMMIT="$(git rev-parse HEAD)" docker compose build --no-cache
docker compose up -d
```

To raise the GitHub API rate limit, set `WEBABLE_GITHUB_TOKEN` (or `GITHUB_TOKEN`).

### Update API

| Endpoint | Returns |
|----------|---------|
| `GET /api/build-info` | Version, commit, build ID and time, channel, deployment mode, update capability flags |
| `GET /api/update/status` | GitHub comparison and orchestration state (phase, message, errors) |
| `POST /api/update/start` | Starts a one-click update job, if the deployment supports it (signed-in users only) |

## Restart button helper (Linux)

The in-app **Restart server** button needs a host-side systemd helper:

```bash
sudo make install-restart-helper     # install and start
sudo make uninstall-restart-helper   # remove
make restart-helper-logs             # follow its logs
```

## AI configuration

`make ai` sets these environment variables on the Webable container:

| Variable | Value |
|----------|-------|
| `WEBABLE_AI_ENABLED` | `1` |
| `OLLAMA_BASE_URL` | `http://ollama:11434` |
| `OLLAMA_MODEL` | `minimax-m2.5:cloud` |

When running uvicorn without Docker, use `OLLAMA_BASE_URL=http://127.0.0.1:11434` instead. `GET /api/ai/status` reports whether AI is configured.

## Release checklist

1. Bump `VERSION` and write the user-facing notes in `update.md`.
2. Merge to `main`, then push a version tag (for example `git tag v1.1.0 && git push --tags`). Pushing a tag is what makes the GitHub workflow build and publish the Docker image.
3. Build or deploy with `WEBABLE_GIT_COMMIT` set to the released SHA.

## GitHub Pages install page

`docs/index.html` is a static install page. It doesn't run the backend and never sees any data. To publish it, go to **Settings → Pages**, choose **Deploy from a branch**, then select `main` and `/docs`.

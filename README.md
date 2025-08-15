# Media Queue Cleaner
Forked from: https://github.com/MattDGTL/sonarr-radarr-queue-cleaner

A Python script designed to monitor and clean out stalled downloads in Sonarr, Radarr, and Lidarr queues, optimized for Docker environments.

## Goals
- Keep Sonarr/Radarr/Lidarr queues healthy by removing stalled items.
- Prevent repeated retries of bad releases via blacklisting.
- Optionally trigger a new search to find a better release.
- Persist "strike" counts across runs to avoid flapping and act only when issues persist.

## How It Works
- Polls each configured service’s `/api/v3/queue` endpoint on a schedule (`API_TIMEOUT`).
- Tracks each queue item’s strike count in a persistent JSON file (`STRIKE_FILE_PATH`).
- Resets/decrements strikes only when actual download progress is detected (via `size`/`sizeleft`), and increments when items are deemed stalled.
  Optionally, torrents with very low seeders and low progress can also be treated as stalled.
- When strikes reach the per-service or global limit, the item is removed and blacklisted; if `*_AUTO_SEARCH=true`, a search command is sent to find a replacement.
- HTTP calls use a timeout and limited retries with exponential backoff (`REQUEST_TIMEOUT`, `RETRY_ATTEMPTS`, `RETRY_BACKOFF`).

## Features
- Supports Sonarr, Radarr, and Lidarr.
- Uses `aiohttp` for asynchronous API interactions.
- Configurable check interval (`general.api_timeout`, default 600s).
- Persistent strike system with file-based tracking to manage repeated stalls.
- Configurable strike reset on download progress.
- Individual service configurations allow fine‑tuned control.
  - Retries and timeouts for resilient API calls.
  - Skips strikes while items are queued/waiting for a client slot.

## Setup and Deployment
### Build Docker Image
```bash
docker build -t media-cleaner .
```

### Run Docker Container
Adjust API keys and URLs to match your setup. Services not configured with both URL and API key will be automatically ignored.

Important: For Sonarr, Radarr, and Lidarr, use the v3 API base path in your URLs (e.g., `http://sonarr:8989/api/v3`, `http://radarr:7878/api/v3`, `http://lidarr:8686/api/v3`).

```bash
docker run -d --name media-cleaner \
  -e SONARR_URL='http://sonarr:8989/api/v3' \
  -e SONARR_API_KEY='your_sonarr_api_key' \
  -e RADARR_URL='http://radarr:7878/api/v3' \
  -e RADARR_API_KEY='your_radarr_api_key' \
  -e LIDARR_URL='http://lidarr:8686/api/v3' \
  -e LIDARR_API_KEY='your_lidarr_api_key' \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config.yaml:/app/config.yaml:ro \
  media-cleaner
```

Or with docker-compose (recommended): ensure `config.yaml` and `data/` exist locally. The compose file uses an `.env` for secrets and mounts both by default.

```yaml
services:
  media-cleaner:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: media-cleaner
    env_file:
      - .env  # put secrets here (see .env.example)
    environment:
      TZ: "UTC"
    volumes:
      - "./data:/app/data"                # Strike DB path
      - "./config.yaml:/app/config.yaml:ro"  # YAML configuration
    restart: unless-stopped
```

#### Configuration Variables (environment)

- `SONARR_URL`, `RADARR_URL`, `LIDARR_URL` (optional): Service API base URLs (use v3 paths).
- `SONARR_API_KEY`, `RADARR_API_KEY`, `LIDARR_API_KEY` (optional): Service API keys.
- `CONFIG_PATH` (optional): Path to YAML configuration (default `/app/config.yaml`).

All other behavior and tuning is configured in `config.yaml` (see the `general`, `rule_engine`, `services`, and `categories` sections).

### Quickstart

1) Copy `.env.example` to `.env` and set URLs + API keys.
2) Copy `config.example.yaml` to `config.yaml` and tune the `general` and `rule_engine` sections.
3) Start with Docker or docker-compose.
4) Check logs; enable `general.debug_logging: true` for more detail.

Minimal `config.yaml` (example):

```yaml
general:
  api_timeout: 1800          # run every 30 minutes
  debug_logging: false        # set true for verbose logs
  structured_logs: true       # JSON logs for tooling
  dry_run: false              # set true to test notifications only
  strike_file_path: /app/data/strikes.json

rule_engine:
  stall_limit: 3              # strikes before removal
  max_queue_age_hours: 0      # 0 disables age-based removal
  tracker_error_strikes: 2    # remove after N tracker errors
  # Optional client rules
  client_zero_activity_minutes: 0
  client_state_as_stalled: false

notifications:
  destinations:
    - name: discord
      type: discord
      url: "https://discord.com/api/webhooks/..."
      batch: true
      reasons: ["*"]
```

#### YAML Config (rule engine, per‑service overrides, notifications, and clients)

Create a `config.yaml` (or copy `config.example.yaml`) to tune grace periods, no‑progress timeouts, per‑service throttles, notifications, and optional torrent client connections for enrichment/min‑speed/reannounce.

Notes
- Reannounce/recheck uses `downloadId` from the queue to target the torrent in the client.
- When a reannounce is scheduled, the script skips strikes/removal for that cycle.
- Use `DRY_RUN=true` to log planned removals without making changes; `EXPLAIN_DECISIONS=true` for per-item decision logs.
- Set `STRUCTURED_LOGS=true` to emit JSON logs suitable for log aggregation.
- When `notifications.destinations[].batch=true`, messages are buffered and sent as a single summary at the end of each run.




### Notifications
- Multi-destination notifications with per-reason routing and per-destination templates.
  - Destinations: `discord`, `slack`, and `generic` (HTTP JSON webhook with optional headers and raw JSON bodies).
  - Batching per destination; messages are concatenated with size guards per service.
  - Per-reason routing using `reasons` (use `*` to match all reasons).
  - Dry-run annotated automatically: adds "[DRY RUN]" for text bodies or `dryRun: true` for JSON bodies.

### Running Tests

Install dev requirements and run tests:

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

#
##### Note
Services not configured with both a valid API_KEY and URL will be ignored. Optional settings like specific stall limits can be omitted to use the global default (`GLOBAL_STALL_LIMIT`).

### CLI Utilities

Basic helper CLI is available in `cli.py`:

 - `python cli.py list` — print the current strikes JSON
 - `python cli.py clear` — clear all strikes
 - `python cli.py clear --key Sonarr:123` — clear a specific strike key
 - `python cli.py simulate item.json --service Sonarr` — print the decision reason for an example item
 - `python cli.py status` — show a summary (entries, active_strikes, indexer_entries) and the next run time based on `API_TIMEOUT`

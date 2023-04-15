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
- Configurable check intervals via `API_TIMEOUT` (default is 600 seconds).
- Persistent strike system with file-based tracking to manage repeated stalls.
- Configurable strike reset on download progress.
- Individual service configurations allow fine-tuned control.
 - Retries and timeouts for resilient API calls.
 - Strike logic skips queued/waiting items to avoid penalizing slot waits.

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
-e SONARR_API_KEY='your_sonarr_api_key' \
-e RADARR_API_KEY='your_radarr_api_key' \
-e LIDARR_API_KEY='your_lidarr_api_key' \
-e SONARR_URL='http://sonarr:8989/api/v3' \
-e RADARR_URL='http://radarr:7878/api/v3' \
-e LIDARR_URL='http://lidarr:8686/api/v3' \
-e API_TIMEOUT='3600' \
-e GLOBAL_STALL_LIMIT='3' \
-e SONARR_STALL_LIMIT='3' \
-e RADARR_STALL_LIMIT='3' \
-e LIDARR_STALL_LIMIT='3' \
-e RESET_STRIKES_ON_PROGRESS='all' \
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

#### Configuration Variables

- API_TIMEOUT: Interval between checks in seconds.
- GLOBAL_STALL_LIMIT, SONARR_STALL_LIMIT, RADARR_STALL_LIMIT, LIDARR_STALL_LIMIT: Service-specific or global strikes before considering removal.
  - You can also set `stall_limit` in `config.yaml` under `rule_engine` (default) or per-service overrides in `services:` and `categories:`.
- STRIKE_FILE_PATH: Path to persistent strike storage file (default `/app/data/strikes.json`).
- DEBUG_LOGGING: Set to `true` for verbose logs (default `false`).
- RESET_STRIKES_ON_PROGRESS: How strikes are reduced on detected progress. Use `all` to reset to 0, or an integer `N` to decrement by `N` (minimum 1). Default `all`.
- REQUEST_TIMEOUT: Per-request timeout in seconds (default `10`).
- RETRY_ATTEMPTS: Number of retry attempts for transient errors (default `2`).
- RETRY_BACKOFF: Base backoff seconds used for exponential backoff with jitter (default `1.0`).
- SONARR_AUTO_SEARCH / RADARR_AUTO_SEARCH / LIDARR_AUTO_SEARCH: When `true`, trigger a search after blacklisting a stalled item.
 - TORRENT_SEEDER_STALL_THRESHOLD: If `>= 0`, consider torrent items stalled when their seeder count is `<=` this value (default `-1`, disabled). Set to `0` to stall when there are no seeders.
 - TORRENT_SEEDER_STALL_PROGRESS_CEILING: Only apply the above when the download progress percent is `<=` this value (default `25.0`). Set to `100` to apply regardless of progress.
 - CONFIG_PATH: Optional path to YAML config file (default `/app/config.yaml`).
 - STRUCTURED_LOGS: Emit JSON logs for decisions/actions (default `true`).
 - DRY_RUN: Don’t mutate state; still send notifications annotated as "[DRY RUN]" (or `dryRun: true` for JSON) (default `false`).
 - EXPLAIN_DECISIONS: Log per-item decision events (progress, strike, remove) (default `false`).

#### YAML Config (rule engine, per-service overrides, notifications, and clients)

Create a `config.yaml` (or copy `config.example.yaml`) to tune grace periods, no-progress timeouts, per-service throttles, notifications, and optional torrent client connections for enrichment/min-speed/reannounce.

Example (`config.example.yaml`):

```yaml
rule_engine:
  grace_period_minutes: 0            # Skip strikes/removal for fresh items
  no_progress_max_age_minutes: 0     # Remove if no byte progress for this long (0 disables)
  min_request_interval_ms: 0         # Per-service throttle between API calls
  max_concurrent_requests: 0         # Per-service concurrent API calls (0 = unlimited)
  remove_from_client: true           # Also remove from client to reclaim disk
  use_blocklist_param: true          # Prefer 'blocklist' over 'blacklist' when supported
  max_queue_age_hours: 0             # Hard cap age for any incomplete item
  tracker_error_strikes: 2           # Remove after N tracker error detections
  # Min-speed stall rule (requires client integration)
  min_speed_bytes_per_sec: 0         # e.g., 51200 (50KB/s)
  min_speed_duration_minutes: 0      # Keep under threshold this long
  # Reannounce/recheck before removal for 0-seed torrents
  reannounce:
    enabled: true
    cooldown_minutes: 60
    max_attempts: 1
    do_recheck: false
    only_when_seeds_zero: true
  # Size-aware policy for large items
  large_size_gb: 20
  large_zero_seeders_remove_minutes: 30
  large_progress_ceiling_percent: 100
  # Treat certain client states as stalled (qBittorrent)
  client_state_as_stalled: false
  # Consider no peers and no seeds as stalled after X minutes (qBittorrent)
  client_zero_activity_minutes: 0

notifications:
  # Multiple destinations with per-reason routing
  destinations:
    - name: discord-default
      type: discord
      url: ""
      batch: true
      template: "Removed {service} id={id} title={title} reason={reason}"
      reasons: ["*"]
    - name: slack-errors
      type: slack
      url: ""
      batch: false
      template: "[{service}] Removed {title} (id={id}) due to {reason}"
      reasons: ["tracker_error", "indexer_failure_policy"]
    - name: generic-json
      type: generic
      url: ""
      headers:
        Authorization: "Bearer <token>"
      batch: true
      raw_json: true
      template: '{"service":"{service}","id":{id},"title":"{title}","reason":"{reason}"}'
      reasons: ["strike_limit", "max_age", "no_progress_timeout"]

services:
  Sonarr:
    grace_period_minutes: 0
    no_progress_max_age_minutes: 0
    min_request_interval_ms: 0
    max_concurrent_requests: 0
  Radarr:
    grace_period_minutes: 0
    no_progress_max_age_minutes: 0
    min_request_interval_ms: 0
    max_concurrent_requests: 0
  Lidarr:
    grace_period_minutes: 0
    no_progress_max_age_minutes: 0
    min_request_interval_ms: 0
    max_concurrent_requests: 0

indexer_policies:
  SomeIndexerName:
    seeder_stall_threshold: 0

clients:
  qbittorrent:
    url: http://qbittorrent:8080
    username: admin
    password: adminadmin
  transmission:
    url: http://transmission:9091/transmission/rpc
    username: ""
    password: ""
  deluge:
    url: http://deluge:8112/json
    username: ""     # optional for web
    password: deluge

whitelist:
  ids: []
  download_ids: []
  title_contains: []
```

Notes
- Reannounce/recheck uses `downloadId` from the queue to target the torrent in the client.
- When a reannounce is scheduled, the script skips strikes/removal for that cycle.
- Use `DRY_RUN=true` to log planned removals without making changes; `EXPLAIN_DECISIONS=true` for per-item decision logs.
- Set `STRUCTURED_LOGS=true` to emit JSON logs suitable for log aggregation.
- When `notifications.destinations[].batch=true`, messages are buffered and sent as a single summary at the end of each run.

Examples:

```bash
# Treat torrents with zero seeders and <=25% complete as stalled
-e TORRENT_SEEDER_STALL_THRESHOLD=0 \
-e TORRENT_SEEDER_STALL_PROGRESS_CEILING=25 \

# Treat torrents with <=2 seeders as stalled regardless of progress
-e TORRENT_SEEDER_STALL_THRESHOLD=2 \
-e TORRENT_SEEDER_STALL_PROGRESS_CEILING=100 \
```

#### Config Precedence

- Endpoints: `SONARR_URL`/`SONARR_API_KEY` (and similarly for Radarr/Lidarr) come from environment variables. YAML does not override these.
- Behavior: YAML values follow category > service > rule_engine precedence when evaluating settings for a specific queue item.
  - Category match is based on `categories[].title_contains` against the queue item title.
  - If no category match provides a key, the `services.<Name>` value is used; otherwise the global `rule_engine` default applies.

#### Validation & Sanitization

- Sanitization coerces numeric fields and clamps them to safe ranges (e.g., non-negative):
  - `rule_engine`: `stall_limit`, `grace_period_minutes`, `no_progress_max_age_minutes`, `min_request_interval_ms`, `max_concurrent_requests`, `max_queue_age_hours`, `tracker_error_strikes`, `min_speed_bytes_per_sec`, `min_speed_duration_minutes`, and `reannounce.{cooldown_minutes,max_attempts}`.
  - `services.*.stall_limit` is coerced to a non-negative integer when present.
  - `notifications.destinations`: invalid entries are dropped; `reasons` is normalized to a list.
- Validation emits non-fatal warnings when:
  - A service has a partial env configuration (URL without API key, or vice versa).
  - `min_request_interval_ms` is set without `max_concurrent_requests`.
  - A notification destination is missing `url`.

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

### Development
- Formatting: `black` (configured in `pyproject.toml`, line length 100)
- Linting: `ruff` (pyflakes/pycodestyle/isort rules)
- Pre-commit: install hooks with `pre-commit install` and run with `pre-commit run -a`

##### Note
Services not configured with both a valid API_KEY and URL will be ignored. Optional settings like specific stall limits can be omitted to use the global default (`GLOBAL_STALL_LIMIT`).

### CLI Utilities

Basic helper CLI is available in `cli.py`:

 - `python cli.py list` — print the current strikes JSON
 - `python cli.py clear` — clear all strikes
 - `python cli.py clear --key Sonarr:123` — clear a specific strike key
 - `python cli.py simulate item.json --service Sonarr` — print the decision reason for an example item
 - `python cli.py status` — show a summary (entries, active_strikes, indexer_entries) and the next run time based on `API_TIMEOUT`

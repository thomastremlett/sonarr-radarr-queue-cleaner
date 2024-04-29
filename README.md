# Media Queue Cleaner
Forked from: https://github.com/MattDGTL/sonarr-radarr-queue-cleaner

A Python script designed to monitor and clean out stalled downloads in Sonarr, Radarr, and Lidarr queues, optimized for Docker environments.

## Features
- Supports Sonarr, Radarr, and Lidarr.
- Uses `aiohttp` for asynchronous API interactions.
- Configurable check intervals via `API_TIMEOUT` (default is 600 seconds).
- Persistent strike system with file-based tracking to manage repeated stalls.
- Configurable strike reset on download progress.
- Individual service configurations allow fine-tuned control.

## Setup and Deployment
### Build Docker Image
```bash
docker build -t media-cleaner .
```

### Run Docker Container
*Adjust API keys and URLs to match your setup. Services not configured with both URL and API key will be automatically ignored.*

```bash
docker run -d --name media-cleaner \
-e SONARR_API_KEY='your_sonarr_api_key' \
-e RADARR_API_KEY='your_radarr_api_key' \
-e LIDARR_API_KEY='your_lidarr_api_key' \
-e SONARR_URL='http://sonarr:8989' \
-e RADARR_URL='http://radarr:7878' \
-e LIDARR_URL='http://lidarr:8686' \
-e API_TIMEOUT='3600' \
-e GLOBAL_STALL_LIMIT='3' \
-e SONARR_STALL_LIMIT='3' \
-e RADARR_STALL_LIMIT='3' \
-e LIDARR_STALL_LIMIT='3' \
-e RESET_STRIKES_ON_PROGRESS='all' \
media-cleaner
```

#### Configuration Variables

- API_TIMEOUT: Interval between checks in seconds.
- GLOBAL_STALL_LIMIT, SONARR_STALL_LIMIT, RADARR_STALL_LIMIT, LIDARR_STALL_LIMIT: Service-specific or global strikes before considering removal.
- RESET_STRIKES_ON_PROGRESS: 'all' or a specific number of strikes to reset if download shows progress.

##### Note
Services not configured with both a valid API_KEY and URL will be ignored. Optional settings like specific stall limits can be omitted to use global defaults.
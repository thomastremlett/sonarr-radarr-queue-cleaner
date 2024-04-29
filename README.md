# Sonarr-Radarr Queue Cleaner
Forked from: https://github.com/MattDGTL/sonarr-radarr-queue-cleaner

A Python script to monitor and clean out stalled downloads in Sonarr and Radarr queues, designed for Docker environments. 

## Features
- Uses `aiohttp` for asynchronous API interactions.
- Configurable check interval via `API_TIMEOUT` (default 600 seconds).
- Persistent strike system with file-based tracking to handle repeated stalls.
- Configurable strike reset on download progress.

## Setup and Deployment
### Build Docker Image
```bash
docker build -t media-cleaner .
```

### Run Docker Container
*Make sure to change the sonarr/radarr api_key and url to suit your needs*

```bash
docker run -d --name media-cleaner \
-e SONARR_API_KEY='your_sonarr_api_key' \
-e RADARR_API_KEY='your_radarr_api_key' \
-e SONARR_URL='http://sonarr:8989' \
-e RADARR_URL='http://radarr:7878' \
-e API_TIMEOUT='3600' \
-e STALL_COUNT_LIMIT='3' \
-e RESET_STRIKES_ON_PROGRESS='all' \
media-cleaner
```

#### Configuration Variables
- API_TIMEOUT: Interval between checks in seconds.
- STALL_COUNT_LIMIT: Strikes before removal.
- RESET_STRIKES_ON_PROGRESS: 'all' or number of strikes to reset if download is progressing.

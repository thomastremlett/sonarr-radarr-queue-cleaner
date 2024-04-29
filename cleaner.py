import os
import asyncio
import logging
import aiohttp
import json

# Set up logging
logging.basicConfig(
    format='%(asctime)s [%(levelname)s]: %(message)s',
    level=logging.INFO,
    handlers=[logging.StreamHandler()]
)

# Sonarr and Radarr API endpoints
SONARR_API_URL = os.environ['SONARR_URL'] + "/api/v3"
RADARR_API_URL = os.environ['RADARR_URL'] + "/api/v3"

# API key for Sonarr and Radarr
SONARR_API_KEY = os.environ['SONARR_API_KEY']
RADARR_API_KEY = os.environ['RADARR_API_KEY']

# Timeout for API requests in seconds
API_TIMEOUT = int(os.environ['API_TIMEOUT'])  # 10 minutes

# Stall count limit before removal
STALL_COUNT_LIMIT = int(os.environ.get('STALL_COUNT_LIMIT', 3))

# Number of strikes to reset when there is download progress
RESET_STRIKES_ON_PROGRESS = os.environ.get('RESET_STRIKES_ON_PROGRESS', 'all')  # 'all' or a number

# Path to the strike data file
STRIKE_FILE_PATH = '/app/data/strikes.json'  # Path on a persistent Docker volume

# Load existing strikes
def load_strikes():
    try:
        with open(STRIKE_FILE_PATH, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}  # Return an empty dictionary if no file exists or if an error occurs

# Save strikes to file
def save_strikes(strike_dict):
    with open(STRIKE_FILE_PATH, 'w') as file:
        json.dump(strike_dict, file, indent=4)

strike_dict = load_strikes()

# Async HTTP requests using aiohttp
async def make_api_request(session, url, api_key, params=None, method='get'):
    headers = {'X-Api-Key': api_key}
    try:
        async with session.request(method, url, headers=headers, params=params) as response:
            response.raise_for_status()
            return await response.json()
    except aiohttp.ClientResponseError as e:
        logging.error(f'HTTP error {e.status} making API request to {url}')
        return None
    except aiohttp.ClientPayloadError as e:
        logging.error(f'Payload error parsing JSON response from {url}: {e}')
        return None

# Reset strikes based on progress
def reset_strikes_on_progress(id):
    if RESET_STRIKES_ON_PROGRESS == 'all':
        strike_dict.pop(id, None)
    else:
        try:
            reset_amount = int(RESET_STRIKES_ON_PROGRESS)
            if id in strike_dict:
                strike_dict[id] = max(0, strike_dict[id] - reset_amount)
                if strike_dict[id] == 0:
                    strike_dict.pop(id, None)
        except ValueError:
            logging.error('RESET_STRIKES_ON_PROGRESS must be "all" or a numeric value')

# Main functions for Sonarr and Radarr download management
async def manage_downloads(session, api_url, api_key, service_name):
    logging.info(f'Checking {service_name} queue...')
    queue_url = f'{api_url}/queue'
    queue = await make_api_request(session, queue_url, api_key, {'page': '1', 'pageSize': await count_records(session, api_url, api_key)})
    if queue and 'records' in queue:
        logging.info(f'Processing {service_name} queue...')
        for item in queue['records']:
            if 'title' in item and 'status' in item and 'trackedDownloadStatus' in item:
                logging.info(f'Checking the status of {item["title"]}')
                if item['status'] in ['downloading', 'paused']:
                    reset_strikes_on_progress(item['id'])
                    save_strikes(strike_dict)
                elif item['status'] == 'warning' and item['errorMessage'] == 'The download is stalled with no connections':
                    strike_dict[item['id']] = strike_dict.get(item['id'], 0) + 1
                    if strike_dict[item['id']] >= STALL_COUNT_LIMIT:
                        logging.info(f'Removing stalled {service_name} download: {item["title"]} after reaching strike limit')
                        await make_api_request(session, f'{api_url}/queue/{item["id"]}', api_key, {'removeFromClient': 'true', 'blocklist': 'true'}, 'delete')
                        strike_dict.pop(item['id'], None)
                    else:
                        logging.info(f'Stalled download {item["title"]} has {strike_dict[item["id"]]} strikes')
                    save_strikes(strike_dict)
            else:
                logging.warning(f'Skipping item in {service_name} queue due to missing or invalid keys')
    else:
        logging.warning(f'{service_name} queue is None or missing "records" key')

async def count_records(session, api_url, api_key):
    the_url = f'{api_url}/queue'
    the_queue = await make_api_request(session, the_url, api_key)
    return the_queue['totalRecords'] if the_queue and 'records' in the_queue else 0

# Main function to loop over cleanup tasks
async def main():
    async with aiohttp.ClientSession() as session:
        while True:
            logging.info('Running media-tools script')
            await manage_downloads(session, SONARR_API_URL, SONARR_API_KEY, 'Sonarr')
            await manage_downloads(session, RADARR_API_URL, RADARR_API_KEY, 'Radarr')
            logging.info('Finished running media-tools script. Sleeping for API_TIMEOUT minutes.')
            await asyncio.sleep(API_TIMEOUT)

if __name__ == '__main__':
    asyncio.run(main())

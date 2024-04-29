import os
import asyncio
import logging
import aiohttp
import json

def get_env_var(key, default=None, cast_to=str):
    value = os.environ.get(key, default)
    if value is not None:
        return cast_to(value)
    return default

DEBUG_LOGGING = get_env_var('DEBUG_LOGGING', default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])
logging_level = logging.DEBUG if DEBUG_LOGGING else logging.INFO
logging.basicConfig(format='%(asctime)s [%(levelname)s]: %(message)s', level=logging_level, handlers=[logging.StreamHandler()])

services = {
    "Sonarr": {"api_url": get_env_var("SONARR_URL"), "api_key": get_env_var("SONARR_API_KEY"), "stall_limit": get_env_var("SONARR_STALL_LIMIT", default=3, cast_to=int), "auto_search": get_env_var("SONARR_AUTO_SEARCH", default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])},
    "Radarr": {"api_url": get_env_var("RADARR_URL"), "api_key": get_env_var("RADARR_API_KEY"), "stall_limit": get_env_var("RADARR_STALL_LIMIT", default=3, cast_to=int), "auto_search": get_env_var("RADARR_AUTO_SEARCH", default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])},
    "Lidarr": {"api_url": get_env_var("LIDARR_URL"), "api_key": get_env_var("LIDARR_API_KEY"), "stall_limit": get_env_var("LIDARR_STALL_LIMIT", default=3, cast_to=int), "auto_search": get_env_var("LIDARR_AUTO_SEARCH", default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])}
}
API_TIMEOUT = get_env_var('API_TIMEOUT', 600, cast_to=int)
STRIKE_FILE_PATH = '/app/data/strikes.json'

def load_strikes():
    try:
        with open(STRIKE_FILE_PATH, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        logging.warning("Strike file not found or is invalid. Starting with an empty strike list.")
        return {}

def save_strikes(strike_dict):
    with open(STRIKE_FILE_PATH, 'w') as file:
        json.dump(strike_dict, file, indent=4)

strike_dict = load_strikes()

def is_service_configured(service_config):
    return service_config['api_url'] and service_config['api_key']
async def make_api_request(session, url, api_key, params=None, data=None, method='get'):
    headers = {'X-Api-Key': api_key}
    try:
        request_args = {'headers': headers, 'params': params}
        if data:
            request_args['json'] = data  # Pass the JSON data

        async with session.request(method, url, **request_args) as response:
            response.raise_for_status()
            raw_response = await response.text()
            content_type = response.headers.get('Content-Type', '')
            if 'application/json' in content_type:
                return json.loads(raw_response)
            elif response.status in (200, 204):
                return {'status': response.status}
            else:
                return {'status': response.status, 'content_type': content_type}
    except aiohttp.ClientResponseError as e:
        logging.error(f'HTTP error {e.status} from {url}: {e.message}')
    except Exception as e:
        logging.error(f'Unexpected error when accessing {url}: {str(e)}')
    return None

async def blacklist_item(session, service_name, item):
    service_config = services[service_name]
    blacklist_url = f'{service_config["api_url"]}/queue/{item["id"]}?blacklist=true'
    method = 'delete'  # Change this to 'post' if necessary
    if not item.get('id'):
        logging.error(f"Item ID missing for {service_name}: {item['title']}. Cannot blacklist.")
        return
    await make_api_request(session, blacklist_url, service_config['api_key'], method=method)
    logging.info(f"Item blacklisted for {service_name}: {item['title']}")

async def search_new_release(session, service_name, item):
    service_config = services[service_name]
    search_url = f'{service_config["api_url"]}/command'
    command_data = {
        "name": "EpisodeSearch" if service_name == 'Sonarr' else "MoviesSearch" if service_name == 'Radarr' else "AlbumSearch",
        "movieId": item.get('movieId'),
        "seriesId": item.get('seriesId'),
        "albumId": item.get('albumId')
    }
    command_data = {k: v for k, v in command_data.items() if v is not None}
    if 'name' in command_data and (command_data.get('movieId') or command_data.get('seriesId') or command_data.get('albumId')):
        await make_api_request(session, search_url, service_config['api_key'], data=command_data, method='post')
        logging.info(f"Search for new release initiated for {service_name}: {item['title']}")
    else:
        logging.error(f"Required IDs are missing for {service_name}: {item['title']}. Cannot initiate search.")


def process_queue_item(session, service_name, item, stall_limit):
    if item['status'] in ['downloading', 'paused']:
        strike_dict[item['id']] = 0
        save_strikes(strike_dict)
    elif item['status'] == 'warning' and item['errorMessage'] == 'The download is stalled with no connections':
        strike_dict[item['id']] = strike_dict.get(item['id'], 0) + 1
        if strike_dict[item['id']] >= stall_limit:
            logging.info(f'{service_name} - Strike limit reached for {item["title"]}. Initiating blacklist and search process.')
            strike_dict.pop(item['id'], None)
            if services[service_name]['auto_search']:
                asyncio.create_task(blacklist_item(session, service_name, item))
                asyncio.create_task(search_new_release(session, service_name, item))
            else:
                asyncio.create_task(blacklist_item(session, service_name, item))
            save_strikes(strike_dict)
        else:
            logging.debug(f'{strike_dict[item["id"]]} strikes on: {service_name} - {item["title"]}')

async def manage_downloads(session, service_config, service_name):
    if not is_service_configured(service_config):
        logging.info(f'Service configuration for {service_name} is incomplete or not set. Skipping.')
        return
    logging.info(f'Starting queue check for {service_name}...')
    queue_url = f'{service_config["api_url"]}/queue'
    initial_queue_data = await make_api_request(session, queue_url, service_config['api_key'], params={'pageSize': 1})

    if initial_queue_data is None or not initial_queue_data.get('totalRecords', 0):
        logging.warning(f'No data or missing "totalRecords" key in initial queue data for {service_name}.')
        return

    total_records = initial_queue_data['totalRecords']
    logging.info(f'Total items in {service_name} queue: {total_records}')
    page_size = min(total_records, 100)
    pages = (total_records + page_size - 1) // page_size
    logging.info(f'Fetching data in {pages} pages with a maximum of {page_size} items per page.')
    for page in range(pages):
        logging.info(f'Fetching page {page + 1} of {pages} for {service_name}.')
        queue_data = await make_api_request(session, queue_url, service_config['api_key'], params={'page': page + 1, 'pageSize': page_size})
        if queue_data and 'records' in queue_data:
            logging.info(f'Processing {len(queue_data["records"])} items from page {page + 1}.')
            for item in queue_data['records']:
                process_queue_item(session, service_name, item, service_config['stall_limit'])
        else:
            logging.warning(f'Failed to retrieve or missing "records" key in response for page {page + 1}.')

async def main():
    async with aiohttp.ClientSession() as session:
        while True:
            logging.info('Running media-queue-cleaner script')
            tasks = [manage_downloads(session, config, service_name) for service_name, config in services.items()]
            await asyncio.gather(*tasks)
            logging.info(f'Finished running media-queue-cleaner script. Sleeping for {API_TIMEOUT} seconds.\n')
            await asyncio.sleep(API_TIMEOUT)

if __name__ == '__main__':
    asyncio.run(main())

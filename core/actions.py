from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional

import aiohttp


@dataclass
class ActionsDeps:
    services: Dict[str, Any]
    get_service_setting: Callable[[str, str, Any], Any]
    throttled_request: Callable[..., Awaitable[Optional[Dict[str, Any]]]]
    event_bus: Any  # expects .emit(session, event, service=..., item=..., reason=..., notify=True)
    debug_logging: bool
    dry_run: bool


def build_search_command(service_name: str, item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if service_name == 'Sonarr':
        if 'episodeId' in item:
            return {"name": "EpisodeSearch", "episodeIds": [item['episodeId']]}
        if 'episodeIds' in item and isinstance(item['episodeIds'], list):
            return {"name": "EpisodeSearch", "episodeIds": item['episodeIds']}
        if 'seriesId' in item:
            return {"name": "SeriesSearch", "seriesId": item['seriesId']}
        return None
    if service_name == 'Radarr':
        if 'movieId' in item:
            return {"name": "MoviesSearch", "movieIds": [item['movieId']]}
        return None
    if service_name == 'Lidarr':
        if 'albumId' in item:
            return {"name": "AlbumSearch", "albumIds": [item['albumId']]}
        return None
    return None


async def remove_and_blacklist(
    session: aiohttp.ClientSession,
    service_name: str,
    item: Dict[str, Any],
    reason: Optional[str],
    deps: ActionsDeps,
) -> None:
    service_config = deps.services[service_name]
    blacklist_url = f'{service_config["api_url"]}/queue/{item["id"]}'
    use_blocklist = bool(deps.get_service_setting(service_name, 'use_blocklist_param', True))
    param_name = 'blocklist' if use_blocklist else 'blacklist'
    remove_from_client = bool(deps.get_service_setting(service_name, 'remove_from_client', True))
    params: Dict[str, str] = {param_name: 'true'}
    if remove_from_client:
        params['removeFromClient'] = 'true'
        params['skipImport'] = 'true'

    if deps.dry_run:
        await deps.event_bus.emit(
            session,
            'dry_remove',
            service=service_name,
            item=item,
            reason=reason,
            notify=True,
        )
        return

    await deps.throttled_request(
        session,
        service_name,
        blacklist_url,
        service_config['api_key'],
        params=params,
        method='delete',
    )
    if deps.debug_logging:
        import logging

        logging.info(
            f"Service {service_name}: removed + blacklisted id={item.get('id')} title={item.get('title')} reason={reason}"
        )
    await deps.event_bus.emit(
        session,
        'remove',
        service=service_name,
        item=item,
        reason=reason,
        notify=True,
    )


async def blacklist_and_search_new_release(
    session: aiohttp.ClientSession,
    service_name: str,
    item: Dict[str, Any],
    deps: ActionsDeps,
) -> None:
    service_config = deps.services[service_name]
    await remove_and_blacklist(session, service_name, item, reason='strike_limit', deps=deps)
    search_url = f'{service_config["api_url"]}/command'
    command_data = build_search_command(service_name, item)
    if command_data is not None:
        await deps.throttled_request(
            session, service_name, search_url, service_config['api_key'], json_data=command_data, method='post'
        )
        if deps.debug_logging:
            import logging

            logging.info(f"Service {service_name}: triggered search after removal")


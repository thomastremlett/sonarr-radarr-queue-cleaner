from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp


async def deluge_request(
    session: aiohttp.ClientSession,
    base_url: str,
    method: str,
    params: list[Any],
    password: Optional[str],
) -> Optional[Dict[str, Any]]:
    url = base_url.rstrip('/')
    if not url.endswith('/json'):
        url = url + '/json'
    try:
        body_login = {"method": "auth.login", "params": [password or 'deluge'], "id": 1}
        r1 = await session.post(url, json=body_login, timeout=aiohttp.ClientTimeout(total=5))
        _ = getattr(r1, 'status', None)
        body = {"method": method, "params": params, "id": 2}
        r2 = await session.post(url, json=body, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(r2, 'status', None) not in (200, 204):
            return None
        try:
            return await r2.json()
        except Exception:
            return None
    except Exception:
        return None


async def deluge_get_info(
    session: aiohttp.ClientSession,
    base_url: str,
    password: Optional[str],
    info_hash: str,
) -> Optional[Dict[str, Any]]:
    keys = ['state', 'download_payload_rate', 'num_peers', 'num_peers_connected', 'num_seeds', 'total_seeds', 'tracker_status']
    j = await deluge_request(session, base_url, 'core.get_torrent_status', [info_hash, keys], password)
    try:
        return (j or {}).get('result')
    except Exception:
        return None


async def deluge_get_speed(
    session: aiohttp.ClientSession,
    base_url: str,
    password: Optional[str],
    info_hash: str,
) -> Optional[int]:
    info = await deluge_get_info(session, base_url, password, info_hash)
    if not isinstance(info, dict):
        return None
    spd = info.get('download_payload_rate')
    try:
        return int(spd) if spd is not None else None
    except Exception:
        return None


async def deluge_reannounce(
    session: aiohttp.ClientSession,
    base_url: str,
    password: Optional[str],
    info_hash: str,
    do_recheck: bool,
) -> bool:
    ok = False
    j = await deluge_request(session, base_url, 'core.force_reannounce', [[info_hash]], password)
    ok = ok or bool((j or {}).get('result', False))
    if do_recheck:
        j2 = await deluge_request(session, base_url, 'core.force_recheck', [[info_hash]], password)
        ok = ok or bool((j2 or {}).get('result', False))
    return ok

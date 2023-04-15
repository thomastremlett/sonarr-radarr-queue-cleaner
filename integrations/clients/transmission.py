from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp


async def transmission_rpc(
    session: aiohttp.ClientSession,
    base_url: str,
    username: Optional[str],
    password: Optional[str],
    method: str,
    arguments: Dict[str, Any],
) -> bool:
    url = base_url.rstrip('/')
    headers: Dict[str, str] = {}
    auth = aiohttp.BasicAuth(username or '', password or '') if (username or password) else None
    body = {"method": method, "arguments": arguments}
    try:
        resp = await session.post(url, json=body, headers=headers, auth=auth, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) == 409:
            sid = getattr(resp, 'headers', {}).get('X-Transmission-Session-Id')
            if sid:
                headers['X-Transmission-Session-Id'] = sid
                resp2 = await session.post(url, json=body, headers=headers, auth=auth, timeout=aiohttp.ClientTimeout(total=5))
                return getattr(resp2, 'status', None) in (200, 204)
        return getattr(resp, 'status', None) in (200, 204)
    except Exception:
        return False


async def transmission_get_speed(
    session: aiohttp.ClientSession,
    base_url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_id: str,
) -> Optional[int]:
    try:
        url = base_url.rstrip('/')
        headers: Dict[str, str] = {}
        auth = aiohttp.BasicAuth(username or '', password or '') if (username or password) else None
        body = {"method": "torrent-get", "arguments": {"ids": [torrent_id], "fields": ["rateDownload"]}}
        resp = await session.post(url, json=body, headers=headers, auth=auth, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) == 409:
            sid = getattr(resp, 'headers', {}).get('X-Transmission-Session-Id')
            if sid:
                headers['X-Transmission-Session-Id'] = sid
                resp2 = await session.post(url, json=body, headers=headers, auth=auth, timeout=aiohttp.ClientTimeout(total=5))
                if getattr(resp2, 'status', None) not in (200, 204):
                    return None
                j = await resp2.json()
                arr = ((j or {}).get('arguments') or {}).get('torrents') or []
                if arr:
                    return int(arr[0].get('rateDownload') or 0)
                return None
        if getattr(resp, 'status', None) not in (200, 204):
            return None
        j = await resp.json()
        arr = ((j or {}).get('arguments') or {}).get('torrents') or []
        if arr:
            return int(arr[0].get('rateDownload') or 0)
        return None
    except Exception:
        return None


async def transmission_call(
    session: aiohttp.ClientSession,
    base_url: str,
    username: Optional[str],
    password: Optional[str],
    method: str,
    arguments: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    try:
        url = base_url.rstrip('/')
        headers: Dict[str, str] = {}
        auth = aiohttp.BasicAuth(username or '', password or '') if (username or password) else None
        body = {"method": method, "arguments": arguments}
        resp = await session.post(url, json=body, headers=headers, auth=auth, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) == 409:
            sid = getattr(resp, 'headers', {}).get('X-Transmission-Session-Id')
            if sid:
                headers['X-Transmission-Session-Id'] = sid
                resp2 = await session.post(url, json=body, headers=headers, auth=auth, timeout=aiohttp.ClientTimeout(total=5))
                if getattr(resp2, 'status', None) not in (200, 204):
                    return None
                try:
                    return await resp2.json()
                except Exception:
                    return None
        if getattr(resp, 'status', None) not in (200, 204):
            return None
        try:
            return await resp.json()
        except Exception:
            return None
    except Exception:
        return None


def transmission_status_to_state(status: Optional[int]) -> str:
    mapping = {0: 'stopped', 1: 'check_wait', 2: 'checking', 3: 'download_wait', 4: 'downloading', 5: 'seed_wait', 6: 'seeding'}
    try:
        return mapping.get(int(status), 'unknown')
    except Exception:
        return 'unknown'


async def transmission_get_info(
    session: aiohttp.ClientSession,
    base_url: str,
    username: Optional[str],
    password: Optional[str],
    torrent_id: str,
) -> Optional[Dict[str, Any]]:
    fields = ['status', 'peersConnected', 'peersSendingToUs', 'peersGettingFromUs', 'rateDownload', 'trackerStats']
    j = await transmission_call(session, base_url, username, password, 'torrent-get', {"ids": [torrent_id], "fields": fields})
    try:
        arr = ((j or {}).get('arguments') or {}).get('torrents') or []
        if arr:
            return arr[0]
    except Exception:
        pass
    return None

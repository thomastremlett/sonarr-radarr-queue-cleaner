from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp


async def qbittorrent_reannounce(
    session: aiohttp.ClientSession,
    base_url: str,
    username: str,
    password: str,
    info_hash: str,
    do_recheck: bool,
) -> bool:
    try:
        login_url = base_url.rstrip('/') + '/api/v2/auth/login'
        form = aiohttp.FormData()
        form.add_field('username', username)
        form.add_field('password', password)
        resp = await session.post(login_url, data=form, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) != 200:
            return False
        reannounce_url = base_url.rstrip('/') + '/api/v2/torrents/reannounce'
        form = aiohttp.FormData()
        form.add_field('hashes', info_hash)
        r1 = await session.post(reannounce_url, data=form, timeout=aiohttp.ClientTimeout(total=5))
        _ = getattr(r1, 'status', None)
        if do_recheck:
            recheck_url = base_url.rstrip('/') + '/api/v2/torrents/recheck'
            form2 = aiohttp.FormData()
            form2.add_field('hashes', info_hash)
            r2 = await session.post(recheck_url, data=form2, timeout=aiohttp.ClientTimeout(total=5))
            _ = getattr(r2, 'status', None)
        return True
    except Exception:
        return False


async def qbittorrent_get_speed(
    session: aiohttp.ClientSession,
    base_url: str,
    username: str,
    password: str,
    info_hash: str,
) -> Optional[int]:
    try:
        login_url = base_url.rstrip('/') + '/api/v2/auth/login'
        form = aiohttp.FormData()
        form.add_field('username', username)
        form.add_field('password', password)
        resp = await session.post(login_url, data=form, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) != 200:
            return None
        info_url = base_url.rstrip('/') + '/api/v2/torrents/info'
        r = await session.get(info_url, params={'hashes': info_hash}, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(r, 'status', None) != 200:
            return None
        data = await r.json()
        if isinstance(data, list) and data:
            d = data[0]
            spd = d.get('dlspeed')
            return int(spd) if spd is not None else None
    except Exception:
        return None


async def qbittorrent_get_info(
    session: aiohttp.ClientSession,
    base_url: str,
    username: str,
    password: str,
    info_hash: str,
) -> Optional[Dict[str, Any]]:
    try:
        login_url = base_url.rstrip('/') + '/api/v2/auth/login'
        form = aiohttp.FormData()
        form.add_field('username', username)
        form.add_field('password', password)
        resp = await session.post(login_url, data=form, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) != 200:
            return None
        info_url = base_url.rstrip('/') + '/api/v2/torrents/info'
        r = await session.get(info_url, params={'hashes': info_hash}, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(r, 'status', None) != 200:
            return None
        data = await r.json()
        if isinstance(data, list) and data:
            return data[0]
        return None
    except Exception:
        return None


async def qbittorrent_get_trackers(
    session: aiohttp.ClientSession,
    base_url: str,
    username: str,
    password: str,
    info_hash: str,
) -> Optional[Any]:
    try:
        login_url = base_url.rstrip('/') + '/api/v2/auth/login'
        form = aiohttp.FormData()
        form.add_field('username', username)
        form.add_field('password', password)
        resp = await session.post(login_url, data=form, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(resp, 'status', None) != 200:
            return None
        tr_url = base_url.rstrip('/') + '/api/v2/torrents/trackers'
        r = await session.get(tr_url, params={'hash': info_hash}, timeout=aiohttp.ClientTimeout(total=5))
        if getattr(r, 'status', None) != 200:
            return None
        return await r.json()
    except Exception:
        return None

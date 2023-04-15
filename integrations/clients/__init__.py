from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp

from . import qbittorrent as qb_mod
from . import transmission as tr_mod
from . import deluge as dl_mod


async def get_client_speed(session: aiohttp.ClientSession, item: Dict[str, Any], CONFIG: Dict[str, Any]) -> Optional[int]:
    clients = CONFIG.get('clients') if isinstance(CONFIG.get('clients'), dict) else {}
    if not clients:
        return None
    dlid = item.get('downloadId') or item.get('downloadID')
    if not dlid:
        return None

    qb = clients.get('qbittorrent') if isinstance(clients.get('qbittorrent'), dict) else {}
    if qb.get('url') and qb.get('username') is not None and qb.get('password') is not None:
        spd = await qb_mod.qbittorrent_get_speed(session, qb.get('url'), qb.get('username') or '', qb.get('password') or '', str(dlid))
        if spd is not None:
            return spd

    tr = clients.get('transmission') if isinstance(clients.get('transmission'), dict) else {}
    if tr.get('url'):
        spd = await tr_mod.transmission_get_speed(session, tr.get('url'), tr.get('username'), tr.get('password'), str(dlid))
        if spd is not None:
            return spd

    dl = clients.get('deluge') if isinstance(clients.get('deluge'), dict) else {}
    if dl.get('url') and dl.get('password') is not None:
        spd = await dl_mod.deluge_get_speed(session, dl.get('url'), dl.get('password'), str(dlid))
        if spd is not None:
            return spd
    return None


async def enrich_with_client_state(session: aiohttp.ClientSession, service_name: str, item: Dict[str, Any], CONFIG: Dict[str, Any]) -> None:
    clients = CONFIG.get('clients') if isinstance(CONFIG.get('clients'), dict) else {}
    dlid = item.get('downloadId') or item.get('downloadID')
    if not dlid:
        return

    qb = clients.get('qbittorrent') if isinstance(clients.get('qbittorrent'), dict) else {}
    if qb and qb.get('url') is not None:
        info = await qb_mod.qbittorrent_get_info(session, qb.get('url'), qb.get('username') or '', qb.get('password') or '', str(dlid))
        if isinstance(info, dict):
            item['clientState'] = info.get('state')
            try:
                item['clientPeers'] = int(info.get('num_leechs') or 0)
                item['clientSeeds'] = int(info.get('num_seeds') or 0)
            except Exception:
                pass
        trackers = await qb_mod.qbittorrent_get_trackers(session, qb.get('url'), qb.get('username') or '', qb.get('password') or '', str(dlid))
        if isinstance(trackers, list):
            msgs = []
            for t in trackers:
                m = t.get('msg')
                if m:
                    msgs.append(str(m))
            if msgs:
                item['clientTrackersMsg'] = ' | '.join(msgs)

    tr = clients.get('transmission') if isinstance(clients.get('transmission'), dict) else {}
    if tr and tr.get('url'):
        tinfo = await tr_mod.transmission_get_info(session, tr.get('url'), tr.get('username'), tr.get('password'), str(dlid))
        if isinstance(tinfo, dict):
            item.setdefault('clientState', tr_mod.transmission_status_to_state(tinfo.get('status')))
            try:
                item.setdefault('clientPeers', int(tinfo.get('peersConnected') or 0))
            except Exception:
                pass
            stats = tinfo.get('trackerStats') if isinstance(tinfo.get('trackerStats'), list) else []
            seed_counts = []
            msgs = []
            for ts in stats:
                try:
                    if ts.get('seederCount') is not None:
                        seed_counts.append(int(ts.get('seederCount')))
                except Exception:
                    pass
                res = ts.get('lastAnnounceResult') or ts.get('lastScrapeResult')
                if res:
                    msgs.append(str(res))
            if seed_counts:
                try:
                    item.setdefault('clientSeeds', max(seed_counts))
                except Exception:
                    pass
            if msgs and not item.get('clientTrackersMsg'):
                item['clientTrackersMsg'] = ' | '.join(msgs)

    dl = clients.get('deluge') if isinstance(clients.get('deluge'), dict) else {}
    if dl and dl.get('url'):
        dinfo = await dl_mod.deluge_get_info(session, dl.get('url'), dl.get('password'), str(dlid))
        if isinstance(dinfo, dict):
            item.setdefault('clientState', (dinfo.get('state') or '').lower() or None)
            try:
                item.setdefault('clientPeers', int(dinfo.get('num_peers') or dinfo.get('num_peers_connected') or 0))
                item.setdefault('clientSeeds', int(dinfo.get('num_seeds') or dinfo.get('total_seeds') or 0))
            except Exception:
                pass
            msg = dinfo.get('tracker_status')
            if msg and not item.get('clientTrackersMsg'):
                item['clientTrackersMsg'] = str(msg)


async def attempt_reannounce(
    session: aiohttp.ClientSession,
    item: Dict[str, Any],
    entry: Dict[str, Any],
    CONFIG: Dict[str, Any],
    EXPLAIN_DECISIONS: bool,
    log_event,
) -> bool:
    rule = CONFIG.get('rule_engine') if isinstance(CONFIG.get('rule_engine'), dict) else {}
    rea = rule.get('reannounce') if isinstance(rule.get('reannounce'), dict) else {}
    enabled = bool(rea.get('enabled', False))
    if not enabled:
        return False
    cooldown_min = float(rea.get('cooldown_minutes', 60))
    max_attempts = int(rea.get('max_attempts', 1))
    do_recheck = bool(rea.get('do_recheck', False))
    only_zero = bool(rea.get('only_when_seeds_zero', True))

    import time
    now = time.time()
    last = entry.get('last_reannounce_ts')
    attempts = int(entry.get('reannounce_attempts') or 0)
    if attempts >= max_attempts:
        return False
    if last and (now - float(last)) < (cooldown_min * 60):
        return False

    seeds = 0
    try:
        seeds = int(item.get('clientSeeds') or 0)
    except Exception:
        seeds = 0
    if only_zero and seeds > 0:
        return False

    download_id = item.get('downloadId') or item.get('downloadID')
    if not download_id:
        return False

    clients = CONFIG.get('clients') if isinstance(CONFIG.get('clients'), dict) else {}
    qb = clients.get('qbittorrent') if isinstance(clients.get('qbittorrent'), dict) else {}
    tr = clients.get('transmission') if isinstance(clients.get('transmission'), dict) else {}
    dl = clients.get('deluge') if isinstance(clients.get('deluge'), dict) else {}

    attempted = False
    if qb.get('url') and qb.get('username') is not None and qb.get('password') is not None:
        ok = await qb_mod.qbittorrent_reannounce(session, qb['url'], qb.get('username') or '', qb.get('password') or '', str(download_id), do_recheck)
        attempted = attempted or ok
    if tr.get('url'):
        rpc_url = str(tr.get('url'))
        ok1 = await tr_mod.transmission_rpc(session, rpc_url, tr.get('username'), tr.get('password'), 'torrent-reannounce', {"ids": [str(download_id)]})
        ok2 = True
        if do_recheck:
            ok2 = await tr_mod.transmission_rpc(session, rpc_url, tr.get('username'), tr.get('password'), 'torrent-verify', {"ids": [str(download_id)]})
        attempted = attempted or (ok1 or ok2)
    if dl.get('url') and dl.get('password') is not None:
        ok = await dl_mod.deluge_reannounce(session, dl.get('url'), dl.get('password'), str(download_id), do_recheck)
        attempted = attempted or ok

    if attempted:
        entry['last_reannounce_ts'] = now
        entry['reannounce_attempts'] = attempts + 1
        entry['last_reason'] = 'reannounce'
        if EXPLAIN_DECISIONS:
            log_event('reannounce_attempted', id=item.get('id'), title=item.get('title'), seeds=seeds, attempts=entry['reannounce_attempts'])
        return True
    return False

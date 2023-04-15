from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional


def is_torrent(item: Dict[str, Any]) -> bool:
    proto = (item.get('protocol') or '').lower()
    if proto:
        return 'torrent' in proto
    try:
        return int(item.get('protocol')) == 1
    except Exception:
        return False


def is_stalled(item: Dict[str, Any]) -> bool:
    tds = (item.get('trackedDownloadStatus') or item.get('trackedDownloadState') or '').lower()
    status = (item.get('status') or '').lower()
    if tds in ('warning', 'error', 'stalled'):
        return True
    if status in ('warning', 'stalled'):
        return True
    for msg in (item.get('statusMessages') or []):
        text = f"{msg.get('title','')} {msg.get('messages','')} {msg.get('message','')}".lower()
        if 'stalled' in text or 'no connections' in text:
            return True
    em = (item.get('errorMessage') or '').lower()
    if 'stalled' in em or 'no connections' in em:
        return True
    return False


def is_stalled_extended(
    item: Dict[str, Any],
    torrent_seeder_stall_threshold: Optional[int],
    torrent_seeder_stall_progress_ceiling: float,
    get_seeders: Callable[[Dict[str, Any]], Optional[int]],
    get_progress_percent: Callable[[Dict[str, Any]], Optional[float]],
) -> bool:
    if is_stalled(item):
        return True
    if torrent_seeder_stall_threshold is not None and torrent_seeder_stall_threshold >= 0:
        if is_torrent(item):
            seeders = get_seeders(item)
            if seeders is not None and seeders <= torrent_seeder_stall_threshold:
                pct = get_progress_percent(item)
                if pct is None:
                    return torrent_seeder_stall_threshold == 0
                return pct <= torrent_seeder_stall_progress_ceiling
    return False


def is_queued(item: Dict[str, Any]) -> bool:
    try:
        status = (item.get('status') or '').lower()
        tds = (item.get('trackedDownloadStatus') or item.get('trackedDownloadState') or '').lower()
        cstate = (item.get('clientState') or '').lower()
        if any(s in status for s in ('queued', 'pending', 'waiting')):
            return True
        if any(s in tds for s in ('queued', 'pending', 'waiting')):
            return True
        if 'queue' in cstate or 'queued' in cstate:
            return True
        if cstate in ('download_wait', 'check_wait'):
            return True
    except Exception:
        return False
    return False


def evaluate_rules(
    service_name: str,
    item: Dict[str, Any],
    entry: Dict[str, Any],
    progressed: bool,
    *,
    get_effective_setting: Callable[[str, Dict[str, Any], str, Any], Any],
    default_grace_minutes: float,
    default_max_queue_age_hours: float,
    default_no_progress_max_age_minutes: float,
    default_min_speed_bps: float,
    default_min_speed_duration_min: float,
    get_total_size: Callable[[Dict[str, Any]], Optional[int]],
    get_seeders: Callable[[Dict[str, Any]], Optional[int]],
    get_progress_percent: Callable[[Dict[str, Any]], Optional[float]],
    get_indexer_name: Callable[[Dict[str, Any]], Optional[str]],
    config: Dict[str, Any],
    torrent_seeder_stall_threshold: Optional[int],
    torrent_seeder_stall_progress_ceiling: float,
) -> Optional[str]:
    now = time.time()
    # Grace period
    grace_min = get_effective_setting(service_name, item, 'grace_period_minutes', default_grace_minutes)
    first_seen = entry.get('first_seen_ts') or now
    try:
        if grace_min and (now - first_seen) < (float(grace_min) * 60):
            return None
    except Exception:
        pass
    # Max queue age hard cap
    max_age_h = get_effective_setting(service_name, item, 'max_queue_age_hours', default_max_queue_age_hours)
    try:
        if max_age_h and (now - first_seen) >= (float(max_age_h) * 3600):
            return 'max_age'
    except Exception:
        pass
    # No-progress timeout
    max_age_min = get_effective_setting(service_name, item, 'no_progress_max_age_minutes', default_no_progress_max_age_minutes)
    last_prog = entry.get('last_progress_ts')
    if not progressed and max_age_min and last_prog:
        if (now - last_prog) >= (float(max_age_min) * 60):
            return 'no_progress_timeout'
    # Min-speed rule using client-enriched speed
    try:
        min_speed = float(get_effective_setting(service_name, item, 'min_speed_bytes_per_sec', default_min_speed_bps))
        min_speed_dur = float(get_effective_setting(service_name, item, 'min_speed_duration_minutes', default_min_speed_duration_min))
    except Exception:
        min_speed = 0.0
        min_speed_dur = 0.0
    if min_speed and min_speed_dur and is_torrent(item):
        spd = item.get('clientDlSpeed')
        if spd is not None:
            try:
                if float(spd) < min_speed:
                    lp = entry.get('last_progress_ts') or first_seen
                    if (now - lp) >= (min_speed_dur * 60):
                        return 'min_speed'
            except Exception:
                pass
    # Client state-based stall (e.g., qBittorrent states)
    try:
        client_state_as_stalled = bool(get_effective_setting(service_name, item, 'client_state_as_stalled', False))
    except Exception:
        client_state_as_stalled = False
    if client_state_as_stalled:
        st = (item.get('clientState') or '').lower()
        if st in ('stalleddl', 'stalledup', 'error'):
            return 'client_state'
    # Client no-peers + no-seeds for duration
    try:
        zero_act_min = float(get_effective_setting(service_name, item, 'client_zero_activity_minutes', 0) or 0)
    except Exception:
        zero_act_min = 0.0
    if zero_act_min and is_torrent(item):
        peers = item.get('clientPeers')
        seeds = item.get('clientSeeds')
        if peers is not None and seeds is not None:
            try:
                if int(peers) == 0 and int(seeds) == 0:
                    lp = entry.get('last_progress_ts') or first_seen
                    if (now - lp) >= (zero_act_min * 60):
                        return 'client_no_peers'
            except Exception:
                pass
    # Size-aware policy: large items with zero seeders for configurable minutes
    rule = config.get('rule_engine') if isinstance(config.get('rule_engine'), dict) else {}
    try:
        large_gb = float(rule.get('large_size_gb', 0))
        large_zero_min = float(rule.get('large_zero_seeders_remove_minutes', 0))
        large_pct_ceiling = float(rule.get('large_progress_ceiling_percent', 100))
    except Exception:
        large_gb = 0
        large_zero_min = 0
        large_pct_ceiling = 100
    if large_gb and large_zero_min and is_torrent(item):
        total = get_total_size(item)
        seeds = get_seeders(item) or 0
        pct = get_progress_percent(item)
        if total and total >= int(large_gb * (1024**3)) and seeds == 0:
            if pct is None or pct <= large_pct_ceiling:
                if (now - first_seen) >= (large_zero_min * 60):
                    return 'large_zero_seeders'
    # Stalled signals
    if is_stalled_extended(item, torrent_seeder_stall_threshold, torrent_seeder_stall_progress_ceiling, get_seeders, get_progress_percent):
        seeds = get_seeders(item)
        pct = get_progress_percent(item)
        # Indexer-aware seeder threshold overrides
        idx_name = get_indexer_name(item)
        idx_cfg = (config.get('indexer_policies') or {}).get(idx_name) if isinstance(config.get('indexer_policies'), dict) else None
        idx_seed_thresh = None
        try:
            if isinstance(idx_cfg, dict) and 'seeder_stall_threshold' in idx_cfg:
                idx_seed_thresh = int(idx_cfg.get('seeder_stall_threshold'))
        except Exception:
            idx_seed_thresh = None
        seed_thresh = idx_seed_thresh if (idx_seed_thresh is not None) else torrent_seeder_stall_threshold
        if seed_thresh is not None and seed_thresh >= 0 and is_torrent(item) and seeds is not None and seeds <= seed_thresh:
            if pct is None or pct <= torrent_seeder_stall_progress_ceiling:
                return 'low_seeders'
        return 'stalled'
    return None


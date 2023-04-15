from __future__ import annotations

from typing import Any, Dict, Optional


def get_downloaded_bytes(item: Dict[str, Any]) -> Optional[int]:
    size = item.get('size')
    sizeleft = item.get('sizeleft') or item.get('sizeLeft')
    try:
        if size is not None and sizeleft is not None:
            return int(size) - int(sizeleft)
    except Exception:
        return None
    return None


def get_total_size(item: Dict[str, Any]) -> Optional[int]:
    size = item.get('size')
    try:
        return int(size) if size is not None else None
    except Exception:
        return None


def get_progress_percent(item: Dict[str, Any]) -> Optional[float]:
    dl = get_downloaded_bytes(item)
    total = get_total_size(item)
    try:
        if dl is not None and total and total > 0:
            pct = (dl / total) * 100.0
            # clamp 0..100
            return max(0.0, min(100.0, pct))
    except Exception:
        return None
    return None


def get_seeders(item: Dict[str, Any]) -> Optional[int]:
    # Direct field
    for key in ('seeders', 'seederCount'):
        if key in item and item.get(key) is not None:
            try:
                return int(item.get(key))
            except Exception:
                pass
    # Nested under release info (Sonarr/Radarr shapes)
    for parent in ('release',):
        rel = item.get(parent) or {}
        if isinstance(rel, dict):
            for key in ('seeders', 'seederCount'):
                if key in rel and rel.get(key) is not None:
                    try:
                        return int(rel.get(key))
                    except Exception:
                        pass
    # Remote episode/movie release info
    for parent in ('remoteEpisode', 'remoteMovie'):
        obj = item.get(parent) or {}
        if isinstance(obj, dict):
            rel = obj.get('release') or {}
            if isinstance(rel, dict):
                for key in ('seeders', 'seederCount'):
                    if key in rel and rel.get(key) is not None:
                        try:
                            return int(rel.get(key))
                        except Exception:
                            pass
    return None


def get_indexer_name(item: Dict[str, Any]) -> Optional[str]:
    for key in ('indexer', 'indexerName'):
        val = item.get(key)
        if val:
            return str(val)
    for parent in ('release',):
        rel = item.get(parent) or {}
        if isinstance(rel, dict):
            for key in ('indexer', 'indexerName'):
                val = rel.get(key)
                if val:
                    return str(val)
    for parent in ('remoteEpisode', 'remoteMovie'):
        obj = item.get(parent) or {}
        if isinstance(obj, dict):
            rel = obj.get('release') or {}
            if isinstance(rel, dict):
                for key in ('indexer', 'indexerName'):
                    val = rel.get(key)
                    if val:
                        return str(val)
    return None


def is_whitelisted(item: Dict[str, Any], whitelist: Dict[str, Any]) -> bool:
    wl = whitelist if isinstance(whitelist, dict) else {}
    if not wl:
        return False
    try:
        ids = set(int(x) for x in (wl.get('ids') or []))
        if 'id' in item and int(item.get('id')) in ids:
            return True
    except Exception:
        pass
    dls = set(str(x) for x in (wl.get('download_ids') or []))
    dlid = item.get('downloadId') or item.get('downloadID')
    if dlid and str(dlid) in dls:
        return True
    try:
        title = (item.get('title') or '').lower()
        for sub in (wl.get('title_contains') or []):
            try:
                if sub and str(sub).lower() in title:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False

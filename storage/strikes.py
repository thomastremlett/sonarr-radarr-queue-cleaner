from __future__ import annotations

import json
import os
import time
from typing import Any, Dict


def load_strikes(path: str, debug_logging: bool = False) -> Dict[str, Any]:
    try:
        with open(path, 'r') as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        if debug_logging:
            import logging
            logging.warning("Strike file not found or is invalid. Starting with an empty strike list.")
        return {}


def save_strikes(data: Dict[str, Any], path: str) -> None:
    tmp_path = path + '.tmp'
    with open(tmp_path, 'w') as file:
        json.dump(data, file, indent=4)
    os.replace(tmp_path, path)


def make_strike_key(service_name: str, item_id: Any) -> str:
    return f"{service_name}:{item_id}"


def normalize_strike_entry(entry: Any) -> Dict[str, Any]:
    now = time.time()
    base = {
        "count": 0,
        "last_dl": None,
        "first_seen_ts": now,
        "last_progress_ts": None,
        "last_seen_seeders": None,
        "last_reason": None,
        "last_reannounce_ts": None,
        "reannounce_attempts": 0,
        "error_strikes": 0,
    }
    if isinstance(entry, int):
        base["count"] = entry
        return base
    if isinstance(entry, dict):
        out = base.copy()
        out.update({
            "count": int(entry.get("count", 0)),
            "last_dl": entry.get("last_dl"),
            "first_seen_ts": entry.get("first_seen_ts", entry.get("seen_ts", now)) or now,
            "last_progress_ts": entry.get("last_progress_ts"),
            "last_seen_seeders": entry.get("last_seen_seeders"),
            "last_reason": entry.get("last_reason"),
            "last_reannounce_ts": entry.get("last_reannounce_ts"),
            "reannounce_attempts": int(entry.get("reannounce_attempts", 0) or 0),
            "error_strikes": int(entry.get("error_strikes", 0) or 0),
        })
        return out
    return base


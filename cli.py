import argparse
import json
import os
import sys
import time
from typing import Any, Dict, Optional

from core.rules import evaluate_rules
from core.utils import (
    get_total_size,
    get_seeders,
    get_progress_percent,
    get_indexer_name,
)
from storage.strikes import load_strikes as storage_load_strikes, save_strikes as storage_save_strikes
from core.config import ConfigAccessor


def _env(key: str, default: Any) -> Any:
    return os.environ.get(key, default)


from core.config import load_yaml as _load_yaml


def _get_effective_setting(cfg: Dict[str, Any], service_name: str, item: Dict[str, Any], key: str, default: Any) -> Any:
    return ConfigAccessor(cfg).get_effective(service_name, item, key, default)


def _evaluate(service_name: str, item: Dict[str, Any], entry: Dict[str, Any], cfg: Dict[str, Any]) -> Optional[str]:
    # Defaults align with cleaner.py
    DEFAULT_GRACE_PERIOD_MINUTES = 0
    DEFAULT_NO_PROGRESS_MAX_AGE_MINUTES = 0
    DEFAULT_MAX_QUEUE_AGE_HOURS = 0
    DEFAULT_MIN_SPEED_BPS = 0
    DEFAULT_MIN_SPEED_DURATION_MIN = 0
    TORRENT_SEEDER_STALL_THRESHOLD = int(_env('TORRENT_SEEDER_STALL_THRESHOLD', -1))
    try:
        TORRENT_SEEDER_STALL_PROGRESS_CEILING = float(_env('TORRENT_SEEDER_STALL_PROGRESS_CEILING', 25.0))
    except Exception:
        TORRENT_SEEDER_STALL_PROGRESS_CEILING = 25.0
    return evaluate_rules(
        service_name,
        item,
        entry,
        progressed=False,
        get_effective_setting=lambda svc, it, k, d: _get_effective_setting(cfg, svc, it, k, d),
        default_grace_minutes=DEFAULT_GRACE_PERIOD_MINUTES,
        default_max_queue_age_hours=DEFAULT_MAX_QUEUE_AGE_HOURS,
        default_no_progress_max_age_minutes=DEFAULT_NO_PROGRESS_MAX_AGE_MINUTES,
        default_min_speed_bps=DEFAULT_MIN_SPEED_BPS,
        default_min_speed_duration_min=DEFAULT_MIN_SPEED_DURATION_MIN,
        get_total_size=get_total_size,
        get_seeders=get_seeders,
        get_progress_percent=get_progress_percent,
        get_indexer_name=get_indexer_name,
        config=cfg,
        torrent_seeder_stall_threshold=TORRENT_SEEDER_STALL_THRESHOLD,
        torrent_seeder_stall_progress_ceiling=TORRENT_SEEDER_STALL_PROGRESS_CEILING,
    )


def _strike_path() -> str:
    return _env('STRIKE_FILE_PATH', '/app/data/strikes.json')


def cmd_list(args):
    data = storage_load_strikes(_strike_path(), debug_logging=False)
    print(json.dumps(data, indent=2))


def cmd_clear(args):
    if args.key:
        d = storage_load_strikes(_strike_path(), debug_logging=False)
        if args.key in d:
            d.pop(args.key, None)
            storage_save_strikes(d, _strike_path())
            print(f"Cleared {args.key}")
        else:
            print("Key not found")
    else:
        storage_save_strikes({}, _strike_path())
        print("Cleared all strikes")


def cmd_simulate(args):
    with open(args.item_json, 'r') as f:
        item = json.load(f)
    entry = {
        "count": 0,
        "last_dl": (int(item.get('size') or 0) - int(item.get('sizeleft') or 0)) if (item.get('size') and item.get('sizeleft')) else 0,
        "first_seen_ts": time.time() - 3600,
        "last_progress_ts": None,
    }
    cfg_path = _env('CONFIG_PATH', '/app/config.yaml')
    cfg = _load_yaml(cfg_path)
    reason = _evaluate(args.service, item, entry, cfg)
    print(json.dumps({"reason": reason}, indent=2))


def cmd_status(args):
    data = storage_load_strikes(_strike_path(), debug_logging=False)
    total_entries = 0
    active_strikes = 0
    indexer_entries = 0
    for k, v in (data or {}).items():
        if not isinstance(v, dict):
            continue
        if ':_indexer:' in str(k):
            indexer_entries += 1
            continue
        total_entries += 1
        try:
            if int(v.get('count') or 0) > 0:
                active_strikes += 1
        except Exception:
            pass
    try:
        api_timeout = int(_env('API_TIMEOUT', 600))
    except Exception:
        api_timeout = 600
    try:
        next_run_ts = time.time() + api_timeout
        next_run_str = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(next_run_ts))
    except Exception:
        next_run_str = 'unknown'
    print(
        json.dumps(
            {
                "strike_file": _strike_path(),
                "entries": total_entries,
                "active_strikes": active_strikes,
                "indexer_entries": indexer_entries,
                "api_timeout": api_timeout,
                "next_run": next_run_str,
            },
            indent=2,
        )
    )


def main():
    ap = argparse.ArgumentParser(description="Media Queue Cleaner CLI")
    sub = ap.add_subparsers(dest='cmd')

    p_list = sub.add_parser('list', help='List strike records')
    p_list.set_defaults(func=cmd_list)

    p_clear = sub.add_parser('clear', help='Clear strikes (all or one key)')
    p_clear.add_argument('--key', help='Strike key to clear (e.g., Sonarr:123)')
    p_clear.set_defaults(func=cmd_clear)

    p_sim = sub.add_parser('simulate', help='Simulate a decision for an item JSON')
    p_sim.add_argument('item_json', help='Path to item JSON file')
    p_sim.add_argument('--service', default='Sonarr')
    p_sim.set_defaults(func=cmd_simulate)

    p_status = sub.add_parser('status', help='Show strike summary and next run time')
    p_status.set_defaults(func=cmd_status)

    args = ap.parse_args()
    if not hasattr(args, 'func'):
        ap.print_help()
        sys.exit(1)
    args.func(args)


if __name__ == '__main__':
    main()

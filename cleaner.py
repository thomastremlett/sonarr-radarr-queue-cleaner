import os
import asyncio
import logging
import aiohttp
import json
import time
import warnings
from typing import Optional, Dict, Any

# Storage module for strikes
from storage.strikes import (
    load_strikes as storage_load_strikes,
    save_strikes as storage_save_strikes,
    make_strike_key as storage_make_key,
    normalize_strike_entry as storage_normalize_entry,
)

# Helper function to get environment variables with type casting
def get_env_var(key, default=None, cast_to=str):
    value = os.environ.get(key, default)
    if value is not None:
        return cast_to(value)
    return default

# Fetch debug flag from environment and set logging level
DEBUG_LOGGING = get_env_var('DEBUG_LOGGING', default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])
logging_level = logging.DEBUG if DEBUG_LOGGING else logging.INFO

# Set up logging (avoid duplicate handlers)
try:
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s]: %(message)s',
        level=logging_level,
        handlers=[logging.StreamHandler()],
        force=True,
    )
except TypeError:
    root_logger = logging.getLogger()
    for _h in list(root_logger.handlers):
        root_logger.removeHandler(_h)
    logging.basicConfig(
        format='%(asctime)s [%(levelname)s]: %(message)s',
        level=logging_level,
        handlers=[logging.StreamHandler()]
    )

# Dedicated non-propagating logger for structured event logs to avoid duplicates
EVENT_LOG = logging.getLogger('media_cleaner.events')
EVENT_LOG.setLevel(logging_level)
# Prevent propagation to root to avoid duplicate lines when both
# this logger and the root logger have StreamHandlers attached.
EVENT_LOG.propagate = False
# Always ensure exactly one handler on the event logger to avoid duplicates
# in cases where the module is re-imported by a runner.
for _h in list(EVENT_LOG.handlers):
    EVENT_LOG.removeHandler(_h)
_h = logging.StreamHandler()
_h.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s]: %(message)s'))
EVENT_LOG.addHandler(_h)

GLOBAL_STALL_LIMIT = get_env_var('GLOBAL_STALL_LIMIT', default=3, cast_to=int)

API_TIMEOUT = get_env_var('API_TIMEOUT', 600, cast_to=int)
STRIKE_FILE_PATH = get_env_var('STRIKE_FILE_PATH', '/app/data/strikes.json')
CONFIG_PATH = get_env_var('CONFIG_PATH', '/app/config.yaml')

# Strike reset behavior: 'all' or integer >=1
RESET_STRIKES_ON_PROGRESS = get_env_var('RESET_STRIKES_ON_PROGRESS', 'all', cast_to=str)

# Logging and run controls
STRUCTURED_LOGS = get_env_var('STRUCTURED_LOGS', default='true', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])
DRY_RUN = get_env_var('DRY_RUN', default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])
EXPLAIN_DECISIONS = get_env_var('EXPLAIN_DECISIONS', default='false', cast_to=lambda x: x.lower() in ['true', '1', 'yes'])

# Request and retry configuration
REQUEST_TIMEOUT = get_env_var('REQUEST_TIMEOUT', 10, cast_to=int)
RETRY_ATTEMPTS = get_env_var('RETRY_ATTEMPTS', 2, cast_to=int)
RETRY_BACKOFF = get_env_var('RETRY_BACKOFF', 1.0, cast_to=float)  # base seconds

# Rule engine configuration (may be overridden by YAML)
DEFAULT_GRACE_PERIOD_MINUTES = 0
DEFAULT_NO_PROGRESS_MAX_AGE_MINUTES = 0
DEFAULT_REMOVE_FROM_CLIENT = True
DEFAULT_USE_BLOCKLIST_PARAM = True
DEFAULT_MIN_REQUEST_INTERVAL_MS = 0
DEFAULT_MAX_CONCURRENT_REQUESTS = 0

# Additional rule defaults
DEFAULT_MAX_QUEUE_AGE_HOURS = 0
DEFAULT_TRACKER_ERROR_STRIKES = 2
DEFAULT_MIN_SPEED_BPS = 0
DEFAULT_MIN_SPEED_DURATION_MIN = 0
DEFAULT_INDEXER_FAILURE_REMOVE_AFTER = 0

from core.config import load_yaml as _load_yaml
from core.config import sanitize_config as _sanitize_config
from core.config import validate_config as _validate_config

# YAML config loading
CONFIG: Dict[str, Any] = _load_yaml(CONFIG_PATH)

# apply sanitization
CONFIG = _sanitize_config(CONFIG, DEBUG_LOGGING)
_validate_config(CONFIG, DEBUG_LOGGING)

# ---- Modularization bindings: notifications wrappers ----
from core.events import EventBus
from core.actions import ActionsDeps as _ActionsDeps
from core import actions as _actions
from core.config import ConfigAccessor as _ConfigAccessor

_AC = _ConfigAccessor(CONFIG)

# Prefer YAML general for app-level settings; fallback to env-loaded defaults
def _get_general(key: str, default: Any) -> Any:
    val = _AC.general(key, None)
    return default if val is None else val

# Override previously read env defaults with YAML when provided
DEBUG_LOGGING = bool(_get_general('debug_logging', DEBUG_LOGGING))
STRUCTURED_LOGS = bool(_get_general('structured_logs', STRUCTURED_LOGS))
DRY_RUN = bool(_get_general('dry_run', DRY_RUN))
EXPLAIN_DECISIONS = bool(_get_general('explain_decisions', EXPLAIN_DECISIONS))
API_TIMEOUT = int(_get_general('api_timeout', API_TIMEOUT))
STRIKE_FILE_PATH = str(_get_general('strike_file_path', STRIKE_FILE_PATH))
REQUEST_TIMEOUT = int(_get_general('request_timeout', REQUEST_TIMEOUT))
RETRY_ATTEMPTS = int(_get_general('retry_attempts', RETRY_ATTEMPTS))
RETRY_BACKOFF = float(_get_general('retry_backoff', RETRY_BACKOFF))
RESET_STRIKES_ON_PROGRESS = _get_general('reset_strikes_on_progress', RESET_STRIKES_ON_PROGRESS)

from integrations.clients import (
    get_client_speed as __clients_get_client_speed,
    enrich_with_client_state as __clients_enrich_with_client_state,
    attempt_reannounce as __clients_attempt_reannounce,
)

 # notify_* provided via notifications module import above

# Environment variables for service endpoints and per-service defaults
def _svc_entry(name: str) -> Dict[str, Any]:
    ep = _AC.service_endpoint(name)
    return {
        'api_url': ep.get('api_url') or '',
        # API key is sourced from environment only (e.g., SONARR_API_KEY)
        'api_key': ep.get('api_key') or '',
        'stall_limit': int(_AC.get_service_setting(name, 'stall_limit', GLOBAL_STALL_LIMIT)),
        'auto_search': bool(_AC.get_service_setting(name, 'auto_search', False)),
    }

services = {
    'Sonarr': _svc_entry('Sonarr'),
    'Radarr': _svc_entry('Radarr'),
    'Lidarr': _svc_entry('Lidarr'),
}

def _get_service_setting(service_name: str, key: str, default: Any) -> Any:
    # Use a fresh accessor to reflect runtime CONFIG updates in tests
    return _ConfigAccessor(CONFIG).get_service_setting(service_name, key, default)

def _get_category_override(item: Dict[str, Any]) -> Dict[str, Any]:
    return _ConfigAccessor(CONFIG).category_override(item)

def _get_effective_setting(service_name: str, item: Dict[str, Any], key: str, default: Any) -> Any:
    return _ConfigAccessor(CONFIG).get_effective(service_name, item, key, default)

EVENT_BUS = EventBus(
    CONFIG,
    structured_logs=STRUCTURED_LOGS,
    dry_run=DRY_RUN,
    debug_logging=DEBUG_LOGGING,
    logger=EVENT_LOG,
)


def _log_event(event: str, **fields):
    payload = {"event": event, **fields}
    try:
        if STRUCTURED_LOGS:
            EVENT_LOG.info(json.dumps(payload, ensure_ascii=False))
        else:
            EVENT_LOG.info(f"{event}: {fields}")
    except Exception:
        EVENT_LOG.info(str(payload))

# Notifications handled by integrations.notifications facade

# Optional: treat low-seed, low-progress torrents as stalled
# - TORRENT_SEEDER_STALL_THRESHOLD <= N seeders will be considered stalled (only for torrent items)
# - TORRENT_SEEDER_STALL_PROGRESS_CEILING only applies the above when progress percent is <= this ceiling
#   Set to 100 to apply regardless of progress; set threshold < 0 to disable feature entirely.
TORRENT_SEEDER_STALL_THRESHOLD = int(_get_general('torrent_seeder_stall_threshold', get_env_var('TORRENT_SEEDER_STALL_THRESHOLD', default=-1, cast_to=int)))
TORRENT_SEEDER_STALL_PROGRESS_CEILING = float(_get_general('torrent_seeder_stall_progress_ceiling', get_env_var('TORRENT_SEEDER_STALL_PROGRESS_CEILING', default=25.0, cast_to=float)))

strike_dict = storage_load_strikes(STRIKE_FILE_PATH, DEBUG_LOGGING)
strike_lock = asyncio.Lock()

def save_strikes(data: Dict[str, Any]) -> None:
    storage_save_strikes(data, STRIKE_FILE_PATH)

def _make_strike_key(service_name, item_id):
    return storage_make_key(service_name, item_id)

def _normalize_strike_entry(entry):
    return storage_normalize_entry(entry)

from core.utils import (
    get_downloaded_bytes as _get_downloaded_bytes,
    get_total_size as _get_total_size,
    get_progress_percent as _get_progress_percent,
    get_seeders as _get_seeders,
    get_indexer_name as _get_indexer_name,
)

 

from core.utils import is_whitelisted as _is_whitelisted_raw

def _is_whitelisted(service_name: str, item: Dict[str, Any]) -> bool:
    wl = CONFIG.get('whitelist') if isinstance(CONFIG.get('whitelist'), dict) else {}
    return _is_whitelisted_raw(item, wl)

from core.rules import (
    is_torrent as rules_is_torrent,
    is_queued as rules_is_queued,
    evaluate_rules as rules_evaluate_rules,
)

 

from integrations.services import is_service_configured as svc_is_configured
from integrations.services import throttled_request as svc_throttled_request
from integrations.services import RequestManager as _RequestManager

async def _throttled_request(session, service_name: str, url, api_key, params=None, json_data=None, method='get'):
    # Use a scoped request manager to isolate throttle/semaphore state per runner
    global _REQ_MANAGER
    try:
        _REQ_MANAGER
    except NameError:
        _REQ_MANAGER = _RequestManager()
    try:
        min_interval_ms = float(_get_service_setting(service_name, 'min_request_interval_ms', DEFAULT_MIN_REQUEST_INTERVAL_MS))
    except Exception:
        min_interval_ms = 0.0
    try:
        max_conc = int(_get_service_setting(service_name, 'max_concurrent_requests', DEFAULT_MAX_CONCURRENT_REQUESTS))
    except Exception:
        max_conc = 0
    return await _REQ_MANAGER.throttled_request(
        session,
        service_name,
        url,
        api_key,
        params=params,
        json_data=json_data,
        method=method,
        min_interval_ms=min_interval_ms,
        max_concurrent=max_conc,
        request_timeout=REQUEST_TIMEOUT,
        retry_attempts=RETRY_ATTEMPTS,
        retry_backoff=RETRY_BACKOFF,
        debug_logging=DEBUG_LOGGING,
    )

removal_reasons: Dict[str, str] = {}
reannounce_requests: Dict[str, bool] = {}

def process_queue_item(service_name, item, stall_limit, metrics):
    # Returns (should_remove, trigger_search)
    if 'id' not in item:
        return (False, False)
    try:
        # Supports both dict and Metrics class
        metrics['processed'] = metrics.get('processed', 0) + 1
        metrics[f'svc:{service_name}:processed'] = metrics.get(f'svc:{service_name}:processed', 0) + 1
    except Exception:
        pass
    key = _make_strike_key(service_name, item['id'])
    entry = _normalize_strike_entry(strike_dict.get(key, {"count": 0, "last_dl": None}))
    now = time.time()

    # Detect completed downloads early so we can preserve them
    # even if indexer/tracker failures occur afterwards.
    try:
        _sz_left = item.get('sizeleft') if item.get('sizeleft') is not None else item.get('sizeLeft')
        _sz_left_zero = (int(_sz_left) == 0) if _sz_left is not None else False
    except Exception:
        _sz_left_zero = False
    try:
        _pct_prog = _get_progress_percent(item)
        fully_downloaded = bool(_sz_left_zero or (_pct_prog is not None and _pct_prog >= 99.9))
    except Exception:
        fully_downloaded = bool(_sz_left_zero)

    # Per-indexer failure policy
    idx = _get_indexer_name(item)
    idx_policies = CONFIG.get('indexer_policies') if isinstance(CONFIG.get('indexer_policies'), dict) else {}
    idx_cfg = idx_policies.get(idx) if isinstance(idx_policies, dict) else None
    try:
        idx_fail_after = int((idx_cfg or {}).get('failure_remove_after', DEFAULT_INDEXER_FAILURE_REMOVE_AFTER))
    except Exception:
        idx_fail_after = DEFAULT_INDEXER_FAILURE_REMOVE_AFTER
    if idx and idx_fail_after:
        ikey = f"{service_name}:_indexer:{idx}"
        ientry = strike_dict.get(ikey) or {}
        if int(ientry.get('failures') or 0) >= idx_fail_after:
            if fully_downloaded:
                # Preserve completed downloads from indexer failure policy removals
                entry['last_reason'] = 'completed_preserved_indexer_failure'
                strike_dict[key] = entry
                if EXPLAIN_DECISIONS:
                    _log_event('preserve_completed_indexer_failure', service=service_name, id=item.get('id'), title=item.get('title'))
                return (False, False)
            removal_reasons[key] = 'indexer_failure_policy'
            strike_dict.pop(key, None)
            try:
                metrics['removed_indexer_failure'] = metrics.get('removed_indexer_failure', 0) + 1
                metrics[f'svc:{service_name}:removed_indexer_failure'] = metrics.get(f'svc:{service_name}:removed_indexer_failure', 0) + 1
            except Exception:
                pass
            return (True, services[service_name]['auto_search'])
    # Whitelist check
    if _is_whitelisted(service_name, item):
        entry['last_reason'] = 'whitelisted'
        strike_dict[key] = entry
        if EXPLAIN_DECISIONS:
            _log_event('whitelisted', service=service_name, id=item.get('id'), title=item.get('title'))
        return (False, False)

    downloaded = _get_downloaded_bytes(item)
    status = (item.get('status') or '').lower()

    # Guard: preserve fully-downloaded items that have post-download errors (e.g., manual import required)
    # `fully_downloaded` computed earlier in the function.
    # Collate any status/error text to detect import-related issues
    texts = []
    for msg in (item.get('statusMessages') or []):
        texts.append(f"{msg.get('title','')} {msg.get('messages','')} {msg.get('message','')}")
    if item.get('errorMessage'):
        texts.append(str(item.get('errorMessage')))
    combined_txt = ' '.join(texts).lower()
    tds = (item.get('trackedDownloadStatus') or item.get('trackedDownloadState') or '').lower()
    # Heuristics: import-related signals or generic warning/error state after full download
    import_keywords = ('import failed', 'failed to import', 'manual import', 'manually import', 'manual intervention', 'waiting to import', 'waiting for import')
    import_related = any(k in combined_txt for k in import_keywords) or ('import' in combined_txt and any(s in combined_txt for s in ('fail', 'manual', 'intervention', 'waiting')))
    post_download_error = (tds in ('warning', 'error')) or (status in ('warning', 'error')) or import_related
    if fully_downloaded and post_download_error:
        # Do not count strikes or remove automatically; allow manual handling
        entry['last_reason'] = 'downloaded_but_errored'
        entry['last_dl'] = downloaded if downloaded is not None else entry.get('last_dl')
        entry['last_progress_ts'] = entry.get('last_progress_ts')  # keep as-is
        entry['last_seen_seeders'] = _get_seeders(item)
        strike_dict[key] = entry
        if EXPLAIN_DECISIONS:
            _log_event('skip_downloaded_errored', service=service_name, id=item.get('id'), title=item.get('title'))
        return (False, False)

    # Pre-progress checks: hard caps, tracker error accumulation, and reannounce scheduling
    # 1) Max queue age hard cap
    try:
        max_age_h = float(_get_effective_setting(service_name, item, 'max_queue_age_hours', DEFAULT_MAX_QUEUE_AGE_HOURS) or 0)
    except Exception:
        max_age_h = 0.0
    if max_age_h and (now - (entry.get('first_seen_ts') or now)) >= (max_age_h * 3600):
        removal_reasons[key] = 'max_age'
        strike_dict.pop(key, None)
        if EXPLAIN_DECISIONS:
            _log_event('remove', service=service_name, id=item.get('id'), title=item.get('title'), reason='max_age', dry_run=DRY_RUN)
        return (True, services[service_name]['auto_search'])

    # 2) Tracker error persistence (increment even if progress occurs)
    try:
        err_needed = int(_get_effective_setting(service_name, item, 'tracker_error_strikes', DEFAULT_TRACKER_ERROR_STRIKES) or 0)
    except Exception:
        err_needed = 0
    if err_needed:
        texts = []
        for msg in (item.get('statusMessages') or []):
            texts.append(f"{msg.get('title','')} {msg.get('messages','')} {msg.get('message','')}")
        if item.get('errorMessage'):
            texts.append(str(item.get('errorMessage')))
        # Include client tracker messages if available (e.g., qBittorrent)
        if item.get('clientTrackersMsg'):
            texts.append(str(item.get('clientTrackersMsg')))
        alltxt = ' '.join(texts).lower()
        phrases = ['unregistered', 'not registered', 'torrent not found', 'not found on tracker']
        if any(p in alltxt for p in phrases):
            entry['error_strikes'] = int(entry.get('error_strikes') or 0) + 1
            if entry['error_strikes'] >= err_needed:
                if fully_downloaded:
                    # Preserve completed downloads despite tracker/indexer error strikes
                    entry['last_reason'] = 'completed_preserved_tracker_error'
                    strike_dict[key] = entry
                    if EXPLAIN_DECISIONS:
                        _log_event('preserve_completed_tracker_error', service=service_name, id=item.get('id'), title=item.get('title'))
                    return (False, False)
                removal_reasons[key] = 'tracker_error'
                # track indexer failures
                idx = _get_indexer_name(item)
                if idx:
                    ikey = f"{service_name}:_indexer:{idx}"
                    ientry = strike_dict.get(ikey) or {}
                    ientry['failures'] = int(ientry.get('failures') or 0) + 1
                    ientry['last_ts'] = now
                    strike_dict[ikey] = ientry
                strike_dict.pop(key, None)
                if EXPLAIN_DECISIONS:
                    _log_event('remove', service=service_name, id=item.get('id'), title=item.get('title'), reason='tracker_error', dry_run=DRY_RUN)
                return (True, services[service_name]['auto_search'])
            else:
                strike_dict[key] = entry

    # 3) Reannounce scheduling (before any strike/removal)
    try:
        rea = CONFIG.get('rule_engine', {}).get('reannounce', {}) if isinstance(CONFIG.get('rule_engine'), dict) else {}
        rea_enabled = bool(rea.get('enabled', False))
    except Exception:
        rea_enabled = False
    if rea_enabled and rules_is_torrent(item):
        seeds = _get_seeders(item) or 0
        only_zero = bool(rea.get('only_when_seeds_zero', True))
        should_consider = (seeds == 0) if only_zero else True
        if should_consider:
            last = entry.get('last_reannounce_ts')
            attempts = int(entry.get('reannounce_attempts') or 0)
            cooldown = float(rea.get('cooldown_minutes', 60))
            max_attempts = int(rea.get('max_attempts', 1))
            if attempts < max_attempts and (not last or (now - float(last)) >= (cooldown * 60)):
                already = reannounce_requests.get(key, False)
                reannounce_requests[key] = True
                entry['last_reason'] = 'reannounce_scheduled'
                strike_dict[key] = entry
                try:
                    if not already:
                        metrics['reannounce_scheduled'] = metrics.get('reannounce_scheduled', 0) + 1
                except Exception:
                    pass
                if EXPLAIN_DECISIONS and not already:
                    _log_event('reannounce_scheduled', service=service_name, id=item.get('id'), title=item.get('title'))
                return (False, False)

    progressed = False
    if downloaded is not None and entry.get('last_dl') is not None:
        progressed = downloaded > (entry.get('last_dl') or 0)
    if status in ('downloading',):
        progressed = True if downloaded is None else (progressed or True)

    # If client zero-activity rule applies (peers=0 and seeds=0 for duration),
    # allow that rule to take precedence over byte-delta progress
    try:
        zero_act_min = float(_get_effective_setting(service_name, item, 'client_zero_activity_minutes', 0) or 0)
    except Exception:
        zero_act_min = 0.0
    if progressed and zero_act_min and rules_is_torrent(item):
        try:
            peers = int(item.get('clientPeers') if item.get('clientPeers') is not None else -1)
            seeds = int(item.get('clientSeeds') if item.get('clientSeeds') is not None else -1)
        except Exception:
            peers = seeds = -1
        lp = entry.get('last_progress_ts')
        if peers == 0 and seeds == 0 and lp and (now - float(lp)) >= (zero_act_min * 60):
            progressed = False

    try:
        effective_limit = int(_get_effective_setting(service_name, item, 'stall_limit', stall_limit))
    except Exception:
        effective_limit = stall_limit

    if progressed:
        _before_cnt = int(entry.get('count') or 0)
        if str(RESET_STRIKES_ON_PROGRESS).lower() == 'all':
            entry['count'] = 0
            try:
                if _before_cnt > 0:
                    metrics['strike_decreased'] = metrics.get('strike_decreased', 0) + 1
                    metrics[f'svc:{service_name}:strike_decreased'] = metrics.get(f'svc:{service_name}:strike_decreased', 0) + 1
            except Exception:
                pass
        else:
            try:
                dec = max(1, int(RESET_STRIKES_ON_PROGRESS))
            except Exception:
                dec = 1
            entry['count'] = max(0, _before_cnt - dec)
            try:
                if entry['count'] < _before_cnt:
                    metrics['strike_decreased'] = metrics.get('strike_decreased', 0) + 1
                    metrics[f'svc:{service_name}:strike_decreased'] = metrics.get(f'svc:{service_name}:strike_decreased', 0) + 1
            except Exception:
                pass
        entry['last_dl'] = downloaded if downloaded is not None else entry['last_dl']
        entry['last_progress_ts'] = now
        entry['last_seen_seeders'] = _get_seeders(item)
        entry['last_reason'] = 'progress'
        strike_dict[key] = entry
        if EXPLAIN_DECISIONS:
            _log_event('progress', service=service_name, id=item.get('id'), title=item.get('title'), strikes=entry['count'])
        return (False, False)

    # Do not strike/remove while queued/waiting for a slot
    if rules_is_queued(item):
        entry['last_reason'] = 'queued'
        entry['last_seen_seeders'] = _get_seeders(item)
        strike_dict[key] = entry
        try:
            metrics['queued'] = metrics.get('queued', 0) + 1
            metrics[f'svc:{service_name}:queued'] = metrics.get(f'svc:{service_name}:queued', 0) + 1
        except Exception:
            pass
        if EXPLAIN_DECISIONS:
            _log_event('queued', service=service_name, id=item.get('id'), title=item.get('title'))
        return (False, False)

    reason = rules_evaluate_rules(
        service_name,
        item,
        entry,
        progressed,
        get_effective_setting=_get_effective_setting,
        default_grace_minutes=DEFAULT_GRACE_PERIOD_MINUTES,
        default_max_queue_age_hours=DEFAULT_MAX_QUEUE_AGE_HOURS,
        default_no_progress_max_age_minutes=DEFAULT_NO_PROGRESS_MAX_AGE_MINUTES,
        default_min_speed_bps=DEFAULT_MIN_SPEED_BPS,
        default_min_speed_duration_min=DEFAULT_MIN_SPEED_DURATION_MIN,
        get_total_size=_get_total_size,
        get_seeders=_get_seeders,
        get_progress_percent=_get_progress_percent,
        get_indexer_name=_get_indexer_name,
        config=CONFIG,
        torrent_seeder_stall_threshold=TORRENT_SEEDER_STALL_THRESHOLD,
        torrent_seeder_stall_progress_ceiling=TORRENT_SEEDER_STALL_PROGRESS_CEILING,
    )
    if reason:
        # schedule reannounce/recheck if enabled and eligible; skip strike/removal this cycle
        def _should_try_reannounce_local():
            rule = CONFIG.get('rule_engine') if isinstance(CONFIG.get('rule_engine'), dict) else {}
            rea = rule.get('reannounce') if isinstance(rule.get('reannounce'), dict) else {}
            if not bool(rea.get('enabled', False)):
                return False
            now2 = time.time()
            last = entry.get('last_reannounce_ts')
            attempts = int(entry.get('reannounce_attempts') or 0)
            cooldown_min = float(rea.get('cooldown_minutes', 60))
            max_attempts = int(rea.get('max_attempts', 1))
            only_zero = bool(rea.get('only_when_seeds_zero', True))
            if attempts >= max_attempts:
                return False
            if last and (now2 - float(last)) < (cooldown_min * 60):
                return False
            seeds = _get_seeders(item) or 0
            if only_zero and seeds > 0:
                return False
            return True
        if _should_try_reannounce_local():
            already = reannounce_requests.get(key, False)
            reannounce_requests[key] = True
            entry['last_reason'] = 'reannounce_scheduled'
            strike_dict[key] = entry
            try:
                if not already:
                    metrics['reannounce_scheduled'] = metrics.get('reannounce_scheduled', 0) + 1
            except Exception:
                pass
            if EXPLAIN_DECISIONS and not already:
                _log_event('reannounce_scheduled', service=service_name, id=item.get('id'), title=item.get('title'))
            return (False, False)
        entry['last_dl'] = downloaded if downloaded is not None else entry.get('last_dl')
        entry['last_seen_seeders'] = _get_seeders(item)
        entry['last_reason'] = reason
        if reason == 'no_progress_timeout':
            # mark and remove immediately (no strikes)
            removal_reasons[key] = reason
            strike_dict.pop(key, None)
            if EXPLAIN_DECISIONS:
                _log_event('remove', service=service_name, id=item.get('id'), title=item.get('title'), reason=reason)
            return (True, services[service_name]['auto_search'])
        _before_cnt2 = int(entry.get('count') or 0)
        entry['count'] = _before_cnt2 + 1
        try:
            if entry['count'] > _before_cnt2:
                metrics['strike_increased'] = metrics.get('strike_increased', 0) + 1
                metrics[f'svc:{service_name}:strike_increased'] = metrics.get(f'svc:{service_name}:strike_increased', 0) + 1
        except Exception:
            pass
        strike_dict[key] = entry
        if entry['count'] >= effective_limit:
            removal_reasons[key] = reason
            strike_dict.pop(key, None)
            if DEBUG_LOGGING:
                logging.info(f'Service {service_name}: strike limit reached; removing id={item.get("id")} title={item.get("title")} reason={reason}')
            if EXPLAIN_DECISIONS:
                _log_event('remove', service=service_name, id=item.get('id'), title=item.get('title'), reason=reason)
            return (True, services[service_name]['auto_search'])
        else:
            if DEBUG_LOGGING:
                seeds = _get_seeders(item)
                pct = _get_progress_percent(item)
                extra = []
                if seeds is not None:
                    extra.append(f'seeds={seeds}')
                if pct is not None:
                    extra.append(f'progress={pct:.1f}%')
                ctx = f" ({', '.join(extra)})" if extra else ''
                logging.info(f'Service {service_name}: strike {entry["count"]} id={item.get("id")} title={item.get("title")} reason={reason}{ctx}')
        if EXPLAIN_DECISIONS:
            _log_event('strike', service=service_name, id=item.get('id'), title=item.get('title'), reason=reason, strikes=entry['count'])
    else:
        if downloaded is not None:
            entry['last_dl'] = downloaded
            entry['last_seen_seeders'] = _get_seeders(item)
            strike_dict[key] = entry
    return (False, False)

_ACTIONS_DEPS = _ActionsDeps(
    services=services,
    get_service_setting=lambda svc, key, default=None: _get_service_setting(svc, key, default),
    throttled_request=_throttled_request,
    event_bus=EVENT_BUS,
    debug_logging=DEBUG_LOGGING,
    dry_run=DRY_RUN,
)


async def remove_and_blacklist(session, service_name, item, reason: Optional[str] = None):
    await _actions.remove_and_blacklist(session, service_name, item, reason, _ACTIONS_DEPS)


async def blacklist_and_search_new_release(session, service_name, item):
    await _actions.blacklist_and_search_new_release(session, service_name, item, _ACTIONS_DEPS)

async def manage_downloads(session, service_config, service_name, metrics):
    deps = ServiceDeps(
        is_service_configured=svc_is_configured,
        throttled_request=_throttled_request,
        rules_is_torrent=rules_is_torrent,
        get_effective_setting=lambda svc, item, key, default=None: _get_effective_setting(svc, item, key, default),
        # Pass direct client facades bound with CONFIG to reduce wrappers usage
        get_client_speed=lambda s, it: __clients_get_client_speed(s, it, CONFIG),
        enrich_with_client_state=lambda s, svc, it: __clients_enrich_with_client_state(s, svc, it, CONFIG),
        process_queue_item=process_queue_item,
        make_strike_key=_make_strike_key,
        normalize_strike_entry=_normalize_strike_entry,
        save_strikes=save_strikes,
        attempt_reannounce=lambda s, it, entry: __clients_attempt_reannounce(s, it, entry, CONFIG, EXPLAIN_DECISIONS, _log_event),
        remove_and_blacklist=remove_and_blacklist,
        blacklist_and_search_new_release=blacklist_and_search_new_release,
        explain_decisions=EXPLAIN_DECISIONS,
        log_event=_log_event,
        dry_run=DRY_RUN,
        debug_logging=DEBUG_LOGGING,
        state=None,  # filled below
    )
    # Fill state reference
    deps.state = RunnerState(
        api_timeout=API_TIMEOUT,
        strike_dict=strike_dict,
        strike_lock=strike_lock,
        reannounce_requests=reannounce_requests,
        removal_reasons=removal_reasons,
        reannounce_seen=set(),
        processed_seen=set(),
    )
    await runner_manage_service(session, service_config, service_name, metrics, deps)

from core.runner import (
    RunnerState,
    run_forever as runner_run_forever,
    ServiceDeps,
    manage_service as runner_manage_service,
)


async def main():
    async with aiohttp.ClientSession() as session:
        if DEBUG_LOGGING:
            logging.info('Running media-queue-cleaner script')

        async def _manage_cb(sess, svc_cfg, svc_name, metrics):
            return await manage_downloads(sess, svc_cfg, svc_name, metrics)

        async def _flush_cb(sess):
            await EVENT_BUS.flush(sess)

        def _log_fn(msg: str):
            logging.info(msg)

        state = RunnerState(
            api_timeout=API_TIMEOUT,
            strike_dict=strike_dict,
            strike_lock=strike_lock,
            reannounce_requests=reannounce_requests,
            removal_reasons=removal_reasons,
            reannounce_seen=set(),
            processed_seen=set(),
        )
        await runner_run_forever(session, services, state, _manage_cb, _flush_cb, _log_fn)

if __name__ == '__main__':
    asyncio.run(main())

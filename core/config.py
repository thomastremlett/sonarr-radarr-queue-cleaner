from __future__ import annotations

import os
from typing import Any, Dict, List, Optional


def load_yaml(path: str) -> Dict[str, Any]:
    try:
        import yaml  # type: ignore
    except Exception:
        return {}
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            data = yaml.safe_load(f) or {}
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _get_env(key: str, default: Any = None) -> Any:
    return os.environ.get(key, default)


class ConfigAccessor:
    def __init__(self, cfg: Dict[str, Any]) -> None:
        self.cfg = cfg if isinstance(cfg, dict) else {}

    # Category/profile-based overrides
    def category_override(self, item: Dict[str, Any]) -> Dict[str, Any]:
        cats = self.cfg.get('categories') if isinstance(self.cfg.get('categories'), list) else []
        title = (item.get('title') or '').lower()
        for cat in cats:
            if not isinstance(cat, dict):
                continue
            subs = cat.get('title_contains') or []
            try:
                if any(str(s).lower() in title for s in subs):
                    return cat
            except Exception:
                continue
        return {}

    # Generic precedence: category > services[svc] > rule_engine
    def get_effective(self, service_name: str, item: Dict[str, Any], key: str, default: Any = None) -> Any:
        cat = self.category_override(item) or {}
        if key in cat:
            return cat[key]
        return self.get_service_setting(service_name, key, default)

    def get_service_setting(self, service_name: str, key: str, default: Any = None) -> Any:
        services_cfg = self.cfg.get('services') if isinstance(self.cfg.get('services'), dict) else {}
        service_cfg = services_cfg.get(service_name, {}) if isinstance(services_cfg, dict) else {}
        if isinstance(service_cfg, dict) and key in service_cfg:
            return service_cfg[key]
        rule_cfg = self.cfg.get('rule_engine') if isinstance(self.cfg.get('rule_engine'), dict) else {}
        if isinstance(rule_cfg, dict) and key in rule_cfg:
            return rule_cfg[key]
        return default

    # Notifications accessors
    def notification_destinations(self) -> List[Dict[str, Any]]:
        notif = self.cfg.get('notifications') if isinstance(self.cfg.get('notifications'), dict) else {}
        dests = notif.get('destinations') if isinstance(notif.get('destinations'), list) else []
        out: List[Dict[str, Any]] = []
        for d in dests:
            if not isinstance(d, dict):
                continue
            url = d.get('url')
            typ = str(d.get('type') or 'generic').lower()
            if not url or typ not in {'discord', 'slack', 'generic'}:
                continue
            out.append(d)
        return out

    # Reannounce config
    def reannounce_config(self) -> Dict[str, Any]:
        rule = self.cfg.get('rule_engine') if isinstance(self.cfg.get('rule_engine'), dict) else {}
        return rule.get('reannounce') if isinstance(rule.get('reannounce'), dict) else {}

    # Clients
    def clients(self) -> Dict[str, Any]:
        return self.cfg.get('clients') if isinstance(self.cfg.get('clients'), dict) else {}

    # Endpoints from env (documented precedence: env-only)
    def service_endpoint(self, service_name: str) -> Dict[str, Optional[str]]:
        upper = service_name.upper()
        return {
            'api_url': _get_env(f'{upper}_URL') or None,
            'api_key': _get_env(f'{upper}_API_KEY') or None,
        }

    # General settings accessor
    def general(self, key: str, default: Any = None) -> Any:
        gen = self.cfg.get('general') if isinstance(self.cfg.get('general'), dict) else {}
        return gen.get(key, default)


def sanitize_config(cfg: Dict[str, Any], debug_logging: bool = False) -> Dict[str, Any]:
    if not isinstance(cfg, dict):
        return {}
    out = dict(cfg)

    def _nz(v, cast, default):
        try:
            return cast(v)
        except Exception:
            return default

    # Rule engine numeric coercions
    re_cfg = out.get('rule_engine') if isinstance(out.get('rule_engine'), dict) else {}
    if re_cfg:
        try:
            re_cfg['stall_limit'] = max(0, int(re_cfg.get('stall_limit', 0)))
        except Exception:
            re_cfg['stall_limit'] = 0
        re_cfg['grace_period_minutes'] = max(0, _nz(re_cfg.get('grace_period_minutes', 0), float, 0))
        re_cfg['no_progress_max_age_minutes'] = max(0, _nz(re_cfg.get('no_progress_max_age_minutes', 0), float, 0))
        re_cfg['min_request_interval_ms'] = max(0, _nz(re_cfg.get('min_request_interval_ms', 0), float, 0))
        re_cfg['max_concurrent_requests'] = max(0, _nz(re_cfg.get('max_concurrent_requests', 0), int, 0))
        re_cfg['max_queue_age_hours'] = max(0, _nz(re_cfg.get('max_queue_age_hours', 0), float, 0))
        re_cfg['tracker_error_strikes'] = max(0, _nz(re_cfg.get('tracker_error_strikes', 0), int, 0))
        re_cfg['min_speed_bytes_per_sec'] = max(0, _nz(re_cfg.get('min_speed_bytes_per_sec', 0), float, 0))
        re_cfg['min_speed_duration_minutes'] = max(0, _nz(re_cfg.get('min_speed_duration_minutes', 0), float, 0))
        rea = re_cfg.get('reannounce') if isinstance(re_cfg.get('reannounce'), dict) else {}
        if rea:
            rea['cooldown_minutes'] = max(0, _nz(rea.get('cooldown_minutes', 60), float, 60))
            rea['max_attempts'] = max(0, _nz(rea.get('max_attempts', 1), int, 1))
        out['rule_engine'] = re_cfg

    # Notifications destinations validation/cleanup
    notif = out.get('notifications') if isinstance(out.get('notifications'), dict) else {}
    dests = notif.get('destinations') if isinstance(notif.get('destinations'), list) else []
    valid_types = {'discord', 'slack', 'generic'}
    cleaned = []
    for d in dests:
        if not isinstance(d, dict):
            continue
        url = d.get('url')
        typ = str(d.get('type') or 'generic').lower()
        if not url or typ not in valid_types:
            if debug_logging:
                import logging
                logging.warning(f'Ignoring invalid notification destination: {d}')
            continue
        rs = d.get('reasons')
        if rs is not None and not isinstance(rs, list):
            d['reasons'] = [str(rs)]
        cleaned.append(d)
    if cleaned:
        notif['destinations'] = cleaned
        out['notifications'] = notif

    # Services numeric sanitization (e.g., stall_limit)
    sv = out.get('services') if isinstance(out.get('services'), dict) else {}
    for sname, scfg in list(sv.items() if isinstance(sv, dict) else []):
        if isinstance(scfg, dict):
            try:
                if 'stall_limit' in scfg:
                    scfg['stall_limit'] = max(0, int(scfg.get('stall_limit') or 0))
            except Exception:
                scfg['stall_limit'] = scfg.get('stall_limit')
    return out


def validate_config(cfg: Dict[str, Any], debug_logging: bool = False) -> None:
    try:
        import logging as _lg
        problems = []
        # Service env pairs
        svcs = ['Sonarr', 'Radarr', 'Lidarr']
        for s in svcs:
            url = os.environ.get(f'{s.upper()}_URL') or None
            key = os.environ.get(f'{s.upper()}_API_KEY') or None
            if (url and not key) or (key and not url):
                problems.append(f"Service {s} has partial env config (URL/API_KEY); it will be skipped.")
        # Rule engine sanity
        re_cfg = cfg.get('rule_engine') if isinstance(cfg.get('rule_engine'), dict) else {}
        if re_cfg:
            if float(re_cfg.get('min_request_interval_ms') or 0) > 0 and int(re_cfg.get('max_concurrent_requests') or 0) == 0:
                problems.append('min_request_interval_ms set without max_concurrent_requests; consider setting both for effect.')
        # Notification destination checks
        notif = cfg.get('notifications') if isinstance(cfg.get('notifications'), dict) else {}
        dests = notif.get('destinations') if isinstance(notif.get('destinations'), list) else []
        if dests:
            for d in dests:
                if not d.get('url'):
                    problems.append(f"Notification destination '{d.get('name') or d.get('type')}' missing url; it will be ignored.")
        for p in problems:
            _lg.warning(p)
    except Exception:
        # Never raise due to validation
        pass

import importlib


def _eval_reason(cfg, service_name, item, entry):
    rules = importlib.import_module('core.rules')
    utils = importlib.import_module('core.utils')
    # simple accessor: service-level only via cfg
    def get_effective(svc, it, key, default=None):
        srv = (cfg.get('services') or {}).get(svc, {}) if isinstance(cfg.get('services'), dict) else {}
        if key in (srv or {}):
            return srv[key]
        return (cfg.get('rule_engine') or {}).get(key, default)

    return rules.evaluate_rules(
        service_name,
        item,
        entry,
        progressed=False,
        get_effective_setting=get_effective,
        default_grace_minutes=0,
        default_max_queue_age_hours=0,
        default_no_progress_max_age_minutes=0,
        default_min_speed_bps=0,
        default_min_speed_duration_min=0,
        get_total_size=utils.get_total_size,
        get_seeders=utils.get_seeders,
        get_progress_percent=utils.get_progress_percent,
        get_indexer_name=utils.get_indexer_name,
        config=cfg,
        torrent_seeder_stall_threshold=0,
        torrent_seeder_stall_progress_ceiling=100,
    )


def test_min_speed_rule_triggers():
    cfg = {'rule_engine': {'min_speed_bytes_per_sec': 1024, 'min_speed_duration_minutes': 10}}
    item = {'id': 1, 'protocol': 'torrent', 'size': 2000, 'sizeleft': 1000, 'clientDlSpeed': 500}
    entry = {'last_progress_ts': __import__('time').time() - 11 * 60}
    r = _eval_reason(cfg, 'Sonarr', item, entry)
    assert r == 'min_speed'


def test_client_zero_activity_rule():
    cfg = {'rule_engine': {'client_zero_activity_minutes': 5}}
    item = {'id': 2, 'protocol': 'torrent', 'size': 1000, 'sizeleft': 900, 'clientPeers': 0, 'clientSeeds': 0}
    entry = {'last_progress_ts': __import__('time').time() - 6 * 60}
    r = _eval_reason(cfg, 'Sonarr', item, entry)
    assert r == 'client_no_peers'


def test_client_state_as_stalled_rule():
    cfg = {'services': {'Sonarr': {'client_state_as_stalled': True}}}
    item = {'id': 3, 'protocol': 'torrent', 'size': 1000, 'sizeleft': 900, 'clientState': 'stalledDL'}
    entry = {'last_progress_ts': None}
    r = _eval_reason(cfg, 'Sonarr', item, entry)
    assert r == 'client_state'


def test_large_zero_seeders_rule():
    cfg = {'rule_engine': {'large_size_gb': 1, 'large_zero_seeders_remove_minutes': 1, 'large_progress_ceiling_percent': 100}}
    item = {'id': 4, 'protocol': 'torrent', 'size': 2 * (1024**3), 'sizeleft': 2 * (1024**3), 'release': {'seeders': 0}}
    entry = {'first_seen_ts': __import__('time').time() - 2 * 60}
    r = _eval_reason(cfg, 'Sonarr', item, entry)
    assert r == 'large_zero_seeders'


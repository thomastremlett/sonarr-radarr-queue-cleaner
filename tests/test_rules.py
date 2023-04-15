import time
import importlib

import pytest


@pytest.fixture(autouse=True)
def reset_module_state(monkeypatch):
    # Reload to ensure a fresh module state each test
    if 'cleaner' in list(globals()):
        import sys
        sys.modules.pop('cleaner', None)
    cleaner = importlib.import_module('cleaner')
    cleaner.strike_dict.clear()
    # Minimal service config
    cleaner.services.setdefault('Sonarr', {
        'api_url': '', 'api_key': '', 'stall_limit': 1, 'auto_search': False
    })
    # Reset global CONFIG
    cleaner.CONFIG.clear()
    yield


def _key(cleaner, item_id):
    return f"Sonarr:{item_id}"


def test_whitelist_skips_strikes_and_removal(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # Add whitelist for this ID
    cleaner.CONFIG.update({'whitelist': {'ids': [500]}})

    item = {
        'id': 500,
        'title': 'Whitelisted Item',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert (should_remove, trigger_search) == (False, False)
    entry = cleaner.strike_dict.get(_key(cleaner, 500))
    assert entry is not None and entry.get('last_reason') == 'whitelisted'


def test_max_queue_age_triggers_removal(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'rule_engine': {'max_queue_age_hours': 1}})

    item = {
        'id': 600,
        'title': 'Old Item',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
    }
    key = _key(cleaner, 600)
    cleaner.strike_dict[key] = {
        'count': 0,
        'last_dl': 100,
        'first_seen_ts': time.time() - 2 * 3600,  # 2 hours ago
        'last_progress_ts': None,
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True


def test_tracker_error_persistence(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'rule_engine': {'tracker_error_strikes': 2}})

    base_item = {
        'id': 700,
        'title': 'Bad Tracker',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'statusMessages': [{'title': 'Tracker', 'message': 'Unregistered torrent'}],
    }
    key = _key(cleaner, 700)
    cleaner.strike_dict[key] = {'count': 0, 'last_dl': 0, 'first_seen_ts': time.time() - 600}

    metrics = {}
    # First pass: increments error_strikes but not enough to remove
    sr1, ts1 = cleaner.process_queue_item('Sonarr', base_item, stall_limit=2, metrics=metrics)
    assert sr1 is False
    # Ensure entry persisted with error_strikes >= 1
    assert cleaner.strike_dict[key].get('error_strikes', 0) >= 1

    # Second pass: should return reason tracker_error and strike to removal if stall_limit=1
    sr2, ts2 = cleaner.process_queue_item('Sonarr', base_item, stall_limit=1, metrics=metrics)
    assert sr2 is True


def test_min_speed_rule(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'rule_engine': {'min_speed_bytes_per_sec': 1024, 'min_speed_duration_minutes': 10}})

    item = {
        'id': 800,
        'title': 'Too Slow',
        'protocol': 'torrent',
        'size': 2000,
        'sizeleft': 1500,
        'clientDlSpeed': 500,  # below threshold
    }
    key = _key(cleaner, 800)
    cleaner.strike_dict[key] = {
        'count': 0,
        'last_dl': 500,
        'first_seen_ts': time.time() - 3600,
        'last_progress_ts': time.time() - 3600,  # no progress for > duration
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True


def test_min_speed_rule_no_speed_info(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'rule_engine': {'min_speed_bytes_per_sec': 1024, 'min_speed_duration_minutes': 10}})

    item = {
        'id': 801,
        'title': 'Too Slow No Info',
        'protocol': 'torrent',
        'size': 2000,
        'sizeleft': 1500,
        # No clientDlSpeed provided
    }
    key = _key(cleaner, 801)
    cleaner.strike_dict[key] = {
        'count': 0,
        'last_dl': 500,
        'first_seen_ts': time.time() - 3600,
        'last_progress_ts': time.time() - 3600,
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    # min-speed rule should not trigger without speed info
    assert should_remove is False


def test_structured_logs_for_remove_and_strike(monkeypatch, caplog):
    cleaner = importlib.import_module('cleaner')
    # Enable structured logs and explain mode
    monkeypatch.setattr(cleaner, 'STRUCTURED_LOGS', True, raising=False)
    monkeypatch.setattr(cleaner, 'EXPLAIN_DECISIONS', True, raising=False)
    import logging as _logging
    caplog.set_level(_logging.INFO)
    # Force immediate remove via max age to trigger a 'remove' event from process_queue_item
    cleaner.CONFIG.update({'rule_engine': {'max_queue_age_hours': 1}})
    item = {
        'id': 950,
        'title': 'Old Item For Logs',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
    }
    key = _key(cleaner, 950)
    cleaner.strike_dict[key] = {
        'count': 0,
        'last_dl': 0,
        'first_seen_ts': time.time() - 2 * 3600,
    }
    caplog.clear()
    should_remove, _ = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics={})
    assert should_remove is True

    # Now test 'strike' event: configure low seeders and stall_limit > 1
    caplog.clear()
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_THRESHOLD', 0, raising=False)
    item2 = {
        'id': 951,
        'title': 'Low Seeds For Strike',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'release': {'seeders': 0},
    }
    should_remove2, _ = cleaner.process_queue_item('Sonarr', item2, stall_limit=5, metrics={})
    assert should_remove2 is False
    found_strike = any('"event": "strike"' in rec.message for rec in caplog.records)
    assert found_strike


def test_reannounce_is_scheduled(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # Enable reannounce scheduling
    cleaner.CONFIG.update({'rule_engine': {
        'reannounce': {
            'enabled': True,
            'cooldown_minutes': 60,
            'max_attempts': 1,
            'do_recheck': False,
            'only_when_seeds_zero': True,
        }
    }})
    # Enable low-seeder rule globally
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_THRESHOLD', 0, raising=False)

    item = {
        'id': 900,
        'title': 'Zero Seeds triggers reannounce',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'release': {'seeders': 0},
    }
    key = _key(cleaner, 900)
    cleaner.strike_dict[key] = {
        'count': 0,
        'last_dl': 100,
        'first_seen_ts': time.time() - 3600,
        'last_progress_ts': time.time() - 3600,
    }

    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    # Not removed on this cycle; reannounce should be scheduled
    assert (should_remove, trigger_search) == (False, False)
    assert cleaner.reannounce_requests.get(key) is True


def test_category_override_stall_limit(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # Category overrides stall_limit to 1 for titles containing 'UHD'
    cleaner.CONFIG.update({'categories': [
        {'title_contains': ['UHD'], 'stall_limit': 1}
    ]})
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_THRESHOLD', 0, raising=False)
    item = {
        'id': 1000,
        'title': 'Movie 2160p UHD Release',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'release': {'seeders': 0},
    }
    metrics = {}
    should_remove, _ = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True


def test_indexer_failure_policy_immediate_remove(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # Configure failure policy
    cleaner.CONFIG.update({'indexer_policies': {'IndexerX': {'failure_remove_after': 1}}})
    # Pre-populate failure counter
    cleaner.strike_dict['Sonarr:_indexer:IndexerX'] = {'failures': 1, 'last_ts': time.time() - 10}
    item = {
        'id': 1100,
        'title': 'Some Title',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'indexerName': 'IndexerX',
    }
    metrics = {}
    should_remove, _ = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True


def test_tracker_error_increments_indexer_counter(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'rule_engine': {'tracker_error_strikes': 1}})
    item = {
        'id': 1200,
        'title': 'Bad Tracker',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'statusMessages': [{'title': 'Tracker', 'message': 'Torrent not found on tracker'}],
        'indexer': 'IndexerY',
    }
    metrics = {}
    should_remove, _ = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True
    idx_key = 'Sonarr:_indexer:IndexerY'
    assert cleaner.strike_dict.get(idx_key, {}).get('failures', 0) >= 1


def test_client_zero_activity_minutes_rule(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'rule_engine': {'client_zero_activity_minutes': 5}})
    item = {
        'id': 1300,
        'title': 'No Peers Or Seeds',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'clientPeers': 0,
        'clientSeeds': 0,
    }
    key = _key(cleaner, 1300)
    cleaner.strike_dict[key] = {
        'count': 0,
        'last_dl': 0,
        'first_seen_ts': time.time() - 3600,
        'last_progress_ts': time.time() - 3600,
    }
    metrics = {}
    should_remove, _ = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True


def test_client_state_as_stalled_rule(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'services': {'Sonarr': {'client_state_as_stalled': True}}})
    item = {
        'id': 1400,
        'title': 'Stalled State',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'clientState': 'stalledDL',
    }
    metrics = {}
    should_remove, _ = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True

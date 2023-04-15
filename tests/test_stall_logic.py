import importlib

import pytest


@pytest.fixture(autouse=True)
def reload_cleaner_and_reset_state(monkeypatch):
    # Ensure environment-driven constants can be overridden in tests
    if 'cleaner' in list(globals()):
        import sys
        sys.modules.pop('cleaner', None)
    cleaner = importlib.import_module('cleaner')
    # Reset global strike dict for isolation
    cleaner.strike_dict.clear()
    # Make sure Sonarr config exists
    cleaner.services.setdefault('Sonarr', {
        'api_url': '', 'api_key': '', 'stall_limit': 1, 'auto_search': False
    })
    yield


def _sonarr_key(cleaner, item_id):
    return f"Sonarr:{item_id}"


def test_torrent_zero_seeders_low_progress_is_stalled_and_removes(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # Enable seed-based stall rule
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_THRESHOLD', 0, raising=False)
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_PROGRESS_CEILING', 25.0, raising=False)
    # Make auto_search True to verify trigger flag
    cleaner.services['Sonarr']['auto_search'] = True

    item = {
        'id': 101,
        'title': 'ZeroSeedersLowProgress',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,  # 10% complete
        'release': {'seeders': 0},
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is True
    assert trigger_search is True
    # Strike entry should be removed after hitting limit
    assert cleaner._make_strike_key('Sonarr', 101) not in cleaner.strike_dict


def test_threshold_disabled_does_not_count_strike(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # Disable seed-based rule
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_THRESHOLD', -1, raising=False)
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_PROGRESS_CEILING', 25.0, raising=False)

    item = {
        'id': 102,
        'title': 'DisabledSeedRule',
        'status': 'queued',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 900,
        'release': {'seeders': 0},
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert should_remove is False
    assert trigger_search is False
    key = _sonarr_key(cleaner, 102)
    # No strikes counted; only last_dl may be tracked
    assert cleaner.strike_dict.get(key, {}).get('count', 0) == 0


def test_progress_resets_strikes_all(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    monkeypatch.setattr(cleaner, 'RESET_STRIKES_ON_PROGRESS', 'all', raising=False)
    key = _sonarr_key(cleaner, 200)
    cleaner.strike_dict[key] = {'count': 3, 'last_dl': 100}
    item = {
        'id': 200,
        'title': 'ProgressResetAll',
        'status': 'queued',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 800,  # downloaded=200 > last_dl=100
        'release': {'seeders': 5},
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=3, metrics=metrics)
    assert (should_remove, trigger_search) == (False, False)
    assert cleaner.strike_dict[key]['count'] == 0
    assert cleaner.strike_dict[key]['last_dl'] == 200


def test_progress_decrements_strikes_integer(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    monkeypatch.setattr(cleaner, 'RESET_STRIKES_ON_PROGRESS', '2', raising=False)
    key = _sonarr_key(cleaner, 201)
    cleaner.strike_dict[key] = {'count': 3, 'last_dl': 100}
    item = {
        'id': 201,
        'title': 'ProgressDecrementTwo',
        'status': 'queued',
        'protocol': 'torrent',
        'size': 1000,
        'sizeleft': 700,  # downloaded=300 > last_dl=100
        'release': {'seeders': 5},
    }
    metrics = {}
    cleaner.process_queue_item('Sonarr', item, stall_limit=3, metrics=metrics)
    assert cleaner.strike_dict[key]['count'] == 1
    assert cleaner.strike_dict[key]['last_dl'] == 300


def test_unknown_progress_and_zero_seeders_flags_stalled(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_THRESHOLD', 0, raising=False)
    monkeypatch.setattr(cleaner, 'TORRENT_SEEDER_STALL_PROGRESS_CEILING', 25.0, raising=False)
    cleaner.services['Sonarr']['auto_search'] = False

    item = {
        'id': 300,
        'title': 'UnknownProgressZeroSeeders',
        'protocol': 'torrent',
        # No size/sizeleft => unknown progress percent
        'release': {'seeders': 0},
    }
    metrics = {}
    should_remove, trigger_search = cleaner.process_queue_item('Sonarr', item, stall_limit=1, metrics=metrics)
    assert (should_remove, trigger_search) == (True, False)

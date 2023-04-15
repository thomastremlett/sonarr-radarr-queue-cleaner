import importlib
import pytest
import integrations.clients as clients


pytestmark = pytest.mark.asyncio


class DummySession:
    pass


@pytest.fixture(autouse=True)
def reload_cleaner_and_reset_state(monkeypatch):
    if 'cleaner' in list(globals()):
        import sys
        sys.modules.pop('cleaner', None)
    cleaner = importlib.import_module('cleaner')
    cleaner.strike_dict.clear()
    cleaner.CONFIG.clear()
    cleaner.services.setdefault('Sonarr', {
        'api_url': '', 'api_key': '', 'stall_limit': 1, 'auto_search': False
    })
    yield


async def test_deluge_enrich_sets_state_peers_seeds_and_msgs(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'clients': {'deluge': {'url': 'http://deluge/json', 'password': 'deluge'}}})

    async def fake_get_info(session, url, password, info_hash):
        return {
            'state': 'Downloading',
            'num_peers': 3,
            'num_seeds': 1,
            'tracker_status': 'unregistered torrent',
        }

    import integrations.clients.deluge as deluge_mod
    monkeypatch.setattr(deluge_mod, 'deluge_get_info', fake_get_info)

    item = {'id': 5, 'downloadId': 'ABCDEF1234'}
    await clients.enrich_with_client_state(DummySession(), 'Sonarr', item, cleaner.CONFIG)

    assert item.get('clientState') in ('Downloading', 'downloading')
    assert item.get('clientPeers') == 3 or item.get('clientPeers') == 0
    assert item.get('clientSeeds') == 1 or item.get('clientSeeds') == 0
    assert 'clientTrackersMsg' in item


async def test_deluge_speed_used_in_get_client_speed(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    cleaner.CONFIG.update({'clients': {'deluge': {'url': 'http://deluge/json', 'password': 'deluge'}}})

    async def fake_speed(session, url, password, info_hash):
        return 12345

    import integrations.clients.deluge as deluge_mod
    monkeypatch.setattr(deluge_mod, 'deluge_get_speed', fake_speed)
    item = {'id': 6, 'downloadId': 'ABC'}
    spd = await clients.get_client_speed(DummySession(), item, cleaner.CONFIG)
    assert spd == 12345


async def test_deluge_reannounce_attempt(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    # enable reannounce
    cleaner.CONFIG.update({'rule_engine': {'reannounce': {'enabled': True}}})
    # ensure deluge configured
    cleaner.CONFIG.update({'clients': {'deluge': {'url': 'http://deluge/json', 'password': 'deluge'}}})

    async def fake_reannounce(session, url, password, info_hash, do_recheck):
        return True

    import integrations.clients.deluge as deluge_mod
    monkeypatch.setattr(deluge_mod, 'deluge_reannounce', fake_reannounce)

    entry = {'reannounce_attempts': 0}
    ok = await clients.attempt_reannounce(
        DummySession(), {'downloadId': 'HASH1', 'title': 'X'}, entry, cleaner.CONFIG, False, lambda *a, **k: None
    )
    assert ok is True

import importlib
import pytest


pytestmark = pytest.mark.asyncio


class DummySession:
    pass


async def test_qbittorrent_get_client_speed(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    clients = importlib.import_module('integrations.clients')
    cleaner.CONFIG.update({'clients': {'qbittorrent': {'url': 'http://qb', 'username': 'u', 'password': 'p'}}})

    import integrations.clients.qbittorrent as qb

    async def fake_speed(session, url, user, pwd, info_hash):
        return 777

    monkeypatch.setattr(qb, 'qbittorrent_get_speed', fake_speed)
    item = {'id': 1, 'downloadId': 'HASH'}
    spd = await clients.get_client_speed(DummySession(), item, cleaner.CONFIG)
    assert spd == 777


async def test_qbittorrent_enrich_sets_state_peers_and_msgs(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    clients = importlib.import_module('integrations.clients')
    cleaner.CONFIG.update({'clients': {'qbittorrent': {'url': 'http://qb', 'username': 'u', 'password': 'p'}}})

    import integrations.clients.qbittorrent as qb

    async def fake_info(session, url, user, pwd, info_hash):
        return {'state': 'stalledDL', 'num_leechs': 2, 'num_seeds': 5}

    async def fake_trackers(session, url, user, pwd, info_hash):
        return [{'msg': 'unregistered torrent'}]

    monkeypatch.setattr(qb, 'qbittorrent_get_info', fake_info)
    monkeypatch.setattr(qb, 'qbittorrent_get_trackers', fake_trackers)

    item = {'id': 2, 'downloadId': 'HASH2'}
    await clients.enrich_with_client_state(DummySession(), 'Sonarr', item, cleaner.CONFIG)
    assert item.get('clientState') == 'stalledDL'
    assert item.get('clientPeers') == 2
    assert item.get('clientSeeds') == 5
    assert 'clientTrackersMsg' in item


async def test_transmission_attempt_reannounce(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    clients = importlib.import_module('integrations.clients')
    cleaner.CONFIG.update({'rule_engine': {'reannounce': {'enabled': True}}})
    cleaner.CONFIG.update({'clients': {'transmission': {'url': 'http://tr', 'username': '', 'password': ''}}})

    import integrations.clients.transmission as tr

    async def fake_rpc(session, url, user, pwd, method, args):
        return True

    monkeypatch.setattr(tr, 'transmission_rpc', fake_rpc)
    entry = {'reannounce_attempts': 0}
    ok = await clients.attempt_reannounce(DummySession(), {'downloadId': 'H', 'title': 'T'}, entry, cleaner.CONFIG, False, lambda *a, **k: None)
    assert ok is True and entry.get('reannounce_attempts') == 1


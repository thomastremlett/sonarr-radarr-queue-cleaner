import importlib
import pytest


pytestmark = pytest.mark.asyncio


class FakeResp:
    def __init__(self, status=200, json_data=None, headers=None):
        self.status = status
        self._json = json_data
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        if isinstance(self._json, Exception):
            raise self._json
        return self._json


class QueueSession:
    def __init__(self, responses):
        # responses: list of tuples (method, FakeResp)
        self._q = list(responses)
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append(('POST', url, kwargs))
        assert self._q, f"Unexpected POST call to {url}"
        m, resp = self._q.pop(0)
        assert m == 'POST'
        return resp

    async def get(self, url, **kwargs):
        self.calls.append(('GET', url, kwargs))
        assert self._q, f"Unexpected GET call to {url}"
        m, resp = self._q.pop(0)
        assert m == 'GET'
        return resp


async def test_qbittorrent_speed_info_trackers_success():
    qb = importlib.import_module('integrations.clients.qbittorrent')
    # login OK, info returns list, trackers returns list
    session = QueueSession([
        ('POST', FakeResp(status=200)),  # login for speed
        ('GET', FakeResp(status=200, json_data=[{'dlspeed': 321, 'name': 't'}])),
        ('POST', FakeResp(status=200)),  # login for info
        ('GET', FakeResp(status=200, json_data=[{'name': 't'}])),
        ('POST', FakeResp(status=200)),  # login for trackers
        ('GET', FakeResp(status=200, json_data=[{'msg': 'ok'}])),
    ])
    spd = await qb.qbittorrent_get_speed(session, 'http://qb', 'u', 'p', 'HASH')
    assert spd == 321
    info = await qb.qbittorrent_get_info(session, 'http://qb', 'u', 'p', 'HASH')
    assert isinstance(info, dict)
    tr = await qb.qbittorrent_get_trackers(session, 'http://qb', 'u', 'p', 'HASH')
    assert isinstance(tr, list) and tr[0]['msg'] == 'ok'


async def test_qbittorrent_reannounce_with_recheck():
    qb = importlib.import_module('integrations.clients.qbittorrent')
    session = QueueSession([
        ('POST', FakeResp(status=200)),  # login
        ('POST', FakeResp(status=200)),  # reannounce
        ('POST', FakeResp(status=200)),  # recheck
    ])
    ok = await qb.qbittorrent_reannounce(session, 'http://qb', 'u', 'p', 'HASH', True)
    assert ok is True


async def test_transmission_rpc_session_handshake_then_success():
    tr = importlib.import_module('integrations.clients.transmission')
    # First returns 409 with session id header, then 200
    session = QueueSession([
        ('POST', FakeResp(status=409, headers={'X-Transmission-Session-Id': 'abc'})),
        ('POST', FakeResp(status=200)),
    ])
    ok = await tr.transmission_rpc(session, 'http://tr', None, None, 'torrent-get', {'ids': []})
    assert ok is True
    # Ensure second call included X-Transmission-Session-Id header
    assert 'X-Transmission-Session-Id' in session.calls[-1][2].get('headers', {})


async def test_transmission_get_speed_and_info():
    tr = importlib.import_module('integrations.clients.transmission')
    # get speed: first returns 409 then 200 with torrents list
    session = QueueSession([
        ('POST', FakeResp(status=409, headers={'X-Transmission-Session-Id': 'abc'})),
        ('POST', FakeResp(status=200, json_data={'arguments': {'torrents': [{'rateDownload': 555}]}})),
        ('POST', FakeResp(status=200, json_data={'arguments': {'torrents': [{'status': 4}]}})),
    ])
    spd = await tr.transmission_get_speed(session, 'http://tr', None, None, '1')
    assert spd == 555
    info = await tr.transmission_get_info(session, 'http://tr', None, None, '1')
    assert isinstance(info, dict) and info.get('status') == 4


async def test_deluge_request_and_helpers():
    dl = importlib.import_module('integrations.clients.deluge')
    # login ok, request returns result
    session = QueueSession([
        ('POST', FakeResp(status=200)),  # login for get_info
        ('POST', FakeResp(status=200, json_data={'result': {'state': 'Downloading', 'download_payload_rate': 42}})),
        ('POST', FakeResp(status=200)),  # login for get_speed (internal get_info)
        ('POST', FakeResp(status=200, json_data={'result': {'download_payload_rate': 42}})),
        ('POST', FakeResp(status=200)),  # login for reannounce
        ('POST', FakeResp(status=200, json_data={'result': True})),
        ('POST', FakeResp(status=200)),  # login for recheck
        ('POST', FakeResp(status=200, json_data={'result': True})),
    ])
    info = await dl.deluge_get_info(session, 'http://dl/json', 'pw', 'HASH')
    assert isinstance(info, dict) and info.get('state') == 'Downloading'
    spd = await dl.deluge_get_speed(session, 'http://dl/json', 'pw', 'HASH')
    assert spd == 42
    ok = await dl.deluge_reannounce(session, 'http://dl/json', 'pw', 'HASH', True)
    assert ok is True


async def test_qbittorrent_login_failure_returns_none_false():
    qb = importlib.import_module('integrations.clients.qbittorrent')
    # get_speed: login 401
    session1 = QueueSession([
        ('POST', FakeResp(status=401)),
    ])
    spd = await qb.qbittorrent_get_speed(session1, 'http://qb', 'u', 'p', 'H')
    assert spd is None
    # get_info: login 401
    session2 = QueueSession([
        ('POST', FakeResp(status=401)),
    ])
    info = await qb.qbittorrent_get_info(session2, 'http://qb', 'u', 'p', 'H')
    assert info is None
    # get_trackers: login 401
    session3 = QueueSession([
        ('POST', FakeResp(status=401)),
    ])
    tr = await qb.qbittorrent_get_trackers(session3, 'http://qb', 'u', 'p', 'H')
    assert tr is None
    # reannounce: login 401
    session4 = QueueSession([
        ('POST', FakeResp(status=401)),
    ])
    ok = await qb.qbittorrent_reannounce(session4, 'http://qb', 'u', 'p', 'H', False)
    assert ok is False


async def test_qbittorrent_non200_or_malformed_json_returns_none():
    qb = importlib.import_module('integrations.clients.qbittorrent')
    # After login 200, GET info 500
    session = QueueSession([
        ('POST', FakeResp(status=200)),
        ('GET', FakeResp(status=500)),
    ])
    info = await qb.qbittorrent_get_info(session, 'http://qb', 'u', 'p', 'H')
    assert info is None
    # Malformed JSON in info
    session2 = QueueSession([
        ('POST', FakeResp(status=200)),
        ('GET', FakeResp(status=200, json_data=ValueError('bad'))),
    ])
    info2 = await qb.qbittorrent_get_info(session2, 'http://qb', 'u', 'p', 'H')
    assert info2 is None


async def test_transmission_rpc_409_without_header_returns_false():
    tr = importlib.import_module('integrations.clients.transmission')
    session = QueueSession([
        ('POST', FakeResp(status=409, headers={})),
    ])
    ok = await tr.transmission_rpc(session, 'http://tr', None, None, 'torrent-get', {'ids': []})
    assert ok is False


async def test_transmission_non2xx_and_malformed_json():
    tr = importlib.import_module('integrations.clients.transmission')
    # get_speed non-2xx
    session = QueueSession([
        ('POST', FakeResp(status=404)),
    ])
    spd = await tr.transmission_get_speed(session, 'http://tr', None, None, '1')
    assert spd is None
    # rpc non-2xx
    session2 = QueueSession([
        ('POST', FakeResp(status=500)),
    ])
    ok = await tr.transmission_rpc(session2, 'http://tr', None, None, 'torrent-get', {'ids': []})
    assert ok is False
    # Malformed JSON for get_info
    session3 = QueueSession([
        ('POST', FakeResp(status=200, json_data=ValueError('bad'))),
    ])
    info = await tr.transmission_get_info(session3, 'http://tr', None, None, '1')
    assert info is None


async def test_deluge_request_non200_and_malformed_json():
    dl = importlib.import_module('integrations.clients.deluge')
    # Non-200 on method call
    session = QueueSession([
        ('POST', FakeResp(status=200)),
        ('POST', FakeResp(status=500)),
    ])
    j = await dl.deluge_request(session, 'http://dl/json', 'core.get_torrent_status', ['H', []], 'pw')
    assert j is None
    # Malformed JSON
    session2 = QueueSession([
        ('POST', FakeResp(status=200)),
        ('POST', FakeResp(status=200, json_data=ValueError('bad'))),
    ])
    j2 = await dl.deluge_request(session2, 'http://dl/json', 'core.get_torrent_status', ['H', []], 'pw')
    assert j2 is None

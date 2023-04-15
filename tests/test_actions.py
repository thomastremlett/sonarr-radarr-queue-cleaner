import importlib
import pytest


pytestmark = pytest.mark.asyncio


class DummySession:
    pass


class DummyBus:
    def __init__(self):
        self.events = []

    async def emit(self, session, event, *, service=None, item=None, reason=None, notify=False):
        self.events.append({
            'event': event, 'service': service, 'item': item, 'reason': reason, 'notify': notify
        })


async def test_remove_and_blacklist_dry_run_emits_notification(monkeypatch):
    actions = importlib.import_module('core.actions')
    cleaner = importlib.import_module('cleaner')

    deps = actions.ActionsDeps(
        services={'Sonarr': {'api_url': 'http://sonarr/api/v3', 'api_key': 'k'}},
        get_service_setting=lambda svc, k, d=None: True if k in ('use_blocklist_param', 'remove_from_client') else d,
        throttled_request=lambda *a, **k: None,
        event_bus=DummyBus(),
        debug_logging=False,
        dry_run=True,
    )

    item = {'id': 1, 'title': 'X'}
    await actions.remove_and_blacklist(DummySession(), 'Sonarr', item, reason='strike_limit', deps=deps)
    assert any(e['event'] == 'dry_remove' and e['notify'] for e in deps.event_bus.events)


async def test_remove_and_blacklist_real_calls_delete_and_emits(monkeypatch):
    actions = importlib.import_module('core.actions')

    called = {}

    async def fake_throttled(session, svc, url, api_key, **kw):
        called['url'] = url
        called['kw'] = kw
        return {'status': 204}

    bus = DummyBus()
    deps = actions.ActionsDeps(
        services={'Radarr': {'api_url': 'http://radarr/api/v3', 'api_key': 'k'}},
        get_service_setting=lambda svc, k, d=None: True if k in ('use_blocklist_param', 'remove_from_client') else d,
        throttled_request=fake_throttled,
        event_bus=bus,
        debug_logging=False,
        dry_run=False,
    )
    item = {'id': 9, 'title': 'Y'}
    await actions.remove_and_blacklist(DummySession(), 'Radarr', item, reason='max_age', deps=deps)
    assert 'url' in called and called['url'].endswith('/queue/9')
    assert called['kw'].get('method') == 'delete'
    assert any(e['event'] == 'remove' and e['notify'] for e in bus.events)


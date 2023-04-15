import importlib
import pytest


pytestmark = pytest.mark.asyncio


class FakeResp:
    def __init__(self, status=204):
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self):
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append({"url": url, "json": json, "headers": headers})
        return FakeResp(status=204)


async def test_flush_slack_batched_dry_run(monkeypatch):
    notif = importlib.import_module('integrations.notifications')
    cleaner = importlib.import_module('cleaner')

    dest = {'name': 'slack-batch', 'type': 'slack', 'url': 'http://slack-webhook', 'batch': True}
    notif.notify_dests['slack-batch'] = dest
    notif.notify_queues['slack-batch'] = ['line one', 'line two']

    session = FakeSession()
    await notif.flush_notifications(session, cleaner.CONFIG, True, False)

    assert len(session.calls) == 1
    assert session.calls[0]['url'] == 'http://slack-webhook'
    body = session.calls[0]['json']
    assert body.get('text', '').startswith('[DRY RUN]\n')
    assert 'line one' in body.get('text', '')


async def test_flush_generic_raw_json_batched_with_dry_flag(monkeypatch):
    notif = importlib.import_module('integrations.notifications')
    cleaner = importlib.import_module('cleaner')

    dest = {
        'name': 'generic-json', 'type': 'generic', 'url': 'http://generic', 'batch': True, 'raw_json': True,
    }
    notif.notify_dests['generic-json'] = dest
    notif.notify_queues['generic-json'] = ['{"a":1}', 'not json']

    session = FakeSession()
    await notif.flush_notifications(session, cleaner.CONFIG, True, False)

    assert len(session.calls) == 1
    assert session.calls[0]['url'] == 'http://generic'
    body = session.calls[0]['json']
    assert isinstance(body, dict) and isinstance(body.get('events'), list)
    assert body.get('dryRun') is True

import importlib
import json

import pytest


pytestmark = pytest.mark.asyncio


class FakeResp:
    def __init__(self, status=204, recorder=None):
        self.status = status
        self._recorder = recorder

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


class FakeSession:
    def __init__(self):
        self.calls = []

    async def post(self, url, json=None, headers=None, timeout=None):
        # record call
        self.calls.append({"url": url, "json": json, "headers": headers})
        return FakeResp(status=204)


@pytest.fixture(autouse=True)
def reload_cleaner_and_reset_state(monkeypatch):
    if 'cleaner' in list(globals()):
        import sys
        sys.modules.pop('cleaner', None)
    cleaner = importlib.import_module('cleaner')
    notif = importlib.import_module('integrations.notifications')
    cleaner.strike_dict.clear()
    notif.notify_queues.clear()
    notif.notify_dests.clear()
    cleaner.CONFIG.clear()
    cleaner.services.setdefault('Sonarr', {
        'api_url': '', 'api_key': '', 'stall_limit': 1, 'auto_search': False
    })
    yield


async def test_notifications_routing_and_queueing(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    notif = importlib.import_module('integrations.notifications')
    # Configure multi-destination routing
    cleaner.CONFIG.update({
        'notifications': {
            'destinations': [
                {'name': 'discord-default', 'type': 'discord', 'url': 'http://discord', 'batch': True,
                 'template': 'Removed {service} id={id} reason={reason}', 'reasons': ['*']},
                {'name': 'slack-errors', 'type': 'slack', 'url': 'http://slack', 'batch': False,
                 'template': '[{service}] {title}: {reason}', 'reasons': ['tracker_error']},
            ]
        }
    })

    # Capture immediate sends
    sent = []

    async def _send(session, dest, line, dry_run=False, debug_logging=False):
        sent.append({"dest": dest.get('name'), "line": line})

    monkeypatch.setattr(notif, '_notif_send_immediate', _send)

    item = {'id': 1, 'title': 'Example'}
    session = FakeSession()

    # Reason matches both: wildcard and tracker_error
    await notif.handle_notifications(session, 'Sonarr', item, 'tracker_error', cleaner.CONFIG, False, False)

    # Immediate send for slack-errors
    assert any(e['dest'] == 'slack-errors' for e in sent)
    # Batched for discord-default
    assert 'discord-default' in notif.notify_dests
    assert notif.notify_queues.get('discord-default') and len(notif.notify_queues['discord-default']) == 1


async def test_flush_batches_discord(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    notif = importlib.import_module('integrations.notifications')
    # Seed a batched discord destination
    dest = {'name': 'discord-default', 'type': 'discord', 'url': 'http://discord-webhook', 'batch': True}
    notif.notify_dests['discord-default'] = dest
    notif.notify_queues['discord-default'] = ['line one', 'line two']

    session = FakeSession()
    await notif.flush_notifications(session, cleaner.CONFIG, False, False)

    # One POST with joined content
    assert len(session.calls) == 1
    assert session.calls[0]['url'] == 'http://discord-webhook'
    assert 'content' in session.calls[0]['json']
    assert 'line one' in session.calls[0]['json']['content']
    assert 'line two' in session.calls[0]['json']['content']
    # Queue cleared
    assert notif.notify_queues['discord-default'] == []


async def test_generic_raw_json_immediate(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    notif = importlib.import_module('integrations.notifications')
    cleaner.CONFIG.update({
        'notifications': {
            'destinations': [
                {'name': 'generic-json', 'type': 'generic', 'url': 'http://generic', 'batch': False,
                 'raw_json': True,
                 'template': '{"service":"{service}","id":{id},"title":"{title}","reason":"{reason}"}',
                 'reasons': ['*']},
            ]
        }
    })
    session = FakeSession()
    item = {'id': 42, 'title': 'Some Title'}
    await notif.handle_notifications(session, 'Radarr', item, 'strike_limit', cleaner.CONFIG, False, False)
    # Immediate generic send with JSON body
    assert len(session.calls) == 1
    assert session.calls[0]['url'] == 'http://generic'
    body = session.calls[0]['json']
    assert isinstance(body, dict)
    # Expect keys from the template
    assert body.get('service') == 'Radarr'
    assert body.get('id') == 42
    assert body.get('title') == 'Some Title'
    assert body.get('reason') == 'strike_limit'


async def test_generic_raw_json_immediate_dry_run(monkeypatch):
    cleaner = importlib.import_module('cleaner')
    notif = importlib.import_module('integrations.notifications')
    cleaner.CONFIG.update({
        'notifications': {
            'destinations': [
                {'name': 'generic-json', 'type': 'generic', 'url': 'http://generic', 'batch': False,
                 'raw_json': True,
                 'template': '{"service":"{service}","id":{id},"title":"{title}","reason":"{reason}"}',
                 'reasons': ['*']},
            ]
        }
    })
    session = FakeSession()
    item = {'id': 99, 'title': 'Dry Title'}
    await notif.handle_notifications(session, 'Sonarr', item, 'strike_limit', cleaner.CONFIG, True, False)
    assert len(session.calls) == 1
    body = session.calls[0]['json']
    assert body.get('dryRun') is True

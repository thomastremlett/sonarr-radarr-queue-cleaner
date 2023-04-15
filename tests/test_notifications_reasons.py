import importlib
import pytest


pytestmark = pytest.mark.asyncio


class Capture:
    def __init__(self):
        self.sent = []


async def test_reasons_filter_blocks_non_matching(monkeypatch):
    notif = importlib.import_module('integrations.notifications')
    cleaner = importlib.import_module('cleaner')

    cfg = {
        'notifications': {
            'destinations': [
                {'name': 'wildcard', 'type': 'discord', 'url': 'http://d1', 'batch': False, 'reasons': ['*']},
                {'name': 'errors-only', 'type': 'slack', 'url': 'http://s1', 'batch': False, 'reasons': ['tracker_error']},
            ]
        }
    }

    cap = Capture()

    async def fake_send(session, dest, line, dry_run, debug_logging):
        cap.sent.append(dest.get('name'))

    monkeypatch.setattr(notif, '_notif_send_immediate', fake_send)

    await notif.handle_notifications(object(), 'Sonarr', {'id': 1, 'title': 'X'}, 'strike_limit', cfg, False, False)
    # Only wildcard gets sent
    assert cap.sent == ['wildcard']


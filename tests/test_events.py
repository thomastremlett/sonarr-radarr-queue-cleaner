import importlib
import pytest


pytestmark = pytest.mark.asyncio


class FakeLogger:
    def __init__(self):
        self.lines = []

    def info(self, msg):
        self.lines.append(str(msg))


class FakeNotif:
    def __init__(self):
        self.calls = []

    async def handle(self, session, service, item, reason, config, dry_run, debug_logging):
        self.calls.append((service, item, reason, dry_run))


async def test_event_bus_emit_logs_and_notifies(monkeypatch):
    events = importlib.import_module('core.events')
    fake_logger = FakeLogger()
    bus = events.EventBus({}, structured_logs=True, dry_run=True, debug_logging=False, logger=fake_logger)

    # Patch notifications facade
    fake = FakeNotif()
    mon = importlib.import_module('integrations.notifications')
    monkeypatch.setattr(mon, 'handle', fake.handle)

    await bus.emit(object(), 'remove', service='Sonarr', item={'id': 1, 'title': 'T'}, reason='x', notify=True)
    # logged
    assert any('"event": "remove"' in ln for ln in fake_logger.lines)
    # notified
    assert fake.calls and fake.calls[0][0] == 'Sonarr'


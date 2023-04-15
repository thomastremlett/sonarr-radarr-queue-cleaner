import importlib
import pytest


pytestmark = pytest.mark.asyncio


async def test_event_bus_flush_calls_notif_flush(monkeypatch):
    events = importlib.import_module('core.events')
    called = {}

    async def fake_flush(session, config, dry_run, debug_logging):
        called['args'] = (config, dry_run, debug_logging)

    notif = importlib.import_module('integrations.notifications')
    monkeypatch.setattr(notif, 'flush', fake_flush)

    fake_logger = type('L', (), {'info': lambda self, m: None})()
    bus = events.EventBus({'k': 'v'}, structured_logs=True, dry_run=True, debug_logging=True, logger=fake_logger)
    await bus.flush(object())
    assert 'args' in called
    cfg, dry_run, dbg = called['args']
    assert cfg == {'k': 'v'} and dry_run is True and dbg is True


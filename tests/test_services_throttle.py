import importlib
import asyncio
import pytest


pytestmark = pytest.mark.asyncio


async def test_request_manager_respects_max_concurrent(monkeypatch):
    svc = importlib.import_module('integrations.services')
    mgr = svc.RequestManager()

    inflight = 0
    max_inflight = 0

    async def fake_make(session, url, api_key, **kw):
        nonlocal inflight, max_inflight
        inflight += 1
        max_inflight = max(max_inflight, inflight)
        await asyncio.sleep(0)  # yield
        inflight -= 1
        return {'status': 204}

    # monkeypatch module-level make_api_request used by RequestManager
    monkeypatch.setattr(svc, 'make_api_request', fake_make)

    async def call_one():
        await mgr.throttled_request(object(), 'Sonarr', 'http://x', 'k', max_concurrent=1)

    await asyncio.gather(call_one(), call_one())
    assert max_inflight == 1


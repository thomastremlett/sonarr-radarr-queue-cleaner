import asyncio
import json

import pytest
from aioresponses import aioresponses
import aiohttp

from integrations.services import make_api_request


pytestmark = pytest.mark.asyncio


async def _call(url, method='get', status=200, payload=None):
    async with aiohttp.ClientSession() as session:
        return await make_api_request(
            session,
            url,
            api_key="dummy",
            method=method,
            json_data=payload,
        )


async def test_make_api_request_success_json():
    url = "http://example.com/api"
    with aioresponses() as m:
        m.get(url, payload={"ok": True})
        resp = await _call(url)
        assert resp == {"ok": True}


async def test_make_api_request_success_no_content():
    url = "http://example.com/api/no-content"
    with aioresponses() as m:
        m.delete(url, status=204)
        resp = await _call(url, method='delete')
        assert resp == {"status": 204}


async def test_make_api_request_retries_then_success(monkeypatch):
    url = "http://example.com/api/retry"
    with aioresponses() as m:
        m.get(url, status=500)
        m.get(url, payload={"ok": True})
        resp = await _call(url)
        assert resp == {"ok": True}


async def test_make_api_request_non_retriable_error():
    url = "http://example.com/api/not-found"
    with aioresponses() as m:
        m.get(url, status=404)
        resp = await _call(url)
        assert resp is None


async def test_make_api_request_timeout_retries(monkeypatch):
    url = "http://example.com/api/timeout"

    # Simulate a timeout followed by success
    with aioresponses() as m:
        m.get(url, exception=asyncio.TimeoutError())
        m.get(url, payload={"ok": True})
        resp = await _call(url)
        assert resp == {"ok": True}

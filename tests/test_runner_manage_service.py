import importlib
import asyncio
import pytest


pytestmark = pytest.mark.asyncio


async def test_manage_service_triggers_remove_and_increments_metrics():
    runner = importlib.import_module('core.runner')

    # Fake deps
    removed = {}

    async def fake_remove(session, service_name, item, reason):
        removed['called'] = (service_name, item.get('id'), reason)

    class Deps:
        pass

    async def _async_none(*args, **kwargs):
        return None

    deps = runner.ServiceDeps(
        is_service_configured=lambda svc_cfg: True,
        throttled_request=None,
        rules_is_torrent=lambda item: False,
        get_effective_setting=lambda svc, item, k, d=None: d,
        get_client_speed=_async_none,
        enrich_with_client_state=_async_none,
        process_queue_item=lambda svc, item, stall, metrics: (True, False),
        make_strike_key=lambda svc, id: f"{svc}:{id}",
        normalize_strike_entry=lambda e: {'count': 0},
        save_strikes=lambda d: None,
        attempt_reannounce=lambda s, it, entry: False,
        remove_and_blacklist=fake_remove,
        blacklist_and_search_new_release=lambda s, svc, it: None,
        explain_decisions=False,
        log_event=lambda *a, **k: None,
        dry_run=False,
        debug_logging=False,
        state=None,
    )

    async def fake_throttled(session, service_name, url, api_key, **kw):
        params = kw.get('params') or {}
        # First call: only pageSize present
        if 'page' not in params:
            return {'totalRecords': 1}
        # Paged call: return one record
        return {'records': [{'id': 5, 'title': 'X'}]}

    deps.throttled_request = fake_throttled

    state = runner.RunnerState(
        api_timeout=1,
        strike_dict={},
        strike_lock=asyncio.Lock(),
        reannounce_requests={},
        removal_reasons={},
    )
    deps.state = state

    metrics = runner.Metrics()
    await runner.manage_service(object(), {'api_url': 'http://svc', 'api_key': 'k', 'stall_limit': 1}, 'Sonarr', metrics, deps)
    assert metrics.removed == 1
    assert removed.get('called') == ('Sonarr', 5, None)

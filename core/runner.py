from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional


@dataclass
class RunnerState:
    api_timeout: int
    strike_dict: Dict[str, Any]
    strike_lock: Any
    reannounce_requests: Dict[str, bool]
    removal_reasons: Dict[str, str]


@dataclass
class ServiceDeps:
    # config helpers
    is_service_configured: Callable[[Dict[str, Any]], bool]
    throttled_request: Callable[..., Awaitable[Optional[Dict[str, Any]]]]
    rules_is_torrent: Callable[[Dict[str, Any]], bool]
    get_effective_setting: Callable[[str, Dict[str, Any], str, Any], Any]

    # client enrichment
    get_client_speed: Callable[[Any, Dict[str, Any]], Awaitable[Optional[int]]]
    enrich_with_client_state: Callable[[Any, str, Dict[str, Any]], Awaitable[None]]

    # strike/rules
    process_queue_item: Callable[[str, Dict[str, Any], int, Dict[str, int]], tuple]
    make_strike_key: Callable[[str, Any], str]
    normalize_strike_entry: Callable[[Dict[str, Any]], Dict[str, Any]]
    save_strikes: Callable[[Dict[str, Any]], None]

    # actions
    attempt_reannounce: Callable[[Any, Dict[str, Any], Dict[str, Any]], Awaitable[bool]]
    remove_and_blacklist: Callable[[Any, str, Dict[str, Any], Optional[str]], Awaitable[None]]
    blacklist_and_search_new_release: Callable[[Any, str, Dict[str, Any]], Awaitable[None]]

    # logging/flags
    explain_decisions: bool
    log_event: Callable[[str], None] | Callable[..., None]
    dry_run: bool
    debug_logging: bool

    # shared state
    state: RunnerState


async def manage_service(
    session: Any,
    service_config: Dict[str, Any],
    service_name: str,
    metrics: Dict[str, int],
    deps: ServiceDeps,
) -> None:
    if not deps.is_service_configured(service_config):
        if deps.debug_logging:
            import logging
            logging.info(f'Service {service_name}: configuration incomplete; skipping')
        return
    if deps.debug_logging:
        import logging
        logging.info(f'Service {service_name}: starting queue check')
    queue_url = f"{service_config['api_url']}/queue"
    initial_queue_data = await deps.throttled_request(
        session, service_name, queue_url, service_config['api_key'], params={'pageSize': 1}
    )

    if initial_queue_data is None:
        if deps.debug_logging:
            import logging
            logging.error(f'Service {service_name}: initial queue request failed; aborting run')
        return

    if 'totalRecords' in initial_queue_data:
        total_records = initial_queue_data['totalRecords']
        if deps.debug_logging:
            import logging
            logging.info(f'Service {service_name}: queue size {total_records}')
        page_size = min(total_records, 100)
        pages = (total_records + page_size - 1) // page_size
        if deps.debug_logging:
            import logging
            logging.info(f'Service {service_name}: fetching {pages} page(s) (pageSize={page_size})')
        for page in range(pages):
            if deps.debug_logging:
                import logging
                logging.info(f'Service {service_name}: fetching page {page + 1}/{pages}')
            queue_data = await deps.throttled_request(
                session,
                service_name,
                queue_url,
                service_config['api_key'],
                params={'page': page + 1, 'pageSize': page_size},
            )
            if queue_data and 'records' in queue_data:
                if deps.debug_logging:
                    import logging
                    logging.info(
                        f'Service {service_name}: processing {len(queue_data["records"])} items from page {page + 1}/{pages}'
                    )
                for item in queue_data['records']:
                    try:
                        # Optional client speed enrichment for min_speed rule
                        try:
                            min_speed = float(
                                deps.get_effective_setting(
                                    service_name, item, 'min_speed_bytes_per_sec', 0.0
                                )
                            )
                        except Exception:
                            min_speed = 0.0
                        if min_speed and deps.rules_is_torrent(item):
                            spd = await deps.get_client_speed(session, item)
                            if spd is not None:
                                item['clientDlSpeed'] = spd
                        # Client state/peers/trackers enrichment
                        await deps.enrich_with_client_state(session, service_name, item)
                        should_remove, trigger_search = deps.process_queue_item(
                            service_name, item, service_config['stall_limit'], metrics
                        )
                        # Reannounce attempts if scheduled
                        key2 = deps.make_strike_key(service_name, item['id'])
                        scheduled = deps.state.reannounce_requests.pop(key2, False)
                        # Some callers store reannounce flag in strike_dict; check and pop if present
                        if not scheduled:
                            entry_tmp = deps.normalize_strike_entry(deps.state.strike_dict.get(key2, {}))
                            if entry_tmp.get('last_reason') == 'reannounce_scheduled':
                                scheduled = True
                        if scheduled:
                            entry2 = deps.normalize_strike_entry(deps.state.strike_dict.get(key2, {}))
                            try:
                                ok = await deps.attempt_reannounce(session, item, entry2)
                                deps.state.strike_dict[key2] = entry2
                                if deps.explain_decisions:
                                    deps.log_event(
                                        f'reannounce service={service_name} id={item.get("id")} title={item.get("title")} ok={ok}'
                                    )
                                continue
                            except Exception as e:
                                import logging
                                logging.error(f'Service {service_name}: reannounce error id={item.get("id")}: {e}')
                        if should_remove:
                            reason = deps.state.removal_reasons.pop(key2, None)
                            if deps.dry_run:
                                await deps.remove_and_blacklist(session, service_name, item, reason)
                            else:
                                if trigger_search:
                                    await deps.blacklist_and_search_new_release(session, service_name, item)
                                else:
                                    await deps.remove_and_blacklist(session, service_name, item, reason)
                            metrics['removed'] = metrics.get('removed', 0) + 1
                    except Exception as e:
                        import logging
                        logging.error(f'Service {service_name}: item processing error: {e}')
                # Save strikes after each page
                async with deps.state.strike_lock:
                    deps.save_strikes(deps.state.strike_dict)
            else:
                if deps.debug_logging:
                    import logging
                    logging.warning(f'Service {service_name}: page {page + 1}/{pages} response missing records')
    else:
        if deps.debug_logging:
            import logging
            logging.warning(f'Service {service_name}: initial queue response missing totalRecords')
class Metrics:
    def __init__(self) -> None:
        self.processed = 0
        self.removed = 0

    # dict-like methods for backward compatibility
    def get(self, key: str, default: int = 0) -> int:
        if key == 'processed':
            return self.processed
        if key == 'removed':
            return self.removed
        return default

    def __getitem__(self, key: str) -> int:
        return self.get(key, 0)

    def __setitem__(self, key: str, value: int) -> None:
        if key == 'processed':
            self.processed = value
        elif key == 'removed':
            self.removed = value


def summarize(state: RunnerState, metrics: Metrics) -> Dict[str, Any]:
    try:
        strikes_active = sum(
            1
            for k, v in state.strike_dict.items()
            if isinstance(v, dict) and int(v.get('count') or 0) > 0 and ':_indexer:' not in k
        )
    except Exception:
        strikes_active = 0
    try:
        next_run_ts = __import__('time').time() + state.api_timeout
        next_run_str = __import__('time').strftime('%Y-%m-%d %H:%M:%S', __import__('time').localtime(next_run_ts))
    except Exception:
        next_run_str = 'unknown'
    return {
        'processed': metrics.processed,
        'removed': metrics.removed,
        'items_with_strikes': strikes_active,
        'next_run': next_run_str,
    }


async def run_forever(
    session: Any,
    services: Dict[str, Any],
    state: RunnerState,
    manage_cb: Callable[[Any, Dict[str, Any], str, Any], Awaitable[None]],
    flush_cb: Callable[[Any], Awaitable[None]],
    log_fn: Callable[[str], None],
) -> None:
    while True:
        metrics = Metrics()
        tasks = [manage_cb(session, cfg, name, metrics) for name, cfg in services.items()]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for svc, res in zip(services.keys(), results):
            if isinstance(res, Exception):
                log_fn(f"Unhandled error in {svc} task: {res}")

        summary = summarize(state, metrics)
        extras_str = f" items_with_strikes={summary['items_with_strikes']}"
        log_fn(
            f"Finished run: processed={summary['processed']} removed={summary['removed']}{extras_str}. "
            f"Next run at {summary['next_run']} (in {state.api_timeout}s)."
        )

        await flush_cb(session)
        await asyncio.sleep(state.api_timeout)

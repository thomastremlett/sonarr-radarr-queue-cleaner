from __future__ import annotations

import asyncio
import random
from typing import Any, Dict, Optional

import aiohttp


_service_last_request_at: Dict[str, float] = {}
_service_semaphore: Dict[str, asyncio.Semaphore] = {}


class RequestManager:
    def __init__(self) -> None:
        self._service_last_request_at: Dict[str, float] = {}
        self._service_semaphore: Dict[str, asyncio.Semaphore] = {}

    async def make_api_request(self, *args, **kwargs):
        return await make_api_request(*args, **kwargs)

    async def throttled_request(
        self,
        session: aiohttp.ClientSession,
        service_name: str,
        url: str,
        api_key: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        method: str = 'get',
        min_interval_ms: float = 0.0,
        max_concurrent: int = 0,
        request_timeout: int = 10,
        retry_attempts: int = 2,
        retry_backoff: float = 1.0,
        debug_logging: bool = False,
    ):
        # Rate limit by elapsed time between calls
        if min_interval_ms and min_interval_ms > 0:
            last = self._service_last_request_at.get(service_name, 0.0)
            now = asyncio.get_event_loop().time()
            wait = (last + (min_interval_ms / 1000.0)) - now
            if wait > 0:
                await asyncio.sleep(wait)
            self._service_last_request_at[service_name] = asyncio.get_event_loop().time()

        # Limit concurrency per service
        if max_concurrent and max_concurrent > 0:
            sem = self._service_semaphore.get(service_name)
            if sem is None:
                sem = asyncio.Semaphore(max_concurrent)
                self._service_semaphore[service_name] = sem
            async with sem:
                return await make_api_request(
                    session,
                    url,
                    api_key,
                    params=params,
                    json_data=json_data,
                    method=method,
                    request_timeout=request_timeout,
                    retry_attempts=retry_attempts,
                    retry_backoff=retry_backoff,
                    debug_logging=debug_logging,
                )
        else:
            return await make_api_request(
                session,
                url,
                api_key,
                params=params,
                json_data=json_data,
                method=method,
                request_timeout=request_timeout,
                retry_attempts=retry_attempts,
                retry_backoff=retry_backoff,
                debug_logging=debug_logging,
            )


def is_service_configured(service_config: Dict[str, Any]) -> bool:
    return bool(service_config.get('api_url')) and bool(service_config.get('api_key'))


async def make_api_request(
    session: aiohttp.ClientSession,
    url: str,
    api_key: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    method: str = 'get',
    request_timeout: int = 10,
    retry_attempts: int = 2,
    retry_backoff: float = 1.0,
    debug_logging: bool = False,
):
    import logging

    headers = {'X-Api-Key': api_key}
    attempts = 0
    last_error: Optional[Exception] = None
    while attempts <= retry_attempts:
        try:
            timeout = aiohttp.ClientTimeout(total=request_timeout)
            async with session.request(method, url, headers=headers, params=params, json=json_data, timeout=timeout) as response:
                response.raise_for_status()
                content_type = response.headers.get('Content-Type', '')
                # Prefer explicit status handling to avoid parsing empty JSON bodies
                if response.status in (200, 204):
                    if response.status != 204 and 'application/json' in content_type:
                        try:
                            return await response.json()
                        except Exception:
                            # Fall back to status on empty/malformed body
                            pass
                    if debug_logging:
                        logging.info(f'HTTP {method.upper()} {url} -> {response.status} (no content)')
                    return {'status': response.status}
                # Non-2xx JSON
                if 'application/json' in content_type:
                    try:
                        return await response.json()
                    except Exception:
                        pass
                if debug_logging:
                    logging.info(f'HTTP {method.upper()} {url} -> {response.status} ({content_type})')
                return {'status': response.status, 'content_type': content_type}
        except aiohttp.ClientResponseError as e:
            if e.status and (500 <= e.status < 600 or e.status == 429) and attempts < retry_attempts:
                attempts += 1
                sleep_for = retry_backoff * (2 ** (attempts - 1)) * (1 + random.uniform(0, 0.25))
                if debug_logging:
                    logging.warning(f'HTTP {method.upper()} {url} {e.status}; retrying in {sleep_for:.2f}s (attempt {attempts}/{retry_attempts})')
                await asyncio.sleep(sleep_for)
                last_error = e
                continue
            else:
                if debug_logging:
                    logging.error(f'HTTP {method.upper()} {url} error {getattr(e, "status", None)}: {getattr(e, "message", str(e))}')
                return None
        except (aiohttp.ClientConnectorError, aiohttp.ClientOSError, aiohttp.ServerTimeoutError, asyncio.TimeoutError) as e:
            if attempts < retry_attempts:
                attempts += 1
                sleep_for = retry_backoff * (2 ** (attempts - 1)) * (1 + random.uniform(0, 0.25))
                if debug_logging:
                    logging.warning(f'HTTP {method.upper()} {url} network/timeout; retrying in {sleep_for:.2f}s (attempt {attempts}/{retry_attempts})')
                await asyncio.sleep(sleep_for)
                last_error = e
                continue
            else:
                if debug_logging:
                    logging.error(f'HTTP {method.upper()} {url} network/timeout: {str(e)}')
                return None
        except Exception as e:
            if debug_logging:
                logging.error(f'HTTP {method.upper()} {url} unexpected error: {str(e)}')
            return None
    if debug_logging and last_error is not None:
        import logging
        logging.error(f'HTTP {method.upper()} {url} failed after {retry_attempts} retries: {last_error}')
    return None


async def throttled_request(
    session: aiohttp.ClientSession,
    service_name: str,
    url: str,
    api_key: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    json_data: Optional[Dict[str, Any]] = None,
    method: str = 'get',
    min_interval_ms: float = 0.0,
    max_concurrent: int = 0,
    request_timeout: int = 10,
    retry_attempts: int = 2,
    retry_backoff: float = 1.0,
    debug_logging: bool = False,
):
    # Rate limit by elapsed time between calls
    if min_interval_ms and min_interval_ms > 0:
        last = _service_last_request_at.get(service_name, 0.0)
        now = asyncio.get_event_loop().time()
        wait = (last + (min_interval_ms / 1000.0)) - now
        if wait > 0:
            await asyncio.sleep(wait)
        _service_last_request_at[service_name] = asyncio.get_event_loop().time()

    # Limit concurrency per service
    if max_concurrent and max_concurrent > 0:
        sem = _service_semaphore.get(service_name)
        if sem is None:
            sem = asyncio.Semaphore(max_concurrent)
            _service_semaphore[service_name] = sem
        async with sem:
            return await make_api_request(
                session,
                url,
                api_key,
                params=params,
                json_data=json_data,
                method=method,
                request_timeout=request_timeout,
                retry_attempts=retry_attempts,
                retry_backoff=retry_backoff,
                debug_logging=debug_logging,
            )
    else:
        return await make_api_request(
            session,
            url,
            api_key,
            params=params,
            json_data=json_data,
            method=method,
            request_timeout=request_timeout,
            retry_attempts=retry_attempts,
            retry_backoff=retry_backoff,
            debug_logging=debug_logging,
        )

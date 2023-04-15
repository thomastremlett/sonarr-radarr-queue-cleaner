from __future__ import annotations

import json
from typing import Any, Dict, Optional

import aiohttp


class EventBus:
    def __init__(
        self,
        config: Dict[str, Any],
        *,
        structured_logs: bool,
        dry_run: bool,
        debug_logging: bool,
        logger,
    ) -> None:
        self.config = config
        self.structured_logs = structured_logs
        self.dry_run = dry_run
        self.debug_logging = debug_logging
        self.logger = logger

    def log(self, event: str, **fields) -> None:
        payload = {"event": event, **fields}
        try:
            if self.structured_logs:
                self.logger.info(json.dumps(payload, ensure_ascii=False))
            else:
                self.logger.info(f"{event}: {fields}")
        except Exception:
            self.logger.info(str(payload))

    async def emit(
        self,
        session: aiohttp.ClientSession,
        event: str,
        *,
        service: Optional[str] = None,
        item: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
        notify: bool = False,
        **fields,
    ) -> None:
        # Compose common fields if present
        if item is not None:
            fields.setdefault('id', item.get('id'))
            fields.setdefault('title', item.get('title'))
        if service is not None:
            fields.setdefault('service', service)
        if reason is not None:
            fields.setdefault('reason', reason)

        self.log(event, **fields)

        if notify and service and item is not None:
            try:
                from integrations import notifications as notif

                await notif.handle(
                    session, service, item, reason, self.config, self.dry_run, self.debug_logging
                )
            except Exception as e:
                if self.debug_logging:
                    import logging

                    logging.warning(f"Service {service}: notify error: {e}")

    async def flush(self, session: aiohttp.ClientSession) -> None:
        try:
            from integrations import notifications as notif

            await notif.flush(session, self.config, self.dry_run, self.debug_logging)
        except Exception as e:
            if self.debug_logging:
                import logging

                logging.warning(f"Notify: flush error: {e}")


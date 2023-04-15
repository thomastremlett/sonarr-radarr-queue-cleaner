from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import aiohttp

# Public queues so callers can inspect/clear for tests
notify_queues: Dict[str, List[str]] = {}
notify_dests: Dict[str, Dict[str, Any]] = {}


def _notif_destinations(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    notifications = config.get('notifications') if isinstance(config.get('notifications'), dict) else {}
    dests = notifications.get('destinations') if isinstance(notifications, dict) else None
    if isinstance(dests, list) and dests:
        return [d for d in dests if isinstance(d, dict) and d.get('url')]
    # No legacy fallback in facade
    return []


def _notif_match_reasons(dest: Dict[str, Any], reason: Optional[str]) -> bool:
    rs = dest.get('reasons')
    if not isinstance(rs, list) or not rs:
        return True
    if '*' in rs:
        return True
    return reason in rs


def _notif_template(dest: Dict[str, Any]) -> str:
    t = dest.get('template')
    if isinstance(t, str) and t:
        return t
    return 'Removed {service} queue item id={id} title={title} reason={reason}'


def _notif_format_line(dest: Dict[str, Any], service: str, item: Dict[str, Any], reason: Optional[str]) -> str:
    template = _notif_template(dest)
    # For raw_json templates, avoid str.format brace parsing; perform minimal substitution
    if bool(dest.get('raw_json', False)) and isinstance(template, str):
        try:
            line = template
            line = line.replace('{service}', str(service))
            line = line.replace('{id}', str(item.get('id')))
            line = line.replace('{title}', str(item.get('title')))
            line = line.replace('{reason}', str(reason or 'unknown'))
            return line
        except Exception:
            pass
    try:
        return template.format(service=service, id=item.get('id'), title=item.get('title'), reason=reason or 'unknown')
    except Exception:
        return f"Removed {service} queue item id={item.get('id')} title={item.get('title')} reason={reason or 'unknown'}"


async def _notif_send_immediate(
    session: aiohttp.ClientSession,
    dest: Dict[str, Any],
    line: str,
    dry_run: bool,
    debug_logging: bool,
) -> None:
    url = dest.get('url')
    typ = str(dest.get('type') or 'generic').lower()
    timeout = aiohttp.ClientTimeout(total=5)
    headers = dest.get('headers') if isinstance(dest.get('headers'), dict) else None
    try:
        if typ == 'discord':
            payload_line = f"[DRY RUN] {line}" if dry_run else line
            payload = {'content': payload_line}
            resp = await session.post(url, json=payload, timeout=timeout)
            _ = getattr(resp, 'status', None)
        elif typ == 'slack':
            payload_line = f"[DRY RUN] {line}" if dry_run else line
            payload = {'text': payload_line}
            resp = await session.post(url, json=payload, timeout=timeout)
            _ = getattr(resp, 'status', None)
        else:
            raw_json = bool(dest.get('raw_json', False))
            if raw_json:
                try:
                    doc = json.loads(line)
                except Exception:
                    doc = {'message': line}
                if dry_run and isinstance(doc, dict) and 'dryRun' not in doc:
                    doc['dryRun'] = True
                resp = await session.post(url, json=doc, headers=headers, timeout=timeout)
                _ = getattr(resp, 'status', None)
            else:
                payload_line = f"[DRY RUN] {line}" if dry_run else line
                payload = {'message': payload_line}
                resp = await session.post(url, json=payload, headers=headers, timeout=timeout)
                _ = getattr(resp, 'status', None)
    except Exception as e:
        if debug_logging:
            import logging
            logging.warning(f"Notify({typ}): send failed: {e}")


def _notif_enqueue(dest: Dict[str, Any], line: str) -> None:
    name = dest.get('name') or dest.get('url')
    key = str(name)
    notify_dests[key] = dest
    notify_queues.setdefault(key, []).append(line)


async def handle_notifications(
    session: aiohttp.ClientSession,
    service: str,
    item: Dict[str, Any],
    reason: Optional[str],
    config: Dict[str, Any],
    dry_run: bool,
    debug_logging: bool,
) -> None:
    dests = _notif_destinations(config)
    if not dests:
        return
    for d in dests:
        if not _notif_match_reasons(d, reason):
            continue
        line = _notif_format_line(d, service, item, reason)
        if bool(d.get('batch', False)):
            _notif_enqueue(d, line)
        else:
            await _notif_send_immediate(session, d, line, dry_run, debug_logging)


async def flush_notifications(
    session: aiohttp.ClientSession,
    config: Dict[str, Any],
    dry_run: bool,
    debug_logging: bool,
) -> None:
    for key, lines in list(notify_queues.items()):
        dest = notify_dests.get(key) or {}
        if not lines:
            continue
        typ = str(dest.get('type') or 'generic').lower()
        url = dest.get('url')
        timeout = aiohttp.ClientTimeout(total=5)
        try:
            if typ == 'discord':
                content = '\n'.join(lines)
                if dry_run:
                    content = '[DRY RUN]\n' + content
                if len(content) > 1900:
                    content = content[:1900] + '\n...'
                resp = await session.post(url, json={'content': content}, timeout=timeout)
                _ = getattr(resp, 'status', None)
            elif typ == 'slack':
                content = '\n'.join(lines)
                if dry_run:
                    content = '[DRY RUN]\n' + content
                if len(content) > 38000:
                    content = content[:38000] + '\n...'
                resp = await session.post(url, json={'text': content}, timeout=timeout)
                _ = getattr(resp, 'status', None)
            else:
                headers = dest.get('headers') if isinstance(dest.get('headers'), dict) else None
                raw_json = bool(dest.get('raw_json', False))
                content = '\n'.join(lines)
                if raw_json:
                    try:
                        arr = [json.loads(l) for l in lines]
                    except Exception:
                        arr = [{'message': l} for l in lines]
                    body: Dict[str, Any] = {'events': arr}
                    if dry_run:
                        body['dryRun'] = True
                    resp = await session.post(url, json=body, headers=headers, timeout=timeout)
                    _ = getattr(resp, 'status', None)
                else:
                    if dry_run:
                        content = '[DRY RUN]\n' + content
                    resp = await session.post(url, json={'message': content}, headers=headers, timeout=timeout)
                    _ = getattr(resp, 'status', None)
        except Exception as e:
            if debug_logging:
                import logging
                logging.warning(f"Notify({typ}): batch flush failed: {e}")
        finally:
            lines.clear()


# Facade-friendly names
async def handle(
    session: aiohttp.ClientSession,
    service: str,
    item: Dict[str, Any],
    reason: Optional[str],
    config: Dict[str, Any],
    dry_run: bool,
    debug_logging: bool,
) -> None:
    await handle_notifications(session, service, item, reason, config, dry_run, debug_logging)


async def flush(
    session: aiohttp.ClientSession,
    config: Dict[str, Any],
    dry_run: bool,
    debug_logging: bool,
) -> None:
    await flush_notifications(session, config, dry_run, debug_logging)


async def send_immediate(
    session: aiohttp.ClientSession,
    dest: Dict[str, Any],
    line: str,
    dry_run: bool,
    debug_logging: bool,
) -> None:
    await _notif_send_immediate(session, dest, line, dry_run, debug_logging)

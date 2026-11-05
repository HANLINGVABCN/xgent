"""A hidden system group for archived chats, preserving their restoration metadata."""
from __future__ import annotations

import json
import time

from .child_conversations import descendant_ids
from .queue_store import one, rows, bump

ARCHIVE_GROUP_ID = '__archived__'
ARCHIVE_GROUP_NAME = '归档'


def archive_origin(session):
    value = session.get('archive_origin')
    try:
        result = json.loads(value) if isinstance(value, str) else value
    except (ValueError, TypeError):
        result = None
    return result if isinstance(result, dict) else {}


async def ensure_archive_group(conn):
    now = time.time()
    await conn.execute('INSERT INTO conversation_groups(id,name,sort_order,created_at,updated_at) '
                       'VALUES(?,?,2147483647,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name',
                       (ARCHIVE_GROUP_ID, ARCHIVE_GROUP_NAME, now, now))


async def archive_tree(conn, cid):
    await ensure_archive_group(conn)
    identifiers = [cid, *await descendant_ids(conn, cid)]
    archived = []
    for identifier in identifiers:
        session = await one(conn, 'SELECT * FROM chat_sessions WHERE id=? AND deleting=0', (identifier,))
        if session is None:
            continue
        origin = archive_origin(session)
        if not session['archived'] or not origin:
            group_id = session.get('group_id') or 'ungrouped'
            if group_id == ARCHIVE_GROUP_ID:
                group_id = 'ungrouped'
            group = await one(conn, 'SELECT name FROM conversation_groups WHERE id=?', (group_id,))
            origin = {'group_id': group_id, 'group_name': group['name'] if group else '默认分组',
                      'pinned': bool(session.get('pinned')), 'archived_at': time.time()}
        await conn.execute('UPDATE chat_sessions SET archived=1,group_id=?,pinned=0,archive_origin=?,title_auto_pending=0 WHERE id=?',
                           (ARCHIVE_GROUP_ID, json.dumps(origin, ensure_ascii=False), identifier))
        archived.append(identifier)
    return archived


async def restore_tree(conn, cid):
    identifiers = [cid, *await descendant_ids(conn, cid)]
    restored = []
    for identifier in identifiers:
        session = await one(conn, 'SELECT * FROM chat_sessions WHERE id=? AND deleting=0', (identifier,))
        if session is None or not session['archived']:
            continue
        origin = archive_origin(session)
        group_id = origin.get('group_id') or 'ungrouped'
        group = await one(conn, 'SELECT id FROM conversation_groups WHERE id=? AND id<>?', (group_id, ARCHIVE_GROUP_ID))
        if group is None:
            group_id = 'ungrouped'
        pinned = bool(origin.get('pinned')) and group is not None
        await conn.execute('UPDATE chat_sessions SET archived=0,group_id=?,pinned=?,archive_origin=NULL WHERE id=?',
                           (group_id, pinned, identifier))
        restored.append(identifier)
    return restored


async def migrate_archives(conn):
    columns = {row['name'] for row in await rows(conn, 'PRAGMA table_info(chat_sessions)')}
    if 'archive_origin' not in columns:
        await conn.execute('ALTER TABLE chat_sessions ADD COLUMN archive_origin TEXT')
    await ensure_archive_group(conn)
    for session in await rows(conn, 'SELECT id FROM chat_sessions WHERE archived=1 AND deleting=0'):
        await archive_tree(conn, session['id'])
    # Old archive pauses were a presentation rule. Explicit Stop/error/form pauses remain.
    controls = await conn.execute("UPDATE message_queue_controls SET state='ready',reason='',owner=NULL "
                                  "WHERE reason='archived' AND conversation_id IN (SELECT id FROM chat_sessions WHERE deleting=0)")
    pending = await conn.execute("UPDATE message_queue SET status='pending',reason='waiting',revision=revision+1 "
                                 "WHERE status='paused' AND reason='archived' AND conversation_id IN "
                                 "(SELECT id FROM chat_sessions WHERE deleting=0 AND generation=message_queue.generation)")
    if controls.rowcount or pending.rowcount:
        await bump(conn)

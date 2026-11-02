"""Fixed native history identities and request-only provider ID conversion."""
from __future__ import annotations

import hashlib
import json
import re


def call_key(link):
    if not isinstance(link, dict) or not all(isinstance(link.get(field), str) and link[field]
            for field in ('run_id', 'response_id', 'id')):
        return None
    return link['run_id'], link['response_id'], link['id']


def message_groups(messages):
    result = set()
    for message in messages:
        links = [message.get('native_result')] + list(message.get('native_calls') or [])
        for link in links:
            key = call_key(link)
            if key is not None:
                result.add(key[:2])
    return result


def wire_call_ids(history, eligible, provider):
    """Keep safe unique IDs, map foreign/duplicate IDs without changing records."""
    result, used = {}, set()
    for message in history:
        for call in message.get('native_calls') or []:
            key = call_key(call)
            if key not in eligible or key in result:
                continue
            value = call['id']
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', value) or value in used:
                salt = 0
                while True:
                    raw = json.dumps([provider, *key, salt], ensure_ascii=False).encode('utf-8')
                    value = 'call_' + hashlib.sha256(raw).hexdigest()[:48]
                    if value not in used:
                        break
                    salt += 1
            result[key] = value
            used.add(value)
    return result

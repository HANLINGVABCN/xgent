"""Use explicit instance proxy configuration over inherited terminal proxies."""
from __future__ import annotations

import os
from collections.abc import Mapping, MutableMapping


def apply_instance_network_environment(values: Mapping, environment: MutableMapping | None = None) -> None:
    """A configured empty proxy means direct access; absent keys keep inheritance.

    .env remains authoritative only for network keys. Caller-supplied secrets,
    runtime identity and test overrides retain the established precedence.
    """
    environment = os.environ if environment is None else environment
    for upper, lower in (('HTTP_PROXY', 'http_proxy'), ('HTTPS_PROXY', 'https_proxy'),
                         ('ALL_PROXY', 'all_proxy'), ('NO_PROXY', 'no_proxy')):
        if upper not in values and lower not in values:
            continue
        value = values[upper] if upper in values else values[lower]
        value = str(value or '').strip()
        for key in (upper, lower):
            if value:
                environment[key] = value
            else:
                environment.pop(key, None)
    for key in ('XGENT_IP_MODE', 'XGENT_SOCKS5_PROXY', 'XGENT_IPV4_ONLY'):
        if key in values:
            value = str(values[key] or '').strip()
            if value:
                environment[key] = value
            else:
                environment.pop(key, None)

"""One shared stream switch with immediate Web/CLI and paced Bot previews."""
from dataclasses import dataclass

WEB_MODES = ('foreground', 'nonstream')
BOT_MODES = ('background', 'nonstream')
RESPONSE_KEYS = frozenset({'stream_mode', 'stream_style', 'web_response_mode', 'response_mode', 'telegram_response_mode'})


def normalize_web_mode(value):
    if value in ('background', 'stream'):
        return 'foreground'  # Older Web clients and the shared streaming alias.
    if value not in WEB_MODES:
        raise ValueError('回复方式只能是流式或非流式')
    return value


def stream_enabled(config):
    enabled = config.get('stream_mode', config.get('web_response_mode') != 'nonstream')
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {'false', '0', 'off', 'no', 'closed', 'disabled'}
    if isinstance(enabled, (bool, int, float)) and not enabled:
        return False
    return True


def shared_values(config):
    enabled = stream_enabled(config)
    return {'stream_mode': enabled, 'stream_style': 'background',
            'web_response_mode': 'foreground' if enabled else 'nonstream'}


def public_values(config):
    values = shared_values(config)
    return {**values, 'response_mode': values['web_response_mode'],
            'telegram_response_mode': 'background' if values['stream_mode'] else 'nonstream'}


def bot_mode(config):
    return 'background' if stream_enabled(config) else 'nonstream'


def web_mode(config):
    return 'foreground' if stream_enabled(config) else 'nonstream'


@dataclass(frozen=True)
class ResponsePolicy:
    generation_mode: str
    telegram_mode: str


def response_policy(config, origin):
    return ResponsePolicy(web_mode(config), bot_mode(config))

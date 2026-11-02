"""One model generation, independently selected Web and Telegram presentation."""
from dataclasses import dataclass

WEB_MODES = ('foreground', 'nonstream')
BOT_MODES = ('foreground', 'background', 'nonstream')


def normalize_web_mode(value):
    if value not in WEB_MODES:
        raise ValueError('网页回复方式只能是前台流式或非流式')
    return value


def bot_mode(config):
    enabled = config.get('stream_mode', True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {'false', '0', 'off', 'no', 'closed', 'disabled'}
    if isinstance(enabled, (bool, int, float)) and not enabled:
        return 'nonstream'
    return 'background' if config.get('stream_style') == 'background' else 'foreground'


def web_mode(config):
    saved = config.get('web_response_mode')
    if saved is None:
        return 'nonstream' if bot_mode(config) == 'nonstream' else 'foreground'
    return normalize_web_mode(saved)


@dataclass(frozen=True)
class ResponsePolicy:
    generation_mode: str
    telegram_mode: str


def response_policy(config, origin):
    telegram = bot_mode(config)
    selected = web_mode(config) if origin == 'web' else telegram
    return ResponsePolicy('nonstream' if selected == 'nonstream' else 'foreground', telegram)

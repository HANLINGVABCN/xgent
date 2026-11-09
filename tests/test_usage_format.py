import html
from datetime import datetime
from zoneinfo import ZoneInfo

from xgent_app.presentation import footer_html, reply_usage_facts, usage_details, usage_line
from xgent_app.telegram_chat import reply_details


STAMP = datetime(2026, 11, 9, 3, 20, tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
FACTS = {'usage': {'input_tokens': 1200, 'cached_tokens': 800, 'output_tokens': 300},
         'elapsed_seconds': 12, 'provider': '服务商', 'model': '模型', 'generated_at': STAMP}
EXPECTED = '2026-11-09 03:20 ↑1,200（800） ↓300 12s 25tok/s 服务商/模型'


def test_three_clients_share_metrics_and_telegram_time_is_last():
    assert usage_line(FACTS) == EXPECTED
    assert usage_details(FACTS).splitlines()[0] == EXPECTED
    assert '已包含在输入量中' in usage_details(FACTS)
    row = {'timestamp': STAMP, 'metadata': {'ai_generation': {
        'provider': '服务商', 'model': '模型', 'generated_at': STAMP}}}
    assert html.unescape(reply_details(row, FACTS)[0]) == (
        '<blockquote expandable>↑1,200（800） ↓300 12s 25tok/s 服务商/模型 2026-11-09 03:20</blockquote>')
    rendered = footer_html(FACTS)
    assert 'data-usage-version="2"' in rendered
    assert 'usage-speed">25tok/s' in rendered


def test_unknown_usage_is_not_zero_and_rate_is_never_infinite():
    line = usage_line({'usage': {'input_tokens': 1200, 'output_tokens': 0}, 'elapsed_seconds': 0})
    assert '↑1,200（未提供） ↓0 0s 速率未提供' in line
    assert '时间未记录' in line and '服务商未记录/模型未记录' in line
    assert '（0）' in usage_line({**FACTS, 'usage': {**FACTS['usage'], 'cached_tokens': 0}})
    assert '耗时未记录 速率未提供' in usage_line({**FACTS, 'elapsed_seconds': float('nan')})
    assert '0.012s 25,000tok/s' in usage_line({**FACTS, 'elapsed_seconds': .012})
    assert '<0.001s' in usage_line({**FACTS, 'elapsed_seconds': .0001})


def test_saved_reply_uses_actual_provider_model_and_timestamp():
    row = {'timestamp': STAMP, 'metadata': {'ai_generation': {'provider': '实际', 'model': '<模型>'}}}
    values = reply_usage_facts(FACTS, row=row)
    assert values['provider'] == '实际' and values['model'] == '<模型>'
    assert '&lt;模型&gt;' in footer_html(values)
    assert FACTS['provider'] == '服务商'


def test_cli_renders_the_same_metrics_without_html_markup():
    from xgent_app.cli_palette import Palette
    from xgent_app.cli_render import MessageRenderer

    rows = MessageRenderer(Palette(False), width=120).render_text(footer_html(FACTS), 'HTML')
    assert '\n'.join(rows).strip() == EXPECTED

"""Human trigger receipts, separate from the model's continuation context."""
from __future__ import annotations

import html

from .presentation import operation_html
from .web_display import build_operation_display


def build_trigger_result_display(notice: str, run: dict) -> dict:
    """Reuse command-output folds without parsing or executing result text."""
    output = str(run.get('output') or '(无输出)')
    if run.get('error'):
        output = f"错误：{run['error']}\n\n命令输出：\n{output}"
    operation = {
        'kind': 'run', 'output': output, 'output_path': run.get('output_path'),
        'return_code': run.get('exit_code'),
        'success': not (run.get('status') in {'failed', 'condition_unmatched', 'interrupted'}
                        or run.get('error') or run.get('exit_code') not in (None, 0)),
    }
    escaped_notice = html.escape(notice, quote=False)
    web_display = build_operation_display(operation, 'folded')
    # Scheduled receipts have no chat command owner or command-result record.
    # Keep their notice and output together rather than projecting an empty card.
    web_display.pop('command_result',None)
    web_display['segments'].insert(0, {
        'kind': 'html', 'text': escaped_notice.replace('\n', '<br>'),
    })
    return {
        'display': {'content': escaped_notice + '\n\n' + operation_html(operation), 'parse_mode': 'HTML'},
        'web_display': web_display,
    }

"""
Telegram Notification Templates

Jinja2 기반 알림 메시지 템플릿.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

try:
    from jinja2 import Environment, BaseLoader
    HAS_JINJA = True
except ImportError:
    HAS_JINJA = False


# --- Template Definitions ---

DAILY_BRIEFING_TEMPLATE = """\
📅 *{{ date }}* 일일 브리핑

{% if alarms %}
📬 *알림 요약*
{% for item in alarms[:5] %}
• {{ item.summary }}
{% endfor %}
{% if alarms|length > 5 %}
...외 {{ alarms|length - 5 }}건
{% endif %}
{% else %}
📭 오늘은 특별한 알림이 없어요!
{% endif %}

{% if tip %}
💡 *오늘의 팁*
{{ tip }}
{% endif %}
"""

ASSET_SUMMARY_TEMPLATE = """\
💰 *자산 현황*

📊 *총 자산*: {{ "{:,.0f}".format(total_value) }}원
📈 *수익률*: {{ "{:+.2f}".format(return_rate * 100) }}%

{% if top_assets %}
*주요 보유*
{% for asset in top_assets[:3] %}
• {{ asset.name }}: {{ "{:,.0f}".format(asset.value) }}원
{% endfor %}
{% endif %}
"""

EXPENSE_ALERT_TEMPLATE = """\
💸 *지출 알림*

*금액*: {{ "{:,.0f}".format(amount|abs) }}원
*가맹점*: {{ merchant or "미상" }}
*카테고리*: {{ category }}

{% if is_unusual %}
⚠️ 평소보다 높은 지출이에요!
{% endif %}
"""


# --- Template Renderer ---

def render_template(template_name: str, **context: Any) -> str:
    """템플릿을 렌더링하여 문자열 반환."""
    if not HAS_JINJA:
        # Fallback: simple string formatting
        return _fallback_render(template_name, context)
    
    templates = {
        "daily_briefing": DAILY_BRIEFING_TEMPLATE,
        "asset_summary": ASSET_SUMMARY_TEMPLATE,
        "expense_alert": EXPENSE_ALERT_TEMPLATE,
    }
    
    template_str = templates.get(template_name)
    if not template_str:
        return f"Template '{template_name}' not found"
    
    env = Environment(loader=BaseLoader())
    template = env.from_string(template_str)
    return template.render(**context)


def _fallback_render(template_name: str, context: dict) -> str:
    """Jinja2 없을 때 간단한 fallback."""
    if template_name == "daily_briefing":
        date = context.get("date", datetime.now().strftime("%Y-%m-%d"))
        alarms = context.get("alarms", [])
        lines = [f"📅 {date} 일일 브리핑", ""]
        if alarms:
            lines.append("📬 알림 요약")
            for item in alarms[:5]:
                lines.append(f"• {item.get('summary', '')}")
        else:
            lines.append("📭 오늘은 특별한 알림이 없어요!")
        return "\n".join(lines)
    
    if template_name == "asset_summary":
        total = context.get("total_value", 0)
        rate = context.get("return_rate", 0)
        return f"💰 자산 현황\n총 자산: {total:,.0f}원\n수익률: {rate*100:+.2f}%"
    
    return str(context)

from __future__ import annotations

import json

from jinja2 import Environment, select_autoescape

from arbiterforge.domain.value_objects import EventEnvelope

_ENV = Environment(autoescape=select_autoescape(default=True, default_for_string=True))
_TEMPLATE = _ENV.from_string(
    """<!DOCTYPE html>
<html lang="ru">
<head><meta charset="utf-8"/><title>Timeline {{ case_id }}</title>
<style>
body{font-family:Georgia,serif;margin:2rem;background:#f7f5f0;color:#1a1a1a}
h1{font-size:1.6rem} .ev{border-left:3px solid #2c5f4a;padding:.5rem 1rem;margin:1rem 0;background:#fff}
.meta{color:#666;font-size:.85rem} .type{font-weight:bold;color:#2c5f4a}
table{border-collapse:collapse} td,th{border:1px solid #ccc;padding:.25rem .5rem;text-align:left}
</style></head>
<body>
<h1>Хронология арбитражного разбирательства</h1>
<p class="meta">Дело {{ case_id }} — событий: {{ events|length }}</p>
{% if deadlines %}
<h2>Сроки</h2>
<table><tr><th>Срок</th><th>Сторона</th><th>Истекает</th><th>Основание</th></tr>
{% for d in deadlines %}<tr><td>{{ d.code }}</td><td>{{ d.party }}</td><td>{{ d.due_date or "—" }}</td><td>{{ d.basis|join(", ") }}</td></tr>
{% endfor %}</table>
{% endif %}
{% for e in events %}
<div class="ev">
  <div class="type">v{{ e.version }} · {{ e.event_type }}</div>
  <div class="meta">{{ e.occurred_at }} · {{ e.event_id }}</div>
  <pre>{{ e.payload }}</pre>
</div>
{% endfor %}
<p class="meta">ArbiterForge — коммерческий арбитраж, не государственные суды.</p>
</body></html>
"""
)


def build_timeline_html(
    case_id: str, events: list[EventEnvelope], deadlines: list[dict[str, object]] | None = None
) -> str:
    return _TEMPLATE.render(
        case_id=case_id,
        deadlines=deadlines or [],
        events=[
            {
                "version": e.version,
                "event_type": e.event_type,
                "occurred_at": e.occurred_at,
                "event_id": e.event_id,
                "payload": json.dumps(e.payload, ensure_ascii=False, indent=2, sort_keys=True),
            }
            for e in events
        ],
    )

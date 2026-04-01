from __future__ import annotations

import json
from typing import List

from .sanitizer import infer_source


def _build_notification_list(items: List[dict]) -> List[str]:
    notification_list: List[str] = []
    seen = set()

    for item in items:
        source = infer_source(item)
        text = (item.get("text") or "").strip()
        if not text:
            continue

        title = (item.get("app_title") or "").strip()
        conversation = (item.get("conversation") or "").strip()
        if title.startswith("%"):
            title = ""
        if conversation.startswith("%"):
            conversation = ""

        dedupe_key = (source, text)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        payload = {
            "idx": len(notification_list) + 1,
            "app": source,
            "title": title,
            "conversation": conversation,
            "body": text,
        }
        notification_list.append(json.dumps(payload, ensure_ascii=False))

    return notification_list

import html
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from backend.integrations.telegram import send_telegram_message

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

NOTICE_LIST_URL = "https://www.dobongsiseol.or.kr/xs_board/board_list.html?num="
STATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "storage"
    / "changdong_registration"
    / "state.json"
)
_NOTICE_LINK_RE = re.compile(
    r"""<a\s+[^>]*href=["'](?P<href>\./board_content\.html\?num=(?P<notice_id>\d+)[^"']*)["'][^>]*>(?P<title>.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(frozen=True)
class RegistrationNotice:
    notice_id: int
    title: str
    url: str


def parse_registration_notices(page_html: str) -> list[RegistrationNotice]:
    notices: dict[int, RegistrationNotice] = {}

    for match in _NOTICE_LINK_RE.finditer(page_html):
        title = re.sub(r"<[^>]+>", " ", match.group("title"))
        title = re.sub(r"\s+", " ", html.unescape(title)).strip()
        if "재등록" not in title or "접수" not in title:
            continue

        notice_id = int(match.group("notice_id"))
        notices[notice_id] = RegistrationNotice(
            notice_id=notice_id,
            title=title,
            url=urljoin(NOTICE_LIST_URL, match.group("href")),
        )

    return sorted(notices.values(), key=lambda notice: notice.notice_id, reverse=True)


async def fetch_latest_registration_notice(
    client: Optional[httpx.AsyncClient] = None,
) -> RegistrationNotice:
    async def _fetch(active_client: httpx.AsyncClient) -> RegistrationNotice:
        response = await active_client.get(NOTICE_LIST_URL, timeout=15.0)
        response.raise_for_status()
        page_html = response.content.decode("cp949", errors="replace")
        notices = parse_registration_notices(page_html)
        if not notices:
            raise RuntimeError("창동문화체육센터 재등록 공지를 찾지 못했습니다.")
        return notices[0]

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(follow_redirects=True) as owned_client:
        return await _fetch(owned_client)


def _load_last_notice_id(state_path: Path) -> Optional[int]:
    if not state_path.exists():
        return None

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    notice_id = payload.get("notice_id")
    if not isinstance(notice_id, int):
        raise ValueError("창동문화체육센터 알림 상태의 notice_id가 올바르지 않습니다.")
    return notice_id


def _save_notice_state(state_path: Path, notice: RegistrationNotice) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **asdict(notice),
        "checked_at": datetime.now(KST).isoformat(),
    }
    temporary_path = state_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(state_path)


def _build_notification_message(notice: RegistrationNotice) -> str:
    safe_title = html.escape(notice.title)
    safe_url = html.escape(notice.url, quote=True)
    return (
        "<b>[창동문화체육센터 재등록 알림]</b>\n"
        f"{safe_title}\n\n"
        f'<a href="{safe_url}">공식 공지 확인하기</a>\n'
        "엄마 강좌 재등록 일정 확인해 주세요. 이번에는 놓치지 말기!"
    )


async def check_changdong_registration_notice(
    *,
    state_path: Path = STATE_PATH,
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[RegistrationNotice]:
    latest = await fetch_latest_registration_notice(client)
    last_notice_id = _load_last_notice_id(state_path)

    if last_notice_id is None:
        _save_notice_state(state_path, latest)
        logger.info(
            "Changdong registration monitor initialized: notice_id=%s title=%s",
            latest.notice_id,
            latest.title,
        )
        return None

    if latest.notice_id <= last_notice_id:
        logger.info(
            "No new Changdong registration notice: latest=%s saved=%s",
            latest.notice_id,
            last_notice_id,
        )
        return None

    sent = await send_telegram_message(
        _build_notification_message(latest),
        bot_type="main",
    )
    if not sent:
        raise RuntimeError("창동문화체육센터 재등록 알림 텔레그램 발송에 실패했습니다.")

    _save_notice_state(state_path, latest)
    logger.info(
        "New Changdong registration notice sent: notice_id=%s title=%s",
        latest.notice_id,
        latest.title,
    )
    return latest

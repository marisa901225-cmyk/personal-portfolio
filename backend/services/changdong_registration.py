import asyncio
import base64
import html
import json
import logging
import mimetypes
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from backend.integrations.telegram import send_telegram_message
from backend.services.llm_service import LLMService

logger = logging.getLogger(__name__)
KST = ZoneInfo("Asia/Seoul")

NOTICE_LIST_URL = "https://www.dobongsiseol.or.kr/xs_board/board_list.html?num="
STATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "storage"
    / "changdong_registration"
    / "state.json"
)
VISION_MODEL = os.getenv("CHANGDONG_REGISTRATION_VISION_MODEL", "gpt-5.6").strip() or "gpt-5.6"
_NOTICE_LINK_RE = re.compile(
    r"""<a\s+[^>]*href=["'](?P<href>\./board_content\.html\?num=(?P<notice_id>\d+)[^"']*)["'][^>]*>(?P<title>.*?)</a>""",
    re.IGNORECASE | re.DOTALL,
)
_NOTICE_IMAGE_RE = re.compile(
    r"""<img\s+[^>]*src=["'](?P<src>[^"']+)["'][^>]*>""",
    re.IGNORECASE,
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


def extract_notice_image_url(detail_html: str, notice_url: str) -> str:
    candidates = [
        urljoin(notice_url, match.group("src"))
        for match in _NOTICE_IMAGE_RE.finditer(detail_html)
    ]
    preferred = [
        url
        for url in candidates
        if "/rx99/rxPhotos/" in url or "/image_up/" in url
    ]
    if not preferred:
        raise RuntimeError("창동문화체육센터 재등록 공지 이미지를 찾지 못했습니다.")
    return preferred[0]


async def _fetch_cp949_page(client: httpx.AsyncClient, url: str) -> str:
    response = await client.get(url, timeout=15.0)
    response.raise_for_status()
    return response.content.decode("cp949", errors="replace")


async def fetch_latest_registration_notice(
    client: Optional[httpx.AsyncClient] = None,
) -> RegistrationNotice:
    async def _fetch(active_client: httpx.AsyncClient) -> RegistrationNotice:
        page_html = await _fetch_cp949_page(active_client, NOTICE_LIST_URL)
        notices = parse_registration_notices(page_html)
        if not notices:
            raise RuntimeError("창동문화체육센터 재등록 공지를 찾지 못했습니다.")
        return notices[0]

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(follow_redirects=True) as owned_client:
        return await _fetch(owned_client)


async def fetch_notice_image_url(
    notice: RegistrationNotice,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    async def _fetch(active_client: httpx.AsyncClient) -> str:
        detail_html = await _fetch_cp949_page(active_client, notice.url)
        return extract_notice_image_url(detail_html, notice.url)

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(follow_redirects=True) as owned_client:
        return await _fetch(owned_client)


async def fetch_notice_image_data_url(
    image_url: str,
    client: Optional[httpx.AsyncClient] = None,
) -> str:
    async def _fetch(active_client: httpx.AsyncClient) -> str:
        response = await active_client.get(image_url, timeout=20.0)
        response.raise_for_status()
        mime_type = mimetypes.guess_type(image_url)[0] or "image/jpeg"
        encoded = base64.b64encode(response.content).decode("ascii")
        return f"data:{mime_type};base64,{encoded}"

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(follow_redirects=True) as owned_client:
        return await _fetch(owned_client)


async def analyze_registration_notice(
    notice: RegistrationNotice,
    image_data_url: str,
    *,
    model: str = VISION_MODEL,
    llm: Optional[LLMService] = None,
) -> str:
    active_llm = llm or LLMService.get_instance()
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "창동문화체육센터 재등록 안내 이미지입니다. "
                        "이미지에 적힌 대상 월, 재등록 접수 날짜와 시간, 온라인/현장 구분, "
                        "꼭 알아야 할 유의사항만 한국어 3~6줄로 정확히 정리하세요. "
                        "이미지에 없는 내용은 추측하지 말고, 날짜가 이미 지났더라도 그대로 적으세요. "
                        f"공지 제목: {notice.title}"
                    ),
                },
                {
                    "type": "image_url",
                    "image_url": {"url": image_data_url, "detail": "high"},
                },
            ],
        }
    ]

    analysis = await asyncio.to_thread(
        active_llm.generate_paid_chat,
        messages,
        max_tokens=600,
        temperature=0.2,
        model=model,
        reasoning_effort="low",
    )
    analysis = (analysis or "").strip()
    if not analysis:
        error = active_llm.get_last_error() or "응답 없음"
        raise RuntimeError(f"창동 재등록 공지 비전 분석에 실패했습니다: {error}")
    return analysis


def _load_cached_analysis(
    state_path: Path,
    notice: RegistrationNotice,
    image_url: str,
) -> Optional[str]:
    if not state_path.exists():
        return None

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if payload.get("notice_id") != notice.notice_id:
        return None
    if payload.get("image_url") != image_url:
        return None

    analysis = str(payload.get("analysis") or "").strip()
    return analysis or None


def _save_analysis_state(
    state_path: Path,
    notice: RegistrationNotice,
    image_url: str,
    analysis: str,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **asdict(notice),
        "image_url": image_url,
        "analysis": analysis,
        "checked_at": datetime.now(KST).isoformat(),
        "model": VISION_MODEL,
    }
    temporary_path = state_path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary_path.replace(state_path)


def _build_notification_message(
    notice: RegistrationNotice,
    analysis: str,
) -> str:
    safe_title = html.escape(notice.title)
    safe_analysis = html.escape(analysis)
    safe_url = html.escape(notice.url, quote=True)
    return (
        "<b>[매일 확인 · 엄마 강좌 재등록]</b>\n"
        f"{safe_title}\n\n"
        f"{safe_analysis}\n\n"
        f'<a href="{safe_url}">공식 공지 이미지 확인하기</a>\n'
        "재등록했으면 오늘 할 일 목록에서 체크해 주세요!"
    )


async def send_daily_changdong_registration_reminder(
    *,
    state_path: Path = STATE_PATH,
    client: Optional[httpx.AsyncClient] = None,
    llm: Optional[LLMService] = None,
    model: str = VISION_MODEL,
) -> RegistrationNotice:
    notice = await fetch_latest_registration_notice(client)
    image_url = await fetch_notice_image_url(notice, client)
    analysis = _load_cached_analysis(state_path, notice, image_url)
    analyzed_now = analysis is None

    if analyzed_now:
        image_data_url = await fetch_notice_image_data_url(image_url, client)
        analysis = await analyze_registration_notice(
            notice,
            image_data_url,
            model=model,
            llm=llm,
        )
    else:
        logger.info(
            "Reusing cached Changdong registration analysis: notice_id=%s",
            notice.notice_id,
        )

    sent = await send_telegram_message(
        _build_notification_message(notice, analysis),
        bot_type="main",
    )
    if not sent:
        raise RuntimeError("창동문화체육센터 재등록 알림 텔레그램 발송에 실패했습니다.")

    if analyzed_now:
        _save_analysis_state(state_path, notice, image_url, analysis)
    logger.info(
        "Daily Changdong registration reminder sent: notice_id=%s model=%s analyzed_now=%s",
        notice.notice_id,
        model,
        analyzed_now,
    )
    return notice

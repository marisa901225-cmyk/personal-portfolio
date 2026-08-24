import asyncio
import base64
import html
import json
import logging
import mimetypes
import os
import re
from dataclasses import dataclass
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

POPUP_PAGE_URL = "https://www.dobongsiseol.or.kr/index_sport.html"
STATE_PATH = (
    Path(__file__).resolve().parents[1]
    / "storage"
    / "changdong_registration"
    / "state.json"
)
VISION_MODEL = os.getenv("CHANGDONG_REGISTRATION_VISION_MODEL", "gpt-5.6").strip() or "gpt-5.6"
_POPUP_IMAGE_RE = re.compile(
    r"""<img\s+[^>]*src=["'](?P<src>/layerpopup/images/sport/[^"']+)["'][^>]*>""",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PopupSnapshot:
    image_urls: tuple[str, ...]


def parse_popup_image_urls(page_html: str) -> tuple[str, ...]:
    urls = {
        urljoin(POPUP_PAGE_URL, match.group("src"))
        for match in _POPUP_IMAGE_RE.finditer(page_html)
    }
    if not urls:
        raise RuntimeError("창동문화체육센터 활성 팝업 이미지를 찾지 못했습니다.")
    return tuple(sorted(urls))


async def _fetch_response(
    client: httpx.AsyncClient,
    url: str,
    *,
    timeout: float,
) -> httpx.Response:
    response = await client.get(url, timeout=timeout)
    response.raise_for_status()
    return response


async def fetch_active_popup_snapshot(
    client: Optional[httpx.AsyncClient] = None,
) -> PopupSnapshot:
    async def _fetch(active_client: httpx.AsyncClient) -> PopupSnapshot:
        response = await _fetch_response(
            active_client,
            POPUP_PAGE_URL,
            timeout=20.0,
        )
        page_html = response.content.decode("cp949", errors="replace")
        return PopupSnapshot(image_urls=parse_popup_image_urls(page_html))

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(follow_redirects=True) as owned_client:
        return await _fetch(owned_client)


async def fetch_popup_image_data_urls(
    snapshot: PopupSnapshot,
    client: Optional[httpx.AsyncClient] = None,
) -> list[tuple[str, str]]:
    async def _download(
        active_client: httpx.AsyncClient,
        image_url: str,
    ) -> tuple[str, str]:
        response = await _fetch_response(
            active_client,
            image_url,
            timeout=20.0,
        )
        mime_type = mimetypes.guess_type(image_url)[0] or "image/jpeg"
        encoded = base64.b64encode(response.content).decode("ascii")
        return image_url, f"data:{mime_type};base64,{encoded}"

    async def _fetch(active_client: httpx.AsyncClient) -> list[tuple[str, str]]:
        return list(
            await asyncio.gather(
                *(
                    _download(active_client, image_url)
                    for image_url in snapshot.image_urls
                )
            )
        )

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(follow_redirects=True) as owned_client:
        return await _fetch(owned_client)


async def analyze_popup_snapshot(
    snapshot: PopupSnapshot,
    image_data_urls: list[tuple[str, str]],
    *,
    model: str = VISION_MODEL,
    llm: Optional[LLMService] = None,
) -> str:
    if tuple(image_url for image_url, _ in image_data_urls) != snapshot.image_urls:
        raise ValueError("팝업 이미지 데이터 순서가 현재 스냅샷과 일치하지 않습니다.")

    content: list[dict[str, object]] = [
        {
            "type": "text",
            "text": (
                "창동문화체육센터 현재 활성 팝업 이미지들입니다. "
                "이 중 재등록 접수 일정이 적힌 이미지만 찾아 대상 월, 재등록 기간, "
                "도봉구민/타구민 신규접수 날짜와 시간, 꼭 알아야 할 유의사항을 "
                "한국어 4~8줄로 정확히 정리하세요. 같은 일정이 여러 이미지에 있으면 "
                "정보를 합쳐 가장 구체적인 내용으로 한 번만 정리하세요. "
                "이미지에 없는 내용은 추측하지 마세요."
            ),
        }
    ]
    for image_url, data_url in image_data_urls:
        content.append(
            {
                "type": "text",
                "text": f"팝업 이미지: {image_url.rsplit('/', 1)[-1]}",
            }
        )
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": data_url, "detail": "high"},
            }
        )

    active_llm = llm or LLMService.get_instance()
    analysis = await asyncio.to_thread(
        active_llm.generate_paid_chat,
        [{"role": "user", "content": content}],
        max_tokens=900,
        temperature=0.2,
        model=model,
        reasoning_effort="low",
    )
    analysis = (analysis or "").strip()
    if not analysis:
        error = active_llm.get_last_error() or "응답 없음"
        raise RuntimeError(f"창동 재등록 팝업 비전 분석에 실패했습니다: {error}")
    return analysis


def _load_cached_analysis(
    state_path: Path,
    snapshot: PopupSnapshot,
) -> Optional[str]:
    if not state_path.exists():
        return None

    payload = json.loads(state_path.read_text(encoding="utf-8"))
    if payload.get("popup_image_urls") != list(snapshot.image_urls):
        return None

    analysis = str(payload.get("analysis") or "").strip()
    return analysis or None


def _save_analysis_state(
    state_path: Path,
    snapshot: PopupSnapshot,
    analysis: str,
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "popup_image_urls": list(snapshot.image_urls),
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


def _build_notification_message(analysis: str) -> str:
    safe_analysis = html.escape(analysis)
    safe_url = html.escape(POPUP_PAGE_URL, quote=True)
    return (
        "<b>[매일 확인 · 엄마 강좌 재등록]</b>\n"
        f"{safe_analysis}\n\n"
        f'<a href="{safe_url}">창동문화체육센터 팝업 확인하기</a>\n'
        "재등록했으면 오늘 할 일 목록에서 체크해 주세요!"
    )


async def send_daily_changdong_registration_reminder(
    *,
    state_path: Path = STATE_PATH,
    client: Optional[httpx.AsyncClient] = None,
    llm: Optional[LLMService] = None,
    model: str = VISION_MODEL,
) -> PopupSnapshot:
    snapshot = await fetch_active_popup_snapshot(client)
    analysis = _load_cached_analysis(state_path, snapshot)
    analyzed_now = analysis is None

    if analyzed_now:
        image_data_urls = await fetch_popup_image_data_urls(snapshot, client)
        analysis = await analyze_popup_snapshot(
            snapshot,
            image_data_urls,
            model=model,
            llm=llm,
        )
    else:
        logger.info(
            "Reusing cached Changdong popup analysis: popup_count=%s",
            len(snapshot.image_urls),
        )

    sent = await send_telegram_message(
        _build_notification_message(analysis),
        bot_type="main",
    )
    if not sent:
        raise RuntimeError("창동문화체육센터 재등록 알림 텔레그램 발송에 실패했습니다.")

    if analyzed_now:
        _save_analysis_state(state_path, snapshot, analysis)
    logger.info(
        "Daily Changdong popup reminder sent: popup_count=%s model=%s analyzed_now=%s",
        len(snapshot.image_urls),
        model,
        analyzed_now,
    )
    return snapshot

import json
from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.services import changdong_registration as monitor


class _FakeResponse:
    def __init__(self, content: str | bytes) -> None:
        self.content = content.encode("cp949") if isinstance(content, str) else content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: dict[str, str | bytes]) -> None:
        self._responses = responses
        self.calls = []

    async def get(self, url: str, *, timeout: float):
        self.calls.append({"url": url, "timeout": timeout})
        return _FakeResponse(self._responses[url])


def _popup_page(*paths: str) -> str:
    return "".join(f'<img src="{path}">' for path in paths)


def test_parse_popup_image_urls_keeps_only_active_sport_popups() -> None:
    page = (
        '<img src="/images/common/logo.png">'
        + _popup_page(
            "/layerpopup/images/sport/sport_260806.png",
            "/layerpopup/images/sport/sport_260730.jpg",
            "/layerpopup/images/sport/sport_260730.jpg",
        )
    )

    urls = monitor.parse_popup_image_urls(page)

    assert urls == (
        "https://www.dobongsiseol.or.kr/layerpopup/images/sport/sport_260730.jpg",
        "https://www.dobongsiseol.or.kr/layerpopup/images/sport/sport_260806.png",
    )


def test_filter_unexpired_registration_sections_removes_past_course_month() -> None:
    analysis = (
        "- **9월 강좌** 재등록 기간: **2026년 8월 18일~8월 24일**.\n"
        "- 9월 신규접수: **도봉구민 8월 26일**, **타구민 8월 27일**.\n"
        "- 9월 유의사항: 모든 강좌 반 변경 불가.\n"
        "- **10월 강좌** 재등록 기간: **2026년 9월 14일~9월 19일**.\n"
        "- 10월 신규접수: **도봉구민 9월 29일**, **타구민 9월 30일**."
    )

    filtered = monitor._filter_unexpired_registration_sections(
        analysis,
        today=date(2026, 9, 2),
    )

    assert filtered is not None
    assert "9월 강좌" not in filtered
    assert "9월 신규접수" not in filtered
    assert "9월 유의사항" not in filtered
    assert "10월 강좌" in filtered
    assert "10월 신규접수" in filtered


@pytest.mark.parametrize(
    ("today", "expected"),
    (
        (date(2026, 8, 24), True),
        (date(2026, 8, 25), False),
    ),
)
def test_filter_unexpired_registration_sections_includes_end_date(
    today: date,
    expected: bool,
) -> None:
    analysis = "- **9월 강좌** 재등록 기간: **2026년 8월 18일부터 24일까지**입니다."

    filtered = monitor._filter_unexpired_registration_sections(
        analysis,
        today=today,
    )

    assert (filtered is not None) is expected


def test_filter_unexpired_registration_sections_requires_end_date() -> None:
    with pytest.raises(ValueError, match="재등록 종료일을 찾지 못했습니다"):
        monitor._filter_unexpired_registration_sections(
            "- **10월 강좌** 재등록 일정은 팝업을 확인해 주세요.",
            today=date(2026, 9, 2),
        )


@pytest.mark.asyncio
async def test_analyze_popup_snapshot_sends_all_images_to_gpt56(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    snapshot = monitor.PopupSnapshot(
        image_urls=(
            "https://example.com/sport_1.jpg",
            "https://example.com/sport_2.png",
        )
    )
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "9월 재등록은 8월 18일부터 24일까지입니다."

    async def run_inline(function, *args, **kwargs):
        return function(*args, **kwargs)

    monkeypatch.setattr(monitor.asyncio, "to_thread", run_inline)

    result = await monitor.analyze_popup_snapshot(
        snapshot,
        [
            (snapshot.image_urls[0], "data:image/jpeg;base64,AAAA"),
            (snapshot.image_urls[1], "data:image/png;base64,BBBB"),
        ],
        llm=llm,
    )

    assert "8월 18일" in result
    _, kwargs = llm.generate_paid_chat.call_args
    assert kwargs["model"] == "gpt-5.6"
    content = llm.generate_paid_chat.call_args.args[0][0]["content"]
    image_parts = [part for part in content if part["type"] == "image_url"]
    assert len(image_parts) == 2


@pytest.mark.asyncio
async def test_daily_reminder_reuses_analysis_until_popup_urls_change(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    first_image = (
        "https://www.dobongsiseol.or.kr/"
        "layerpopup/images/sport/sport_260730.jpg"
    )
    client = _FakeClient(
        {
            monitor.POPUP_PAGE_URL: _popup_page(
                "/layerpopup/images/sport/sport_260730.jpg"
            ),
            first_image: b"image-bytes",
        }
    )
    analyze = AsyncMock(
        return_value=(
            "- **10월 강좌** 재등록 기간: "
            "**2026년 9월 14일부터 19일까지**입니다."
        )
    )
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor, "analyze_popup_snapshot", analyze)
    monkeypatch.setattr(monitor, "send_telegram_message", send)
    state_path = tmp_path / "state.json"

    first = await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        current_date=date(2026, 9, 2),
    )
    second = await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        current_date=date(2026, 9, 2),
    )

    assert first == second
    assert analyze.await_count == 1
    assert send.await_count == 2
    assert "엄마 강좌" in send.await_args.args[0]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["popup_image_urls"] == [first_image]


@pytest.mark.asyncio
async def test_daily_reminder_skips_send_when_registration_period_expired(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    image_url = "https://www.dobongsiseol.or.kr/layerpopup/images/sport/old.jpg"
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "popup_image_urls": [image_url],
                "analysis": (
                    "- **9월 강좌** 재등록 기간: "
                    "**2026년 8월 18일부터 24일까지**입니다."
                ),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = _FakeClient(
        {
            monitor.POPUP_PAGE_URL: _popup_page(
                "/layerpopup/images/sport/old.jpg"
            ),
        }
    )
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor, "send_telegram_message", send)

    await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        current_date=date(2026, 9, 2),
    )

    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_changed_popup_url_triggers_new_vision_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    old_image = "https://www.dobongsiseol.or.kr/layerpopup/images/sport/old.jpg"
    new_image = "https://www.dobongsiseol.or.kr/layerpopup/images/sport/new.jpg"
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "popup_image_urls": [old_image],
                "analysis": "이전 분석",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = _FakeClient(
        {
            monitor.POPUP_PAGE_URL: _popup_page(
                "/layerpopup/images/sport/new.jpg"
            ),
            new_image: b"new-image-bytes",
        }
    )
    analyze = AsyncMock(
        return_value=(
            "- **10월 강좌** 재등록 기간: "
            "**2026년 9월 14일부터 19일까지**입니다."
        )
    )
    monkeypatch.setattr(monitor, "analyze_popup_snapshot", analyze)
    monkeypatch.setattr(
        monitor,
        "send_telegram_message",
        AsyncMock(return_value=True),
    )

    await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        current_date=date(2026, 9, 2),
    )

    analyze.assert_awaited_once()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["popup_image_urls"] == [new_image]
    assert "10월 강좌" in state["analysis"]


@pytest.mark.asyncio
async def test_failed_send_does_not_write_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    image_url = "https://www.dobongsiseol.or.kr/layerpopup/images/sport/new.jpg"
    client = _FakeClient(
        {
            monitor.POPUP_PAGE_URL: _popup_page(
                "/layerpopup/images/sport/new.jpg"
            ),
            image_url: b"new-image-bytes",
        }
    )
    analyze = AsyncMock(
        return_value=(
            "- **10월 강좌** 재등록 기간: "
            "**2026년 9월 14일부터 19일까지**입니다."
        )
    )
    monkeypatch.setattr(monitor, "analyze_popup_snapshot", analyze)
    monkeypatch.setattr(
        monitor,
        "send_telegram_message",
        AsyncMock(return_value=False),
    )
    state_path = tmp_path / "state.json"

    with pytest.raises(RuntimeError, match="텔레그램 발송에 실패"):
        await monitor.send_daily_changdong_registration_reminder(
            state_path=state_path,
            client=client,
            current_date=date(2026, 9, 2),
        )

    assert not state_path.exists()

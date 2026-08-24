import json
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


@pytest.mark.asyncio
async def test_analyze_popup_snapshot_sends_all_images_to_gpt56() -> None:
    snapshot = monitor.PopupSnapshot(
        image_urls=(
            "https://example.com/sport_1.jpg",
            "https://example.com/sport_2.png",
        )
    )
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "9월 재등록은 8월 18일부터 24일까지입니다."

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
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "9월 재등록은 8월 18일부터 24일까지입니다."
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor, "send_telegram_message", send)
    state_path = tmp_path / "state.json"

    first = await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        llm=llm,
    )
    second = await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        llm=llm,
    )

    assert first == second
    assert llm.generate_paid_chat.call_count == 1
    assert send.await_count == 2
    assert "엄마 강좌" in send.await_args.args[0]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["popup_image_urls"] == [first_image]


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
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "변경된 팝업 분석"
    monkeypatch.setattr(
        monitor,
        "send_telegram_message",
        AsyncMock(return_value=True),
    )

    await monitor.send_daily_changdong_registration_reminder(
        state_path=state_path,
        client=client,
        llm=llm,
    )

    llm.generate_paid_chat.assert_called_once()
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["popup_image_urls"] == [new_image]
    assert state["analysis"] == "변경된 팝업 분석"


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
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "재등록 일정"
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
            llm=llm,
        )

    assert not state_path.exists()

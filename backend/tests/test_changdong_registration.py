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
    def __init__(self, responses: dict[str, str]) -> None:
        self._responses = responses
        self.calls = []

    async def get(self, url: str, *, timeout: float):
        self.calls.append({"url": url, "timeout": timeout})
        return _FakeResponse(self._responses[url])


def _notice_page(*rows: tuple[int, str]) -> str:
    return "".join(
        f'<a href="./board_content.html?num={notice_id}">{title}</a>'
        for notice_id, title in rows
    )


def test_parse_registration_notices_filters_and_deduplicates() -> None:
    page = _notice_page(
        (2461, "2026년 8월 신규 접수 안내"),
        (2460, "2026년 8월 재등록 접수일 안내"),
        (2460, "2026년 8월 재등록 접수일 안내"),
        (2439, "2026년 7월 재등록 접수일 안내"),
    )

    notices = monitor.parse_registration_notices(page)

    assert [notice.notice_id for notice in notices] == [2460, 2439]
    assert notices[0].url.endswith("/xs_board/board_content.html?num=2460")


def test_extract_notice_image_url_prefers_notice_content_image() -> None:
    detail_html = (
        '<img src="/images/common/logo.png">'
        '<img src="https://www.dobongsiseol.or.kr/rx99/rxPhotos/notice.jpg">'
        '<img src="/image_up/attachment.jpg">'
    )

    image_url = monitor.extract_notice_image_url(
        detail_html,
        "https://www.dobongsiseol.or.kr/xs_board/board_content.html?num=2460",
    )

    assert image_url.endswith("/rx99/rxPhotos/notice.jpg")


@pytest.mark.asyncio
async def test_fetch_notice_image_data_url_encodes_downloaded_image() -> None:
    image_url = "https://example.com/notice.jpg"
    client = _FakeClient({image_url: b"image-bytes"})

    data_url = await monitor.fetch_notice_image_data_url(image_url, client)

    assert data_url.startswith("data:image/jpeg;base64,")
    assert not data_url.endswith("image-bytes")


@pytest.mark.asyncio
async def test_analyze_registration_notice_uses_gpt56_vision() -> None:
    notice = monitor.RegistrationNotice(
        notice_id=2460,
        title="2026년 8월 재등록 접수일 안내",
        url="https://example.com/notice",
    )
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "재등록 접수: 7월 15일 오전 9시"

    result = await monitor.analyze_registration_notice(
        notice,
        "data:image/jpeg;base64,AAAA",
        llm=llm,
    )

    assert "7월 15일" in result
    _, kwargs = llm.generate_paid_chat.call_args
    assert kwargs["model"] == "gpt-5.6"
    content = llm.generate_paid_chat.call_args.args[0][0]["content"]
    image_part = next(part for part in content if part["type"] == "image_url")
    assert image_part["image_url"]["url"] == "data:image/jpeg;base64,AAAA"


@pytest.mark.asyncio
async def test_daily_reminder_reuses_analysis_until_notice_or_image_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    notice_url = (
        "https://www.dobongsiseol.or.kr/xs_board/"
        "board_content.html?num=2460"
    )
    client = _FakeClient(
        {
            monitor.NOTICE_LIST_URL: _notice_page(
                (2460, "2026년 8월 재등록 접수일 안내")
            ),
            notice_url: '<img src="/rx99/rxPhotos/notice.jpg">',
            "https://www.dobongsiseol.or.kr/rx99/rxPhotos/notice.jpg": b"image-bytes",
        }
    )
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "재등록 접수는 7월 15일 오전 9시입니다."
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

    assert first.notice_id == 2460
    assert second.notice_id == 2460
    assert llm.generate_paid_chat.call_count == 1
    assert send.await_count == 2
    assert "엄마 강좌" in send.await_args.args[0]
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["notice_id"] == 2460
    assert state["model"] == "gpt-5.6"


@pytest.mark.asyncio
async def test_changed_image_url_triggers_new_vision_analysis(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    notice_url = (
        "https://www.dobongsiseol.or.kr/xs_board/"
        "board_content.html?num=2460"
    )
    old_image_url = "https://www.dobongsiseol.or.kr/rx99/rxPhotos/old.jpg"
    new_image_url = "https://www.dobongsiseol.or.kr/rx99/rxPhotos/new.jpg"
    state_path = tmp_path / "state.json"
    state_path.write_text(
        json.dumps(
            {
                "notice_id": 2460,
                "image_url": old_image_url,
                "analysis": "이전 분석",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    client = _FakeClient(
        {
            monitor.NOTICE_LIST_URL: _notice_page(
                (2460, "2026년 8월 재등록 접수일 안내")
            ),
            notice_url: f'<img src="{new_image_url}">',
            new_image_url: b"new-image-bytes",
        }
    )
    llm = MagicMock()
    llm.generate_paid_chat.return_value = "변경된 이미지 분석"
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
    assert state["image_url"] == new_image_url
    assert state["analysis"] == "변경된 이미지 분석"


@pytest.mark.asyncio
async def test_failed_send_does_not_write_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    notice_url = (
        "https://www.dobongsiseol.or.kr/xs_board/"
        "board_content.html?num=2460"
    )
    client = _FakeClient(
        {
            monitor.NOTICE_LIST_URL: _notice_page(
                (2460, "2026년 8월 재등록 접수일 안내")
            ),
            notice_url: '<img src="/rx99/rxPhotos/notice.jpg">',
            "https://www.dobongsiseol.or.kr/rx99/rxPhotos/notice.jpg": b"image-bytes",
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

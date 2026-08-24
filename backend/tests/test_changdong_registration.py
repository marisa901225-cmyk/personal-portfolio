import json
from unittest.mock import AsyncMock

import pytest

from backend.services import changdong_registration as monitor


class _FakeResponse:
    def __init__(self, page_html: str) -> None:
        self.content = page_html.encode("cp949")

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, page_html: str) -> None:
        self._response = _FakeResponse(page_html)
        self.calls = []

    async def get(self, url: str, *, timeout: float):
        self.calls.append({"url": url, "timeout": timeout})
        return self._response


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


@pytest.mark.asyncio
async def test_first_check_initializes_state_without_sending(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    client = _FakeClient(_notice_page((2460, "2026년 8월 재등록 접수일 안내")))
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor, "send_telegram_message", send)
    state_path = tmp_path / "state.json"

    result = await monitor.check_changdong_registration_notice(
        state_path=state_path,
        client=client,
    )

    assert result is None
    assert json.loads(state_path.read_text(encoding="utf-8"))["notice_id"] == 2460
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_notice_sends_once_and_updates_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"notice_id": 2460}', encoding="utf-8")
    client = _FakeClient(_notice_page((2500, "2026년 9월 재등록 접수일 안내")))
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(monitor, "send_telegram_message", send)

    result = await monitor.check_changdong_registration_notice(
        state_path=state_path,
        client=client,
    )
    duplicate = await monitor.check_changdong_registration_notice(
        state_path=state_path,
        client=client,
    )

    assert result is not None
    assert result.notice_id == 2500
    assert duplicate is None
    assert json.loads(state_path.read_text(encoding="utf-8"))["notice_id"] == 2500
    send.assert_awaited_once()
    assert "엄마 강좌" in send.await_args.args[0]
    assert send.await_args.kwargs["bot_type"] == "main"


@pytest.mark.asyncio
async def test_failed_send_does_not_advance_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    state_path = tmp_path / "state.json"
    state_path.write_text('{"notice_id": 2460}', encoding="utf-8")
    client = _FakeClient(_notice_page((2500, "2026년 9월 재등록 접수일 안내")))
    monkeypatch.setattr(
        monitor,
        "send_telegram_message",
        AsyncMock(return_value=False),
    )

    with pytest.raises(RuntimeError, match="텔레그램 발송에 실패"):
        await monitor.check_changdong_registration_notice(
            state_path=state_path,
            client=client,
        )

    assert json.loads(state_path.read_text(encoding="utf-8"))["notice_id"] == 2460

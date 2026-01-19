import asyncio
import tempfile
import unittest
from pathlib import Path
from datetime import datetime as DateTime
from unittest.mock import patch, AsyncMock
import types
import sys

from backend.services.alarm.match_notifier import check_upcoming_matches, _filter_catchphrases


class _FakeQuery:
    def __init__(self):
        self.filter_args = None
        self._rows = []

    def filter(self, *args):
        self.filter_args = args
        return self

    def all(self):
        return list(self._rows)


class _FakeSession:
    def __init__(self):
        self._query = _FakeQuery()

    def query(self, _model):
        return self._query
    
    def commit(self):
        return None


class _Match:
    def __init__(self, *, game_tag: str, league_tag: str, title: str, event_time: DateTime):
        self.game_tag = game_tag
        self.league_tag = league_tag
        self.title = title
        self.event_time = event_time
        self.category_tag = ""
        self.full_content = ""


class TestMatchNotifier(unittest.TestCase):
    def test_filter_does_not_receive_datetime_literal(self):
        db = _FakeSession()

        result = asyncio.run(check_upcoming_matches(db, catchphrases_file="/does/not/exist.json", window_minutes=5))
        self.assertFalse(result)

        self.assertIsNotNone(db._query.filter_args)
        self.assertFalse(any(isinstance(arg, DateTime) for arg in db._query.filter_args))

    def test_filter_catchphrases_removes_meta_and_english(self):
        phrases = [
            "우선 요구사항을 정리해 보겠습니다.",
            "출력은 정확히 10줄만",
            "<think>사고과정</think> 이제 시작!",
            "지금 시작됐어요!",
            "관중이 폭발! 달려요 ON!",
            "VCT Pacific 시작 전 입장!",
        ]
        filtered = _filter_catchphrases(phrases)
        self.assertIn("지금 시작됐어요!", filtered)
        self.assertIn("VCT Pacific 시작 전 입장!", filtered)
        self.assertNotIn("우선 요구사항을 정리해 보겠습니다.", filtered)
        self.assertNotIn("출력은 정확히 10줄만", filtered)

    def test_v2_file_path_is_not_doubled_and_used(self):
        db = _FakeSession()
        db._query._rows = [
            _Match(
                game_tag="LoL",
                league_tag="LCK",
                title="[Esports Schedule] LoL - BRO vs BFX",
                event_time=DateTime.now(),
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            v2_path = Path(tmpdir) / "esports_catchphrases_v2.json"
            v2_path.write_text('{"LoL": ["이건 V2 문구입니다"], "Valorant": []}', encoding="utf-8")

            with patch("backend.services.alarm.match_notifier.choose_phrase", return_value="이건 V2 문구입니다"):
                stub_mod = types.ModuleType("backend.integrations.telegram")
                stub_mod.send_telegram_message = AsyncMock()
                old = sys.modules.get("backend.integrations.telegram")
                sys.modules["backend.integrations.telegram"] = stub_mod
                try:
                    result = asyncio.run(check_upcoming_matches(db, catchphrases_file=str(v2_path), window_minutes=5))
                finally:
                    if old is None:
                        sys.modules.pop("backend.integrations.telegram", None)
                    else:
                        sys.modules["backend.integrations.telegram"] = old

        self.assertTrue(result)
        sent = stub_mod.send_telegram_message.call_args[0][0]
        self.assertIn("이건 V2 문구입니다", sent)

    def test_when_v2_phrases_invalid_uses_high_quality_fallback(self):
        db = _FakeSession()
        db._query._rows = [
            _Match(
                game_tag="LoL",
                league_tag="LCK",
                title="[Esports Schedule] LoL - BRO vs BFX",
                event_time=DateTime.now(),
            )
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            v2_path = Path(tmpdir) / "esports_catchphrases_v2.json"
            v2_path.write_text('{"LoL": ["우선 요구사항을 정리해 보겠습니다."], "Valorant": []}', encoding="utf-8")

            def _pick_first(phrases, **_kwargs):
                return phrases[0]

            with patch("backend.services.alarm.match_notifier.choose_phrase", side_effect=_pick_first):
                stub_mod = types.ModuleType("backend.integrations.telegram")
                stub_mod.send_telegram_message = AsyncMock()
                old = sys.modules.get("backend.integrations.telegram")
                sys.modules["backend.integrations.telegram"] = stub_mod
                try:
                    result = asyncio.run(check_upcoming_matches(db, catchphrases_file=str(v2_path), window_minutes=5))
                finally:
                    if old is None:
                        sys.modules.pop("backend.integrations.telegram", None)
                    else:
                        sys.modules["backend.integrations.telegram"] = old

        self.assertTrue(result)
        sent = stub_mod.send_telegram_message.call_args[0][0]
        # 진짜 고퀄 폴백 문구가 포함되어 있는지 확인 (LoL 첫 번째 항목)
        self.assertIn("대결이 시작됩니다", sent)

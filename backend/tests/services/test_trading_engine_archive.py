from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.db import Base
from backend.core.models_misc import TradingEngineArchive
from backend.services.trading_engine.archive import archive_trading_engine_weekly
from backend.services.trading_engine.bot import HybridTradingBot
from backend.services.trading_engine.day_chart_review import DayChartReviewResult
from backend.services.trading_engine.entry_support import apply_day_chart_review, apply_swing_chart_review
from backend.services.trading_engine.google_calendar import _build_finalize_event, _build_profit_event
from backend.services.trading_engine.bot_runtime_support import (
    finalize_account_summary,
    finalize_calendar_account_context,
    finalize_calendar_account_summary,
    finalize_price_sync_summary,
    finalize_state_sync_summary,
    finalize_trade_activity_summary,
    summarize_finalize_pass_reasons,
)
from backend.services.trading_engine.config import TradeEngineConfig
from backend.services.trading_engine.journal import TradeJournal
from backend.services.trading_engine.state import PositionState, new_state, save_state
from backend.services.market_data import MarketDataService


class _SpyNotifier:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.files: list[tuple[str, str | None]] = []

    def enqueue_text(self, text: str) -> None:
        self.texts.append(text)

    def enqueue_file(self, path: str, caption: str | None = None) -> None:
        self.files.append((path, caption))

    def flush(self, timeout_sec: float = 2.0) -> None:
        del timeout_sec

    def close(self, timeout_sec: float = 2.0) -> None:
        del timeout_sec


def test_archive_trading_engine_weekly_moves_files_to_db_and_cleans_up(tmp_path) -> None:
    db_path = tmp_path / "archive.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    journal_path = output_dir / "trade_journal_20260414.jsonl"
    journal_path.write_text('{"event":"SCAN_DONE"}\n', encoding="utf-8")
    legacy_zip_path = output_dir / "trade_backup_20260414.zip"
    legacy_zip_path.write_bytes(b"\x50\x4b\x03\x04\xff")

    state_path = tmp_path / "state.json"
    state = new_state("20260418")
    save_state(str(state_path), state)

    runlog_path = tmp_path / "run.log"
    runlog_path.write_text("line one\nline two\n", encoding="utf-8")

    cfg = TradeEngineConfig(
        state_path=str(state_path),
        output_dir=str(output_dir),
        runlog_path=str(runlog_path),
    )

    with SessionLocal() as db:
        result = archive_trading_engine_weekly(
            db,
            config=cfg,
            now=datetime(2026, 4, 18, 6, 40),
        )
        row = db.query(TradingEngineArchive).one()
        payload_json = row.payload_json
        manifest_json = row.manifest_json
        cleanup_completed_at = row.cleanup_completed_at
        cleanup_error = row.cleanup_error

    payload = json.loads(payload_json)
    manifest = json.loads(manifest_json)
    archived_names = {item["name"] for item in payload["output_files"]}

    assert result.status == "ARCHIVED"
    assert result.archived_output_file_count == 2
    assert result.removed_output_file_count == 2
    assert result.runlog_truncated is True
    assert result.covered_trade_dates == ["20260414"]
    assert archived_names == {"trade_journal_20260414.jsonl", "trade_backup_20260414.zip"}
    assert payload["state_snapshot"]["name"] == "state.json"
    assert payload["runlog_snapshot"]["path"] == "runlog_current.log"
    assert any(item["encoding"] == "base64" for item in payload["output_files"])
    assert all("content" not in item for item in manifest["output_files"])
    assert cleanup_completed_at is not None
    assert cleanup_error is None
    assert not journal_path.exists()
    assert not legacy_zip_path.exists()
    assert state_path.exists()
    assert runlog_path.read_text(encoding="utf-8") == ""

    engine.dispose()


def test_archive_trading_engine_weekly_is_noop_without_output_and_runlog(tmp_path) -> None:
    db_path = tmp_path / "archive.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    state_path = tmp_path / "state.json"
    save_state(str(state_path), new_state("20260418"))
    cfg = TradeEngineConfig(
        state_path=str(state_path),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )

    with SessionLocal() as db:
        result = archive_trading_engine_weekly(
            db,
            config=cfg,
            now=datetime(2026, 4, 18, 6, 40),
        )
        row_count = db.query(TradingEngineArchive).count()

    assert result.status == "NOOP"
    assert result.archive_id is None
    assert row_count == 0
    assert state_path.exists()

    engine.dispose()


def test_finalize_day_no_longer_creates_backup_zip(tmp_path) -> None:
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = _SpyNotifier()
    bot = HybridTradingBot(object(), config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260418"
    bot.journal = TradeJournal(output_dir=cfg.output_dir, asof_date="20260418")

    summary_text = bot.finalize_day()

    assert summary_text is not None
    assert summary_text.startswith("[마감] 20260418")
    assert notifier.files == []
    assert list((tmp_path / "output").glob("*.zip")) == []


def test_finalize_day_prefers_account_realized_pnl_summary(tmp_path) -> None:
    class _RealizedPnlAPI:
        def inquire_realized_pnl(self) -> dict:
            return {
                "output1": [],
                "output2": [{"rlzt_pfls": "12345"}],
            }

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = _SpyNotifier()
    bot = HybridTradingBot(_RealizedPnlAPI(), config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260422"
    bot.state.realized_pnl_today = 0.0
    bot.journal = TradeJournal(output_dir=cfg.output_dir, asof_date="20260422")

    summary_text = bot.finalize_day()

    assert summary_text is not None
    assert "실현손익: 12,345원" in summary_text
    assert bot.state.realized_pnl_today == 12345.0


def test_finalize_day_uses_local_llm_readable_summary(tmp_path, monkeypatch) -> None:
    class _Settings:
        def is_remote_configured(self) -> bool:
            return True

    class _LocalLLM:
        settings = _Settings()

        def generate_chat(self, messages, **kwargs) -> str:  # type: ignore[no-untyped-def]
            assert kwargs["allow_paid_fallback"] is True
            assert kwargs["model"] == "gpt-5.4-mini"
            assert "단타 후보 제외" in messages[1]["content"]
            assert "계좌 상황:" in messages[1]["content"]
            return "[마감] 20260423\n오늘은 스캔과 보류가 많았고, 실행 이벤트는 적었습니다.\n실현손익: -3,900원 (-0.39%)"

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = _SpyNotifier()
    bot = HybridTradingBot(object(), config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260423"
    bot.state.realized_pnl_today = -3900.0
    bot.journal = TradeJournal(output_dir=cfg.output_dir, asof_date="20260423")
    bot.journal.log("DAY_CANDIDATE_FILTERED", asof_date="20260423", code="011790")

    monkeypatch.setattr(
        "backend.services.trading_engine.bot_runtime_support.LLMService.get_instance",
        lambda: _LocalLLM(),
    )

    summary_text = bot.finalize_day()

    assert summary_text == notifier.texts[-1]
    assert summary_text is not None
    assert summary_text.startswith("[마감] 20260423")
    assert "오늘은 스캔과 보류가 많았고" in summary_text
    assert "실현손익: -3,900원" in summary_text


def test_finalize_day_does_not_duplicate_llm_realized_amount(tmp_path, monkeypatch) -> None:
    class _Settings:
        def is_remote_configured(self) -> bool:
            return True

    class _LocalLLM:
        settings = _Settings()

        def generate_chat(self, messages, **kwargs) -> str:  # type: ignore[no-untyped-def]
            del messages, kwargs
            return "[마감] 20260424\n실현손익은 57,112원 (+5.71%)입니다."

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = _SpyNotifier()
    bot = HybridTradingBot(object(), config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260424"
    bot.state.realized_pnl_today = 57112.0
    bot.journal = TradeJournal(output_dir=cfg.output_dir, asof_date="20260424")

    monkeypatch.setattr(
        "backend.services.trading_engine.bot_runtime_support.LLMService.get_instance",
        lambda: _LocalLLM(),
    )

    summary_text = bot.finalize_day()

    assert summary_text is not None
    assert summary_text.count("57,112원") == 1


def test_finalize_pass_reason_summary_ignores_routine_reasons() -> None:
    summary = summarize_finalize_pass_reasons(
        {
            "ENTRY_WINDOW_CLOSED": 111,
            "MAX_SWING_POSITIONS": 67,
        }
    )

    assert summary == "특이사항 없음"
    assert "111" not in summary
    assert "67" not in summary


def test_finalize_pass_reason_summary_reports_noteworthy_failures() -> None:
    summary = summarize_finalize_pass_reasons(
        {
            "ENTRY_WINDOW_CLOSED": 111,
            "DAY_ENTRY_FAILED": 2,
            "FETCH_FAILED": 1,
        }
    )

    assert summary == "단타 진입 실패, 장중 데이터 조회 실패"
    assert "ENTRY_WINDOW_CLOSED" not in summary


def test_finalize_account_summary_includes_cash_positions_and_eval_pnl() -> None:
    class _API:
        def cash_available(self) -> int:
            return 123456

        def positions(self) -> list[dict[str, object]]:
            return [
                {
                    "code": "011790",
                    "name": "SKC",
                    "qty": 2,
                    "avg_price": 10000,
                    "current_price": 11000,
                    "pnl": 2000,
                },
                {
                    "code": "010170",
                    "name": "대한광통신",
                    "qty": 1,
                    "avg_price": 20000,
                    "current_price": 19000,
                    "pnl": -1000,
                },
            ]

    class _Bot:
        api = _API()

    summary = finalize_account_summary(_Bot(), logger=__import__("logging").getLogger(__name__))

    assert (
        summary
        == "예수금 123,456원, 보유 2종목: SKC, 대한광통신, 평가금액 41,000원, 평가손익 1,000원 (+2.50%)"
    )


def test_finalize_calendar_account_summary_uses_total_account_value() -> None:
    class _API:
        def cash_available(self) -> int:
            return 123456

        def positions(self) -> list[dict[str, object]]:
            return [
                {"name": "SKC", "qty": 2, "avg_price": 10000, "current_price": 11000, "pnl": 2000},
                {"name": "대한광통신", "qty": 1, "avg_price": 20000, "current_price": 19000, "pnl": -1000},
            ]

    class _Bot:
        api = _API()

    summary = finalize_calendar_account_summary(_Bot(), logger=__import__("logging").getLogger(__name__))

    assert summary == "총평가 164,456원 / 현금 123,456원 / 보유 2종목"

    context = finalize_calendar_account_context(_Bot(), logger=__import__("logging").getLogger(__name__))
    assert context == {
        "account_line": "총평가 164,456원 / 현금 123,456원 / 보유 2종목",
        "eval_pct": 2.5,
    }


def test_finalize_trade_activity_summary_names_entries_and_exits(tmp_path, monkeypatch) -> None:
    class _Info:
        def __init__(self, name: str) -> None:
            self.name = name

    monkeypatch.setattr(
        "backend.services.trading_engine.bot_runtime_support.load_stock_master_map",
        lambda **kwargs: {  # type: ignore[no-untyped-def]
            "011790": _Info("SKC"),
            "487240": _Info("에스케이증권제13호스팩"),
        },
    )

    journal = TradeJournal(output_dir=str(tmp_path), asof_date="20260508")
    journal.log("ENTRY_FILL", asof_date="20260508", code="011790", qty=1, avg_price=155900, strategy_type="T")
    journal.log("STATE_RECONCILE_ADD", asof_date="20260508", code="011790", qty=1, avg_price=155900, strategy_type="T")
    journal.log(
        "STATE_RECONCILE_DROP",
        asof_date="20260508",
        code="487240",
        qty=4,
        exit_reason="SL",
        exit_fill_avg_price=61775,
        exit_fill_pnl_pct=-1.6478,
    )
    journal.log("STATE_RECONCILE_UPDATE", asof_date="20260508", code="011790", old_qty=1, new_qty=1)

    summary = finalize_trade_activity_summary(
        journal=journal,
        config=TradeEngineConfig(),
        logger=__import__("logging").getLogger(__name__),
    )

    assert summary is not None
    assert "매수: 단타 SKC 1주 155,900원" in summary
    assert "청산: 에스케이증권제13호스팩 4주 손절 61,775원 -1.65%" in summary
    assert "상태동기화" not in summary
    assert finalize_state_sync_summary(journal=journal, logger=__import__("logging").getLogger(__name__)) == "3건"


def test_bot_reconcile_records_state_sync_without_telegram(tmp_path) -> None:
    class _API:
        def positions(self) -> list[dict[str, object]]:
            return []

        def quote(self, code: str) -> dict[str, object]:
            del code
            return {"price": 4352}

    state_path = tmp_path / "state.json"
    output_dir = tmp_path / "output"
    state = new_state("20260508")
    state.open_positions["018880"] = PositionState(
        type="T",
        entry_time="2026-05-08T09:00:00",
        entry_price=4400,
        qty=44,
        highest_price=4400,
        entry_date="20260508",
    )
    save_state(str(state_path), state)
    bot = HybridTradingBot(
        _API(),
        config=TradeEngineConfig(state_path=str(state_path), output_dir=str(output_dir)),
        notifier=_SpyNotifier(),
    )
    bot._ensure_journal("20260508")

    bot._reconcile_state_with_broker_positions(now=datetime(2026, 5, 8, 15, 20))

    assert bot.notifier.texts == []
    assert bot.journal is not None
    assert finalize_state_sync_summary(journal=bot.journal, logger=__import__("logging").getLogger(__name__)) == "1건"


def test_chart_review_records_journal_without_telegram(tmp_path) -> None:
    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
    )
    notifier = _SpyNotifier()
    bot = HybridTradingBot(object(), config=cfg, notifier=notifier)  # type: ignore[arg-type]
    bot.state.trade_date = "20260508"
    bot.journal = TradeJournal(output_dir=cfg.output_dir, asof_date="20260508")

    def _review_fn(**kwargs):  # type: ignore[no-untyped-def]
        del kwargs
        return DayChartReviewResult(
            shortlisted_codes=["066570", "090710"],
            approved_codes=["066570"],
            selected_code="066570",
            summary="유료 2차 재정렬 결과",
            chart_paths=["backend/storage/trading_engine/output/day_chart.png"],
            raw_response={},
        )

    approved_codes, reviewed = apply_day_chart_review(
        bot,
        ranked_codes=["066570", "090710"],
        candidates=object(),
        quotes={},
        review_fn=_review_fn,
    )

    swing_codes, swing_reviewed = apply_swing_chart_review(
        bot,
        ranked_codes=["011210", "064400"],
        candidates=object(),
        quotes={},
        review_fn=_review_fn,
    )

    assert approved_codes == ["066570"]
    assert reviewed is True
    assert swing_codes == ["066570"]
    assert swing_reviewed is True
    assert notifier.texts == []
    assert notifier.files == []

    with open(bot.journal.jsonl_path, encoding="utf-8") as f:
        rows = [json.loads(line) for line in f if line.strip()]
    events = [row["event"] for row in rows]
    assert "DAY_CHART_REVIEW" in events
    assert "SWING_CHART_REVIEW" in events


def test_price_sync_completion_is_summarized_for_finalize(tmp_path) -> None:
    status_path = tmp_path / "sync_prices_status.json"
    MarketDataService.record_sync_completion(
        ticker_count=7,
        status_path=str(status_path),
        now=datetime(2026, 5, 8, 15, 33, 2),
    )

    summary = finalize_price_sync_summary(
        trade_date="20260508",
        status_path=str(status_path),
        logger=__import__("logging").getLogger(__name__),
    )

    assert summary == "7종목 완료 (2026-05-08 15:33:02 기준)"


def test_finalize_google_calendar_event_payload_uses_trade_date_and_summary() -> None:
    event = _build_finalize_event(
        config=TradeEngineConfig(),
        trade_date="20260508",
        summary_text="[마감] 20260508\n실현손익은 57,112원 (+5.71%)이었습니다.",
        realized_pnl=57112.0,
        realized_pct=5.7112,
        account_summary="총평가 1,423,000원 / 현금 300,000원 / 보유 4종목",
        eval_pct=-0.8,
        trade_activity_summary="매수: 한화오션 외 2건 / 청산: SK하이닉스 - 손절",
    )

    assert event["summary"] == "[매매마감] 20260508 57,112원 (+5.71%)"
    assert event["description"] == (
        "[마감] 20260508\n"
        "손익: 실현 +57,112원 / 평가 -0.80%\n"
        "계좌: 총평가 1,423,000원 / 현금 300,000원 / 보유 4종목\n"
        "매수: 한화오션 외 2건\n"
        "청산: SK하이닉스 - 손절"
    )
    assert event["start"]["dateTime"].startswith("2026-05-08T15:40:00")
    assert event["extendedProperties"]["private"]["trading_finalize_date"] == "20260508"


def test_profit_google_calendar_event_payload_is_concise_all_day_record() -> None:
    event = _build_profit_event(
        config=TradeEngineConfig(),
        trade_date="20260508",
        realized_pnl=57112.0,
        pnl_rate=2.20540307,
    )

    assert event["summary"] == "[자동매매] 57,112원 (+2.21%)"
    assert event["description"] == "실현손익: 57,112원 (+2.21%)"
    assert event["start"] == {"date": "2026-05-08"}
    assert event["end"] == {"date": "2026-05-09"}
    assert event["extendedProperties"]["private"]["trading_profit_date"] == "20260508"


def test_archive_trading_engine_weekly_keeps_large_files_on_disk(tmp_path) -> None:
    db_path = tmp_path / "archive.db"
    engine = create_engine(
        f"sqlite:///{db_path.as_posix()}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    SessionLocal = sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        future=True,
    )
    Base.metadata.create_all(bind=engine)

    output_dir = tmp_path / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    large_path = output_dir / "trade_journal_20260418.jsonl"
    large_path.write_text("x" * 32, encoding="utf-8")
    state_path = tmp_path / "state.json"
    save_state(str(state_path), new_state("20260418"))
    runlog_path = tmp_path / "run.log"
    runlog_path.write_text("y" * 32, encoding="utf-8")

    cfg = TradeEngineConfig(
        state_path=str(state_path),
        output_dir=str(output_dir),
        runlog_path=str(runlog_path),
        archive_inline_max_bytes=8,
    )

    with SessionLocal() as db:
        result = archive_trading_engine_weekly(
            db,
            config=cfg,
            now=datetime(2026, 4, 18, 6, 40),
        )
        row = db.query(TradingEngineArchive).one()

    payload = json.loads(row.payload_json)
    output_entry = payload["output_files"][0]
    runlog_entry = payload["runlog_snapshot"]

    assert result.status == "ARCHIVED"
    assert result.removed_output_file_count == 0
    assert result.runlog_truncated is False
    assert output_entry["encoding"] == "omitted"
    assert output_entry["retained_on_disk"] is True
    assert "content" not in output_entry
    assert runlog_entry["encoding"] == "omitted"
    assert large_path.exists()
    assert runlog_path.read_text(encoding="utf-8") == "y" * 32

    engine.dispose()

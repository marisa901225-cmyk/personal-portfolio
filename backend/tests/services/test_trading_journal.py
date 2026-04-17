from __future__ import annotations

from backend.services.trading_engine.journal import TradeJournal


def test_trade_journal_summary_uses_full_file_counts_across_restarts(tmp_path) -> None:
    journal1 = TradeJournal(output_dir=str(tmp_path), asof_date="20260415")
    journal1.log("RUN_START", asof_date="20260415")
    journal1.log("SCAN_DONE", asof_date="20260415")
    journal1.log("PASS", asof_date="20260415", reason="NO_CANDIDATE")
    journal1.log("ENTRY_FILL", asof_date="20260415", code="005880")
    journal1.log("NEWS_SENTIMENT", asof_date="20260415", market_score=0.3)

    journal2 = TradeJournal(output_dir=str(tmp_path), asof_date="20260415")
    journal2.log("RUN_START", asof_date="20260415")
    journal2.log("SCAN_DONE", asof_date="20260415")
    journal2.log("PASS", asof_date="20260415", reason="ENTRY_WINDOW_CLOSED")
    journal2.log("DAY_CANDIDATE_FILTERED", asof_date="20260415", code="005930", reason="RETRACE")
    journal2.log("RUN_END", asof_date="20260415")

    assert journal2.summary() == "스캔: 2회 | 단타 후보 제외: 1회 | 진입 체결: 1회 | 뉴스 심리: 1회 | 패스: 2회"

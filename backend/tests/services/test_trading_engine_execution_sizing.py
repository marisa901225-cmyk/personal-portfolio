from .trading_engine_support import *  # noqa: F401,F403

from backend.services.trading_engine.day_stop_review import (
    DayOvernightCarryReviewResult,
    DayStopReviewResult,
)

def test_day_entry_uses_strategy_cap_not_remaining_cash(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 250_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-04-08T09:05:00",
        entry_price=100_000.0,
        qty=8,
        highest_price=100_000.0,
        entry_date="20260408",
        bars_held=2,
    )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 4

def test_day_entry_adds_realized_profit_buffer_on_top_of_strategy_cap(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 260_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
        use_realized_profit_buffer=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.realized_pnl_total = 50_000.0

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 5, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 5

def test_day_entry_uses_account_basis_buffer_without_unrealized_gain(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 250_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}
    api._positions = [
        {
            "code": "SWING01",
            "qty": 8,
            "avg_price": 100_000.0,
            "current_price": 110_000,
            "pnl": 80_000,
        }
    ]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        day_cash_ratio=0.20,
        use_realized_profit_buffer=True,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 5, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 5


def test_day_entry_reuses_unused_swing_budget_when_leftover_exceeds_threshold(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 400_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}
    api._positions = [{"code": "SWING01", "qty": 10, "avg_price": 66_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        swing_cash_ratio=0.80,
        day_cash_ratio=0.20,
        day_reuse_unused_swing_cash_enabled=True,
        day_reuse_unused_swing_cash_min_krw=100_000,
        use_realized_profit_buffer=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-04-10T09:05:00",
        entry_price=66_000.0,
        qty=10,
        highest_price=66_000.0,
        entry_date="20260410",
        bars_held=0,
    )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 6, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 6


def test_day_entry_does_not_reuse_unused_swing_budget_below_threshold(tmp_path) -> None:
    asof = "20260410"
    api = FakeAPI()
    api._cash_available = 400_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.5}
    api._positions = [{"code": "SWING01", "qty": 10, "avg_price": 71_000.0}]

    cfg = TradeEngineConfig(
        state_path=str(tmp_path / "state.json"),
        output_dir=str(tmp_path / "output"),
        runlog_path=str(tmp_path / "run.log"),
        use_news_sentiment=False,
        use_intraday_circuit_breaker=False,
        initial_capital=1_000_000,
        swing_cash_ratio=0.80,
        day_cash_ratio=0.20,
        day_reuse_unused_swing_cash_enabled=True,
        day_reuse_unused_swing_cash_min_krw=100_000,
        use_realized_profit_buffer=False,
    )
    bot = HybridTradingBot(api, config=cfg)
    bot.state.trade_date = asof
    bot.state.open_positions["SWING01"] = PositionState(
        type="S",
        entry_time="2026-04-10T09:05:00",
        entry_price=71_000.0,
        qty=10,
        highest_price=71_000.0,
        entry_date="20260410",
        bars_held=0,
    )

    candidates = Candidates(
        asof=asof,
        popular=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000", "close": 50000, "change_pct": "1.5", "is_etf": False},
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(
            [
                {"code": "005930", "name": "삼성전자", "avg_value_5d": "90000000000"},
            ]
        ),
        quote_codes=["005930"],
    )

    with patch("backend.services.trading_engine.bot.rank_daytrade_codes", return_value=["005930"]):
        bot._try_enter_day(
            now=datetime(2026, 4, 10, 9, 10),
            regime="RISK_ON",
            candidates=candidates,
            quotes={"005930": api.quote("005930")},
            news_signal=None,
        )

    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 4, "order_type": "limit", "price": 50_100}
    ]
    assert bot.state.open_positions["005930"].qty == 4

def test_enter_position_returns_sizing_metadata() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "005930"
            assert order_type == "best"
            assert price == 50_000
            return {
                "ord_psbl_cash": 900_000,
                "nrcvb_buy_amt": 900_000,
                "nrcvb_buy_qty": 14,
                "max_buy_qty": 14,
                "psbl_qty_calc_unpr": 50_000,
            }

    api = BuyableAPI()
    api._cash_available = 1_000_000
    api._quotes["005930"] = {"price": 50_000, "change_pct": 1.0}
    state = new_state("20260408")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="S",
        code="005930",
        cash_ratio=0.8,
        asof_date="20260408",
        now=datetime(2026, 4, 8, 9, 10),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 14
    assert result.sizing == {
        "cash_available_snapshot": 1_000_000,
        "sizing_cash": 900_000,
        "quote_price": 50_000.0,
        "sizing_price": 50_000.0,
        "budget_cash": 720_000,
        "max_qty": 14,
        "requested_qty": 14,
        "cash_ratio": 0.8,
        "order_type": "best",
    }

def test_enter_position_best_order_uses_quote_price_before_retrying_down() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "050890"
            assert order_type == "best"
            assert price == 17_430
            return {
                "ord_psbl_cash": 374_960,
                "nrcvb_buy_amt": 374_960,
                "nrcvb_buy_qty": 17,
                "max_buy_qty": 17,
                "psbl_qty_calc_unpr": 21_900,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if qty >= 11:
                return {"success": False, "msg": "주문가능금액을 초과 했습니다"}
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": self.quote(code).get("price", 0),
            }

    api = BuyableAPI()
    api._cash_available = 378_245
    api._quotes["050890"] = {"price": 17_430, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="050890",
        cash_ratio=1.0,
        budget_cash_cap=200_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 10
    assert api.order_calls == [
        {"side": "BUY", "code": "050890", "qty": 11, "order_type": "best", "price": None},
        {"side": "BUY", "code": "050890", "qty": 10, "order_type": "best", "price": None},
    ]
    assert result.sizing == {
        "cash_available_snapshot": 378_245,
        "sizing_cash": 374_960,
        "quote_price": 17_430.0,
        "sizing_price": 17_430.0,
        "budget_cash": 200_000,
        "max_qty": 17,
        "requested_qty": 10,
        "cash_ratio": 1.0,
        "order_type": "best",
    }

def test_enter_position_does_not_initially_cap_order_by_broker_max_qty() -> None:
    class BuyableAPI(FakeAPI):
        def buy_order_capacity(self, code: str, order_type: str, price: int | None) -> dict:
            assert code == "018880"
            assert order_type == "best"
            assert price == 4_265
            return {
                "ord_psbl_cash": 239_888,
                "nrcvb_buy_amt": 238_694,
                "nrcvb_buy_qty": 44,
                "max_buy_qty": 44,
                "psbl_qty_calc_unpr": 4_265,
            }

        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-{qty}",
                "filled_qty": qty,
                "avg_price": 4_225,
            }

    api = BuyableAPI()
    api._cash_available = 239_888
    api._quotes["018880"] = {"price": 4_265, "change_pct": 1.0}
    state = new_state("20260421")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="018880",
        cash_ratio=0.20,
        budget_cash_cap=214_728,
        asof_date="20260421",
        now=datetime(2026, 4, 21, 9, 16),
        order_type="best",
    )

    assert result is not None
    assert result.qty == 50
    assert api.order_calls == [
        {"side": "BUY", "code": "018880", "qty": 50, "order_type": "best", "price": None}
    ]
    assert result.sizing == {
        "cash_available_snapshot": 239_888,
        "sizing_cash": 238_694,
        "quote_price": 4_265.0,
        "sizing_price": 4_265.0,
        "budget_cash": 214_728,
        "max_qty": 44,
        "requested_qty": 50,
        "cash_ratio": 0.2,
        "order_type": "best",
    }

def test_enter_position_does_not_book_fill_from_order_acceptance_only() -> None:
    class PendingOnlyAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {"success": True, "order_id": f"{side}-{code}", "msg": "주문 접수"}

    api = PendingOnlyAPI()
    api._cash_available = 500_000
    api._quotes["005930"] = {"price": 100_000, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="S",
        code="005930",
        cash_ratio=0.5,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="MKT",
    )

    assert result is None
    assert "005930" not in state.open_positions
    assert state.swing_entries_today == 0

def test_enter_position_limit_order_retries_with_higher_price_after_rejection() -> None:
    class RetryPriceAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            if price == 10_010:
                return {"success": False, "order_id": "BUY-005930-1", "msg": "호가 부적합"}
            return {
                "success": True,
                "order_id": "BUY-005930-2",
                "filled_qty": qty,
                "avg_price": price,
            }

    api = RetryPriceAPI()
    api._cash_available = 500_000
    api._quotes["005930"] = {"price": 10_000, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="005930",
        cash_ratio=0.2,
        budget_cash_cap=200_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 9, 8),
        order_type="limit",
        price=10_010,
    )

    assert result is not None
    assert result.avg_price == 10_020
    assert api.order_calls == [
        {"side": "BUY", "code": "005930", "qty": 20, "order_type": "limit", "price": 10_010},
        {"side": "BUY", "code": "005930", "qty": 19, "order_type": "limit", "price": 10_020},
    ]

def test_enter_position_normalizes_invalid_limit_price_to_valid_tick() -> None:
    class NormalizePriceAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-1",
                "filled_qty": qty,
                "avg_price": price,
            }

    api = NormalizePriceAPI()
    api._cash_available = 500_000
    api._quotes["027360"] = {"price": 14_340, "change_pct": 1.0}
    state = new_state("20260415")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="027360",
        cash_ratio=0.2,
        budget_cash_cap=250_000,
        asof_date="20260415",
        now=datetime(2026, 4, 15, 13, 2),
        order_type="limit",
        price=14_345,
    )

    assert result is not None
    assert result.avg_price == 14_350
    assert api.order_calls == [
        {"side": "BUY", "code": "027360", "qty": 17, "order_type": "limit", "price": 14_350},
    ]

def test_enter_position_fills_missing_limit_price_from_quote() -> None:
    class MissingLimitPriceAPI(FakeAPI):
        def place_order(self, side: str, code: str, qty: int, order_type: str, price: int | None) -> dict:
            self.order_calls.append(
                {"side": side, "code": code, "qty": qty, "order_type": order_type, "price": price}
            )
            return {
                "success": True,
                "order_id": f"{side}-{code}-1",
                "filled_qty": qty,
                "avg_price": price,
            }

    api = MissingLimitPriceAPI()
    api._cash_available = 500_000
    api._quotes["100790"] = {"price": 60_250, "change_pct": 3.5}
    state = new_state("20260423")

    from backend.services.trading_engine.execution import enter_position

    result = enter_position(
        api,
        state,
        position_type="T",
        code="100790",
        cash_ratio=0.2,
        budget_cash_cap=250_000,
        asof_date="20260423",
        now=datetime(2026, 4, 23, 13, 4),
        order_type="limit",
        price=None,
    )

    assert result is not None
    assert result.avg_price == 60_300
    assert api.order_calls == [
        {"side": "BUY", "code": "100790", "qty": 4, "order_type": "limit", "price": 60_300},
    ]

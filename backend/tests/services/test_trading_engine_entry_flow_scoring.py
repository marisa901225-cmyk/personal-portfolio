from .trading_engine_support import *  # noqa: F401,F403

def test_rank_daytrade_codes_prefers_near_high_strength_over_faded_liquidity() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(
            [
                {
                    "code": "FADE01",
                    "name": "Fade Corp",
                    "avg_value_5d": 500_000_000_000,
                    "close": 101.0,
                    "change_pct": 1.0,
                    "is_etf": False,
                },
                {
                    "code": "LEAD01",
                    "name": "Leader Corp",
                    "avg_value_5d": 60_000_000_000,
                    "close": 106.0,
                    "change_pct": 3.0,
                    "is_etf": False,
                },
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["FADE01", "LEAD01"],
    )
    quotes = {
        "FADE01": {
            "price": 101.0,
            "open": 101.0,
            "high": 106.0,
            "low": 100.0,
            "change_pct": 1.0,
        },
        "LEAD01": {
            "price": 106.0,
            "open": 103.0,
            "high": 107.0,
            "low": 102.0,
            "change_pct": 3.0,
        },
    }

    ranked = rank_daytrade_codes(candidates, quotes, cfg)

    assert ranked[:2] == ["LEAD01", "FADE01"]

def test_pick_swing_prefers_sector_etf_on_theme_day() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": 1_800_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "000660",
                    "name": "SK하이닉스",
                    "avg_value_20d": 1_200_000_000_000,
                    "ma20": 95.0,
                    "ma60": 90.0,
                    "close": 103.0,
                    "change_pct": 3.2,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(
            [
                {
                    "code": "ETF001",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 2.8,
                    "is_etf": True,
                },
                {
                    "code": "ETF002",
                    "name": "TIGER 반도체TOP10",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 99.0,
                    "ma60": 94.0,
                    "close": 109.0,
                    "change_pct": 3.1,
                    "is_etf": True,
                }
            ]
        ),
        merged=pd.DataFrame(),
        quote_codes=["005930", "000660", "ETF001", "ETF002"],
    )
    quotes = {
        "005930": {"price": 110.0, "change_pct": 4.0},
        "000660": {"price": 103.0, "change_pct": 3.2},
        "ETF001": {"price": 108.0, "change_pct": 2.8},
        "ETF002": {"price": 109.0, "change_pct": 3.1},
    }
    news_signal = NewsSentimentSignal(
        market_score=0.3,
        sector_scores={"semiconductor": 0.75},
        sector_keywords={"semiconductor": ("반도체", "삼성전자", "sk하이닉스")},
        article_count=50,
    )

    picked = pick_swing(candidates, quotes, cfg, news_signal=news_signal)

    assert picked == "ETF001"

def test_pick_swing_keeps_stock_when_theme_breadth_is_not_met() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "005930",
                    "name": "삼성전자",
                    "avg_value_20d": 1_800_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 110.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(
            [
                {
                    "code": "ETF001",
                    "name": "KODEX 반도체",
                    "avg_value_20d": 700_000_000_000,
                    "ma20": 98.0,
                    "ma60": 93.0,
                    "close": 108.0,
                    "change_pct": 2.8,
                    "is_etf": True,
                }
            ]
        ),
        merged=pd.DataFrame(),
        quote_codes=["005930", "ETF001"],
    )
    quotes = {
        "005930": {"price": 110.0, "change_pct": 4.0},
        "ETF001": {"price": 108.0, "change_pct": 2.8},
    }
    news_signal = NewsSentimentSignal(
        market_score=0.3,
        sector_scores={"semiconductor": 0.75},
        sector_keywords={"semiconductor": ("반도체", "삼성전자", "sk하이닉스")},
        article_count=50,
    )

    picked = pick_swing(candidates, quotes, cfg, news_signal=news_signal)

    assert picked == "005930"

def test_pick_swing_prefers_stock_holding_near_high_over_faded_large_cap() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "FADE01",
                    "name": "Fade LargeCap",
                    "avg_value_20d": 900_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 108.0,
                    "change_pct": 4.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "LEAD01",
                    "name": "Leader LargeCap",
                    "avg_value_20d": 600_000_000_000,
                    "ma20": 100.0,
                    "ma60": 96.0,
                    "close": 109.0,
                    "change_pct": 3.5,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["FADE01", "LEAD01"],
    )
    quotes = {
        "FADE01": {
            "price": 108.0,
            "open": 112.0,
            "high": 116.0,
            "low": 107.0,
            "change_pct": 4.0,
        },
        "LEAD01": {
            "price": 109.0,
            "open": 106.0,
            "high": 110.0,
            "low": 105.0,
            "change_pct": 3.5,
        },
    }

    picked = pick_swing(candidates, quotes, cfg, news_signal=None)

    assert picked == "LEAD01"

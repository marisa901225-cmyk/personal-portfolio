from .trading_engine_support import *  # noqa: F401,F403
from backend.services.trading_engine.candidate_scoring import _score_day_row, _score_swing_row
from backend.services.trading_engine.global_market_signal import GlobalMarketSignal
from backend.services.trading_engine.global_market_signal import _filter_us_leadership_rows

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


def test_rank_daytrade_codes_penalizes_extreme_intraday_volatility() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(
            [
                {
                    "code": "WILD01",
                    "name": "Wild Corp",
                    "avg_value_5d": 150_000_000_000,
                    "close": 112.0,
                    "change_pct": 5.5,
                    "is_etf": False,
                },
                {
                    "code": "CALM01",
                    "name": "Calm Corp",
                    "avg_value_5d": 110_000_000_000,
                    "close": 108.0,
                    "change_pct": 4.5,
                    "is_etf": False,
                },
            ]
        ),
        model=pd.DataFrame(),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["WILD01", "CALM01"],
    )
    quotes = {
        "WILD01": {
            "price": 112.0,
            "open": 104.0,
            "high": 124.0,
            "low": 99.0,
            "change_pct": 5.5,
        },
        "CALM01": {
            "price": 108.0,
            "open": 105.0,
            "high": 109.0,
            "low": 104.0,
            "change_pct": 4.5,
        },
    }

    ranked = rank_daytrade_codes(candidates, quotes, cfg)

    assert ranked[:2] == ["CALM01", "WILD01"]


def test_pick_swing_penalizes_extreme_intraday_volatility() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    candidates = Candidates(
        asof="20260216",
        popular=pd.DataFrame(),
        model=pd.DataFrame(
            [
                {
                    "code": "WILD01",
                    "name": "Wild LargeCap",
                    "avg_value_20d": 850_000_000_000,
                    "ma20": 100.0,
                    "ma60": 94.0,
                    "close": 111.0,
                    "change_pct": 5.0,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
                {
                    "code": "CALM01",
                    "name": "Calm LargeCap",
                    "avg_value_20d": 780_000_000_000,
                    "ma20": 100.0,
                    "ma60": 95.0,
                    "close": 109.0,
                    "change_pct": 4.3,
                    "is_etf": False,
                    "trend_tier": "strict",
                },
            ]
        ),
        etf=pd.DataFrame(),
        merged=pd.DataFrame(),
        quote_codes=["WILD01", "CALM01"],
    )
    quotes = {
        "WILD01": {
            "price": 111.0,
            "open": 103.0,
            "high": 122.0,
            "low": 98.0,
            "change_pct": 5.0,
        },
        "CALM01": {
            "price": 109.0,
            "open": 106.0,
            "high": 110.0,
            "low": 105.0,
            "change_pct": 4.3,
        },
    }

    picked = pick_swing(candidates, quotes, cfg, news_signal=None)

    assert picked == "CALM01"


def test_swing_ma20_premium_penalty_is_gradual_near_threshold() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    row_79 = pd.Series(
        {
            "code": "NEAR79",
            "name": "Near Threshold 79",
            "avg_value_20d": 700_000_000_000,
            "ma20": 100.0,
            "ma60": 95.0,
            "close": 107.9,
            "change_pct": 4.0,
            "is_etf": False,
            "trend_tier": "strict",
            "source_model": True,
        }
    )
    row_81 = pd.Series(
        {
            "code": "NEAR81",
            "name": "Near Threshold 81",
            "avg_value_20d": 700_000_000_000,
            "ma20": 100.0,
            "ma60": 95.0,
            "close": 108.1,
            "change_pct": 4.0,
            "is_etf": False,
            "trend_tier": "strict",
            "source_model": True,
        }
    )
    quotes = {
        "NEAR79": {"price": 107.9, "open": 105.0, "high": 108.2, "low": 104.8, "change_pct": 4.0},
        "NEAR81": {"price": 108.1, "open": 105.2, "high": 108.4, "low": 105.0, "change_pct": 4.0},
    }

    score_79 = _score_swing_row(row_79, quotes, cfg, news_signal=None)
    score_81 = _score_swing_row(row_81, quotes, cfg, news_signal=None)

    assert score_79 > score_81
    assert (score_79 - score_81) < 2.0


def test_swing_location_ratio_needs_volume_confirmation() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    row_low_volume = pd.Series(
        {
            "code": "LIGHT01",
            "name": "Light Volume",
            "avg_value_20d": 100_000_000_000,
            "ma20": 100.0,
            "ma60": 95.0,
            "close": 109.0,
            "change_pct": 4.0,
            "is_etf": False,
            "trend_tier": "strict",
            "source_model": True,
        }
    )
    row_heavy_volume = pd.Series(
        {
            "code": "HEAVY01",
            "name": "Heavy Volume",
            "avg_value_20d": 100_000_000_000,
            "ma20": 100.0,
            "ma60": 95.0,
            "close": 109.0,
            "change_pct": 4.0,
            "is_etf": False,
            "trend_tier": "strict",
            "source_model": True,
        }
    )
    quotes = {
        "LIGHT01": {
            "price": 109.0,
            "open": 104.0,
            "high": 110.0,
            "low": 103.0,
            "change_pct": 4.0,
            "volume": 200_000,
        },
        "HEAVY01": {
            "price": 109.0,
            "open": 104.0,
            "high": 110.0,
            "low": 103.0,
            "change_pct": 4.0,
            "volume": 1_600_000,
        },
    }

    light_score = _score_swing_row(row_low_volume, quotes, cfg, news_signal=None)
    heavy_score = _score_swing_row(row_heavy_volume, quotes, cfg, news_signal=None)

    assert heavy_score > light_score


def test_day_negative_penalty_uses_ratio_cap_by_default() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    row_small_drop = pd.Series(
        {
            "code": "DROP01",
            "name": "Drop 1",
            "_avg_value_5d_num": 80_000_000_000,
            "avg_value_5d": 80_000_000_000,
            "change_pct": -1.0,
            "is_etf": False,
        }
    )
    row_large_drop = pd.Series(
        {
            "code": "DROP10",
            "name": "Drop 10",
            "_avg_value_5d_num": 80_000_000_000,
            "avg_value_5d": 80_000_000_000,
            "change_pct": -10.0,
            "is_etf": False,
        }
    )

    score_small_drop = _score_day_row(row_small_drop, quotes={}, config=cfg, news_signal=None)
    score_large_drop = _score_day_row(row_large_drop, quotes={}, config=cfg, news_signal=None)

    assert score_small_drop == 32.8
    assert round(score_large_drop, 1) == 5.8


def test_day_negative_penalty_can_be_tuned_by_full_pct() -> None:
    cfg = TradeEngineConfig(
        use_news_sentiment=False,
        day_negative_penalty_per_pct=999.0,
        day_negative_penalty_max=30.0,
        day_negative_penalty_full_pct=20.0,
    )
    row = pd.Series(
        {
            "code": "DROP10",
            "name": "Drop 10",
            "_avg_value_5d_num": 80_000_000_000,
            "avg_value_5d": 80_000_000_000,
            "change_pct": -10.0,
            "is_etf": False,
        }
    )

    score = _score_day_row(row, quotes={}, config=cfg, news_signal=None)

    assert round(score, 1) == 20.8


def test_day_positive_momentum_relies_more_on_intraday_structure_than_raw_change_pct() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    row = pd.Series(
        {
            "code": "MOMO1",
            "name": "Momentum One",
            "_avg_value_5d_num": 80_000_000_000,
            "avg_value_5d": 80_000_000_000,
            "change_pct": 6.0,
            "is_etf": False,
        }
    )
    strong_quotes = {
        "MOMO1": {
            "price": 106.0,
            "open": 102.0,
            "high": 106.2,
            "low": 101.8,
            "change_pct": 6.0,
        }
    }
    weak_quotes = {
        "MOMO1": {
            "price": 106.0,
            "open": 109.0,
            "high": 111.0,
            "low": 100.0,
            "change_pct": 6.0,
        }
    }

    strong_score = _score_day_row(row, quotes=strong_quotes, config=cfg, news_signal=None)
    weak_score = _score_day_row(row, quotes=weak_quotes, config=cfg, news_signal=None)

    assert strong_score > weak_score


def test_day_etf_score_emphasizes_structure_and_sector_news_over_raw_momentum() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=True)
    row = pd.Series(
        {
            "code": "ETFSEM",
            "name": "KODEX 반도체",
            "_avg_value_5d_num": 90_000_000_000,
            "avg_value_5d": 90_000_000_000,
            "change_pct": 4.0,
            "is_etf": True,
            "sector_bucket_selected": True,
            "theme_sector": "semiconductor",
            "industry_bucket_name": "semiconductor",
            "industry_close": 104.0,
            "industry_ma5": 101.0,
            "industry_ma20": 99.0,
            "industry_day_change_pct": 1.8,
            "industry_5d_change_pct": 4.5,
        }
    )
    news_signal = NewsSentimentSignal(
        market_score=0.4,
        sector_scores={"semiconductor": 0.8},
        sector_keywords={"semiconductor": ("반도체", "삼성전자")},
        article_count=40,
    )
    strong_quotes = {
        "ETFSEM": {
            "price": 104.0,
            "open": 102.0,
            "high": 104.2,
            "low": 101.7,
            "change_pct": 4.0,
        }
    }
    weak_quotes = {
        "ETFSEM": {
            "price": 104.0,
            "open": 106.5,
            "high": 108.0,
            "low": 99.5,
            "change_pct": 4.0,
        }
    }

    strong_score = _score_day_row(row, quotes=strong_quotes, config=cfg, news_signal=news_signal)
    weak_score = _score_day_row(row, quotes=weak_quotes, config=cfg, news_signal=news_signal)

    assert strong_score > weak_score + 10.0


def test_global_market_signal_boosts_semiconductor_and_penalizes_bio() -> None:
    cfg = TradeEngineConfig(use_news_sentiment=False)
    signal = GlobalMarketSignal(
        asof_date="20260430",
        market_score=-0.2,
        sector_scores={"semiconductor": 0.8, "bio_healthcare": -0.9},
        sector_high_counts={"semiconductor": 5},
        sector_low_counts={"bio_healthcare": 6},
        high_count=8,
        low_count=12,
    )
    semi_row = pd.Series(
        {
            "code": "SEMI1",
            "name": "반도체장비주",
            "_avg_value_5d_num": 80_000_000_000,
            "avg_value_5d": 80_000_000_000,
            "change_pct": 3.0,
            "is_etf": False,
            "theme_sector": "semiconductor",
        }
    )
    bio_row = pd.Series(
        {
            "code": "BIO1",
            "name": "바이오주",
            "_avg_value_5d_num": 80_000_000_000,
            "avg_value_5d": 80_000_000_000,
            "change_pct": 3.0,
            "is_etf": False,
            "theme_sector": "bio_healthcare",
        }
    )

    semi_score = _score_day_row(semi_row, quotes={}, config=cfg, news_signal=None, global_signal=signal)
    bio_score = _score_day_row(bio_row, quotes={}, config=cfg, news_signal=None, global_signal=signal)

    assert semi_score > bio_score + 8.0


def test_global_market_signal_filters_out_leveraged_and_low_quality_us_rows() -> None:
    cfg = TradeEngineConfig()
    rows = [
        {
            "symbol": "NVDA",
            "name": "엔비디아",
            "ename": "NVIDIA CORP",
            "price": 123.45,
            "change_pct": 3.2,
            "volume": 12_000_000,
            "tradable": "Y",
        },
        {
            "symbol": "BEX",
            "name": "TRADR BE DAILY 2X",
            "ename": "TRADR BE DAILY 2X",
            "price": 22.0,
            "change_pct": 18.0,
            "volume": 1_500_000,
            "tradable": "Y",
        },
        {
            "symbol": "WARR1",
            "name": "Sample Call Warrant",
            "ename": "Sample Call Warrant",
            "price": 9.0,
            "change_pct": 6.0,
            "volume": 900_000,
            "tradable": "Y",
        },
        {
            "symbol": "PENNY",
            "name": "Penny Semi",
            "ename": "Penny Semi",
            "price": 1.5,
            "change_pct": 5.0,
            "volume": 2_000_000,
            "tradable": "Y",
        },
    ]

    filtered = _filter_us_leadership_rows(rows, config=cfg, high_low_type="1")

    assert [row["symbol"] for row in filtered] == ["NVDA"]

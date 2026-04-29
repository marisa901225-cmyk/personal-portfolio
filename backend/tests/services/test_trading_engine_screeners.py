from .trading_engine_support import *  # noqa: F401,F403

@patch("backend.services.trading_engine.screeners.load_stock_master_map")
def test_popular_screener_attaches_master_market(mock_load_stock_master_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
    ]
    api._bars[("000001", asof)] = _make_bars(asof, 10, 100, 1, value=20_000_000_000)
    mock_load_stock_master_map.return_value = {
        "000001": StockMasterInfo(
            code="000001",
            name="Alpha",
            market="KOSPI",
            master_market_cap=1_000_000_000_000,
            listed_shares=1_000_000,
            base_price=1000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        )
    }

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        ),
    )

    assert not out.empty
    assert out.iloc[0]["master_market"] == "KOSPI"

def test_popular_screener_intersection_and_proxy() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
        {"code": "000002", "name": "Beta", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
        {"code": "000003", "name": "Gamma", "rank": 2},
    ]
    api._bars[("000001", asof)] = _make_bars(asof, 10, 100, 1, value=None)  # proxy path
    api._bars[("000002", asof)] = _make_bars(asof, 10, 90, 0, value=20_000_000_000)
    api._bars[("000003", asof)] = _make_bars(asof, 10, 80, 0, value=10_000_000_000)

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        ),
    )

    assert not out.empty
    assert "000001" in set(out["code"])
    row = out[out["code"] == "000001"].iloc[0]
    assert bool(row["used_value_proxy"]) is True
    assert int(row["value_rank"]) == 1
    assert row["hts_view_rank"] is None

def test_popular_screener_attaches_hts_view_rank_without_expanding_candidate_universe() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 3},
    ]
    api._hts_top_view_rank[asof] = [
        {"code": "000001", "name": "Alpha", "rank": 2},
        {"code": "999999", "name": "OutsideOnly", "rank": 1},
    ]
    api._bars[("000001", asof)] = _make_bars(asof, 10, 100, 1, value=20_000_000_000)

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
            day_hts_top_view_top_n=20,
        ),
    )

    assert list(out["code"]) == ["000001"]
    assert int(out.iloc[0]["hts_view_rank"]) == 2

def test_popular_screener_prefers_current_value_rank_over_avg5_when_compressing_candidates() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "HOT001", "name": "핫종목", "rank": 1},
        {"code": "OLD001", "name": "구형대금주", "rank": 30},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "HOT001", "name": "핫종목", "rank": 1},
        {"code": "OLD001", "name": "구형대금주", "rank": 120},
    ]
    api._bars[("HOT001", asof)] = _make_bars(asof, 10, 100, 1, value=40_000_000_000)
    api._bars[("OLD001", asof)] = _make_bars(asof, 10, 100, 1, value=120_000_000_000)

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=1,
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        ),
    )

    assert list(out["code"]) == ["HOT001"]
    row = out.iloc[0]
    assert int(row["value_rank"]) == 1

def test_popular_screener_exposes_breakout_vs_previous_10d_high_for_prompting() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "000001", "name": "Alpha", "rank": 1},
    ]
    api._bars[("000001", asof)] = _make_bars_from_closes(
        asof,
        [100, 101, 102, 103, 104, 105, 106, 107, 108, 110],
        value=20_000_000_000,
    )

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            day_stock_min_avg_value_5d=0,
            day_stock_min_mcap=0,
        ),
    )

    assert not out.empty
    row = out.iloc[0]
    assert round(float(row["retrace_from_high_10d_pct"]), 4) == 0.0
    assert round(float(row["breakout_vs_prev_high_10d_pct"]), 4) == round((110 / 108 - 1.0) * 100.0, 4)

@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
def test_model_screener_filters_etf_and_applies_ma_chain(mock_load_universe) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_universe.return_value = [
        {"code": "111111", "name": "GoodStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "222222", "name": "KODEX ETF", "mcap": 3_000_000_000_000, "is_etf": True},
    ]
    api._bars[("111111", asof)] = _make_bars(asof, 140, 100, 1, value=700_000_000_000)
    api._bars[("222222", asof)] = _make_bars(asof, 140, 100, 1, value=900_000_000_000)

    out = model_screener(api, asof=asof)

    assert not out.empty
    assert set(out["code"]) == {"111111"}

@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
def test_model_screener_allows_relaxed_large_cap_from_master_universe(mock_load_universe) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_universe.return_value = [
        {"code": "333333", "name": "LargeCapNoMetric", "mcap": 1_200_000_000_000, "is_etf": False},
    ]
    api._bars[("333333", asof)] = _make_bars(asof, 100, 100, 1, value=900_000_000_000)

    out = model_screener(api, asof=asof)

    assert not out.empty
    row = out[out["code"] == "333333"].iloc[0]
    assert row["trend_tier"] == "relaxed"

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
def test_model_screener_enriches_industry_index_trend_fields(
    mock_load_universe,
    mock_load_industry_map,
) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_universe.return_value = [
        {"code": "111111", "name": "GoodStock", "mcap": 2_000_000_000_000, "is_etf": False},
    ]
    api._bars[("111111", asof)] = _make_bars(asof, 140, 100, 1, value=700_000_000_000)
    api._index_bars[("2250", asof)] = _make_bars(asof, 60, 800, 3)
    mock_load_industry_map.return_value = {
        "111111": StockIndustryInfo(
            code="111111",
            name="GoodStock",
            market="KOSDAQ",
            large_code="1014",
            large_name="금융",
            medium_code="2240",
            medium_name="창업투자",
            small_code="2250",
            small_name="창업투자",
        )
    }

    out = model_screener(api, asof=asof)

    assert len(out) == 1
    row = out.iloc[0]
    assert row["industry_bucket_code"] == "2250"
    assert row["industry_bucket_name"] == "창업투자"
    assert float(row["industry_5d_change_pct"]) > 0
    assert float(row["industry_ma20"]) > 0

@patch("backend.services.trading_engine.screeners.load_swing_universe_candidates")
@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_model_screener_filters_live_management_warning_risk_candidates(
    mock_load_industry_map,
    mock_load_universe,
) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}
    mock_load_universe.return_value = [
        {"code": "OK001", "name": "GoodStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "WARN01", "name": "WarnStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "RISK01", "name": "RiskStock", "mcap": 2_000_000_000_000, "is_etf": False},
        {"code": "MGMT01", "name": "MgmtStock", "mcap": 2_000_000_000_000, "is_etf": False},
    ]
    for code in ("OK001", "WARN01", "RISK01", "MGMT01"):
        api._bars[(code, asof)] = _make_bars(asof, 140, 100, 1, value=150_000_000_000)
    api._quotes.update(
        {
            "OK001": {"market_warning_code": "00", "management_issue_code": "N"},
            "WARN01": {"market_warning_code": "02", "management_issue_code": "N"},
            "RISK01": {"market_warning_code": "03", "management_issue_code": "N"},
            "MGMT01": {"market_warning_code": "00", "management_issue_code": "Y"},
        }
    )

    out = model_screener(api, asof=asof)

    assert list(out["code"]) == ["OK001"]

@patch("backend.services.trading_engine.stock_master.load_stock_master_map")
def test_load_swing_universe_candidates_prefers_index_members_and_near_cutoff_large_caps(
    mock_load_stock_master_map,
) -> None:
    mock_load_stock_master_map.return_value = {
        "AAA111": StockMasterInfo(
            code="AAA111",
            name="KOSPI200 Member",
            market="KOSPI",
            master_market_cap=2_000_000_000_000,
            listed_shares=10_000_000,
            base_price=200_000,
            is_etf=False,
            is_kospi200=True,
            is_kosdaq150=False,
        ),
        "BBB222": StockMasterInfo(
            code="BBB222",
            name="Near KOSPI Cutoff",
            market="KOSPI",
            master_market_cap=1_050_000_000_000,
            listed_shares=10_000_000,
            base_price=105_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
        "CCC333": StockMasterInfo(
            code="CCC333",
            name="KOSDAQ150 Member",
            market="KOSDAQ",
            master_market_cap=650_000_000_000,
            listed_shares=10_000_000,
            base_price=65_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=True,
        ),
        "DDD444": StockMasterInfo(
            code="DDD444",
            name="Near KOSDAQ Cutoff",
            market="KOSDAQ",
            master_market_cap=590_000_000_000,
            listed_shares=10_000_000,
            base_price=59_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
        "EEE555": StockMasterInfo(
            code="EEE555",
            name="Too Small",
            market="KOSDAQ",
            master_market_cap=300_000_000_000,
            listed_shares=10_000_000,
            base_price=30_000,
            is_etf=False,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
        "ETF999": StockMasterInfo(
            code="ETF999",
            name="KODEX ETF",
            market="KOSPI",
            master_market_cap=2_500_000_000_000,
            listed_shares=10_000_000,
            base_price=250_000,
            is_etf=True,
            is_kospi200=False,
            is_kosdaq150=False,
        ),
    }
    cfg = TradeEngineConfig(model_top_k=10, model_mcap_min=1_000_000_000_000)

    rows = load_swing_universe_candidates(cfg)
    codes = [str(row["code"]) for row in rows]

    assert codes[:4] == ["AAA111", "CCC333", "BBB222", "DDD444"]
    assert "EEE555" not in codes
    assert "ETF999" not in codes

def test_etf_swing_screener_excludes_broad_market_index_etfs() -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "379800", "name": "KODEX 미국S&P500", "rank": 1, "is_etf": True},
        {"code": "091230", "name": "TIGER 반도체", "rank": 2, "is_etf": True},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "379800", "name": "KODEX 미국S&P500", "rank": 1, "is_etf": True},
        {"code": "091230", "name": "TIGER 반도체", "rank": 2, "is_etf": True},
    ]
    api._bars[("379800", asof)] = _make_bars(asof, 80, 100, 0.5, value=200_000_000_000)
    api._bars[("091230", asof)] = _make_bars(asof, 80, 90, 0.6, value=250_000_000_000)

    out = etf_swing_screener(api, asof=asof)

    assert not out.empty
    assert "379800" not in set(out["code"])
    assert "091230" in set(out["code"])

def test_popular_screener_injects_theme_candidate_from_strong_news_sector() -> None:
    asof = "20260213"
    api = FakeAPI()

    base_rows = []
    for idx in range(10):
        code = f"{100001 + idx:06d}"
        base_rows.append({"code": code, "name": f"일반주{idx + 1}", "rank": idx + 1})
        api._bars[(code, asof)] = _make_bars(asof, 10, 100, 0, value=100_000_000_000 - (idx * 5_000_000_000))

    theme_code = "777777"
    themed = {"code": theme_code, "name": "한싹", "rank": 11}
    api._bars[(theme_code, asof)] = _make_bars(asof, 10, 90, 0, value=35_000_000_000)

    api._volume_rank[("volume", asof)] = [*base_rows, themed]
    api._volume_rank[("value", asof)] = [*base_rows, themed]

    cfg = TradeEngineConfig(
        popular_sector_top_n=0,
        popular_final_top_n=10,
        day_theme_candidate_injection_enabled=True,
        day_theme_candidate_max_injections=2,
        day_theme_candidate_min_sector_score=0.4,
        day_theme_candidate_min_avg_value_5d=30_000_000_000,
    )
    news_signal = NewsSentimentSignal(
        market_score=0.2,
        sector_scores={"cyber_security": 0.8},
        sector_keywords={"cyber_security": ("한싹", "보안")},
        article_count=30,
    )

    out = popular_screener(api, asof=asof, include_etf=False, config=cfg, news_signal=news_signal)

    assert len(out) == 11
    assert theme_code in set(out["code"])
    theme_row = out[out["code"] == theme_code].iloc[0]
    assert bool(theme_row["theme_injected"]) is True
    assert theme_row["theme_sector"] == "cyber_security"

def test_popular_screener_does_not_inject_theme_candidate_when_sector_score_is_weak() -> None:
    asof = "20260213"
    api = FakeAPI()

    base_rows = []
    for idx in range(10):
        code = f"{200001 + idx:06d}"
        base_rows.append({"code": code, "name": f"일반주{idx + 1}", "rank": idx + 1})
        api._bars[(code, asof)] = _make_bars(asof, 10, 100, 0, value=100_000_000_000 - (idx * 5_000_000_000))

    theme_code = "888888"
    themed = {"code": theme_code, "name": "드림시큐리티", "rank": 11}
    api._bars[(theme_code, asof)] = _make_bars(asof, 10, 90, 0, value=35_000_000_000)

    api._volume_rank[("volume", asof)] = [*base_rows, themed]
    api._volume_rank[("value", asof)] = [*base_rows, themed]

    cfg = TradeEngineConfig(
        popular_sector_top_n=0,
        popular_final_top_n=10,
        day_theme_candidate_injection_enabled=True,
        day_theme_candidate_max_injections=2,
        day_theme_candidate_min_sector_score=0.4,
        day_theme_candidate_min_avg_value_5d=30_000_000_000,
    )
    news_signal = NewsSentimentSignal(
        market_score=0.2,
        sector_scores={"cyber_security": 0.25},
        sector_keywords={"cyber_security": ("드림시큐리티", "보안")},
        article_count=30,
    )

    out = popular_screener(api, asof=asof, include_etf=False, config=cfg, news_signal=news_signal)

    assert len(out) == 10
    assert theme_code not in set(out["code"])

def test_popular_screener_keeps_sector_bucket_and_legacy_top10_together() -> None:
    asof = "20260213"
    api = FakeAPI()

    legacy_rows = []
    for idx in range(10):
        code = f"{300001 + idx:06d}"
        legacy_rows.append({"code": code, "name": f"일반주{idx + 1}", "rank": idx + 1})
        api._bars[(code, asof)] = _make_bars(
            asof,
            10,
            100,
            0,
            value=120_000_000_000 - (idx * 5_000_000_000),
        )

    sector_rows = [
        {"code": "399991", "name": "창투에이스", "rank": 11},
        {"code": "399992", "name": "태양광리더", "rank": 12},
    ]
    api._bars[("399991", asof)] = _make_bars(asof, 10, 90, 0, value=45_000_000_000)
    api._bars[("399992", asof)] = _make_bars(asof, 10, 85, 0, value=42_000_000_000)

    api._volume_rank[("volume", asof)] = [*legacy_rows, *sector_rows]
    api._volume_rank[("value", asof)] = [*legacy_rows, *sector_rows]

    cfg = TradeEngineConfig(
        popular_sector_top_n=1,
        popular_final_top_n=10,
    )
    news_signal = NewsSentimentSignal(
        market_score=0.1,
        sector_scores={
            "venture_capital": 0.8,
            "solar": 0.7,
        },
        sector_keywords={
            "venture_capital": ("창투",),
            "solar": ("태양광",),
        },
        article_count=12,
    )

    out = popular_screener(api, asof=asof, include_etf=False, config=cfg, news_signal=news_signal)

    assert "399991" in set(out["code"])
    assert "399992" in set(out["code"])
    assert bool(out[out["code"] == "399991"].iloc[0]["sector_bucket_selected"]) is True
    assert bool(out[out["code"] == "399991"].iloc[0]["legacy_top10_selected"]) is False
    assert bool(out[out["code"] == "300001"].iloc[0]["legacy_top10_selected"]) is True

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_uses_db_industry_bucket_when_available(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()

    api._volume_rank[("volume", asof)] = [
        {"code": "410001", "name": "AlphaOne", "rank": 1},
        {"code": "410002", "name": "BetaTwo", "rank": 2},
        {"code": "410003", "name": "GammaThree", "rank": 3},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "410001", "name": "AlphaOne", "rank": 1},
        {"code": "410002", "name": "BetaTwo", "rank": 2},
        {"code": "410003", "name": "GammaThree", "rank": 3},
    ]
    api._bars[("410001", asof)] = _make_bars(asof, 10, 100, 0, value=90_000_000_000)
    api._bars[("410002", asof)] = _make_bars(asof, 10, 90, 0, value=60_000_000_000)
    api._bars[("410003", asof)] = _make_bars(asof, 10, 80, 0, value=50_000_000_000)

    mock_load_industry_map.return_value = {
        "410001": StockIndustryInfo(
            code="410001",
            name="AlphaOne",
            market="KOSDAQ",
            large_code="0027",
            large_name="제조",
            medium_code="0013",
            medium_name="전기·전자",
            small_code=None,
            small_name=None,
        ),
        "410002": StockIndustryInfo(
            code="410002",
            name="BetaTwo",
            market="KOSDAQ",
            large_code="1014",
            large_name="금융",
            medium_code=None,
            medium_name=None,
            small_code=None,
            small_name=None,
        ),
        "410003": StockIndustryInfo(
            code="410003",
            name="GammaThree",
            market="KOSDAQ",
            large_code="0027",
            large_name="제조",
            medium_code="0013",
            medium_name="전기·전자",
            small_code=None,
            small_name=None,
        ),
    }

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=1,
            popular_final_top_n=1,
        ),
    )

    assert "410001" in set(out["code"])
    assert "410002" in set(out["code"])
    assert bool(out[out["code"] == "410002"].iloc[0]["sector_bucket_selected"]) is True
    assert out[out["code"] == "410002"].iloc[0]["industry_bucket_name"] == "금융"


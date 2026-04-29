from .trading_engine_support import *  # noqa: F401,F403

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_enriches_industry_index_trend_fields(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    api._volume_rank[("volume", asof)] = [
        {"code": "410010", "name": "VentureAlpha", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = list(api._volume_rank[("volume", asof)])
    api._bars[("410010", asof)] = _make_bars(asof, 10, 100, 1, value=90_000_000_000)
    api._index_bars[("2250", asof)] = _make_bars(asof, 30, 800, 4)

    mock_load_industry_map.return_value = {
        "410010": StockIndustryInfo(
            code="410010",
            name="VentureAlpha",
            market="KOSDAQ",
            large_code="1014",
            large_name="금융",
            medium_code="2240",
            medium_name="창업투자",
            small_code="2250",
            small_name="창업투자",
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

    assert len(out) == 1
    row = out.iloc[0]
    assert row["industry_bucket_code"] == "2250"
    assert row["industry_bucket_name"] == "창업투자"
    assert float(row["industry_day_change_pct"]) > 0
    assert float(row["industry_ma20"]) > 0

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_applies_default_day_stock_liquidity_floor(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}

    api._volume_rank[("volume", asof)] = [
        {"code": "431001", "name": "BelowFloor", "rank": 1},
        {"code": "431002", "name": "AboveFloor", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "431001", "name": "BelowFloor", "rank": 1},
        {"code": "431002", "name": "AboveFloor", "rank": 2},
    ]
    api._bars[("431001", asof)] = _make_bars(asof, 10, 100, 0, value=9_000_000_000)
    api._bars[("431002", asof)] = _make_bars(asof, 10, 100, 0, value=12_000_000_000)
    api._quotes["431001"] = {"price": 10000, "change_pct": 2.0, "market_cap": 1_200_000_000_000}
    api._quotes["431002"] = {"price": 10000, "change_pct": 2.0, "market_cap": 1_200_000_000_000}

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=10,
        ),
    )

    assert "431001" not in set(out["code"])
    assert "431002" in set(out["code"])

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_filters_small_stock_by_mcap_floor(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}

    api._volume_rank[("volume", asof)] = [
        {"code": "430001", "name": "SmallCap", "rank": 1},
        {"code": "430002", "name": "LargeCap", "rank": 2},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "430001", "name": "SmallCap", "rank": 1},
        {"code": "430002", "name": "LargeCap", "rank": 2},
    ]
    api._bars[("430001", asof)] = _make_bars(asof, 10, 100, 0, value=60_000_000_000)
    api._bars[("430002", asof)] = _make_bars(asof, 10, 100, 0, value=60_000_000_000)
    api._quotes["430001"] = {"price": 10000, "change_pct": 2.0, "market_cap": 400_000_000_000}
    api._quotes["430002"] = {"price": 10000, "change_pct": 2.0, "market_cap": 1_200_000_000_000}

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=10,
            day_stock_min_avg_value_5d=30_000_000_000,
            day_stock_min_mcap=1_000_000_000_000,
        ),
    )

    assert "430001" not in set(out["code"])
    assert "430002" in set(out["code"])

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_filters_live_management_warning_risk_candidates(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()
    mock_load_industry_map.return_value = {}

    api._volume_rank[("volume", asof)] = [
        {"code": "440001", "name": "관리종목", "rank": 1},
        {"code": "440002", "name": "투경종목", "rank": 2},
        {"code": "440003", "name": "투위험종목", "rank": 3},
        {"code": "440004", "name": "정상종목", "rank": 4},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "440001", "name": "관리종목", "rank": 1},
        {"code": "440002", "name": "투경종목", "rank": 2},
        {"code": "440003", "name": "투위험종목", "rank": 3},
        {"code": "440004", "name": "정상종목", "rank": 4},
    ]
    for code in ("440001", "440002", "440003", "440004"):
        api._bars[(code, asof)] = _make_bars(asof, 10, 100, 0, value=60_000_000_000)

    api._quotes["440001"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "Y",
        "market_warning_code": "00",
    }
    api._quotes["440002"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "N",
        "market_warning_code": "02",
    }
    api._quotes["440003"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "N",
        "market_warning_code": "03",
    }
    api._quotes["440004"] = {
        "price": 10_000,
        "change_pct": 2.0,
        "market_cap": 1_200_000_000_000,
        "management_issue_code": "N",
        "market_warning_code": "00",
    }

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(
            popular_sector_top_n=0,
            popular_final_top_n=10,
            day_stock_min_avg_value_5d=30_000_000_000,
            day_stock_min_mcap=1_000_000_000_000,
        ),
    )

    assert set(out["code"]) == {"440004"}

@patch("backend.services.trading_engine.screeners.load_stock_industry_db_map")
def test_popular_screener_does_not_stringify_missing_industry_bucket(mock_load_industry_map) -> None:
    asof = "20260213"
    api = FakeAPI()

    api._volume_rank[("volume", asof)] = [
        {"code": "420001", "name": "드림시큐리티", "rank": 1},
    ]
    api._volume_rank[("value", asof)] = [
        {"code": "420001", "name": "드림시큐리티", "rank": 1},
    ]
    api._bars[("420001", asof)] = _make_bars(asof, 10, 100, 0, value=55_000_000_000)
    mock_load_industry_map.return_value = {}

    news_signal = NewsSentimentSignal(
        market_score=0.1,
        sector_scores={"cyber_security": 0.8},
        sector_keywords={"cyber_security": ("드림시큐리티", "보안")},
        article_count=8,
    )

    out = popular_screener(
        api,
        asof=asof,
        include_etf=False,
        config=TradeEngineConfig(popular_sector_top_n=1, popular_final_top_n=0),
        news_signal=news_signal,
    )

    row = out[out["code"] == "420001"].iloc[0]
    assert row["industry_bucket_name"] == "cyber_security"

def test_resolve_stock_industry_info_parses_master_zips(tmp_path) -> None:
    idx_zip = tmp_path / "idxcode.mst.zip"
    kospi_zip = tmp_path / "kospi_code.mst.zip"
    kosdaq_zip = tmp_path / "kosdaq_code.mst.zip"

    _write_idx_master_zip(
        idx_zip,
        {
            "0027": "제조",
            "0013": "전기·전자",
            "1014": "금융",
        },
    )
    _write_stock_master_zip(
        kospi_zip,
        member_name="kospi_code.mst",
        tail_width=227,
        rows=[
            ("005930", "삼성전자", "0027", "0013", "0000"),
        ],
    )
    _write_stock_master_zip(
        kosdaq_zip,
        member_name="kosdaq_code.mst",
        tail_width=221,
        rows=[
            ("027360", "아주IB투자", "1014", "0000", "0000"),
        ],
    )

    samsung = resolve_stock_industry_info(
        "005930",
        idxcode_path=str(idx_zip),
        kospi_master_path=str(kospi_zip),
        kosdaq_master_path=str(kosdaq_zip),
    )
    venture = resolve_stock_industry_info(
        "027360",
        idxcode_path=str(idx_zip),
        kospi_master_path=str(kospi_zip),
        kosdaq_master_path=str(kosdaq_zip),
    )

    assert samsung is not None
    assert samsung.market == "KOSPI"
    assert samsung.large_name == "제조"
    assert samsung.medium_name == "전기·전자"
    assert samsung.bucket_name == "전기·전자"
    assert venture is not None
    assert venture.market == "KOSDAQ"
    assert venture.large_name == "금융"
    assert venture.bucket_name == "금융"

def test_load_stock_industry_db_map_syncs_from_master_zips(tmp_path) -> None:
    idx_zip = tmp_path / "idxcode.mst.zip"
    kospi_zip = tmp_path / "kospi_code.mst.zip"
    kosdaq_zip = tmp_path / "kosdaq_code.mst.zip"

    _write_idx_master_zip(
        idx_zip,
        {
            "0027": "제조",
            "0013": "전기·전자",
        },
    )
    _write_stock_master_zip(
        kospi_zip,
        member_name="kospi_code.mst",
        tail_width=227,
        rows=[
            ("005930", "삼성전자", "0027", "0013", "0000"),
        ],
    )
    _write_stock_master_zip(
        kosdaq_zip,
        member_name="kosdaq_code.mst",
        tail_width=221,
        rows=[
            ("011930", "신성이엔지", "0027", "0013", "0000"),
        ],
    )

    test_engine = create_engine("sqlite:///:memory:", future=True)
    TestSessionLocal = sessionmaker(bind=test_engine, autoflush=False, autocommit=False, future=True)

    with (
        patch("backend.services.trading_engine.industry_master.engine", test_engine),
        patch("backend.services.trading_engine.industry_master.SessionLocal", TestSessionLocal),
    ):
        industry_map = load_stock_industry_db_map(
            idxcode_path=str(idx_zip),
            kospi_master_path=str(kospi_zip),
            kosdaq_master_path=str(kosdaq_zip),
        )

        assert "005930" in industry_map
        assert "011930" in industry_map
        assert industry_map["011930"].bucket_name == "전기·전자"

        with TestSessionLocal() as db:
            sync_state = db.get(TradingEngineIndustrySyncState, "stock_master")
            rows = db.execute(select(TradingEngineStockIndustry)).scalars().all()

        assert sync_state is not None
        assert sync_state.row_count == 2
        assert {row.code for row in rows} == {"005930", "011930"}

def test_market_calendar_fallback_uses_proxy_etf_bars() -> None:
    api = FakeAPI()
    api._bars[("069500", "20260214")] = pd.DataFrame(
        [
            {"date": "20260212", "close": 100, "volume": 1},
            {"date": "20260213", "close": 101, "volume": 1},
        ]
    )
    api._bars[("069500", "20260213")] = pd.DataFrame(
        [
            {"date": "20260213", "close": 101, "volume": 1},
        ]
    )

    assert is_trading_day(api, "20260214") is False
    assert get_last_trading_day(api, "20260214") == "20260213"

from __future__ import annotations

from dataclasses import dataclass
import re
import threading

from .config import TradeEngineConfig
from .news_sentiment import NewsSentimentSignal, _load_sector_keywords
from .utils import match_name_to_sectors

_DEFAULT_US_EXCHANGES: tuple[str, ...] = ("NAS", "NYS", "AMS")
_GLOBAL_MARKET_SIGNAL_CACHE_LOCK = threading.Lock()
_GLOBAL_MARKET_SIGNAL_CACHE: dict[str, "GlobalMarketSignal"] = {}
_EXCLUDED_US_LEADERSHIP_KEYWORDS: tuple[str, ...] = (
    "2x",
    "3x",
    "-2x",
    "-3x",
    "daily 2x",
    "daily -2x",
    "daily target 2x",
    "daily target -2x",
    "ultra",
    "ultrapro",
    "lever",
    "leverage",
    "inverse",
    "bear",
    "bull",
    "tradr",
    "defiance",
    "direxion",
    "graniteshares",
    "yieldmax",
    "single stock",
    "warrant",
    "right",
    "call ",
    " put ",
    "option",
    "spac",
    "acquisition",
)

_GLOBAL_SECTOR_US_KEYWORDS: dict[str, tuple[str, ...]] = {
    "semiconductor": (
        "nvda",
        "nvidia",
        "amd",
        "advanced micro devices",
        "tsm",
        "taiwan semiconductor",
        "avgo",
        "broadcom",
        "mu",
        "micron",
        "asml",
        "amat",
        "applied materials",
        "nxpi",
        "nxp",
        "intc",
        "intel",
        "on",
        "onsemi",
        "on semiconductor",
        "txn",
        "texas instruments",
        "adi",
        "analog devices",
        "mpwr",
        "monolithic power",
        "mtsi",
        "macom",
        "swks",
        "skyworks",
        "qrvo",
        "qorvo",
        "lrcx",
        "lam research",
        "klac",
        "kla",
        "qcom",
        "qualcomm",
        "mrvl",
        "marvell",
        "soxx",
        "smh",
        "반도체",
    ),
    "bio_healthcare": (
        "xbi",
        "ibb",
        "amgn",
        "amgen",
        "gild",
        "gilead",
        "biib",
        "biogen",
        "mRNA",
        "moderna",
        "regn",
        "regeneron",
        "pfe",
        "pfizer",
        "jnj",
        "johnson",
        "lly",
        "eli lilly",
        "biotech",
        "healthcare",
        "pharma",
        "바이오",
        "헬스케어",
        "제약",
    ),
    "secondary_battery": (
        "tsla",
        "tesla",
        "alb",
        "albemarle",
        "sqm",
        "lithium",
        "battery",
    ),
    "internet_platform": (
        "msft",
        "microsoft",
        "goog",
        "google",
        "meta",
        "amzn",
        "amazon",
        "artificial intelligence",
        "datadog",
        "snowflake",
        "palantir",
        "oracle",
        "cloud",
        "software",
    ),
    "auto_mobility": (
        "tsla",
        "tesla",
        "rivn",
        "rivian",
        "lcid",
        "lucid",
        "f",
        "ford",
        "gm",
        "general motors",
        "mbly",
        "mobileye",
        "aptv",
        "autoliv",
        "autonomous",
        "mobility",
    ),
    "finance": (
        "jpm",
        "jp morgan",
        "gs",
        "goldman sachs",
        "ms",
        "morgan stanley",
        "bac",
        "bank of america",
        "wfc",
        "wells fargo",
        "blk",
        "blackrock",
        "kbe",
        "xlf",
        "bank",
        "financial",
        "insurance",
        "broker",
    ),
    "shipbuilding_defense": (
        "lmt",
        "lockheed",
        "noc",
        "northrop",
        "rtx",
        "raytheon",
        "gd",
        "general dynamics",
        "hii",
        "huntington ingalls",
        "ba",
        "boeing",
        "ita",
        "dfen",
        "defense",
        "aerospace",
        "shipbuilding",
    ),
    "energy_materials": (
        "xom",
        "exxon",
        "cvx",
        "chevron",
        "slb",
        "schlumberger",
        "fcx",
        "freeport",
        "energy",
        "oil",
        "gas",
        "uranium",
        "copper",
    ),
}


@dataclass(slots=True)
class GlobalMarketSignal:
    asof_date: str
    market_score: float
    sector_scores: dict[str, float]
    sector_high_counts: dict[str, int]
    sector_low_counts: dict[str, int]
    high_count: int
    low_count: int


def clear_global_market_signal_cache(*, trade_date: str | None = None) -> None:
    with _GLOBAL_MARKET_SIGNAL_CACHE_LOCK:
        if trade_date is None:
            _GLOBAL_MARKET_SIGNAL_CACHE.clear()
            return
        _GLOBAL_MARKET_SIGNAL_CACHE.pop(str(trade_date), None)


def get_or_build_global_market_signal(
    api,
    config: TradeEngineConfig,
    *,
    trade_date: str,
    force_refresh: bool = False,
) -> tuple[GlobalMarketSignal | None, bool]:
    normalized_trade_date = str(trade_date)
    if not force_refresh:
        with _GLOBAL_MARKET_SIGNAL_CACHE_LOCK:
            cached = _GLOBAL_MARKET_SIGNAL_CACHE.get(normalized_trade_date)
        if cached is not None:
            return cached, True

    signal = build_global_market_signal(api, config, trade_date=normalized_trade_date)
    if signal is None:
        return None, False

    with _GLOBAL_MARKET_SIGNAL_CACHE_LOCK:
        _GLOBAL_MARKET_SIGNAL_CACHE.clear()
        _GLOBAL_MARKET_SIGNAL_CACHE[normalized_trade_date] = signal
    return signal, False


def build_global_market_signal(
    api,
    config: TradeEngineConfig,
    *,
    trade_date: str,
) -> GlobalMarketSignal | None:
    if not bool(getattr(config, "use_global_market_leadership", True)):
        return None

    fetch_rank = getattr(api, "overseas_new_highlow_rank", None)
    if not callable(fetch_rank):
        return None

    exchanges = tuple(getattr(config, "global_market_signal_exchanges", _DEFAULT_US_EXCHANGES))
    nday = str(getattr(config, "global_market_signal_nday", "6"))
    vol_rang = str(getattr(config, "global_market_signal_vol_rang", "2"))
    gubn2 = str(getattr(config, "global_market_signal_breakout_mode", "1"))

    highs: list[dict[str, object]] = []
    lows: list[dict[str, object]] = []
    for exchange in exchanges:
        try:
            highs.extend(
                _keep_sector_matched_rows(
                    _filter_us_leadership_rows(
                        fetch_rank(
                            exchange_code=str(exchange),
                            high_low_type="1",
                            breakout_type=gubn2,
                            nday=nday,
                            volume_rank=vol_rang,
                        )
                        or [],
                        config=config,
                        high_low_type="1",
                    )
                )
            )
        except Exception:
            continue

        try:
            lows.extend(
                _keep_sector_matched_rows(
                    _filter_us_leadership_rows(
                        fetch_rank(
                            exchange_code=str(exchange),
                            high_low_type="0",
                            breakout_type=gubn2,
                            nday=nday,
                            volume_rank=vol_rang,
                        )
                        or [],
                        config=config,
                        high_low_type="0",
                    )
                )
            )
        except Exception:
            continue

    if not highs and not lows:
        return None

    sector_high_counts = _aggregate_sector_counts(highs)
    sector_low_counts = _aggregate_sector_counts(lows)
    sector_scores = _build_sector_scores(sector_high_counts, sector_low_counts)
    market_score = _normalized_balance(len(highs), len(lows))
    return GlobalMarketSignal(
        asof_date=str(trade_date),
        market_score=market_score,
        sector_scores=sector_scores,
        sector_high_counts=sector_high_counts,
        sector_low_counts=sector_low_counts,
        high_count=len(highs),
        low_count=len(lows),
    )


def global_signal_bonus_for_row(
    row,
    signal: GlobalMarketSignal | None,
    config: TradeEngineConfig,
    *,
    strategy: str,
    news_signal: NewsSentimentSignal | None = None,
) -> float:
    if signal is None:
        return 0.0

    sector = _resolve_row_sector(row, config, news_signal)
    if not sector:
        return 0.0

    sector_score = float(signal.sector_scores.get(sector, 0.0))
    strategy_upper = str(strategy or "").strip().upper()
    if strategy_upper == "S":
        positive_max = float(getattr(config, "swing_global_sector_positive_bonus_max", 8.0))
        negative_max = float(getattr(config, "swing_global_sector_negative_penalty_max", 10.0))
        market_negative_max = float(getattr(config, "swing_global_market_negative_penalty_max", 2.0))
    else:
        positive_max = float(getattr(config, "day_global_sector_positive_bonus_max", 4.0))
        negative_max = float(getattr(config, "day_global_sector_negative_penalty_max", 6.0))
        market_negative_max = float(getattr(config, "day_global_market_negative_penalty_max", 1.5))

    score = 0.0
    if sector_score > 0:
        score += min(positive_max, sector_score * positive_max)
    elif sector_score < 0:
        score -= min(negative_max, abs(sector_score) * negative_max)

    if signal.market_score < 0:
        score -= min(market_negative_max, abs(float(signal.market_score)) * market_negative_max)

    return score


def _aggregate_sector_counts(records: list[dict[str, object]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records or []:
        for sector in _match_us_record_sectors(record):
            counts[sector] = int(counts.get(sector, 0)) + 1
    return counts


def _filter_us_leadership_rows(
    rows: list[dict[str, object]],
    *,
    config: TradeEngineConfig,
    high_low_type: str,
) -> list[dict[str, object]]:
    filtered: list[dict[str, object]] = []
    for row in rows or []:
        if not _is_eligible_us_leadership_row(row, config=config, high_low_type=high_low_type):
            continue
        filtered.append(row)
    return filtered


def _keep_sector_matched_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    return [row for row in rows if _match_us_record_sectors(row)]


def _build_sector_scores(
    sector_high_counts: dict[str, int],
    sector_low_counts: dict[str, int],
) -> dict[str, float]:
    sectors = set(sector_high_counts) | set(sector_low_counts)
    return {
        sector: _normalized_balance(
            int(sector_high_counts.get(sector, 0)),
            int(sector_low_counts.get(sector, 0)),
        )
        for sector in sectors
    }


def _match_us_record_sectors(record: dict[str, object]) -> set[str]:
    text = " ".join(
        str(record.get(key) or "").strip().lower()
        for key in ("symb", "name", "ename", "symbol", "code")
    ).strip()
    if not text:
        return set()
    tokens = set(re.findall(r"[a-z0-9]+", text))

    matched: set[str] = set()
    for sector, keywords in _GLOBAL_SECTOR_US_KEYWORDS.items():
        if any(_text_matches_keyword(text, tokens, keyword) for keyword in keywords):
            matched.add(str(sector))
    return matched


def _is_eligible_us_leadership_row(
    record: dict[str, object],
    *,
    config: TradeEngineConfig,
    high_low_type: str,
) -> bool:
    text = " ".join(
        str(record.get(key) or "").strip().lower()
        for key in ("symb", "name", "ename", "symbol", "code")
    ).strip()
    if not text:
        return False

    compact_text = f" {text.replace('-', ' ').replace('/', ' ')} "
    if any(keyword in compact_text for keyword in _EXCLUDED_US_LEADERSHIP_KEYWORDS):
        return False

    price = _to_float(record.get("price") or record.get("last"))
    if price < float(getattr(config, "global_market_signal_min_price", 5.0)):
        return False

    volume = _to_int(record.get("volume") or record.get("tvol"))
    if volume < int(getattr(config, "global_market_signal_min_volume", 500_000)):
        return False

    signed_change_pct = _to_float(record.get("change_pct") or record.get("rate"))
    change_pct = abs(signed_change_pct)
    if change_pct > float(getattr(config, "global_market_signal_max_abs_change_pct", 60.0)):
        return False

    normalized_type = str(high_low_type or "").strip()
    if normalized_type == "1" and signed_change_pct <= 0:
        return False
    if normalized_type == "0" and signed_change_pct >= 0:
        return False

    if bool(getattr(config, "global_market_signal_require_tradable", True)):
        tradable = str(record.get("tradable") or record.get("e_ordyn") or "").strip().upper()
        if tradable and tradable not in {"Y", "YES", "○"}:
            return False

    return True


def _normalized_balance(high_count: int, low_count: int) -> float:
    total = max(0, int(high_count)) + max(0, int(low_count))
    if total <= 0:
        return 0.0
    return (float(high_count) - float(low_count)) / float(total)


def _to_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _to_int(value: object) -> int:
    try:
        return int(float(value or 0))
    except (TypeError, ValueError):
        return 0


def _text_matches_keyword(text: str, tokens: set[str], keyword: str) -> bool:
    normalized = str(keyword or "").strip().lower()
    if not normalized:
        return False
    if " " in normalized:
        return normalized in text
    if len(normalized) <= 4 and normalized.isalnum():
        return normalized in tokens
    return normalized in text


def _resolve_row_sector(
    row,
    config: TradeEngineConfig,
    news_signal: NewsSentimentSignal | None,
) -> str:
    theme_sector = str(row.get("theme_sector") or "").strip()
    if theme_sector:
        return theme_sector

    industry_bucket = str(row.get("industry_bucket_name") or "").strip()
    if industry_bucket:
        return industry_bucket

    sector_keywords = news_signal.sector_keywords if news_signal is not None else _load_sector_keywords(config.news_sector_queries_path)
    matched = match_name_to_sectors(str(row.get("name") or ""), sector_keywords)
    if not matched:
        return ""
    if news_signal is None:
        return sorted(matched)[0]
    ranked = sorted(
        matched,
        key=lambda sector: (float(news_signal.sector_scores.get(sector, 0.0)), str(sector)),
        reverse=True,
    )
    return str(ranked[0]) if ranked else ""

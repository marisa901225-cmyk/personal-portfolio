import asyncio
import json

from backend.services.economy.kr_weekly_sentiment import (
    analyze_kr_weekly_sentiment,
    format_kr_weekly_sentiment_report,
)


async def main() -> None:
    result = await analyze_kr_weekly_sentiment(
        futures_symbol="101000",
        lookback_days=45,
        lookback_bars=5,
    )

    print(format_kr_weekly_sentiment_report(result))
    print("\n[raw]")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

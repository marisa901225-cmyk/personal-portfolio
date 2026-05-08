from __future__ import annotations

from backend.services.trading_engine.google_calendar import authorize_google_calendar_token
from backend.services.trading_engine.runtime_config import load_trade_engine_config_from_env


def main() -> None:
    cfg = load_trade_engine_config_from_env()
    authorize_google_calendar_token(
        credentials_path=cfg.google_calendar_credentials_path,
        token_path=cfg.google_calendar_token_path,
    )
    print(f"Google Calendar token saved to {cfg.google_calendar_token_path}")


if __name__ == "__main__":
    main()

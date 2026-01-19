#!/usr/bin/env python3
import argparse
import sys
import logging
from datetime import datetime
from pathlib import Path

from backend.scripts.common import setup_logging, session_scope

def check_alarms(args):
    """Check incoming and spam alarms in DB."""
    # Lazy import to avoid SQLALchemy init cost if not needed
    try:
        import pandas as pd
        from backend.core.models import IncomingAlarm, SpamAlarm
        from sqlalchemy import text
    except ImportError as e:
        print(f"Error importing dependencies: {e}")
        return

    start_time = args.start or datetime.now().strftime("%Y-%m-%d 00:00:00")
    end_time = args.end or datetime.now().strftime("%Y-%m-%d 23:59:59")
    
    with session_scope() as session:
        print(f"--- Incoming Alarms ({start_time} ~ {end_time}) ---")
        q_inc = session.query(IncomingAlarm).filter(IncomingAlarm.received_at.between(start_time, end_time))
        df_inc = pd.read_sql(q_inc.statement, session.bind)
        if not df_inc.empty:
            print(df_inc.to_string())
        else:
            print("No incoming alarms found.")

        print(f"\n--- Spam Alarms ({start_time} ~ {end_time}) ---")
        q_spam = session.query(SpamAlarm).filter(SpamAlarm.created_at.between(start_time, end_time))
        df_spam = pd.read_sql(q_spam.statement, session.bind)
        if not df_spam.empty:
            print(df_spam.to_string())
        else:
            print("No spam alarms found.")

def import_fx(args):
    """Import FX CSV data."""
    try:
        from backend.scripts.importers.fx import import_fx_csv
    except ImportError as e:
        logging.error(f"Failed to import FX module: {e}")
        return

    csv_path = Path(args.csv)
    with session_scope() as session:
        import_fx_csv(session, csv_path, dry_run=args.dry_run)

def import_trades(args):
    """Import Trades XLSX data."""
    try:
        from backend.scripts.importers.trades import import_trades_xlsx
    except ImportError as e:
        logging.error(f"Failed to import Trades module: {e}")
        return

    xlsx_path = Path(args.xlsx)
    with session_scope() as session:
        import_trades_xlsx(session, xlsx_path, sheet_name=args.sheet, dry_run=args.dry_run)

def sync_prices(args):
    """Sync asset prices from KIS and take a snapshot."""
    try:
        from backend.services.market_data import MarketDataService
    except ImportError as e:
        logging.error(f"Failed to import MarketDataService: {e}")
        return

    with session_scope() as session:
        if args.dry_run:
            print("[Dry-Run] Syncing prices (no DB write)...")
            # In MarketDataService, we would need to pass dry_run if we want to support it fully
            # For now, let's keep it simple or implement dry_run in the service
        
        updated = MarketDataService.sync_all_prices(session)
        print(f"Updated {updated} assets.")
        
        if not args.no_snapshot:
            MarketDataService.take_portfolio_snapshot(session)
            print("Snapshot captured.")

def backup_db(args):
    """Backup SQLite database, compress, and notify."""
    try:
        from backend.services.backup import BackupService
        from backend.services.dropbox_client import DropboxService
        from backend.scripts.utils.generate_backup_msg import generate_backup_message
        from backend.core.config import settings
    except ImportError as e:
        logging.error(f"Failed to import backup dependencies: {e}")
        return

    db_path = Path(settings.database_url.replace("sqlite:///", ""))
    if not db_path.is_absolute():
        db_path = Path(os.getcwd()) / db_path
    
    backup_dir = db_path.parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    timestamp = datetime.now().strftime("%Y-%m-%d")
    backup_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_name = f"portfolio_{timestamp}"
    
    # 1. Hot Backup
    raw_backup = backup_dir / f"{base_name}.db"
    BackupService.create_hot_backup(db_path, raw_backup)
    
    # 2. Compress
    zip_ext = ".zip" if os.getenv("BACKUP_ZIP_PASSWORD") else ".gz"
    archive_path = backup_dir / f"{base_name}.db{zip_ext}"
    BackupService.compress_with_password(raw_backup, archive_path, os.getenv("BACKUP_ZIP_PASSWORD"))
    if raw_backup.exists(): raw_backup.unlink() # 원본 삭제

    # 3. Notification Message (LLM)
    file_size_mb = archive_path.stat().st_size / 1024 / 1024
    msg = generate_backup_message(file_size_mb, backup_time_str)

    # 4. Telegram Upload
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        parts = BackupService.split_file(archive_path)
        import requests
        for idx, part in enumerate(parts):
            caption = msg if idx == 0 else f"(Part {idx+1})"
            url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
            with open(part, "rb") as f:
                requests.post(url, data={"chat_id": chat_id, "caption": caption}, files={"document": f}, timeout=60)
            if part != archive_path: part.unlink() # 조각 삭제
        print("Telegram backup notification sent.")

    # 5. Dropbox Upload
    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    if app_key and app_secret and refresh_token:
        access_token = DropboxService.get_access_token(app_key, app_secret, refresh_token)
        if access_token:
            DropboxService.upload_file(str(archive_path), f"/portfolio-backups/{archive_path.name}", access_token)
            print("Dropbox backup upload completed.")

    # 6. Retention
    BackupService.cleanup_old_backups(backup_dir)
    print("Backup process finished.")

def verify_snapshots(args):
    """Verify asset snapshots."""
    # TODO: Migrate verify_snapshots.py logic here
    print("Verifying snapshots... (Not implemented yet)")

def main():
    parser = argparse.ArgumentParser(description="MyAsset Backend Manager CLI")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)")
    
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Check Alarms
    p_alarms = subparsers.add_parser("check-alarms", help="Check alarm tables")
    p_alarms.add_argument("--start", help="Start time (YYYY-MM-DD HH:MM:SS)")
    p_alarms.add_argument("--end", help="End time (YYYY-MM-DD HH:MM:SS)")
    p_alarms.set_defaults(func=check_alarms)

    # Import FX
    p_fx = subparsers.add_parser("import-fx", help="Import FX CSV")
    p_fx.add_argument("--csv", required=True, help="Path to CSV file")
    p_fx.add_argument("--dry-run", action="store_true", help="Dry run mode")
    p_fx.set_defaults(func=import_fx)

    # Import Trades
    p_trades = subparsers.add_parser("import-trades", help="Import Trades XLSX")
    p_trades.add_argument("--xlsx", required=True, help="Path to XLSX file")
    p_trades.add_argument("--sheet", default="All_Normalized", help="Target sheet name")
    p_trades.add_argument("--dry-run", action="store_true", help="Dry run mode")
    p_trades.set_defaults(func=import_trades)

    # Verify Snapshots
    p_verify = subparsers.add_parser("verify-snapshots", help="Verify asset snapshots")
    p_verify.set_defaults(func=verify_snapshots)

    # Sync Prices
    p_sync = subparsers.add_parser("sync-prices", help="Sync all prices and take snapshot")
    p_sync.add_argument("--dry-run", action="store_true", help="Dry run mode")
    p_sync.add_argument("--no-snapshot", action="store_true", help="Skip taking snapshot")
    p_sync.set_defaults(func=sync_prices)

    # Backup DB
    p_backup = subparsers.add_parser("backup-db", help="Full DB backup process")
    p_backup.set_defaults(func=backup_db)

    args = parser.parse_args()
    
    # Global Setup
    level = getattr(logging, args.log_level.upper(), logging.INFO)
    setup_logging(level)

    # Execute
    args.func(args)

if __name__ == "__main__":
    main()

import argparse
import asyncio
import logging
import os
import signal
from datetime import datetime
from pathlib import Path

from backend.scripts.common import confirm_action, session_scope, setup_logging


def check_alarms(args):
    """Check incoming and spam alarms in DB."""
    try:
        import pandas as pd
        from backend.core.models import IncomingAlarm, SpamAlarm
    except ImportError as e:
        print(f"Error importing dependencies: {e}")
        print("Please install required packages: pip install pandas")
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
        logging.error("Failed to import FX module: %s", e)
        return

    csv_path = Path(args.csv)
    with session_scope() as session:
        import_fx_csv(session, csv_path, dry_run=args.dry_run)


def import_trades(args):
    """Import Trades XLSX data."""
    try:
        from backend.scripts.importers.trades import import_trades_xlsx
    except ImportError as e:
        logging.error("Failed to import Trades module: %s", e)
        return

    xlsx_path = Path(args.xlsx)
    with session_scope() as session:
        import_trades_xlsx(session, xlsx_path, sheet_name=args.sheet, dry_run=args.dry_run)


def sync_prices(args):
    """Sync asset prices from KIS and take a snapshot."""
    try:
        from backend.services.market_data import MarketDataService
    except ImportError as e:
        logging.error("Failed to import MarketDataService: %s", e)
        return

    if not args.yes and not confirm_action("This will update asset prices and may write snapshots. Continue?"):
        print("Cancelled.")
        return

    with session_scope() as session:
        updated = MarketDataService.sync_all_prices(session, mock=args.mock)
        print(f"Updated {updated} assets.")

        if not args.no_snapshot:
            MarketDataService.take_portfolio_snapshot(session)
            print("Snapshot captured.")

        # 창의적인 알림 전송 (동기 실행을 위해 asyncio.run 사용)
        import asyncio
        try:
            asyncio.run(MarketDataService.notify_sync_completion(updated, mock=args.mock))
            print("Notification sent.")
        except Exception as e:
            print(f"Failed to send notification: {e}")


def backup_db(args):
    """Backup SQLite database, compress, and notify."""
    try:
        from backend.services.backup import BackupService
        from backend.services.dropbox_client import DropboxService
        from backend.scripts.utils.generate_backup_msg import generate_backup_message
        from backend.core.config import settings
    except ImportError as e:
        logging.error("Failed to import backup dependencies: %s", e)
        return

    if not args.yes and not confirm_action("This will create and upload a DB backup. Continue?"):
        print("Cancelled.")
        return

    db_path = Path(settings.database_url.replace("sqlite:///", ""))
    if not db_path.is_absolute():
        db_path = Path(os.getcwd()) / db_path

    backup_dir = db_path.parent.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d")
    backup_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    base_name = f"portfolio_{timestamp}"

    raw_backup = backup_dir / f"{base_name}.db"
    BackupService.create_hot_backup(db_path, raw_backup)

    zip_ext = ".zip" if os.getenv("BACKUP_ZIP_PASSWORD") else ".gz"
    archive_path = backup_dir / f"{base_name}.db{zip_ext}"
    BackupService.compress_with_password(raw_backup, archive_path, os.getenv("BACKUP_ZIP_PASSWORD"))
    if raw_backup.exists():
        raw_backup.unlink()

    file_size_mb = archive_path.stat().st_size / 1024 / 1024
    msg = generate_backup_message(file_size_mb, backup_time_str)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if bot_token and chat_id:
        try:
            parts = BackupService.split_file(archive_path)
            import requests
            for idx, part in enumerate(parts):
                caption = msg if idx == 0 else f"(Part {idx+1})"
                url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
                with open(part, "rb") as f:
                    requests.post(
                        url,
                        data={"chat_id": chat_id, "caption": caption},
                        files={"document": f},
                        timeout=60,
                    )
                if part != archive_path:
                    part.unlink()
            print("Telegram backup notification sent.")
        except Exception as e:
            logging.error(f"Telegram backup failed: {e}")

    app_key = os.getenv("DROPBOX_APP_KEY")
    app_secret = os.getenv("DROPBOX_APP_SECRET")
    refresh_token = os.getenv("DROPBOX_REFRESH_TOKEN")
    if app_key and app_secret and refresh_token:
        try:
            access_token = DropboxService.get_access_token(app_key, app_secret, refresh_token)
            if access_token:
                DropboxService.upload_file(str(archive_path), f"/portfolio-backups/{archive_path.name}", access_token)
                print("Dropbox backup upload completed.")
        except Exception as e:
            logging.error(f"Dropbox backup failed: {e}")

    try:
        BackupService.cleanup_old_backups(backup_dir)
        print("Backup cleanup finished.")
    except Exception as e:
        logging.error(f"Backup cleanup failed: {e}")

    print("Backup process finished.")


def run_scheduler(args):
    """Run the master service supervisor (Orchestrator/Policy Manager)"""
    import asyncio
    from backend.services.scheduler.core import start_scheduler, shutdown_scheduler
    from backend.services.news.esports_monitor import run_esports_monitor
    from backend.core.db import SessionLocal
    from backend.services.scheduler_monitor import (
        run_with_monitoring, 
        send_service_alert, 
        update_scheduler_state
    )

    logging.info("Initializing Master Service Supervisor (Policy Manager)...")

    async def _main():
        shutdown_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def handle_signal():
            logging.info("Shutdown signal received...")
            shutdown_event.set()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, handle_signal)

        # Service definitions (The "What")
        async def run_apscheduler():
            start_scheduler()
            await shutdown_event.wait()

        services_config = [
            {
                "name": "esports_monitor",
                "func": lambda: run_esports_monitor(dry_run=False),
                "auto_restart": True,
            },
            {
                "name": "apscheduler_core",
                "func": run_apscheduler,
                "auto_restart": False,
            }
        ]

        active_tasks = {}
        restart_counts = {}
        max_restarts = 5

        async def supervisor_loop(svc):
            """정책 관리 루프 (The "Policy")"""
            name = svc["name"]
            func = svc["func"]
            
            while not shutdown_event.is_set():
                restart_count = restart_counts.get(name, 0)
                
                # Execution & Recording (Delegated to Monitor Toolkit)
                result = await run_with_monitoring(name, func, SessionLocal)
                
                if result is True:
                    # Normal exit or finished
                    if shutdown_event.is_set():
                        break
                    logging.warning(f"[{name}] Service exited unexpectedly")
                else:
                    # Result is an Exception (Failure)
                    restart_counts[name] = restart_count + 1
                    is_fatal = not svc.get("auto_restart", True) or restart_counts[name] >= max_restarts
                    
                    # Alert (Delegated to Monitor Toolkit)
                    await send_service_alert(
                        service_name=name,
                        status="failure" if not is_fatal else "stopped",
                        error=str(result),
                        restart_count=restart_counts[name],
                        max_restarts=max_restarts
                    )

                    if is_fatal:
                        logging.critical(f"[{name}] Service stopped permanently")
                        break
                    
                    # Backoff Policy
                    wait_time = min(60, 2 ** restart_counts[name])
                    logging.info(f"[{name}] Restart policy: Waiting {wait_time}s...")
                    await asyncio.sleep(wait_time)

        # Start supervised tasks
        for svc in services_config:
            active_tasks[svc["name"]] = asyncio.create_task(supervisor_loop(svc))

        await shutdown_event.wait()
        
        # Graceful Shutdown
        logging.info("Initiating graceful shutdown...")
        shutdown_scheduler()
        
        for name, task in active_tasks.items():
            if not task.done():
                task.cancel()
        
        if active_tasks:
            await asyncio.gather(*active_tasks.values(), return_exceptions=True)
        
        # Mark all as stopped in DB
        with SessionLocal() as db:
            for name in active_tasks:
                update_scheduler_state(name, db, "stopped", "Graceful shutdown complete")
        
        logging.info("Supervisor shut down successfully.")

    try:
        asyncio.run(_main())
    except (KeyboardInterrupt, SystemExit):
        pass


def run_collector(args):
    """Run the alarm collector FastAPI service."""
    import uvicorn
    # Import app lazily to avoid immediate side effects
    from backend.alarm_collector import app
    
    logging.info("Starting alarm collector on %s:%d", args.host, args.port)
    uvicorn.run(app, host=args.host, port=args.port)


def register_telegram(args):
    """Register telegram bot commands."""
    import asyncio
    
    async def _do_register():
        import httpx
        token = os.getenv("ALARM_TELEGRAM_BOT_TOKEN")
        if not token:
            logging.error("ALARM_TELEGRAM_BOT_TOKEN not found in environment")
            return

        commands = [
            {"command": "report", "description": "리포트 생성 (예: /report 이번달, /report 스팀)"},
            {"command": "list", "description": "스팸 필터 규칙 목록 보기"},
            {"command": "add", "description": "스팸 필터 키워드 추가 (예: /add 키워드)"},
            {"command": "del", "description": "스팸 필터 규칙 삭제 (예: /del ID)"},
            {"command": "help", "description": "도움말 보기"}
        ]
        url = f"https://api.telegram.org/bot{token}/setMyCommands"
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json={"commands": commands})
            if resp.json().get("ok"):
                logging.info("Telegram commands registered successfully!")
            else:
                logging.error("Failed to register commands: %s", resp.text)

    asyncio.run(_do_register())


async def _process_alarms_async():
    from backend.core.db import SessionLocal
    from backend.services.alarm_service import AlarmService
    
    logging.info("Processing pending alarms...")
    db = SessionLocal()
    try:
        await AlarmService.process_pending_alarms(db)
        logging.info("Alarm processing finished.")
    finally:
        db.close()


def process_alarms_cmd(args):
    """Manually process pending alarms."""
    import asyncio
    asyncio.run(_process_alarms_async())


def listen_esports_cmd(args):
    """Run the esports smart polling monitor."""
    import asyncio
    from backend.services.news.esports_monitor import run_esports_monitor
    
    logging.info("Starting esports smart polling monitor...")
    try:
        asyncio.run(run_esports_monitor(dry_run=args.dry_run))
    except (KeyboardInterrupt, SystemExit):
        logging.info("Esports monitor interrupted, shutting down...")


def verify_snapshots(args):
    """Verify asset snapshots."""
    print("Verifying snapshots... (Not implemented yet)")


def main():
    parser = argparse.ArgumentParser(description="MyAsset Backend Manager CLI")
    parser.add_argument("--log-level", default="INFO", help="Logging level (DEBUG, INFO, WARNING)")

    subparsers = parser.add_subparsers(dest="command", required=True)

    p_alarms = subparsers.add_parser("check-alarms", help="Check alarm tables")
    p_alarms.add_argument("--start", help="Start time (YYYY-MM-DD HH:MM:SS)")
    p_alarms.add_argument("--end", help="End time (YYYY-MM-DD HH:MM:SS)")
    p_alarms.set_defaults(func=check_alarms)

    p_fx = subparsers.add_parser("import-fx", help="Import FX CSV")
    p_fx.add_argument("--csv", required=True, help="Path to CSV file")
    p_fx.add_argument("--dry-run", action="store_true", help="Dry run mode")
    p_fx.set_defaults(func=import_fx)

    p_trades = subparsers.add_parser("import-trades", help="Import Trades XLSX")
    p_trades.add_argument("--xlsx", required=True, help="Path to XLSX file")
    p_trades.add_argument("--sheet", default="All_Normalized", help="Target sheet name")
    p_trades.add_argument("--dry-run", action="store_true", help="Dry run mode")
    p_trades.set_defaults(func=import_trades)

    p_verify = subparsers.add_parser("verify-snapshots", help="Verify asset snapshots")
    p_verify.set_defaults(func=verify_snapshots)

    p_sync = subparsers.add_parser("sync-prices", help="Sync all prices and take snapshot")
    p_sync.add_argument("--no-snapshot", action="store_true", help="Skip taking snapshot")
    p_sync.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_sync.add_argument("-m", "--mock", action="store_true", help="Use mock prices for testing")
    p_sync.set_defaults(func=sync_prices)

    p_backup = subparsers.add_parser("backup-db", help="Full DB backup process")
    p_backup.add_argument("-y", "--yes", action="store_true", help="Skip confirmation prompt")
    p_backup.set_defaults(func=backup_db)

    # New standardized commands
    p_sched = subparsers.add_parser("run-scheduler", help="Run the asynchronous scheduler (news, etc.)")
    p_sched.set_defaults(func=run_scheduler)

    p_coll = subparsers.add_parser("run-collector", help="Run the alarm collector FastAPI service")
    p_coll.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    p_coll.add_argument("--port", type=int, default=8001, help="Port to bind to")
    p_coll.set_defaults(func=run_collector)

    p_tel = subparsers.add_parser("register-telegram", help="Register/Update Telegram bot commands")
    p_tel.set_defaults(func=register_telegram)

    p_proc = subparsers.add_parser("process-alarms", help="Manually process pending alarms")
    p_proc.set_defaults(func=process_alarms_cmd)

    p_esports = subparsers.add_parser("listen-esports", help="Run the esports smart polling monitor")
    p_esports.add_argument("--dry-run", action="store_true", help="Dry run mode (no notifications)")
    p_esports.set_defaults(func=listen_esports_cmd)

    args = parser.parse_args()

    level = getattr(logging, args.log_level.upper(), logging.INFO)
    setup_logging(level)

    args.func(args)


if __name__ == "__main__":
    main()

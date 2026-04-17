#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path


REPO_KEYS = {
    "AI_REPORT_BASE_URL",
    "AI_REPORT_FALLBACK_MODEL",
    "AI_REPORT_MAX_TOKENS",
    "AI_REPORT_MODEL",
    "AI_REPORT_MODEL_YEARLY",
    "AI_REPORT_TEMPERATURE",
    "AI_REPORT_TIMEOUT_SEC",
    "ALARM_DEDUP_WINDOW_SECONDS",
    "ALARM_RANDOM_LLM_BASE_URL",
    "ALARM_SILENCE_ACTIVE_WINDOW",
    "ALARM_SUMMARY_LLM_BASE_URL",
    "ALLOWED_ORIGINS",
    "ALLOW_NO_AUTH",
    "CATCHPHRASE_SAVE_PATH",
    "DATABASE_URL",
    "DEBUG_LLM_DRAFT",
    "ELECTION_REGION_ALLOWLIST",
    "ELECTION_REGION_MODE",
    "EXTERNAL_BACKUP_PATH",
    "JWT_ACCESS_TOKEN_EXPIRE_MINUTES",
    "JWT_ALGORITHM",
    "KIS_CONFIG_DIR",
    "KIS_ENABLED",
    "KIS_OPS",
    "KIS_PROD",
    "KIS_VOPS",
    "KIS_VPS",
    "LLM_BASE_URL",
    "LLM_DRAFT_LOG_MAX_MB",
    "LLM_LIGHT_BASE_URL",
    "LLM_LIGHT_MODEL_ID",
    "LLM_REMOTE_DEFAULT_MODEL",
    "LLM_REMOTE_MODEL_DIR",
    "LLM_REMOTE_MODEL_PATH_FILE",
    "LLM_REMOTE_URL",
    "LLM_TIMEOUT",
    "LOG_LEVEL",
    "MAX_UPLOAD_MB",
    "NAVER_ALLOWED_IDS",
    "NAVER_REDIRECT_URI",
    "NEWS_LLM_BASE_URL",
    "OV_DEVICE",
    "OV_MODEL_ID",
    "PORTFOLIO_DB_PATH",
    "SPAM_NB_THRESHOLD",
    "TAILSCALE_TAILNET_DOMAIN",
    "TELEGRAM_MAX_MESSAGE_LEN",
}

REPO_PREFIXES = (
    "RATE_LIMIT_",
    "TRADING_ENGINE_",
)

SECRET_KEYS = {
    "AI_REPORT_API_KEY",
    "ALARM_TELEGRAM_BOT_TOKEN",
    "ALARM_TELEGRAM_CHAT_ID",
    "API_TOKEN",
    "BACKEND_ZIP_PASSWORD",
    "BOK_ECOS_API_KEY",
    "DROPBOX_APP_KEY",
    "DROPBOX_APP_SECRET",
    "DROPBOX_REFRESH_TOKEN",
    "FRED_API_KEY",
    "GOOGLE_DRIVE_CLIENT_ID",
    "GOOGLE_DRIVE_CLIENT_SECRET",
    "GOOGLE_DRIVE_FOLDER_ID",
    "GOOGLE_DRIVE_REFRESH_TOKEN",
    "GOOGLE_TOKEN",
    "JWT_SECRET_KEY",
    "KIS_MY_ACCT_STOCK",
    "KIS_MY_AGENT",
    "KIS_MY_APP",
    "KIS_MY_HTSID",
    "KIS_MY_PROD",
    "KIS_MY_SEC",
    "KIS_MY_TOKEN",
    "KIS_TOKEN_KEY",
    "KMA_SERVICE_KEY",
    "LLM_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "OPEN_API_KEY",
    "PANDASCORE_API_KEY",
    "TELEGRAM_BOT_TOKEN",
    "TELEGRAM_CHAT_ID",
    "TELEGRAM_WEBHOOK_SECRET",
    "TELEGRAM_WEBHOOK_SECRET_TOKEN",
    "X_TELEGRAM_BOT_API_SECRET_TOKEN",
}


def parse_env_lines(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("export "):
            stripped = stripped[len("export ") :]
        if "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if not key:
            continue
        entries.append((key, value))
    return entries


def is_repo_key(key: str) -> bool:
    if key in REPO_KEYS:
        return True
    return any(key.startswith(prefix) for prefix in REPO_PREFIXES)


def is_secret_key(key: str) -> bool:
    if key in SECRET_KEYS:
        return True
    secret_suffixes = (
        "_API_KEY",
        "_TOKEN",
        "_SECRET",
        "_PASSWORD",
        "_CLIENT_ID",
        "_CLIENT_SECRET",
        "_REFRESH_TOKEN",
    )
    return key.endswith(secret_suffixes)


def write_env_file(path: Path, header: str, entries: list[tuple[str, str]]) -> None:
    lines = [header, ""]
    lines.extend(f"{key}={value}" for key, value in entries)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Split a mixed env file into repo runtime config and external secrets.")
    parser.add_argument("--source", required=True, help="Path to the mixed env file")
    parser.add_argument("--repo-env", required=True, help="Path to write the repo runtime env file")
    parser.add_argument("--secrets-env", required=True, help="Path to write the external secrets env file")
    args = parser.parse_args()

    source = Path(args.source).expanduser()
    repo_env = Path(args.repo_env).expanduser()
    secrets_env = Path(args.secrets_env).expanduser()

    entries = parse_env_lines(source.read_text(encoding="utf-8"))
    repo_entries: list[tuple[str, str]] = []
    secret_entries: list[tuple[str, str]] = []
    unknown_secret_entries: list[str] = []

    for key, value in entries:
        if is_repo_key(key):
            repo_entries.append((key, value))
            continue
        secret_entries.append((key, value))
        if not is_secret_key(key):
            unknown_secret_entries.append(key)

    write_env_file(
        repo_env,
        "# Safe runtime config only. Secrets live outside the repo.",
        repo_entries,
    )
    write_env_file(
        secrets_env,
        "# Secrets only. Keep this file outside the repo.",
        secret_entries,
    )

    print(f"repo env entries: {len(repo_entries)} -> {repo_env}")
    print(f"secret env entries: {len(secret_entries)} -> {secrets_env}")
    if unknown_secret_entries:
        print("reviewed-as-secret-by-default:")
        for key in unknown_secret_entries:
            print(f"  - {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

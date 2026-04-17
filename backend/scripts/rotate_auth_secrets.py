from __future__ import annotations

import argparse
import json

from dotenv import load_dotenv

from backend.core.env_paths import get_project_env_files
from backend.services.auth_secret_rotation import rotate_backend_auth_secrets


def main() -> int:
    parser = argparse.ArgumentParser(description="Rotate backend API_TOKEN and JWT_SECRET_KEY.")
    parser.add_argument("--force", action="store_true", help="Rotate immediately even if the interval has not elapsed.")
    parser.add_argument("--no-notify", action="store_true", help="Skip Telegram notification after rotation.")
    args = parser.parse_args()

    for env_path in get_project_env_files():
        load_dotenv(env_path, override=False)

    result = rotate_backend_auth_secrets(force=args.force, notify=not args.no_notify)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

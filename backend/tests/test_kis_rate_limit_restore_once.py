from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from uuid import uuid4


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "shell" / "kis_rate_limit_restore_once.sh"
TEST_ROOT = Path(__file__).resolve().parents[1] / "storage" / "test_kis_rate_limit_restore_once"


def _make_case_dir(name: str) -> Path:
    TEST_ROOT.mkdir(parents=True, exist_ok=True)
    case_dir = TEST_ROOT / f"{name}_{uuid4().hex}"
    case_dir.mkdir(parents=True, exist_ok=True)
    return case_dir


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _prepare_case_files(case_dir: Path) -> dict[str, Path]:
    env_file = case_dir / "backend.env"
    if not env_file.exists():
        env_file.write_text(
            "FOO=bar\n"
            "KIS_REST_RATE_LIMIT_PER_SEC=20\n"
            "KIS_REST_RATE_WINDOW_SEC=1.0\n",
            encoding="utf-8",
        )

    compose_file = case_dir / "docker-compose.yml"
    if not compose_file.exists():
        compose_file.write_text("services: {}\n", encoding="utf-8")

    docker_log = case_dir / "docker.log"
    fake_docker = case_dir / "docker"
    if not fake_docker.exists():
        _write_executable(
            fake_docker,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "printf '%s\\n' \"$*\" >> \"${FAKE_DOCKER_LOG:?}\"\n",
        )

    crontab_file = case_dir / "crontab.txt"
    fake_crontab = case_dir / "crontab"
    if not fake_crontab.exists():
        _write_executable(
            fake_crontab,
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            "if [[ \"${1:-}\" == \"-l\" ]]; then\n"
            "  if [[ -f \"${FAKE_CRONTAB_FILE:?}\" ]]; then\n"
            "    cat \"${FAKE_CRONTAB_FILE:?}\"\n"
            "  fi\n"
            "  exit 0\n"
            "fi\n"
            "if [[ $# -eq 1 ]]; then\n"
            "  cp \"$1\" \"${FAKE_CRONTAB_FILE:?}\"\n"
            "  exit 0\n"
            "fi\n"
            "exit 0\n",
        )

    return {
        "env_file": env_file,
        "compose_file": compose_file,
        "docker_log": docker_log,
        "fake_docker": fake_docker,
        "crontab_file": crontab_file,
    }


def _run_script(
    case_dir: Path,
    *,
    restore_at: str,
    now_epoch: int,
    target_rate_limit: int = 18,
    target_services: str = "backend-api news-scheduler",
) -> subprocess.CompletedProcess[str]:
    prepared = _prepare_case_files(case_dir)
    env = os.environ.copy()
    env.update(
        {
            "KIS_RATE_LIMIT_RESTORE_ENV_FILE": str(prepared["env_file"]),
            "KIS_RATE_LIMIT_RESTORE_COMPOSE_FILE": str(prepared["compose_file"]),
            "KIS_RATE_LIMIT_RESTORE_LOG_FILE": str(case_dir / "restore.log"),
            "KIS_RATE_LIMIT_RESTORE_STATE_FILE": str(case_dir / "restore_state.json"),
            "KIS_RATE_LIMIT_RESTORE_LOCK_FILE": str(case_dir / "restore.lock"),
            "KIS_RATE_LIMIT_RESTORE_AT": restore_at,
            "KIS_RATE_LIMIT_RESTORE_TZ": "Asia/Seoul",
            "KIS_RATE_LIMIT_RESTORE_NOW_EPOCH": str(now_epoch),
            "KIS_RATE_LIMIT_RESTORE_TARGET": str(target_rate_limit),
            "KIS_RATE_LIMIT_RESTORE_SERVICES": target_services,
            "KIS_RATE_LIMIT_RESTORE_DOCKER_BIN": str(prepared["fake_docker"]),
            "FAKE_DOCKER_LOG": str(prepared["docker_log"]),
            "FAKE_CRONTAB_FILE": str(prepared["crontab_file"]),
            "PATH": f"{case_dir}:{env.get('PATH', '')}",
        }
    )
    return subprocess.run(
        ["bash", str(SCRIPT_PATH)],
        check=True,
        cwd=case_dir,
        env=env,
        capture_output=True,
        text=True,
    )


def test_kis_rate_limit_restore_script_skips_before_cutover():
    case_dir = _make_case_dir("skip_before_cutover")
    try:
        _run_script(
            case_dir,
            restore_at="2099-04-20 00:00:00",
            now_epoch=0,
        )

        env_text = (case_dir / "backend.env").read_text(encoding="utf-8")
        assert "KIS_REST_RATE_LIMIT_PER_SEC=20" in env_text
        assert not (case_dir / "restore_state.json").exists()
        assert not (case_dir / "docker.log").exists()
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_kis_rate_limit_restore_script_updates_env_and_restarts_once():
    case_dir = _make_case_dir("apply_cutover")
    try:
        _run_script(
            case_dir,
            restore_at="2000-04-20 00:00:00",
            now_epoch=9_999_999_999,
        )

        env_text = (case_dir / "backend.env").read_text(encoding="utf-8")
        assert "KIS_REST_RATE_LIMIT_PER_SEC=18" in env_text

        payload = json.loads((case_dir / "restore_state.json").read_text(encoding="utf-8"))
        assert payload["done"] is True
        assert payload["target_rate_limit"] == 18
        assert payload["services"] == "backend-api news-scheduler"

        docker_lines = (case_dir / "docker.log").read_text(encoding="utf-8").strip().splitlines()
        assert docker_lines == [
            f"compose -f {case_dir / 'docker-compose.yml'} up -d --force-recreate backend-api news-scheduler",
        ]

        _run_script(
            case_dir,
            restore_at="2000-04-20 00:00:00",
            now_epoch=9_999_999_999,
        )
        docker_lines_after_second_run = (case_dir / "docker.log").read_text(encoding="utf-8").strip().splitlines()
        assert docker_lines_after_second_run == docker_lines
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)


def test_kis_rate_limit_restore_script_ignores_done_state_from_old_plan():
    case_dir = _make_case_dir("stale_done_state")
    try:
        (case_dir / "restore_state.json").write_text(
            json.dumps(
                {
                    "done": True,
                    "restore_at": "2026-04-10 10:40:00",
                    "restore_tz": "Asia/Seoul",
                    "target_rate_limit": 20,
                }
            ),
            encoding="utf-8",
        )

        _run_script(
            case_dir,
            restore_at="2000-04-20 00:00:00",
            now_epoch=9_999_999_999,
        )

        payload = json.loads((case_dir / "restore_state.json").read_text(encoding="utf-8"))
        assert payload["done"] is True
        assert payload["restore_at"] == "2000-04-20 00:00:00"
        assert payload["target_rate_limit"] == 18
    finally:
        shutil.rmtree(case_dir, ignore_errors=True)

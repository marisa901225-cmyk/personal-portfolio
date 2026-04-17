import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = PROJECT_ROOT / "backend" / "scripts" / "shell" / "llm_fan_guard.sh"


class TestLlmFanGuard(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmp.name)
        self.actions_log = self.tmp_path / "actions.log"
        self.state_file = self.tmp_path / "llm_fan_guard_state.json"
        self.log_file = self.tmp_path / "llm_fan_guard.log"
        self.lock_file = self.tmp_path / "llm_fan_guard.lock"
        self.sensors_bin = self.tmp_path / "fake-sensors.sh"
        self.schedule_script = self.tmp_path / "fake-llm-schedule.sh"

        self._write_executable(
            self.sensors_bin,
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "${FAKE_SENSORS_OUTPUT:-}"
""",
        )
        self._write_executable(
            self.schedule_script,
            """#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s\n' "${1:-}" "${LLM_SCHEDULE_ALLOW_WEEKEND_START:-0}" >> "${ACTIONS_LOG:?}"
""",
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_executable(self, path: Path, content: str) -> None:
        path.write_text(textwrap.dedent(content), encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)

    def _run_guard(
        self,
        *,
        sensors_output: str,
        now_epoch: int,
        threshold_rpm: int = 1600,
        cooldown_sec: int = 3600,
        sensor_pattern: str = "",
        start_max_temp_c: str = "0",
        start_retry_sec: int = 300,
        temp_sensor_pattern: str = "",
    ) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            {
                "ACTIONS_LOG": str(self.actions_log),
                "FAKE_SENSORS_OUTPUT": textwrap.dedent(sensors_output).strip(),
                "LLM_FAN_GUARD_STATE_FILE": str(self.state_file),
                "LLM_FAN_GUARD_LOG_FILE": str(self.log_file),
                "LLM_FAN_GUARD_LOCK_FILE": str(self.lock_file),
                "LLM_FAN_GUARD_SCHEDULE_SCRIPT": str(self.schedule_script),
                "LLM_FAN_GUARD_SENSORS_BIN": str(self.sensors_bin),
                "LLM_FAN_GUARD_THRESHOLD_RPM": str(threshold_rpm),
                "LLM_FAN_GUARD_COOLDOWN_SEC": str(cooldown_sec),
                "LLM_FAN_GUARD_NOW_EPOCH": str(now_epoch),
                "LLM_FAN_GUARD_SENSOR_PATTERN": sensor_pattern,
                "LLM_FAN_GUARD_START_MAX_TEMP_C": str(start_max_temp_c),
                "LLM_FAN_GUARD_START_RETRY_SEC": str(start_retry_sec),
                "LLM_FAN_GUARD_TEMP_SENSOR_PATTERN": temp_sensor_pattern,
            }
        )
        return subprocess.run(
            ["bash", str(SCRIPT_PATH)],
            cwd=PROJECT_ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=False,
        )

    def _read_actions(self) -> list[str]:
        if not self.actions_log.exists():
            return []
        return self.actions_log.read_text(encoding="utf-8").splitlines()

    def test_enters_cooldown_and_stops_llm_services(self) -> None:
        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        2350 RPM
                fan2:           0 RPM
            """,
            now_epoch=1_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["stop|0"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 1', state_text)
        self.assertIn('"cooldown_started_epoch": 1000', state_text)
        self.assertIn('"cooldown_until_epoch": 4600', state_text)
        self.assertIn('"last_trigger_rpm": 2350', state_text)
        self.assertIn('"last_action": "stop"', state_text)

    def test_does_not_retrigger_while_cooldown_is_active(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 1,
                  "cooldown_started_epoch": 1000,
                  "cooldown_until_epoch": 4600,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 2350,
                  "last_action": "stop",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:        2800 RPM
            """,
            now_epoch=2_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])

    def test_restarts_llm_services_after_cooldown_expires(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 1,
                  "cooldown_started_epoch": 1000,
                  "cooldown_until_epoch": 4600,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 2350,
                  "last_action": "stop",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:          90 RPM
            """,
            now_epoch=5_000,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), ["start|1"])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 0', state_text)
        self.assertIn('"cooldown_until_epoch": 0', state_text)
        self.assertIn('"last_action": "start"', state_text)

    def test_defers_restart_when_temperature_is_still_high(self) -> None:
        self.state_file.write_text(
            textwrap.dedent(
                """
                {
                  "cooldown_active": 1,
                  "cooldown_started_epoch": 1000,
                  "cooldown_until_epoch": 4600,
                  "last_trigger_rpm": 2350,
                  "last_seen_rpm": 2350,
                  "last_action": "stop",
                  "updated_at_epoch": 1000
                }
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )

        result = self._run_guard(
            sensors_output="""
                xe-pci-0300
                Adapter: PCI adapter
                fan1:          90 RPM
                pkg:         +68.0 C
                vram:        +72.5 C
            """,
            now_epoch=5_000,
            start_max_temp_c="70",
            start_retry_sec=600,
            temp_sensor_pattern="xe-pci-0300",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])
        state_text = self.state_file.read_text(encoding="utf-8")
        self.assertIn('"cooldown_active": 1', state_text)
        self.assertIn('"cooldown_until_epoch": 5600', state_text)
        self.assertIn('"last_action": "start_deferred_hot"', state_text)

    def test_sensor_pattern_limits_which_fan_section_is_used(self) -> None:
        result = self._run_guard(
            sensors_output="""
                chassis-fan
                Adapter: ISA adapter
                fan1:        2600 RPM

                xe-pci-0300
                Adapter: PCI adapter
                fan1:        1200 RPM
            """,
            now_epoch=1_000,
            sensor_pattern="xe-pci-0300",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self._read_actions(), [])


if __name__ == "__main__":
    unittest.main()
